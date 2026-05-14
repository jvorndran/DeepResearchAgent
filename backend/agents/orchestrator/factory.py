"""Execution-agent and parent graph factories."""

from pathlib import Path

from .common import (
    ClientSession,
    END,
    ResearchContext,
    START,
    StateGraph,
    _BACKEND_DIR,
    _CHECKPOINTER,
    _SAFE_SHELL_ENV,
    _WORKSPACE_DIR,
    create_deep_agent,
    emit_chat_message,
    emit_approval_message_node,
    evaluate_intake_node,
    get_data_engineer_subagent,
    intake_chat_node,
    GENERAL_PURPOSE_SUBAGENT,
    SPECIALIST_SUBAGENTS_STATIC,
    ToolMessage,
)
from .middleware import (
    GuardedLocalShellBackend,
    _HIDE_TODO_TOOL_MIDDLEWARE,
    _STRIP_TOOL_CALL_CONTENT_MIDDLEWARE,
    OrchestratorToolBoundaryMiddleware,
    _with_hidden_todo_tool,
)
from .nodes import (
    approval_gate_node,
    prepare_execution_node,
    route_after_approval,
    route_after_evaluate,
    route_by_phase,
)
from .prompts import EXECUTION_SYSTEM_PROMPT
from .state import OrchestratorState
from .toolbox_router import route_toolbox_node

# =============================================================================
# AGENT FACTORIES
# =============================================================================

_ORCHESTRATOR_SKILLS_DIR = (_BACKEND_DIR / "skills" / "orchestrator").resolve()


def _is_orchestrator_skill_file(file_path: object) -> bool:
    try:
        path = Path(str(file_path)).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return path.name == "SKILL.md" and path.is_relative_to(_ORCHESTRATOR_SKILLS_DIR)


class OrchestratorSkillBoundaryMiddleware(OrchestratorToolBoundaryMiddleware):
    """Allow only native orchestrator skill reads plus status/delegation tools."""

    _ALLOWED_TOOL_NAMES = {"emit_chat_message", "task", "read_file"}

    def _enforce_tool_boundary(self, request):
        tool_call = request.tool_call
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
        if tool_name != "read_file":
            return super()._enforce_tool_boundary(request)

        args = self._tool_call_args(request.tool_call)
        file_path = args.get("file_path") if isinstance(args, dict) else None
        if _is_orchestrator_skill_file(file_path):
            return None

        return ToolMessage(
            content=(
                "Blocked orchestrator tool `read_file`. The top-level execution "
                "agent may read only orchestrator skill `SKILL.md` files for "
                "progressive disclosure; it must not inspect artifacts, generated "
                "code, data files, or repository files directly. Delegate artifact "
                "work to the appropriate specialist."
            ),
            name="read_file",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )


_ORCHESTRATOR_SKILL_BOUNDARY_MIDDLEWARE = OrchestratorSkillBoundaryMiddleware()


async def _create_execution_agent(fred_session: ClientSession | None = None):
    """Full deep agent for the pipeline execution phase.

    Has all subagents (data-engineer, quant-developer, technical-writer,
    quality-analyst) and the ``task()`` tool. No intake / approval tools.
    ``interrupt_on`` is intentionally unset so subagents do not inherit
    interrupt behavior that would pause file/shell work.
    """
    import agents.orchestrator as public_orchestrator

    data_engineer_factory = getattr(
        public_orchestrator, "get_data_engineer_subagent", get_data_engineer_subagent
    )
    deep_agent_factory = getattr(public_orchestrator, "create_deep_agent", create_deep_agent)
    data_engineer = await data_engineer_factory(fred_session=fred_session)

    return deep_agent_factory(
        model="deepseek:deepseek-chat",
        system_prompt=EXECUTION_SYSTEM_PROMPT,
        tools=[emit_chat_message],
        middleware=[
            _HIDE_TODO_TOOL_MIDDLEWARE,
            _ORCHESTRATOR_SKILL_BOUNDARY_MIDDLEWARE,
            _STRIP_TOOL_CALL_CONTENT_MIDDLEWARE,
        ],
        subagents=[
            _with_hidden_todo_tool(GENERAL_PURPOSE_SUBAGENT),
            _with_hidden_todo_tool(data_engineer),
            *[_with_hidden_todo_tool(subagent) for subagent in SPECIALIST_SUBAGENTS_STATIC],
        ],
        backend=GuardedLocalShellBackend(
            root_dir=_WORKSPACE_DIR,
            virtual_mode=False,
            env=_SAFE_SHELL_ENV,
            inherit_env=False,
        ),
        context_schema=ResearchContext,
        # No checkpointer — parent graph owns the checkpoint.
        skills=[str(_ORCHESTRATOR_SKILLS_DIR)],
        memory=[str(_BACKEND_DIR / "AGENTS.md")],
        name="orchestrator",
    )


# =============================================================================
# CREATE ORCHESTRATOR (parent StateGraph)
# =============================================================================


async def create_orchestrator(fred_session: ClientSession | None = None):
    """Build the deterministic orchestrator pipeline.

    Returns a compiled ``StateGraph`` with nodes:
    evaluate_intake → route_toolbox → emit_approval_message → approval_gate
                    → prepare_execution → execute
                    ↘ intake_chat → END when clarification is needed

    Complete requests skip ``intake_chat`` so explicit prompts do not burn
    message budget on streamed clarification text before approval, but still
    emit the deterministic approval prompt the frontend uses for the
    "Commence Deep Research" affordance.

    **FRED MCP is required** for the data-engineer subagent used in the
    execution phase.
    """
    execution_agent = await _create_execution_agent(fred_session=fred_session)

    graph = StateGraph(OrchestratorState, context_schema=ResearchContext)

    # --- nodes ---
    graph.add_node("intake_chat", intake_chat_node)
    graph.add_node("evaluate_intake", evaluate_intake_node)
    graph.add_node("route_toolbox", route_toolbox_node)
    graph.add_node("emit_approval_message", emit_approval_message_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("prepare_execution", prepare_execution_node)
    graph.add_node("execute", execution_agent)

    # --- edges ---
    graph.add_conditional_edges(
        START,
        route_by_phase,
        {
            "intake": "evaluate_intake",
            "executing": "prepare_execution",
        },
    )
    graph.add_conditional_edges(
        "evaluate_intake",
        route_after_evaluate,
        {
            "needs_more": "intake_chat",
            "complete": "route_toolbox",
        },
    )
    graph.add_edge("intake_chat", END)
    graph.add_edge("route_toolbox", "emit_approval_message")
    graph.add_edge("emit_approval_message", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "executing": "prepare_execution",
            "intake": "evaluate_intake",
        },
    )
    graph.add_edge("prepare_execution", "execute")
    graph.add_edge("execute", END)

    return graph.compile(
        checkpointer=_CHECKPOINTER,
    ).with_config(
        {
            "recursion_limit": 9_999,
            "metadata": {"lc_agent_name": "orchestrator"},
        }
    )
