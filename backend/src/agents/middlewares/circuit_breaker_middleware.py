import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class CircuitBreakerMiddlewareState(AgentState):
    pass


class CircuitBreakerMiddleware(AgentMiddleware[CircuitBreakerMiddlewareState]):
    state_schema = CircuitBreakerMiddlewareState

    def _apply(self, state: AgentState) -> dict | None:
        cb = state.get("circuit_breaker") or {}
        if not cb or not cb.get("triggered"):
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        blocked_indices: list[int] = []
        first_blocked_id: str | None = None
        for i, tc in enumerate(tool_calls):
            if tc.get("name") != "task":
                continue
            args = tc.get("args") or {}
            subagent_type = args.get("subagent_type")
            if subagent_type in {"composer_agent", "composer"}:
                blocked_indices.append(i)
                if first_blocked_id is None:
                    first_blocked_id = tc.get("id")

        if not blocked_indices:
            return None

        reasons = cb.get("reasons") or []
        confidence_score = cb.get("confidence_score")
        posterior = cb.get("posterior_risk")
        industry = cb.get("industry")
        question = "Circuit breaker triggered. Please provide more independent signals or request a manual review."
        context = f"blocked_briefing=true, industry={industry}, posterior={posterior}, confidence={confidence_score}, reasons={reasons}"

        replacement_id = first_blocked_id or (tool_calls[blocked_indices[0]].get("id") if blocked_indices else "circuit_breaker")
        ask_tc = {
            "name": "ask_clarification",
            "id": replacement_id,
            "args": {
                "question": question,
                "clarification_type": "missing_info",
                "context": context,
                "options": ["Provide more signals", "Request manual review"],
            },
        }

        kept_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in set(blocked_indices)]
        kept_tool_calls.insert(0, ask_tc)

        updated_msg = last_msg.model_copy(update={"tool_calls": kept_tool_calls})
        logger.info("Circuit breaker blocked %d composer task call(s) and requested clarification", len(blocked_indices))
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)
