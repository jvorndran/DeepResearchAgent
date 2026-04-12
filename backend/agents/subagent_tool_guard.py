from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


class ToolBlocklistMiddleware(AgentMiddleware):
    """Reject disallowed tool calls before they reach the backend."""

    def __init__(self, blocked_tools: Iterable[str], reason: str) -> None:
        self._blocked_tools = frozenset(blocked_tools)
        self._reason = reason

    def _maybe_block(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_name = request.tool_call.get("name", "")
        if tool_name not in self._blocked_tools:
            return None

        return ToolMessage(
            content=(
                f"Tool '{tool_name}' is unavailable for this subagent. {self._reason}"
            ),
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return await handler(request)


FILESYSTEM_AND_SHELL_TOOLS = (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "execute",
)

