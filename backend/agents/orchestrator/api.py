"""Public orchestrator API."""
from .common import (
    Any,
    AsyncIterator,
    ClientSession,
    Dict,
    FredMCPRequiredError,
    MCPTimeoutError,
    ResearchContext,
    _BACKEND_DIR,
    asyncio,
    logger,
    resolve_graph_input,
)
from .factory import create_orchestrator
from .nodes import _fred_setup_error_payload, _is_transient_stream_error

# PUBLIC API FUNCTIONS
# =============================================================================


async def run_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Run the complete research workflow and return final results.

    This is the main entrypoint for executing a research job.

    Args:
        query: The research query from the user
        job_id: Unique identifier for this research job
        messages: Optional full message history for multi-turn conversations.
                  When provided, overrides the default single-message format.

    Returns:
        Dict containing:
        - status: "completed" or "failed"
        - job_id: The job identifier
        - response: The final response content
        - result: Full result object from the agent
        - error: Error message if failed

    Example:
        >>> result = await run_research(
        ...     query="Analyze correlation between TSMC capex and wafer shipments",
        ...     job_id="abc123"
        ... )
        >>> print(result["status"])
        'completed'
    """
    try:
        import agents.orchestrator as public_orchestrator

        if agent is None:
            agent_factory = getattr(public_orchestrator, "create_orchestrator", create_orchestrator)
            agent = await agent_factory()

        if messages is None:
            messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

        ctx = ResearchContext(
            job_id=job_id,
            output_dir=str(_BACKEND_DIR / "outputs" / job_id),
            data_dir=str(_BACKEND_DIR / "data" / job_id),
            user_id=user_id,
        )

        config = {"configurable": {"thread_id": job_id}}

        graph_input_resolver = getattr(public_orchestrator, "resolve_graph_input", resolve_graph_input)
        graph_input = await graph_input_resolver(agent, config, messages)
        result = await agent.ainvoke(graph_input, context=ctx, config=config)

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                content = last_message.content
                if isinstance(content, list):
                    # Extract text parts from content blocks
                    text_parts = [
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    ]
                    response_content = "".join(text_parts)
                else:
                    response_content = str(content)
            else:
                response_content = str(last_message)

            return {
                "status": "completed",
                "job_id": job_id,
                "response": response_content,
                "result": result,
            }

        return {"status": "completed", "job_id": job_id, "result": result}

    except FredMCPRequiredError as e:
        error = _fred_setup_error_payload(e)
        return {
            "status": "failed",
            "job_id": job_id,
            "error": error["message"],
            "error_type": error["type"],
            "phase": error["phase"],
            "retryable": error["retryable"],
            "agent_recoverable": error["agent_recoverable"],
            "hint": error["hint"],
        }
    except MCPTimeoutError as e:
        return {"status": "failed", "job_id": job_id, "error": f"MCP timeout: {e}"}
    except Exception as e:
        return {"status": "failed", "job_id": job_id, "error": str(e)}


async def stream_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
    user_id: str | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream the research workflow progress in real-time.

    Use this for WebSocket connections or when you want to show
    live progress updates to the user.

    Args:
        query: The research query from the user
        job_id: Unique identifier for this research job
        messages: Optional full message history for multi-turn conversations.
                  When provided, overrides the default single-message format.

    Yields:
        Dict events from the agent execution showing:
        - Tool calls being made
        - Subagent delegations
        - Progress through the workflow

    Example:
        >>> async for event in stream_research(query="...", job_id="abc123"):
        ...     print(event)
    """
    try:
        import agents.orchestrator as public_orchestrator

        if agent is None:
            agent_factory = getattr(public_orchestrator, "create_orchestrator", create_orchestrator)
            agent = await agent_factory()

        if messages is None:
            messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

        ctx = ResearchContext(
            job_id=job_id,
            output_dir=str(_BACKEND_DIR / "outputs" / job_id),
            data_dir=str(_BACKEND_DIR / "data" / job_id),
            user_id=user_id,
        )

        config = {"configurable": {"thread_id": job_id}}

        graph_input_resolver = getattr(public_orchestrator, "resolve_graph_input", resolve_graph_input)
        graph_input = await graph_input_resolver(agent, config, messages)

        max_retries = 3
        retry_delay = 2
        for attempt in range(max_retries + 1):
            try:
                # If we are retrying (attempt > 0), pass None as graph input to resume
                # from the last checkpoint.
                current_input = graph_input if attempt == 0 else None
                async for event in agent.astream(
                    current_input,
                    context=ctx,
                    config=config,
                    stream_mode=["updates", "messages", "custom"],
                    subgraphs=True,
                    version="v2",
                ):
                    yield event
                break  # Success
            except Exception as e:
                is_transient = _is_transient_stream_error(e)
                if is_transient and attempt < max_retries:
                    logger.warning(
                        "Transient model stream error for job %s (attempt %d/%d): %s. Retrying in %ds...",
                        job_id,
                        attempt + 1,
                        max_retries,
                        e,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise
    except FredMCPRequiredError as e:
        yield {"error": _fred_setup_error_payload(e)}
    except MCPTimeoutError as e:
        yield {"error": {"type": "mcp_timeout", "message": str(e)}}
