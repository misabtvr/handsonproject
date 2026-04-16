from __future__ import annotations

from app.agents import AgentOutput, ExplainerAgent, MemoryAgent, PlannerAgent, ResearchAgent, build_route_for_mode
from app.memory import MemoryStore
from app.tools import ToolClient


class RoutePredictorPipeline:
    """End-to-end orchestrator with explicit agent handoff."""

    def __init__(self) -> None:
        self.memory_store = MemoryStore()
        self.tools = ToolClient()
        self.memory_agent = MemoryAgent(self.memory_store)
        self.research_agent = ResearchAgent(self.tools)
        self.planner_agent = PlannerAgent()
        self.explainer_agent = ExplainerAgent()

    def run(self, source: str, destination: str, passengers: int = 1) -> AgentOutput:
        normalized_passengers = max(1, passengers)
        memories = self.memory_agent.recall(source, destination)
        evidence = self.research_agent.collect(source, destination)
        ranked_options, climate_label, public_transport_assessment = self.planner_agent.decide(
            evidence, memories, normalized_passengers
        )
        if not ranked_options:
            raise RuntimeError("No route options could be produced.")

        top = ranked_options[0]
        reason = self.explainer_agent.explain(ranked_options)
        best_route_id, best_route_path = build_route_for_mode(top.mode, evidence)

        self.memory_store.save_trip(
            source=source,
            destination=destination,
            recommended_mode=top.mode,
            reason=reason,
        )

        return AgentOutput(
            source_display=evidence["source_geo"]["display_name"],
            destination_display=evidence["destination_geo"]["display_name"],
            selected_mode=top.mode,
            selected_reason=reason,
            all_options=ranked_options,
            similar_memories=memories,
            tool_log=evidence["tool_log"],
            climate_label=climate_label,
            public_transport_assessment=public_transport_assessment,
            best_route_id=best_route_id,
            best_route_path=best_route_path,
        )
