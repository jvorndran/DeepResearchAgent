"""Compatibility wrappers around shared tool-call helpers."""
from typing import Any

from ..tool_utils import (
    message_tool_name,
    state_messages,
    tool_call_args,
    tool_call_id,
    tool_call_name,
    tool_name,
)


def _tool_name(tool: Any) -> str | None:
    return tool_name(tool)


def _tool_call_name(tool_call: Any) -> str | None:
    return tool_call_name(tool_call)


def _tool_call_id(tool_call: Any) -> str:
    return tool_call_id(tool_call, "quant-developer-blocked-tool")


def _tool_call_args(tool_call: Any) -> dict[str, Any]:
    return tool_call_args(tool_call)


def _message_tool_name(message: Any) -> str | None:
    return message_tool_name(message)


def _state_messages(state: Any) -> list[Any]:
    return state_messages(state)
