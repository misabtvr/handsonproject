from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

@dataclass
class ToolResult:
    name: str
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class ToolClient:
    """Wraps all external API calls used by agents."""

    def __init__(self, timeout_seconds: int = 12) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = "route-predictor-agent/1.0"
        self._offline_coords = {
            "bangalore": (12.9716, 77.5946),
            "bengaluru": (12.9716, 77.5946),
            "mysore": (12.2958, 76.6394),
            "kochi": (9.9312, 76.2673),
            "palakkad": (10.7867, 76.6548),
            "coimbatore": (11.0168, 76.9558),
            "salem": (11.6643, 78.1460),
            "chennai": (13.0827, 80.2707),
            "hyderabad": (17.3850, 78.4867),
            "mumbai": (19.0760, 72.8777),
            "delhi": (28.6139, 77.2090),
            "pune": (18.5204, 73.8567),
        }
        self._route_hubs: List[Tuple[str, float, float]] = [
            ("Kochi", 9.9312, 76.2673),
            ("Thrissur", 10.5276, 76.2144),
            ("Palakkad", 10.7867, 76.6548),
            ("Coimbatore", 11.0168, 76.9558),
            ("Erode", 11.3410, 77.7172),
            ("Salem", 11.6643, 78.1460),
            ("Vellore", 12.9165, 79.1325),
            ("Chennai", 13.0827, 80.2707),
            ("Bangalore", 12.9716, 77.5946),
            ("Mysore", 12.2958, 76.6394),
            ("Madurai", 9.9252, 78.1198),
            ("Trichy", 10.7905, 78.7047),
            ("Pune", 18.5204, 73.8567),
            ("Mumbai", 19.0760, 72.8777),
            ("Hyderabad", 17.3850, 78.4867),
            ("Delhi", 28.6139, 77.2090),
        ]

    def _request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        request_url = f"{url}?{query}" if query else url
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(request_url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def geocode_location(self, query: str) -> ToolResult:
        try:
            payload = self._request_json(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
            )
            if not payload:
                return ToolResult(
                    name="geocode_location",
                    success=False,
                    data={},
                    error=f"No geocoding result for '{query}'.",
                )
            best = payload[0]
            return ToolResult(
                name="geocode_location",
                success=True,
                data={
                    "query": query,
                    "lat": float(best["lat"]),
                    "lon": float(best["lon"]),
                    "display_name": best.get("display_name", query),
                    "importance": best.get("importance", 0.0),
                    "raw_type": best.get("type", "unknown"),
                },
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            offline = self._offline_geocode(query)
            if offline:
                return ToolResult(
                    name="geocode_location",
                    success=True,
                    data=offline,
                    error=f"Live geocoder unavailable, used offline fallback: {exc}",
                )
            return ToolResult(
                name="geocode_location",
                success=False,
                data={},
                error=f"Geocoding request failed: {exc}",
            )

    def get_route(
        self,
        src_lon: float,
        src_lat: float,
        dst_lon: float,
        dst_lat: float,
        profile: str,
        source_label: str = "source",
        destination_label: str = "destination",
    ) -> ToolResult:
        try:
            payload = self._request_json(
                f"https://router.project-osrm.org/route/v1/{profile}/{src_lon},{src_lat};{dst_lon},{dst_lat}",
                params={"overview": "full", "geometries": "geojson", "alternatives": "false", "steps": "false"},
            )
            routes = payload.get("routes", [])
            if not routes:
                return ToolResult(
                    name=f"route_{profile}",
                    success=False,
                    data={},
                    error=f"No route returned for profile '{profile}'.",
                )
            top_route = routes[0]
            geometry_points = top_route.get("geometry", {}).get("coordinates", [])
            route_path = self._build_route_path(
                geometry_points=geometry_points,
                source_label=source_label,
                destination_label=destination_label,
            )
            return ToolResult(
                name=f"route_{profile}",
                success=True,
                data={
                    "profile": profile,
                    "distance_m": top_route["distance"],
                    "duration_s": top_route["duration"],
                    "route_path": route_path,
                    "route_id": self._build_route_id(profile=profile, route_path=route_path),
                },
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            distance_m = self._haversine_m(src_lat, src_lon, dst_lat, dst_lon)
            speed_kmh = {"driving": 38.0, "cycling": 17.0}.get(profile, 22.0)
            duration_s = (distance_m / 1000.0) / speed_kmh * 3600.0
            return ToolResult(
                name=f"route_{profile}",
                success=True,
                data={
                    "profile": profile,
                    "distance_m": distance_m,
                    "duration_s": duration_s,
                    "fallback": True,
                    "route_path": self._build_route_path(
                        geometry_points=[[src_lon, src_lat], [dst_lon, dst_lat]],
                        source_label=source_label,
                        destination_label=destination_label,
                    ),
                    "route_id": self._build_route_id(
                        profile=profile,
                        route_path=[source_label.title(), destination_label.title()],
                    ),
                },
                error=f"OSRM unavailable, used offline estimate: {exc}",
            )
        except Exception as exc:  # Defensive catch for unknown API responses.
            return ToolResult(
                name=f"route_{profile}",
                success=False,
                data={},
                error=f"OSRM route request failed: {exc}",
            )

    def get_weather(self, lat: float, lon: float) -> ToolResult:
        try:
            payload = self._request_json(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,precipitation,wind_speed_10m",
                },
            )
            current = payload.get("current")
            if not current:
                return ToolResult(
                    name="get_weather",
                    success=False,
                    data={},
                    error="Weather API returned no current conditions.",
                )
            return ToolResult(
                name="get_weather",
                success=True,
                data={
                    "temperature_c": current.get("temperature_2m"),
                    "precipitation_mm": current.get("precipitation"),
                    "wind_kmh": current.get("wind_speed_10m"),
                },
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            return ToolResult(
                name="get_weather",
                success=True,
                data={"temperature_c": 29.0, "precipitation_mm": 0.0, "wind_kmh": 12.0, "fallback": True},
                error=f"Weather API unavailable, used offline weather fallback: {exc}",
            )
        except Exception as exc:  # Defensive catch for unknown API responses.
            return ToolResult(
                name="get_weather",
                success=False,
                data={},
                error=f"Weather request failed: {exc}",
            )

    def _offline_geocode(self, query: str) -> Optional[Dict[str, Any]]:
        key = query.strip().lower()
        coords = self._offline_coords.get(key)
        if coords:
            return {
                "query": query,
                "lat": coords[0],
                "lon": coords[1],
                "display_name": f"{query} (offline fallback)",
                "importance": 0.5,
                "raw_type": "city",
                "fallback": True,
            }
        return None

    def _build_route_path(
        self,
        geometry_points: List[List[float]],
        source_label: str,
        destination_label: str,
    ) -> List[str]:
        cleaned_source = source_label.split(",")[0].strip().title()
        cleaned_dest = destination_label.split(",")[0].strip().title()
        if not geometry_points:
            return [cleaned_source, cleaned_dest]

        selected_hubs: List[str] = []
        total = len(geometry_points)
        if total > 2:
            checkpoints = [geometry_points[min(round((total - 1) * r), total - 1)] for r in (0.25, 0.5, 0.75)]
            for lon, lat in checkpoints:
                best_name = ""
                best_dist = 10_000_000.0
                for name, hub_lat, hub_lon in self._route_hubs:
                    dist = self._haversine_m(lat, lon, hub_lat, hub_lon)
                    if dist < best_dist:
                        best_dist = dist
                        best_name = name
                if (
                    best_name
                    and best_dist <= 95_000
                    and best_name not in selected_hubs
                    and best_name not in {cleaned_source, cleaned_dest}
                ):
                    selected_hubs.append(best_name)
        else:
            src_lon, src_lat = geometry_points[0]
            dst_lon, dst_lat = geometry_points[-1]
            corridor_hubs: List[Tuple[float, str]] = []
            for name, hub_lat, hub_lon in self._route_hubs:
                if name in {cleaned_source, cleaned_dest}:
                    continue
                projection, dist = self._projection_and_distance_to_segment(
                    src_lat, src_lon, dst_lat, dst_lon, hub_lat, hub_lon
                )
                if 0.1 <= projection <= 0.9 and dist <= 60_000:
                    corridor_hubs.append((projection, name))
            corridor_hubs.sort(key=lambda x: x[0])
            selected_hubs = [name for _, name in corridor_hubs[:3]]
        return [cleaned_source, *selected_hubs, cleaned_dest]

    @staticmethod
    def _build_route_id(profile: str, route_path: List[str]) -> str:
        compact = "".join(word[0] for word in route_path if word).upper()
        mode = "CAR" if profile == "driving" else "2W"
        return f"RT-{mode}-{compact[:8]}-{len(route_path)}"

    @staticmethod
    def _projection_and_distance_to_segment(
        lat1: float, lon1: float, lat2: float, lon2: float, latp: float, lonp: float
    ) -> Tuple[float, float]:
        ax = lon1
        ay = lat1
        bx = lon2
        by = lat2
        px = lonp
        py = latp
        abx = bx - ax
        aby = by - ay
        ab_sq = abx * abx + aby * aby
        if ab_sq == 0:
            return 0.0, ToolClient._haversine_m(lat1, lon1, latp, lonp)
        apx = px - ax
        apy = py - ay
        t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_sq))
        closest_x = ax + t * abx
        closest_y = ay + t * aby
        dist_m = ToolClient._haversine_m(closest_y, closest_x, latp, lonp)
        return t, dist_m

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_m = 6_371_000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius_m * c
