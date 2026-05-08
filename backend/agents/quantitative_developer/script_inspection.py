"""Static validation helpers for generated quant analysis scripts."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.prebuilt.tool_node import ToolCallRequest

from .constants import (
    _AUTO_SAVED_DATA_STEM_RE,
    _DATA_FILE_SUFFIXES,
    _DATA_FILES_MANIFEST_NAMES,
    _HIGH_FREQUENCY_FRED_KEYS,
    _MONTHLY_OR_LOWER_FRED_KEYS,
)
from .tool_utils import _tool_call_args

def _extract_data_files_manifest(content: str) -> dict[str, str] | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id in _DATA_FILES_MANIFEST_NAMES
            for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
        if isinstance(value, dict):
            return {
                str(key): str(path)
                for key, path in value.items()
                if isinstance(key, str) and isinstance(path, str)
            }
        return None
    return None


def _unique_existing_sibling_data_path(path_text: str) -> str | None:
    """Resolve one-character auto-save suffix drift without shell inspection."""
    path = Path(path_text).expanduser()
    if path.exists() or path.suffix.lower() not in _DATA_FILE_SUFFIXES:
        return None
    parent = path.parent
    if not parent.exists():
        return None
    stem = path.stem
    if "_" not in stem:
        return None
    prefix = stem.rsplit("_", 1)[0]
    matches = sorted(
        candidate
        for candidate in parent.glob(f"{prefix}_*{path.suffix}")
        if candidate.is_file()
    )
    if len(matches) != 1:
        if repaired := _nearest_existing_auto_saved_data_path(path):
            return repaired
        return None
    return str(matches[0])


def _nearest_existing_auto_saved_data_path(path: Path) -> str | None:
    """Repair hallucinated auto-save timestamps for the same provider/series."""
    match = _AUTO_SAVED_DATA_STEM_RE.match(path.stem)
    if not match:
        return None

    requested_timestamp = int(match.group("timestamp"))
    prefix = match.group("prefix")
    candidates: list[tuple[int, Path]] = []
    for candidate in path.parent.glob(f"{prefix}_*{path.suffix}"):
        if not candidate.is_file():
            continue
        candidate_match = _AUTO_SAVED_DATA_STEM_RE.match(candidate.stem)
        if not candidate_match or candidate_match.group("prefix") != prefix:
            continue
        delta = abs(int(candidate_match.group("timestamp")) - requested_timestamp)
        candidates.append((delta, candidate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    nearest_delta, nearest_path = candidates[0]
    if len(candidates) > 1 and candidates[1][0] == nearest_delta:
        return None

    # Auto-save filenames use time_ns(); only repair close same-run timestamp
    # drift, not stale artifacts from earlier agent runs.
    five_minutes_ns = 5 * 60 * 1_000_000_000
    if nearest_delta > five_minutes_ns:
        return None
    return str(nearest_path)


def _rewrite_manifest_paths(content: str, replacements: dict[str, str]) -> str | None:
    rewritten = content
    for old, new in replacements.items():
        changed = False
        for quoted_old, quoted_new in (
            (repr(old), repr(new)),
            (json.dumps(old), json.dumps(new)),
        ):
            if quoted_old in rewritten:
                rewritten = rewritten.replace(quoted_old, quoted_new)
                changed = True
        if not changed:
            return None
    return rewritten


def _request_with_tool_content(request: ToolCallRequest, content: str) -> ToolCallRequest:
    tool_call = request.tool_call
    if isinstance(tool_call, dict):
        args = dict(_tool_call_args(tool_call))
        args["content"] = content
        new_tool_call = {**tool_call, "args": args}
        if hasattr(request, "override"):
            return request.override(tool_call=new_tool_call)
        return type(request)(
            tool_call=new_tool_call, state=getattr(request, "state", None)
        )
    args = dict(_tool_call_args(tool_call))
    args["content"] = content
    new_tool_call = SimpleNamespace(
        **{
            key: value
            for key, value in vars(tool_call).items()
            if key != "args"
        },
        args=args,
    )
    if hasattr(request, "override"):
        return request.override(tool_call=new_tool_call)
    return type(request)(
        tool_call=new_tool_call, state=getattr(request, "state", None)
    )


def _needs_period_alignment_guard(manifest: dict[str, str]) -> bool:
    keys = {key.upper() for key in manifest}
    return bool(keys & _HIGH_FREQUENCY_FRED_KEYS) and bool(
        keys & _MONTHLY_OR_LOWER_FRED_KEYS
    )


def _python_tree_for_write(content: str) -> tuple[ast.Module | None, SyntaxError | None]:
    try:
        return ast.parse(content), None
    except SyntaxError as exc:
        return None, exc


def _calls_named(tree: ast.Module, function_name: str) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == function_name:
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == function_name:
                calls.append(node)
    return calls


def _imports_forbidden_forecast_library(tree: ast.Module) -> bool:
    """Return True for direct sklearn/statsmodels imports in generated scripts."""

    forbidden_roots = {"sklearn", "statsmodels"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in forbidden_roots:
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in forbidden_roots:
                return True
    return False


def _uses_runtime_installer(tree: ast.Module) -> bool:
    """Return True when generated code attempts to install packages at runtime."""

    installer_tokens = {
        "pip",
        "pip3",
        "ensurepip",
        "get-pip.py",
        "uv",
        "poetry",
        "conda",
        "mamba",
        "apt",
        "apt-get",
    }
    shell_install_markers = (
        "pip install",
        "pip3 install",
        "python -m pip install",
        "python3 -m pip install",
        "uv pip install",
        "uv add",
        "poetry add",
        "conda install",
        "mamba install",
        "apt install",
        "apt-get install",
        "ensurepip",
        "get-pip.py",
    )

    def _constant_text(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                else:
                    return None
            return "".join(parts)
        return None

    def _literal_command_parts(node: ast.AST) -> list[str]:
        if isinstance(node, (ast.List, ast.Tuple)):
            parts: list[str] = []
            for element in node.elts:
                text = _constant_text(element)
                if text is None:
                    return []
                parts.append(text)
            return parts
        text = _constant_text(node)
        return text.split() if text is not None else []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""]
            if any(name.split(".", 1)[0] in {"ensurepip"} for name in names):
                return True

        if not isinstance(node, ast.Call):
            continue

        func = node.func
        func_name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute) else ""
        )
        if func_name in {"system", "popen"} and node.args:
            text = _constant_text(node.args[0])
            if text and any(marker in text.lower() for marker in shell_install_markers):
                return True
        if func_name in {"run", "call", "check_call", "check_output", "Popen"} and node.args:
            parts = _literal_command_parts(node.args[0])
            lowered = [part.lower() for part in parts]
            if lowered and any(token in lowered[0] for token in installer_tokens):
                return True
            joined = " ".join(lowered)
            if any(marker in joined for marker in shell_install_markers):
                return True

    return False


def _direct_forecast_result_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            continue
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        called = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute) else None
        )
        if called != "direct_ols_forecast":
            continue
        targets = [node.target] if isinstance(node, (ast.AnnAssign, ast.NamedExpr)) else node.targets
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _dict_literal_has_keys(node: ast.Dict, required: set[str]) -> bool:
    found: set[str] = set()
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            found.add(key.value)
    return required.issubset(found)


def _forecast_handoff_preserved(tree: ast.Module) -> bool:
    """Return True when direct forecast validation reaches execution_summary."""

    forecast_names = _direct_forecast_result_names(tree)
    if not forecast_names:
        return False
    required = {"backtest_summary", "model_comparison"}
    preserved_summary_names: set[str] = set()

    def _dict_preserves_forecast_packet(value: ast.Dict) -> bool:
        if _dict_literal_has_keys(value, required):
            return True
        for dict_value in value.values:
            if isinstance(dict_value, ast.Name) and (
                dict_value.id in forecast_names
                or dict_value.id in preserved_summary_names
            ):
                return True
        return False

    def _target_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        return [target.id for target in targets if isinstance(target, ast.Name)]

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = getattr(node, "value", None)
            names = _target_names(node)
            preserves_packet = (
                isinstance(value, ast.Name)
                and (value.id in forecast_names or value.id in preserved_summary_names)
            ) or (
                isinstance(value, ast.Dict) and _dict_preserves_forecast_packet(value)
            )
            if not preserves_packet:
                continue
            if "execution_summary" in names:
                return True
            new_names = set(names) - preserved_summary_names
            if new_names:
                preserved_summary_names.update(new_names)
                changed = True

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            getattr(node, "value", None), ast.Name
        ):
            if (
                node.value.id in forecast_names
                or node.value.id in preserved_summary_names
            ) and "execution_summary" in _target_names(node):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            getattr(node, "value", None), ast.Dict
        ):
            if "execution_summary" not in _target_names(node):
                continue
            if _dict_preserves_forecast_packet(node.value):
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            called = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None
            )
            if called != "save_quant_outputs" or len(node.args) < 3:
                continue
            summary_arg = node.args[2]
            if isinstance(summary_arg, ast.Name) and (
                summary_arg.id in forecast_names
                or summary_arg.id in preserved_summary_names
            ):
                return True
            if isinstance(summary_arg, ast.Dict) and _dict_preserves_forecast_packet(
                summary_arg
            ):
                return True
    return False


def _call_has_keyword_bool(call: ast.Call, keyword_name: str, expected: bool) -> bool:
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        return isinstance(value, ast.Constant) and value.value is expected
    return False


def _looped_direct_forecasts_without_backtest_skip(tree: ast.Module) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            is_direct_forecast = (
                (isinstance(func, ast.Name) and func.id == "direct_ols_forecast")
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "direct_ols_forecast"
                )
            )
            if is_direct_forecast and not _call_has_keyword_bool(
                child, "run_backtests", False
            ):
                calls.append(child)
    return calls


def _has_empty_list_call_arg(call: ast.Call) -> bool:
    if not call.args:
        return False
    return isinstance(call.args[0], ast.List) and not call.args[0].elts


def _literal_string_arg(call: ast.Call, keyword_name: str = "freq") -> str | None:
    if call.args:
        value = call.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _align_period_output_period_reference(tree: ast.Module) -> str | None:
    """Return the aligned-panel variable name if code expects a period column."""

    aligned_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        is_align_call = (
            isinstance(func, ast.Name)
            and func.id == "align_period_features"
        ) or (
            isinstance(func, ast.Attribute)
            and func.attr == "align_period_features"
        )
        if not is_align_call:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                aligned_names.add(target.id)

    if not aligned_names:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id not in aligned_names:
                continue
            key_node = node.slice
            if isinstance(key_node, ast.Constant) and key_node.value == "period":
                return node.value.id
            if isinstance(key_node, ast.List) and any(
                isinstance(item, ast.Constant) and item.value == "period"
                for item in key_node.elts
            ):
                return node.value.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in aligned_names and node.attr == "period":
                return node.value.id
    return None
