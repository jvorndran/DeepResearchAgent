"""Middleware guardrails for the quantitative developer subagent."""
import ast
from collections.abc import Awaitable, Callable
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from .constants import (
    _AFTER_WRITE_TOOL_NAMES,
    _BACKEND_DIR,
    _DATA_FILE_SUFFIXES,
    _FIRST_WRITE_TOOL_NAMES,
    _INSPECTION_TOOL_NAMES,
    _MAX_ANALYSIS_SCRIPT_CHARS,
    _MAX_ANALYSIS_SCRIPT_LINES,
    _TRUNCATED_ARGUMENT_MARKERS,
)
from .handoff import (
    _has_successful_quant_handoff,
    _has_written_analysis_script,
    _is_final_prewrite_opportunity,
    _latest_successful_quant_handoff_content,
    _prewrite_failure_handoff,
    _should_stop_prewrite_loop,
)
from .path_helpers import (
    _is_allowed_analysis_script_path,
    _job_id_from_request,
    _required_script_path_hint,
)
from .script_inspection import (
    _align_period_output_period_reference,
    _calls_named,
    _extract_data_files_manifest,
    _forecast_handoff_preserved,
    _has_empty_list_call_arg,
    _imports_forbidden_forecast_library,
    _literal_string_arg,
    _looped_direct_forecasts_without_backtest_skip,
    _needs_period_alignment_guard,
    _python_tree_for_write,
    _request_with_tool_content,
    _rewrite_manifest_paths,
    _unique_existing_sibling_data_path,
)
from .tool_utils import (
    _state_messages,
    _tool_call_args,
    _tool_call_id,
    _tool_call_name,
    _tool_name,
)

class QuantDeveloperToolBoundaryMiddleware(AgentMiddleware):
    """Force quant-developer to write the analysis script before probing data."""

    def _allowed_tools(self, request: ModelRequest) -> set[str]:
        if _has_written_analysis_script(list(request.messages)):
            return _AFTER_WRITE_TOOL_NAMES
        return _FIRST_WRITE_TOOL_NAMES

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        if _has_successful_quant_handoff(list(request.messages)):
            return request.override(tools=[])
        allowed = self._allowed_tools(request)
        tools = [
            tool
            for tool in request.tools
            if (
                _tool_name(tool) in allowed
                and _tool_name(tool) not in _INSPECTION_TOOL_NAMES
            )
        ]
        if len(tools) == len(request.tools):
            return request
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if _should_stop_prewrite_loop(list(request.messages)):
            return ModelResponse(
                result=[
                    AIMessage(content=_prewrite_failure_handoff(list(request.messages)))
                ],
                structured_response=None,
            )
        filtered_request = self._filter_tools(request)
        response = handler(filtered_request)
        return self._force_compact_handoff_response(request, response)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if _should_stop_prewrite_loop(list(request.messages)):
            return ModelResponse(
                result=[
                    AIMessage(content=_prewrite_failure_handoff(list(request.messages)))
                ],
                structured_response=None,
            )
        filtered_request = self._filter_tools(request)
        response = await handler(filtered_request)
        return self._force_compact_handoff_response(request, response)

    def _force_compact_handoff_response(
        self, request: ModelRequest, response: ModelResponse
    ) -> ModelResponse:
        messages = list(request.messages)
        if _should_stop_prewrite_loop(messages):
            return ModelResponse(
                result=[AIMessage(content=_prewrite_failure_handoff(messages))],
                structured_response=getattr(response, "structured_response", None),
            )

        handoff = _latest_successful_quant_handoff_content(messages)
        if handoff is None or not isinstance(response, ModelResponse):
            return response
        return ModelResponse(
            result=[AIMessage(content=handoff)],
            structured_response=response.structured_response,
        )

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        path_hint = _required_script_path_hint(
            _job_id_from_request(request, "")
        )
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for quant-developer. "
                "First write a compact analysis.py from the provided data_files and "
                "schema_summary. Do not inspect CSVs with shell probes; put loading, "
                "validation, and chart generation inside analysis.py. After the first "
                "script write, use execute/read_file/edit_file only for running and "
                "repairing that script. Import `save_quant_outputs` from "
                "`agents.quant_macro_stats` for artifact serialization; do not import "
                "`agents.quant_utils`. For econometric forecast tasks, import "
                "`direct_ols_forecast` from `agents.quant_macro_stats` and do not "
                "import `statsmodels` or hand-roll OLS diagnostics. Do not read "
                "`agents/quant_macro_stats.py`; the helper signatures in your prompt "
                "and skill context are sufficient. If you call "
                "`direct_ols_forecast` inside a recursive pseudo-OOS validation loop, "
                "pass `run_backtests=False` in those repeated calls and run the full "
                "helper backtests once for the current forecast artifact. For broad macro + equity + "
                "regional + international requests, your next script must be under "
                "120 lines, FRED/helper-centered, and limited to at most four computed "
                "charts. If the user explicitly requested international peers, "
                "regional consumers, or company earnings risk and those CSVs are in "
                "`data_files`, include compact table-style summaries in "
                "`execution_summary` from the handed-off schemas; otherwise preserve "
                "unused paths under `execution_summary[\"source_context_files\"]`. "
                f"{path_hint} Your next assistant response should contain only the "
                "`write_file` tool call: exactly one `write_file` call to that path "
                "and no prose."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _script_budget_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None
        line_count = content.count("\n") + 1
        char_count = len(content)
        if (
            line_count <= _MAX_ANALYSIS_SCRIPT_LINES
            and char_count <= _MAX_ANALYSIS_SCRIPT_CHARS
        ):
            return None
        return ToolMessage(
            content=(
                "Blocked oversized quant analysis script before writing. "
                f"Proposed script has {line_count} lines and {char_count} characters; "
                f"limit is {_MAX_ANALYSIS_SCRIPT_LINES} lines and "
                f"{_MAX_ANALYSIS_SCRIPT_CHARS} characters. Rewrite a compact "
                "analysis.py under 120 lines. After three blocked drafts, the "
                "next write is the final compact rewrite opportunity before a "
                "failed handoff. Produce no more than four computed "
                "charts, prioritize recession-risk, unemployment outlook, scenario, "
                "and regime artifacts, use a small DATA_FILES subset containing "
                "only exact paths you will load. Include at most one compact "
                "non-FRED summary block when the user explicitly requested peer, "
                "state, or company metrics and matching World Bank, Census, SEC "
                "EDGAR, or BLS CSVs were handed off; otherwise preserve those paths "
                "under `execution_summary[\"source_context_files\"]`. Loop over DATA_FILES "
                "instead of repeating chart blocks, call "
                "`save_quant_outputs(output_dir, charts, execution_summary)`, and "
                "print only the compact handoff JSON. Use this minimum viable broad-macro "
                "shape: one DATA_FILES subset with FRED keys plus any explicitly "
                "required compact context CSVs, one `load_series` "
                "helper, one `series_frames` dict, one `align_period_features(...)` "
                "call, then helper calls for composite risk and either the "
                "historical-simulation path (`compare_analog_windows(...)`, "
                "`historical_scenario_replay(...)`, and/or "
                "`signal_framework_backtest(...)`) for prior-cycle, "
                "historical-simulation, replay, false-alarm, or pre-downturn "
                "evidence, or the direct forecast path "
                "when the user explicitly asks for a point forecast. Add scenario "
                "table or regime classification only when requested or clearly "
                "needed by the prompt. Do not add verbose SEC, "
                "Census, World Bank, BLS, company, state, or country parsing loops to "
                "the rewrite, and never leave requested provider sections as "
                "`not processed` placeholders when data_files include those sources. "
                "For explicit analog-window prompts such as `looks like 1995, 2001, "
                "2008, or 2020`, use the analog fast path instead of the full broad "
                "macro template: align the core FRED panel, call "
                "`compare_analog_windows(...)`, optionally call "
                "`summarize_sec_company_facts(path)` for AAPL/MSFT, make two or "
                "three charts from analog ranking/profile rows, then save. Do not "
                "add unemployment forecast, scenario, or regime-classifier helper "
                "calls unless the user explicitly asked for those artifacts. "
                "Do not inspect files before rewriting."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _script_path_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if _is_allowed_analysis_script_path(file_path):
            return None
        path_hint = _required_script_path_hint(_job_id_from_request(request, file_path))
        reason = "the target path is empty" if not file_path else (
            f"the target path `{file_path}` is outside the required code artifact location"
        )
        return ToolMessage(
            content=(
                "Blocked quant analysis script before writing because "
                f"{reason}. {path_hint} Do not write analysis scripts directly "
                "in the job output root."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _existing_initial_script_message(
        self, request: ToolCallRequest
    ) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        if _has_written_analysis_script(_state_messages(getattr(request, "state", None))):
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.replace("\\", "/").endswith("/code/analysis.py"):
            return None
        path = Path(file_path).expanduser()
        if not path.exists():
            return None
        fallback_path = path.with_name("analysis_v2.py")
        return ToolMessage(
            content=(
                "Blocked initial quant script write because `analysis.py` already "
                f"exists at `{path}` from an earlier quant attempt for this job. "
                f"Write one compact replacement script to `{fallback_path}` and "
                "execute that file. Still save final artifacts to the job output "
                "directory via `save_quant_outputs`; do not inspect, delete, or "
                "overwrite the existing `analysis.py` first."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _truncated_argument_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        content = args.get("content")
        if not isinstance(content, str):
            return None
        marker = next(
            (marker for marker in _TRUNCATED_ARGUMENT_MARKERS if marker in content),
            None,
        )
        if marker is None:
            return None
        return ToolMessage(
            content=(
                "Blocked quant analysis script before writing because the proposed "
                f"`write_file` content contains the tool-argument truncation marker "
                f"`{marker}`. This is not a recoverable script draft. Rewrite a much "
                "smaller complete analysis.py under 180 lines, with one DATA_FILES "
                "dictionary, small helper functions, and compact JSON outputs. Do not "
                "write, execute, delete, or patch a truncated placeholder file."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _python_static_lint_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None

        tree, syntax_error = _python_tree_for_write(content)
        if syntax_error is not None:
            location = (
                f"line {syntax_error.lineno}, column {syntax_error.offset}"
                if syntax_error.lineno is not None
                else "unknown location"
            )
            return ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because Python "
                    f"syntax validation failed at {location}: {syntax_error.msg}. "
                    "Rewrite a complete compact file before calling `write_file`; "
                    "do not rely on execute/read/edit cycles to close truncated "
                    "dicts, strings, or JSON handoff blocks."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )

        assert tree is not None
        for call in _calls_named(tree, "align_period_features"):
            if len(call.args) > 1:
                return ToolMessage(
                    content=(
                        "Blocked quant analysis script before writing because "
                        "`align_period_features` accepts only `series_frames` as a "
                        "positional argument. Use keyword arguments for the rest: "
                        'align_period_features(series_frames, frequency="M", '
                        'how="outer", timestamp_position="start", '
                        'fill_method="ffill", fill_limit=2).'
                    ),
                    name="write_file",
                    tool_call_id=_tool_call_id(request.tool_call),
                    status="error",
                )
        if period_ref_name := _align_period_output_period_reference(tree):
            return ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    f"`{period_ref_name}` is assigned from `align_period_features(...)` "
                    "and then read as if it has a `period` column. "
                    "`align_period_features` returns only `date` plus one column per "
                    "series key; use the returned `date` column for chart labels, "
                    "sorting, and forecast frames. Do not reference "
                    f"`{period_ref_name}[\"period\"]` or `{period_ref_name}.period`."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        for call in _calls_named(tree, "to_period"):
            freq = _literal_string_arg(call)
            if freq in {"ME", "QE"}:
                replacement = "M" if freq == "ME" else "Q"
                return ToolMessage(
                    content=(
                        "Blocked quant analysis script before writing because "
                        f"`to_period({freq!r})` uses a pandas resample alias. "
                        f"Use `to_period({replacement!r})` for Period conversion. "
                        "Keep `resample('ME')`/`resample('QE')` only for "
                        "resampling, then convert dates to period keys with "
                        "`to_period('M')` or `to_period('Q')`."
                    ),
                    name="write_file",
                    tool_call_id=_tool_call_id(request.tool_call),
                    status="error",
                )
        return None

    def _data_manifest_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None

        manifest = _extract_data_files_manifest(content)
        if not manifest:
            return None

        invalid: list[str] = []
        missing: list[str] = []
        for key, path_text in manifest.items():
            suffix = Path(path_text).suffix.lower()
            if suffix not in _DATA_FILE_SUFFIXES:
                invalid.append(f"{key} -> {path_text}")
                continue
            if not Path(path_text).expanduser().exists():
                missing.append(f"{key} -> {path_text}")
        if not invalid and not missing:
            return None

        details: list[str] = []
        if invalid:
            details.append("non-data extension: " + "; ".join(invalid[:4]))
        if missing:
            details.append("missing file: " + "; ".join(missing[:4]))
        return ToolMessage(
            content=(
                "Blocked quant analysis script before writing because its DATA_FILES "
                "manifest does not match existing data artifacts ("
                + " | ".join(details)
                + "). Copy exact CSV paths from the task description for only the "
                "DATA_FILES keys the script will load; do not mutate CSV paths into "
                "chart/image paths, hand-edit auto-save suffixes, or guess filenames."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _data_manifest_repair_request(
        self, request: ToolCallRequest
    ) -> ToolCallRequest | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None

        manifest = _extract_data_files_manifest(content)
        if not manifest:
            return None

        replacements: dict[str, str] = {}
        for path_text in manifest.values():
            if Path(path_text).expanduser().exists():
                continue
            if repaired := _unique_existing_sibling_data_path(path_text):
                replacements[path_text] = repaired
            else:
                return None
        if not replacements:
            return None

        rewritten = _rewrite_manifest_paths(content, replacements)
        if rewritten is None:
            return None
        return _request_with_tool_content(request, rewritten)

    def _period_alignment_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None
        manifest = _extract_data_files_manifest(content)
        if not manifest or not _needs_period_alignment_guard(manifest):
            return None
        if "align_period_features(" in content:
            return None
        return ToolMessage(
            content=(
                "Blocked mixed-frequency FRED analysis script before writing. "
                "The DATA_FILES manifest combines high-frequency series such as "
                "Treasury yields or initial claims with monthly/quarterly macro "
                "series. Import and call `align_period_features(series_frames, "
                "frequency=\"M\", how=\"outer\", timestamp_position=\"start\", "
                "fill_method=\"ffill\", fill_limit=2)` "
                "from `agents.quant_macro_stats` before deriving features or "
                "calling `direct_ols_forecast`; do not first merge resampled "
                "month-end timestamps against month-start FRED observations."
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _sec_company_facts_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None
        lowered = content.lower()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        manifest = _extract_data_files_manifest(content) or {}
        has_sec_company_facts = any(
            "sec_edgar_company_facts" in Path(path_text).name.lower()
            for path_text in manifest.values()
        )
        has_sec_company_facts = (
            has_sec_company_facts or "sec_edgar_company_facts" in lowered
        )
        if not has_sec_company_facts:
            return None
        positional_numeric_patterns = (
            "select_dtypes",
            ".iloc[:,-",
            ".iloc[:, -",
            ".iloc[: , -",
            "numeric_columns[-",
        )
        if any(pattern in lowered for pattern in positional_numeric_patterns):
            return ToolMessage(
                content=(
                    "Blocked SEC company-facts analysis before writing because it "
                    "derives issuer metrics from positional numeric columns. SEC "
                    "company-facts CSVs include shares, assets, liabilities, and other "
                    "numeric fields, so positional inference can produce impossible "
                    "margins or growth rates. Import `summarize_sec_company_facts` "
                    "from `agents.quant_macro_stats`, call it once per issuer CSV, and "
                    "use named fields such as `revenue`, `net_income`, "
                    "`operating_income`, `assets`, and `long_term_debt` for compact "
                    "earnings-risk rows and charts."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )

        computes_order_sensitive_growth = (
            "pct_change(" in lowered
            or "cagr" in lowered
            or "values[-1]" in lowered
            or ".iloc[-1]" in lowered
        )
        if (
            computes_order_sensitive_growth
            and tree is not None
            and _calls_named(tree, "summarize_sec_company_facts")
            and not _calls_named(tree, "read_csv")
        ):
            return None
        fiscal_year_sort_patterns = (
            ".sort_values(\"fiscal_year\"",
            ".sort_values('fiscal_year'",
            ".sort_values(by=\"fiscal_year\"",
            ".sort_values(by='fiscal_year'",
        )
        if (
            computes_order_sensitive_growth
            and "fiscal_year" in lowered
            and not any(pattern in lowered for pattern in fiscal_year_sort_patterns)
        ):
            return ToolMessage(
                content=(
                    "Blocked SEC company-facts analysis before writing because it "
                    "computes year-over-year growth, latest/first values, or CAGR "
                    "without first sorting rows by `fiscal_year` ascending. SEC "
                    "company-facts handoffs may arrive latest-first; unsorted "
                    "`pct_change()`, `.iloc[-1]`, or `values[-1] / values[0]` "
                    "can invert growth rates and misstate the report. After loading "
                    "each issuer CSV, run "
                    "`frame = frame.sort_values(\"fiscal_year\").reset_index(drop=True)` "
                    "before deriving growth, CAGR, latest rows, chart rows, or "
                    "execution_summary values. Prefer `summarize_sec_company_facts` "
                    "for compact named-column issuer summaries."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        return None

    def _macro_helper_contract_message(
        self, request: ToolCallRequest
    ) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None

        tree, syntax_error = _python_tree_for_write(content)
        if syntax_error is not None:
            return None

        assert tree is not None
        scenario_calls = _calls_named(tree, "build_scenario_stress_test")
        if any(_has_empty_list_call_arg(call) for call in scenario_calls):
            return ToolMessage(
                content=(
                    "Blocked scenario helper call before writing because "
                    "`build_scenario_stress_test([])` always fails validation and "
                    "causes avoidable edit loops. Define `scenario_rows` first with "
                    "exactly three dictionaries using scenarios `base`, `bull`, and "
                    "`bear`; each row must include `assumptions`, "
                    "`indicator_triggers`, `confidence`, and `uncertainty_notes`. "
                    "Then call `build_scenario_stress_test(scenario_rows, "
                    "topic=\"macro cycle\")` and merge its returned "
                    "`scenario_table` into `execution_summary`."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )

        manifest = _extract_data_files_manifest(content) or {}
        manifest_keys = {key.upper() for key in manifest}
        has_recession_indicator = "USREC" in manifest_keys
        lowered = content.lower()
        if (
            _calls_named(tree, "save_quant_outputs")
            and "chart_ids = list(charts.keys())" in content
        ):
            return ToolMessage(
                content=(
                    "Blocked stale quant handoff before writing. "
                    "`save_quant_outputs(...)` may drop chart definitions that do "
                    "not satisfy the frontend render contract, so do not rebuild "
                    "`chart_ids` from the original `charts` dict after calling it. "
                    "Use `handoff = save_quant_outputs(output_dir, charts, "
                    "execution_summary)` and `print(json.dumps(handoff))` so the "
                    "writer receives only saved chart IDs."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )

        missing_helpers: list[tuple[str, str]] = []
        regime_keys = (
            "regime_classification",
            "regime_label",
            "category_scores",
            "evidence_table",
            "historical_analogs",
            "false_positive_caveat",
        )
        if any(key in content for key in regime_keys) and not _calls_named(
            tree, "classify_recession_regime"
        ):
            missing_helpers.append(
                ("regime classification", "classify_recession_regime")
            )
        has_scenario_artifact = (
            "scenario_table" in content
            or '"scenarios"' in content
            or "'scenarios'" in content
        )
        if has_scenario_artifact and not _calls_named(tree, "build_scenario_stress_test"):
            missing_helpers.append(("scenario table", "build_scenario_stress_test"))
        recession_risk_keys = (
            "composite_risk",
            "recession_risk",
            "latest_index_value",
            "weights_or_model",
        )
        if (
            has_recession_indicator
            and any(key in lowered for key in recession_risk_keys)
            and not _calls_named(tree, "build_composite_predictive_indicator")
        ):
            missing_helpers.append(
                ("recession-risk framework", "build_composite_predictive_indicator")
            )
        if (
            has_recession_indicator
            and _calls_named(tree, "build_composite_predictive_indicator")
            and _calls_named(tree, "save_quant_outputs")
            and not _calls_named(tree, "historical_scenario_replay")
            and not _calls_named(tree, "signal_framework_backtest")
            and "historical_simulations" not in content
        ):
            missing_helpers.append(
                ("historical replay rows", "historical_scenario_replay or signal_framework_backtest")
            )
        signal_framework_markers = (
            "false_alarm",
            "pre_recession",
            "recession_calls_correct",
            "signal_framework",
        )
        if (
            has_recession_indicator
            and any(marker in lowered for marker in signal_framework_markers)
            and not _calls_named(tree, "signal_framework_backtest")
            and not _calls_named(tree, "event_signal_backtest")
            and not _calls_named(tree, "historical_scenario_replay")
        ):
            missing_helpers.append(
                ("signal framework hit/miss evidence", "signal_framework_backtest")
            )
        if (
            (
                "analog_similarity_ranking" in content
                or "analogy_breakdown" in content
            )
            and not _calls_named(tree, "compare_analog_windows")
        ):
            missing_helpers.append(("analog window comparison", "compare_analog_windows"))

        bad_signal_recession_cols: list[str] = []
        for call in _calls_named(tree, "signal_framework_backtest"):
            recession_col = _literal_string_arg(call, keyword_name="recession_col")
            if recession_col and recession_col.upper() in {
                "UNRATE",
                "UNEMPLOY",
                "UEMPMEAN",
            }:
                bad_signal_recession_cols.append(recession_col)
        if bad_signal_recession_cols:
            bad_cols = ", ".join(sorted(set(bad_signal_recession_cols)))
            return ToolMessage(
                content=(
                    "Blocked invalid signal-framework backtest before writing. "
                    "`signal_framework_backtest(...)` requires `recession_col` to "
                    "be a binary 0/1 event indicator such as `USREC`, not a "
                    f"continuous labor-market level like {bad_cols}. Keep UNRATE "
                    "as the forecast target/outcome, derive binary component "
                    "columns for warning signals, and call "
                    '`signal_framework_backtest(panel, component_cols=component_cols, '
                    'recession_col="USREC", date_col="date", threshold=2, '
                    "lookback_periods=12, false_alarm_lookahead_periods=12)`."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )

        if not missing_helpers:
            return None

        details = "; ".join(
            f"{artifact} requires `{helper}`"
            for artifact, helper in missing_helpers[:3]
        )
        is_unemployment_forecast_false_alarm = (
            ("unemployment" in lowered or "unrate" in lowered)
            and "forecast" in lowered
            and any(marker in lowered for marker in signal_framework_markers)
        )
        targeted_forecast_recipe = ""
        if is_unemployment_forecast_false_alarm:
            targeted_forecast_recipe = (
                "For a six-month unemployment forecast with false-alarm or prior-miss "
                "analysis, `direct_ols_forecast(...)` and "
                "`signal_framework_backtest(...)` are complements, not alternatives: "
                "call `direct_ols_forecast(forecast_frame, target_col=\"UNRATE\", "
                "feature_cols=feature_cols, date_col=\"date\", horizon=6, "
                "include_target_lag=True, min_observations=12)` for the point "
                "forecast, baseline comparison, and diagnostics; then derive a few "
                "binary component columns such as inverted curve, rising claims, "
                "weak payroll momentum, and falling industrial production on the "
                "same monthly panel and call `signal_framework_backtest(panel, "
                "component_cols=component_cols, recession_col=\"USREC\", "
                "date_col=\"date\", threshold=2, lookback_periods=12, "
                "false_alarm_lookahead_periods=12)` for false alarms, missed calls, "
                "and pre-recession hit/miss evidence. Merge both helper returns "
                "at top level in `execution_summary`; keep charts to forecast vs "
                "actual, model-vs-baseline RMSE, predictor/indicator contribution, "
                "and false-alarm counts. "
            )
        recovery_recipe = (
            f"{targeted_forecast_recipe}"
            "Use these canonical calls without inspecting helper source: "
            '`composite = build_composite_predictive_indicator(panel, '
            'target_col="USREC", feature_cols=feature_cols, date_col="date", '
            'target="recession_risk", prediction_horizon=1, '
            'feature_transforms={feature: "level" for feature in feature_cols}, '
            "feature_directions=feature_directions, "
            'normalization_method="zscore", min_feature_coverage=3)`; '
            '`scenario = build_scenario_stress_test(rows, topic="macro cycle")` '
            "where rows are exactly base/upside/downside dictionaries with "
            "`scenario`, `assumptions`, `indicator_triggers`, `confidence`, and "
            "`uncertainty_notes`; "
            '`regime = classify_recession_regime(scored_frame, date_col="date", '
            "indicator_specs=indicator_specs, recession_col=\"USREC\", "
            "momentum_periods=3, min_categories=3, analog_count=3)`. "
            '`replay = historical_scenario_replay(panel, '
            'signal_cols=["composite_index"], outcome_col="USREC", '
            'date_col="date", lookahead_periods=12)` after attaching the '
            "composite score to the aligned panel, or preserve the composite "
            "`score_history` under `historical_simulations` if you already "
            "converted it into replay rows. For threshold component frameworks, "
            '`signal_bt = signal_framework_backtest(panel, component_cols=component_cols, '
            'recession_col="USREC", date_col="date", threshold=3, '
            "lookback_periods=12, false_alarm_lookahead_periods=12)` and merge "
            "its `historical_simulations` into `execution_summary`. "
            '`analog = compare_analog_windows(panel, date_col="date", '
            'value_cols=value_cols, windows=analog_windows, '
            'current_window={"start": "2023-01-01", "end": latest_date})` '
            "for explicit 1995/2001/2008/2020/current analogy rankings and "
            "breakdown rows. "
            "For an explicit analog-window prompt, this analog call is the main "
            "quant framework; do not also add forecast, scenario, or regime helper "
            "calls unless those outputs were explicitly requested. "
            "Merge returned dictionaries into `execution_summary` and keep the "
            "script under 120 lines with at most four charts."
        )
        return ToolMessage(
            content=(
                "Blocked broad macro analysis script before writing because it "
                "hand-rolls helper-owned quantitative artifacts. "
                f"{details}. Import the required helper(s) from "
                "`agents.quant_macro_stats`, call them inside `analysis.py`, merge "
                "their returned dictionaries into `execution_summary`, and then "
                "write artifacts with `save_quant_outputs`. This prevents oversized "
                "scripts and avoidable repair loops from bespoke regime, scenario, "
                "or recession-risk code. "
                f"{recovery_recipe}"
            ),
            name="write_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _forecast_helper_contract_message(
        self, request: ToolCallRequest
    ) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "write_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path.endswith(".py"):
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None

        tree, syntax_error = _python_tree_for_write(content)
        if syntax_error is not None:
            return None

        assert tree is not None
        lowered = content.lower()
        forecast_context = any(
            token in lowered
            for token in (
                "forecast",
                "unemployment outlook",
                "unrate",
                "prediction_interval",
            )
        )
        handrolled_forecast = (
            _imports_forbidden_forecast_library(tree)
            or bool(_calls_named(tree, "LinearRegression"))
        )
        if (
            forecast_context
            and handrolled_forecast
            and not _calls_named(tree, "direct_ols_forecast")
        ):
            return ToolMessage(
                content=(
                    "Blocked econometric forecast script before writing because it "
                    "hand-rolls a local regression forecast. Importing "
                    "`direct_ols_forecast` is not enough; call "
                    "`direct_ols_forecast(forecast_frame, target_col=..., "
                    "feature_cols=..., date_col=\"date\", horizon=6, "
                    "include_target_lag=True, min_observations=12)` and preserve "
                    "its returned `forecast_table`, `diagnostics`, `model_spec`, "
                    "`backtest_summary`, `model_comparison`, `method_notes`, and "
                    "`caveats` in `execution_summary`. Do not "
                    "import sklearn/statsmodels or write a second manual forecast loop. "
                    "If you need many recursive pseudo-OOS forecast calls, use "
                    "`run_backtests=False` on those repeated helper calls so each "
                    "iteration does not recursively run a full walk-forward backtest."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        if (
            forecast_context
            and handrolled_forecast
            and _calls_named(tree, "direct_ols_forecast")
        ):
            return ToolMessage(
                content=(
                    "Blocked econometric forecast script before writing because it "
                    "adds a manual sklearn/statsmodels forecast or replay loop next "
                    "to `direct_ols_forecast(...)`. The helper already owns the OLS "
                    "forecast, walk-forward backtests, model comparison, diagnostics, "
                    "and validation packet. Keep one full `direct_ols_forecast(...)` "
                    "call, preserve `execution_summary = {**forecast_result, ...}`, "
                    "and use `signal_framework_backtest(...)`, "
                    "`event_signal_backtest(...)`, or `historical_scenario_replay(...)` "
                    "for historical hit/miss, false-alarm, or prior-cycle evidence "
                    "instead of importing sklearn/statsmodels or fitting another "
                    "regression loop."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        if forecast_context and _looped_direct_forecasts_without_backtest_skip(tree):
            return ToolMessage(
                content=(
                    "Blocked econometric forecast script before writing because it "
                    "calls `direct_ols_forecast` inside a loop without "
                    "`run_backtests=False`. Recursive pseudo-OOS validation loops "
                    "must use `direct_ols_forecast(..., run_backtests=False)` for "
                    "the repeated cut-date forecasts, then run one default full "
                    "`direct_ols_forecast(...)` call for the current forecast artifact "
                    "and preserve that call's `backtest_summary` and "
                    "`model_comparison` in `execution_summary`."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        if (
            forecast_context
            and _calls_named(tree, "direct_ols_forecast")
            and not _forecast_handoff_preserved(tree)
        ):
            return ToolMessage(
                content=(
                    "Blocked econometric forecast script before writing because it "
                    "calls `direct_ols_forecast(...)` but does not preserve the "
                    "helper's validation packet in `execution_summary`. Put the "
                    "helper return at top level, for example "
                    "`forecast_result = direct_ols_forecast(...)` followed by "
                    "`execution_summary = {**forecast_result, ...}`, so QA and "
                    "the writer receive `backtest_summary`, `model_comparison`, "
                    "`forecast_table`, `model_spec`, `diagnostics`, "
                    "`method_notes`, and `caveats`. Do not rename these into "
                    "`baseline_comparison` or prose-only statistical summaries."
                ),
                name="write_file",
                tool_call_id=_tool_call_id(request.tool_call),
                status="error",
            )
        return None

    def _helper_source_read_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if _tool_call_name(request.tool_call) != "read_file":
            return None
        args = _tool_call_args(request.tool_call)
        file_path = str(args.get("file_path") or args.get("path") or "")
        if not file_path:
            return None
        try:
            is_helper_source = (
                Path(file_path).expanduser().resolve()
                == (_BACKEND_DIR / "agents" / "quant_macro_stats.py").resolve()
            )
        except OSError:
            is_helper_source = file_path.replace("\\", "/").endswith(
                "/agents/quant_macro_stats.py"
            )
        if not is_helper_source:
            return None
        return ToolMessage(
            content=(
                "Blocked helper-source inspection for quant-developer. Do not read "
                "`agents/quant_macro_stats.py` to rediscover signatures during a "
                "repair loop. Patch the local analysis script using these canonical "
                "calls: `align_period_features(series_frames, frequency=\"M\", "
                "how=\"outer\", timestamp_position=\"start\", fill_method=\"ffill\", "
                "fill_limit=2)`; `direct_ols_forecast(forecast_frame, "
                "target_col=\"UNRATE\", feature_cols=feature_cols, date_col=\"date\", "
                "horizon=6, include_target_lag=True, min_observations=12)`; "
                "`build_composite_predictive_indicator(panel, target_col=\"USREC\", "
                "feature_cols=feature_cols, date_col=\"date\", target=\"recession_risk\", "
                "prediction_horizon=1, feature_transforms={feature: \"level\" for "
                "feature in feature_cols}, feature_directions=feature_directions, "
                "normalization_method=\"zscore\", min_feature_coverage=3)`; "
                "`build_scenario_stress_test(rows, topic=\"macro cycle\")`; and "
                "`classify_recession_regime(scored_frame, date_col=\"date\", "
                "indicator_specs=indicator_specs, recession_col=\"USREC\", "
                "momentum_periods=3, min_categories=3, analog_count=3)`; "
                "`historical_scenario_replay(panel, signal_cols=signal_cols, "
                "outcome_col=\"USREC\", date_col=\"date\", lookahead_periods=12)`; "
                "and `event_signal_backtest(panel, signal_col=\"composite\", "
                "target_col=\"USREC\", date_col=\"date\", threshold=3, "
                "direction=\"high\", prediction_horizon=12)`; or "
                "`signal_framework_backtest(panel, component_cols=component_cols, "
                "recession_col=\"USREC\", date_col=\"date\", threshold=3, "
                "lookback_periods=12, false_alarm_lookahead_periods=12)` for "
                "multi-component threshold score frameworks. "
                "Use `read_file` only for the generated analysis script or traceback "
                "context, then repair with `edit_file`."
            ),
            name="read_file",
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _handoff_complete_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        return ToolMessage(
            content=(
                "Blocked post-success quant tool call. A prior execute result already "
                "returned the compact handoff fields `charts_json`, "
                "`execution_summary_json`, and `chart_ids`. Return only that compact "
                "JSON now; do not run exploratory checks, read files, or edit the "
                "successful script unless a later tool result reported a concrete "
                "validation failure."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _tool_runtime_exception_message(
        self, request: ToolCallRequest, exc: Exception
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        exc_type = type(exc).__name__
        exc_text = str(exc).strip() or "<empty exception message>"
        content = (
            f"Recoverable `{tool_name}` tool runtime error for quant-developer: "
            f"{exc_type}: {exc_text}. "
        )
        if tool_name == "write_file" and not _has_written_analysis_script(
            _state_messages(getattr(request, "state", None))
        ):
            content += (
                "The initial analysis script was not confirmed written. Retry with "
                "exactly one compact `write_file` call using both named arguments: "
                "`file_path` ending in `/code/analysis.py` and complete `content` "
                "under the script budget. Do not call read_file, execute, ls, glob, "
                "or shell probes before that write succeeds."
            )
        else:
            content += (
                "Inspect the last concrete tool result, then retry the smallest "
                "valid tool call or return a failed quant handoff if recovery is not "
                "possible."
            )
        return ToolMessage(
            content=content,
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        try:
            state_messages = _state_messages(getattr(request, "state", None))
            if _has_successful_quant_handoff(
                state_messages
            ):
                return self._handoff_complete_message(request)
            if not _has_written_analysis_script(
                state_messages
            ):
                if tool_name not in _FIRST_WRITE_TOOL_NAMES:
                    return self._blocked_tool_message(request)
            if tool_name not in _AFTER_WRITE_TOOL_NAMES:
                return self._blocked_tool_message(request)
            if path_message := self._script_path_message(request):
                return path_message
            if existing_script_message := self._existing_initial_script_message(request):
                return existing_script_message
            if helper_source_read_message := self._helper_source_read_message(request):
                return helper_source_read_message
            if truncated_message := self._truncated_argument_message(request):
                return truncated_message
            if budget_message := self._script_budget_message(request):
                return budget_message
            if lint_message := self._python_static_lint_message(request):
                return lint_message
            if repaired_request := self._data_manifest_repair_request(request):
                request = repaired_request
            if manifest_message := self._data_manifest_message(request):
                return manifest_message
            if _is_final_prewrite_opportunity(state_messages):
                return handler(request)
            if period_alignment_message := self._period_alignment_message(request):
                return period_alignment_message
            if sec_company_facts_message := self._sec_company_facts_message(request):
                return sec_company_facts_message
            if helper_contract_message := self._macro_helper_contract_message(request):
                return helper_contract_message
            if forecast_helper_message := self._forecast_helper_contract_message(request):
                return forecast_helper_message
            return handler(request)
        except Exception as exc:
            return self._tool_runtime_exception_message(request, exc)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        try:
            state_messages = _state_messages(getattr(request, "state", None))
            if _has_successful_quant_handoff(
                state_messages
            ):
                return self._handoff_complete_message(request)
            if not _has_written_analysis_script(
                state_messages
            ):
                if tool_name not in _FIRST_WRITE_TOOL_NAMES:
                    return self._blocked_tool_message(request)
            if tool_name not in _AFTER_WRITE_TOOL_NAMES:
                return self._blocked_tool_message(request)
            if path_message := self._script_path_message(request):
                return path_message
            if existing_script_message := self._existing_initial_script_message(request):
                return existing_script_message
            if helper_source_read_message := self._helper_source_read_message(request):
                return helper_source_read_message
            if truncated_message := self._truncated_argument_message(request):
                return truncated_message
            if budget_message := self._script_budget_message(request):
                return budget_message
            if lint_message := self._python_static_lint_message(request):
                return lint_message
            if repaired_request := self._data_manifest_repair_request(request):
                request = repaired_request
            if manifest_message := self._data_manifest_message(request):
                return manifest_message
            if _is_final_prewrite_opportunity(state_messages):
                return await handler(request)
            if period_alignment_message := self._period_alignment_message(request):
                return period_alignment_message
            if sec_company_facts_message := self._sec_company_facts_message(request):
                return sec_company_facts_message
            if helper_contract_message := self._macro_helper_contract_message(request):
                return helper_contract_message
            if forecast_helper_message := self._forecast_helper_contract_message(request):
                return forecast_helper_message
            return await handler(request)
        except Exception as exc:
            return self._tool_runtime_exception_message(request, exc)


