from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.memory import MemoryMatch, MemoryStore
from app.tools import ToolClient, ToolResult


@dataclass
class ModeOption:
    mode: str
    duration_min: float
    distance_km: float
    score: float
    notes: List[str]


@dataclass
class AgentOutput:
    source_display: str
    destination_display: str
    selected_mode: str
    selected_reason: str
    all_options: List[ModeOption]
    similar_memories: List[MemoryMatch]
    tool_log: List[str]
    climate_label: str
    public_transport_assessment: str
    best_route_id: str
    best_route_path: str


class MemoryAgent:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def recall(self, source: str, destination: str) -> List[MemoryMatch]:
        return self.store.find_similar(source=source, destination=destination)


class ResearchAgent:
    """Collects route, geocoding and weather evidence via tools."""

    def __init__(self, tools: ToolClient) -> None:
        self.tools = tools

    def collect(self, source: str, destination: str) -> Dict[str, object]:
        tool_log: List[str] = []

        src_geo = self.tools.geocode_location(source)
        dst_geo = self.tools.geocode_location(destination)
        for item in (src_geo, dst_geo):
            tool_log.append(_fmt_tool(item))

        if not src_geo.success or not dst_geo.success:
            raise RuntimeError("Unable to geocode source/destination.")

        src_lat = src_geo.data["lat"]
        src_lon = src_geo.data["lon"]
        dst_lat = dst_geo.data["lat"]
        dst_lon = dst_geo.data["lon"]

        driving = self.tools.get_route(
            src_lon,
            src_lat,
            dst_lon,
            dst_lat,
            profile="driving",
            source_label=source,
            destination_label=destination,
        )
        cycling = self.tools.get_route(
            src_lon,
            src_lat,
            dst_lon,
            dst_lat,
            profile="cycling",
            source_label=source,
            destination_label=destination,
        )
        weather = self.tools.get_weather(src_lat, src_lon)
        for item in (driving, cycling, weather):
            tool_log.append(_fmt_tool(item))

        if not driving.success and not cycling.success:
            raise RuntimeError("Unable to fetch any route from OSRM.")

        return {
            "source_geo": src_geo.data,
            "destination_geo": dst_geo.data,
            "driving": driving,
            "cycling": cycling,
            "weather": weather,
            "tool_log": tool_log,
        }


class PlannerAgent:
    """Scores transport modes and selects best route mode."""

    def decide(
        self,
        evidence: Dict[str, object],
        memories: List[MemoryMatch],
        passengers: int,
    ) -> tuple[List[ModeOption], str, str]:
        driving: ToolResult = evidence["driving"]  # type: ignore[assignment]
        cycling: ToolResult = evidence["cycling"]  # type: ignore[assignment]
        weather: ToolResult = evidence["weather"]  # type: ignore[assignment]

        options: List[ModeOption] = []
        weather_data = weather.data if weather.success else {}
        rain = float(weather_data.get("precipitation_mm", 0.0) or 0.0)
        wind = float(weather_data.get("wind_kmh", 0.0) or 0.0)
        temp = float(weather_data.get("temperature_c", 25.0) or 25.0)
        climate_label = self._classify_climate(temp=temp, rain=rain)
        avoid_two_wheeler = climate_label in {"very_hot", "rainy"}
        avoid_public_transport = climate_label in {"very_hot", "rainy"}
        public_transport_assessment = "Public transport not evaluated."

        if driving.success:
            d_km = driving.data["distance_m"] / 1000.0
            d_min = driving.data["duration_s"] / 60.0
            score = d_min
            notes = [f"Fastest road ETA from OSRM: {d_min:.1f} min."]
            if rain > 5:
                score += 3
                notes.append("Rain present, enclosed mode gets comfort advantage.")
            score -= self._memory_bonus(memories, "car")
            options.append(
                ModeOption(
                    mode="car",
                    duration_min=d_min,
                    distance_km=d_km,
                    score=score,
                    notes=notes,
                )
            )

            transit_duration = (d_km / 26.0) * 60.0 + 14.0
            transit_mode = self._suggest_public_transport_mode(distance_km=d_km)
            transit_comfort = self._public_transport_comfort(climate_label=climate_label, passengers=passengers)
            public_transport_assessment = (
                f"Mode possibility: {transit_mode}. Comfort level: {transit_comfort}. "
                f"Estimated ETA: {transit_duration:.1f} min."
            )

            if not avoid_public_transport or passengers == 1:
                transit_score = transit_duration
                transit_notes = [
                    f"Estimated public transport ETA: {transit_duration:.1f} min (transfer-aware heuristic).",
                    f"Recommended public transport mode: {transit_mode}.",
                    f"Comfort estimate for {passengers} passenger(s): {transit_comfort}.",
                ]
                if d_km >= 10:
                    transit_score -= 4
                    transit_notes.append("Distance is suitable for public transport corridors.")
                if passengers == 1:
                    transit_score -= 2.5
                    transit_notes.append("Single passenger boost applied to public transport efficiency.")
                if climate_label in {"very_hot", "rainy"}:
                    transit_score += 6
                    transit_notes.append("Climate discomfort penalty applied to public transport.")
                transit_score -= self._memory_bonus(memories, "public_transport")
                options.append(
                    ModeOption(
                        mode="public_transport",
                        duration_min=transit_duration,
                        distance_km=d_km,
                        score=transit_score,
                        notes=transit_notes,
                    )
                )

            ride_share_duration = d_min * 1.1 + 4.0
            ride_share_score = ride_share_duration + max(passengers - 2, 0) * 2.5
            ride_share_notes = [
                f"Ride-share ETA estimate: {ride_share_duration:.1f} min.",
                "Added as an extra mode option for flexible point-to-point travel.",
            ]
            if climate_label in {"very_hot", "rainy"}:
                ride_share_score -= 2
                ride_share_notes.append("Climate favors covered ride-share travel.")
            ride_share_score -= self._memory_bonus(memories, "ride_share")
            options.append(
                ModeOption(
                    mode="ride_share",
                    duration_min=ride_share_duration,
                    distance_km=d_km,
                    score=ride_share_score,
                    notes=ride_share_notes,
                )
            )

        if cycling.success and not avoid_two_wheeler:
            c_km = cycling.data["distance_m"] / 1000.0
            c_min = cycling.data["duration_s"] / 60.0
            score = c_min
            notes = [f"Two-wheeler (cycling profile) ETA from OSRM: {c_min:.1f} min."]
            if rain > 2:
                score += 8
                notes.append("Rain penalty applied for two-wheeler safety/comfort.")
            if wind > 25:
                score += 4
                notes.append("High wind penalty applied for two-wheeler stability.")
            if temp > 38:
                score += 3
                notes.append("Very hot weather penalty applied.")
            score -= self._memory_bonus(memories, "two_wheeler")
            options.append(
                ModeOption(
                    mode="two_wheeler",
                    duration_min=c_min,
                    distance_km=c_km,
                    score=score,
                    notes=notes,
                )
            )
        elif cycling.success and avoid_two_wheeler:
            options.append(
                ModeOption(
                    mode="two_wheeler",
                    duration_min=cycling.data["duration_s"] / 60.0,
                    distance_km=cycling.data["distance_m"] / 1000.0,
                    score=10_000.0,
                    notes=[f"Avoided due to climate condition: {climate_label}."],
                )
            )

        options.sort(key=lambda x: x.score)
        return options, climate_label, public_transport_assessment

    @staticmethod
    def _memory_bonus(memories: List[MemoryMatch], mode: str) -> float:
        bonus = 0.0
        for memory in memories:
            if memory.recommended_mode == mode:
                bonus += memory.score * 2.5
        return min(bonus, 6.0)

    @staticmethod
    def _classify_climate(temp: float, rain: float) -> str:
        if rain >= 2.0:
            return "rainy"
        if temp >= 36.0:
            return "very_hot"
        if temp <= 8.0:
            return "very_cold"
        if temp <= 18.0:
            return "cool"
        return "pleasant"

    @staticmethod
    def _suggest_public_transport_mode(distance_km: float) -> str:
        if distance_km < 5:
            return "city_bus"
        if distance_km < 18:
            return "metro + feeder_bus"
        return "intercity_bus_or_train"

    @staticmethod
    def _public_transport_comfort(climate_label: str, passengers: int) -> str:
        base = "medium"
        if climate_label in {"very_hot", "rainy"}:
            base = "low"
        elif climate_label in {"cool", "pleasant"}:
            base = "high"
        if passengers > 3 and base == "high":
            return "medium"
        return base


class ExplainerAgent:
    def explain(self, ranked_options: List[ModeOption]) -> str:
        best = ranked_options[0]
        alternatives = ", ".join(
            f"{item.mode} ({item.duration_min:.1f} min, score={item.score:.1f})"
            for item in ranked_options[1:]
        )
        reasons = " ".join(best.notes)
        if alternatives:
            return f"Selected {best.mode} because {reasons} Alternatives considered: {alternatives}."
        return f"Selected {best.mode} because {reasons}"


def _fmt_tool(result: ToolResult) -> str:
    if result.success:
        if result.error:
            return f"{result.name}: success ({result.error})"
        return f"{result.name}: success"
    return f"{result.name}: failed ({result.error})"


def build_route_for_mode(selected_mode: str, evidence: Dict[str, object]) -> tuple[str, str]:
    driving: ToolResult = evidence["driving"]  # type: ignore[assignment]
    cycling: ToolResult = evidence["cycling"]  # type: ignore[assignment]
    if selected_mode == "two_wheeler" and cycling.success:
        route_data = cycling.data
    else:
        route_data = driving.data if driving.success else cycling.data
    route_id = str(route_data.get("route_id", "RT-NA-0000-0"))
    route_path = route_data.get("route_path", [])
    if isinstance(route_path, list) and route_path:
        return route_id, " - ".join(str(node) for node in route_path)
    return route_id, "Route path unavailable"
