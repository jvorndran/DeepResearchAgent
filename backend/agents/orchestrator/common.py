"""Shared imports and constants for orchestrator modules."""
import asyncio
import json
import logging
import os
import re
import warnings
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Dict, TypedDict

import google.genai.errors
import httpx
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import interrupt
from mcp import ClientSession

from core.context import ResearchContext
from ..chat_surface_tool import emit_chat_message
from ..data_engineer import FredMCPRequiredError, MCPTimeoutError, get_data_engineer_subagent
from ..graph_input import resolve_graph_input
from ..intake import emit_approval_message_node, evaluate_intake_node, intake_chat_node
from ..subagents_registry import GENERAL_PURPOSE_SUBAGENT, SPECIALIST_SUBAGENTS_STATIC

__all__ = [
    "AIMessage",
    "AgentMiddleware",
    "Annotated",
    "Any",
    "AnyMessage",
    "AsyncIterator",
    "Awaitable",
    "Callable",
    "ClientSession",
    "Dict",
    "END",
    "EditResult",
    "ExecuteResponse",
    "FredMCPRequiredError",
    "GENERAL_PURPOSE_SUBAGENT",
    "GlobResult",
    "GrepResult",
    "HumanMessage",
    "LocalShellBackend",
    "LsResult",
    "MCPTimeoutError",
    "MemorySaver",
    "ModelRequest",
    "ModelResponse",
    "ReadResult",
    "ResearchContext",
    "SPECIALIST_SUBAGENTS_STATIC",
    "START",
    "StateGraph",
    "ToolCallRequest",
    "ToolMessage",
    "TypedDict",
    "WriteResult",
    "_BACKEND_DIR",
    "_CHECKPOINTER",
    "_SAFE_SHELL_ENV",
    "_SECRET_SHELL_RE",
    "_SENSITIVE_DIR_PARTS",
    "_SENSITIVE_PATH_PARTS",
    "_WORKSPACE_DIR",
    "add_messages",
    "asyncio",
    "create_deep_agent",
    "emit_approval_message_node",
    "emit_chat_message",
    "evaluate_intake_node",
    "get_data_engineer_subagent",
    "google",
    "httpx",
    "intake_chat_node",
    "interrupt",
    "json",
    "logger",
    "resolve_graph_input",
]

logger = logging.getLogger(__name__)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings",
    category=UserWarning,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_WORKSPACE_DIR = _BACKEND_DIR.parent
_CHECKPOINTER = MemorySaver()

_SAFE_SHELL_ENV = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "PYTHONPATH": str(_BACKEND_DIR),
}

_SENSITIVE_PATH_PARTS = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".envrc",
    ".netrc",
    ".pypirc",
    ".npmrc",
    ".docker/config.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_SENSITIVE_DIR_PARTS = {".ssh", ".gnupg", ".aws", ".azure", ".config/gcloud"}
_SECRET_SHELL_RE = re.compile(
    r"(?ix)"
    r"(^|[\s;&|()])("
    r"env|printenv|set|export"
    r")($|[\s;&|()])"
    r"|"
    r"(^|[/\s;&|()])("
    r"\.env(?:\.[\w-]+)?|\.envrc|\.netrc|\.pypirc|\.npmrc|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519"
    r")($|[/\s;&|()])"
    r"|"
    r"(^|[/\s;&|()])("
    r"\.ssh|\.gnupg|\.aws|\.azure|\.config/gcloud"
    r")($|[/\s;&|()])"
)
