"""Shared helpers for LangChain/OpenAI-style tool and message envelopes."""
import json
from typing import Any


def tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        name = tool.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def tool_call_name(tool_call: Any) -> str | None:
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        if isinstance(name, str):
            return name
        function = tool_call.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        return None
    name = getattr(tool_call, "name", None)
    return name if isinstance(name, str) else None


def tool_call_id(tool_call: Any, default: str = "blocked-tool") -> str:
    if isinstance(tool_call, dict):
        value = tool_call.get("id") or tool_call.get("tool_call_id")
        return str(value or default)
    return str(
        getattr(tool_call, "id", None)
        or getattr(tool_call, "tool_call_id", None)
        or default
    )


def tool_call_args(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            return args
        function = tool_call.get("function")
        if isinstance(function, dict):
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                return arguments
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    args = getattr(tool_call, "args", None)
    return args if isinstance(args, dict) else {}


def message_tool_name(message: Any) -> str | None:
    name = getattr(message, "name", None)
    if isinstance(name, str):
        return name
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        value = additional_kwargs.get("name")
        if isinstance(value, str):
            return value
    return None


def state_messages(state: Any) -> list[Any]:
    if isinstance(state, dict):
        value = state.get("messages")
    else:
        value = getattr(state, "messages", None)
    return list(value or [])
