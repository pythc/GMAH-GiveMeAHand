"""LangGraph runtime adapter for session turns."""

import importlib
from typing import Any

from agent_workflow.orchestrator.models import RunSessionRequest, RunSessionResult
from agent_workflow.orchestrator.service import SessionOrchestrator


class LangGraphRuntimeError(RuntimeError):
    """Raised when LangGraph cannot be loaded or invoked."""


class LangGraphSessionRuntime:
    """Execute session turns through an actual LangGraph state graph."""

    def __init__(self, orchestrator: SessionOrchestrator) -> None:
        self.orchestrator = orchestrator
        self._graph = self._compile_graph()

    def run(self, request: RunSessionRequest) -> RunSessionResult:
        payload = self._graph.invoke({"request": request.model_dump(mode="json")})
        result_payload = payload.get("result")
        if not isinstance(result_payload, dict):
            raise LangGraphRuntimeError("LangGraph turn did not return a result payload")
        return RunSessionResult.model_validate(result_payload)

    def _compile_graph(self) -> Any:
        try:
            graph_module = importlib.import_module("langgraph.graph")
        except ImportError as exc:  # pragma: no cover - dependency is installed in normal envs.
            raise LangGraphRuntimeError("langgraph is not installed") from exc

        state_graph = graph_module.StateGraph(dict)
        end = graph_module.END

        def run_turn(state: dict[str, Any]) -> dict[str, Any]:
            request_payload = state.get("request")
            request = RunSessionRequest.model_validate(request_payload)
            result = self.orchestrator.run(request)
            return {"result": result.model_dump(mode="json")}

        state_graph.add_node("run_turn", run_turn)
        state_graph.set_entry_point("run_turn")
        state_graph.add_edge("run_turn", end)
        return state_graph.compile()
