"""Report and execution-summary fidelity checks."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone

from ..report_artifacts import load_report_json
from .utils import _truncate

def _load_sibling_execution_summary(report_path: Path) -> dict[str, object]:
    """Return a compact quant summary from execution_summary.json when available."""
    summary_path = report_path.with_name("execution_summary.json")
    if not summary_path.is_file():
        return {
            "status": "missing",
            "path": str(summary_path),
            "note": "No sibling execution_summary.json was found.",
        }

    try:
        parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "path": str(summary_path),
            "error": str(exc),
        }

    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "path": str(summary_path),
            "error": "Expected execution_summary.json to contain a JSON object.",
        }

    source_status = str(parsed.get("status") or "success")
    compact: dict[str, object] = {
        "status": source_status,
        "path": str(summary_path),
    }
    for key in (
        "failure_stage",
        "error",
        "limitations",
        "methods_used",
        "statistical_summary",
        "statistical_text",
        "brief_analysis_summary",
        "chart_ids",
        "backtest_summary",
        "model_comparison",
        "historical_simulations",
        "false_positive_analysis",
        "validation_window",
        "similarity_scores",
        "top_analog",
        "composite_recession_risk",
        "regime_classification",
        "aapl_msft_metrics",
    ):
        value = parsed.get(key)
        if value is not None:
            if key in {"chart_ids", "methods_used", "limitations"} and isinstance(
                value, list
            ):
                compact[key] = [str(chart_id) for chart_id in value]
            elif isinstance(value, (dict, list)):
                compact[key] = _truncate(json.dumps(value, ensure_ascii=False), 4000)
            else:
                compact[key] = _truncate(str(value), 4000)
    composite = parsed.get("composite_predictive_indicator")
    if isinstance(composite, dict):
        backtest = composite.get("backtest_summary")
        if isinstance(backtest, dict):
            compact["composite_predictive_indicator_backtest"] = _truncate(
                json.dumps(backtest, ensure_ascii=False), 4000
            )
        for key in ("latest_signal", "latest_index_value", "latest_percentile_0_100"):
            if composite.get(key) is not None:
                compact[f"composite_predictive_indicator_{key}"] = _truncate(
                    str(composite.get(key)), 4000
                )
    return compact


def _load_execution_summary_payload(report_path: Path) -> dict[str, object] | None:
    summary_path = report_path.with_name("execution_summary.json")
    try:
        parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _numeric_text_variants(value: object) -> set[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return set()
    variants = {
        f"{number:.0f}",
        f"{number:.1f}",
        f"{number:.2f}",
        f"{number:,.0f}",
        f"{number:,.1f}",
        f"{number:,.2f}",
        f"{number:.0f}%",
        f"{number:.1f}%",
        f"{number:.2f}%",
        f"{number:,.0f}%",
        f"{number:,.1f}%",
        f"{number:,.2f}%",
    }
    if abs(number) < 1:
        variants.update({f"{number * 100:.1f}", f"{number * 100:.1f}%"})
    return variants


def _contains_numeric_variant(text: str, value: object) -> bool:
    variants = _numeric_text_variants(value)
    return bool(variants) and any(variant in text for variant in variants)


def _state_comparison_fidelity_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    rows = summary.get("state_comparison")
    if not isinstance(rows, list) or not rows:
        return []

    mentioned_state_count = 0
    missing_income_states: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = row.get("state")
        income = row.get("income") or row.get("median_income")
        if not isinstance(state, str) or not state.strip() or income is None:
            continue
        if state.lower() not in markdown.lower():
            continue
        mentioned_state_count += 1
        if not _contains_numeric_variant(markdown, income):
            missing_income_states.append(state)

    if mentioned_state_count < 3 or not missing_income_states:
        return []
    return [
        "Report discusses the execution_summary.json state_comparison table but "
        "does not include the exact median-income values for "
        f"{', '.join(missing_income_states[:6])}. Regenerate state prose and "
        "tables from execution_summary.json instead of substituting stale Census "
        "or public-memory figures."
    ]


def _tech_earnings_fidelity_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    tech = summary.get("tech_earnings")
    if not isinstance(tech, dict) or not tech:
        return []

    markdown_lower = markdown.lower()
    expected_metrics = (
        ("AAPL_rev_b", ("aapl", "apple"), "AAPL revenue"),
        ("MSFT_rev_b", ("msft", "microsoft"), "MSFT revenue"),
        ("AAPL_nm_pct", ("aapl", "apple"), "AAPL net margin"),
        ("MSFT_nm_pct", ("msft", "microsoft"), "MSFT net margin"),
    )
    missing: list[str] = []
    for key, aliases, label in expected_metrics:
        if tech.get(key) is None:
            continue
        if not any(alias in markdown_lower for alias in aliases):
            continue
        if not _contains_numeric_variant(markdown, tech.get(key)):
            missing.append(label)

    if not missing:
        return []
    return [
        "Report discusses Apple/Microsoft earnings sensitivity but omits or "
        "contradicts exact SEC-derived tech_earnings values from "
        f"execution_summary.json for {', '.join(missing)}. Regenerate the "
        "large-cap tech section from the quantitative handoff."
    ]


_CLOSEST_ANALOG_RE = re.compile(
    r"(?:closest|most similar|best|top)[^\n.]{0,100}?\b(1995|2001|2008|2020)\b",
    re.IGNORECASE,
)

_UNSUPPORTED_FORWARD_OUTCOMES = (
    ("SP500", re.compile(r"\b(?:s&p\s*500|sp500)\b.{0,80}\b(?:return|returns)\b", re.IGNORECASE)),
    ("UNRATE", re.compile(r"\b(?:unrate|unemployment)\b.{0,80}\b(?:delta|change|rose|rising|fell|fall|increase|decrease|pp|percentage point)", re.IGNORECASE)),
    ("INDPRO", re.compile(r"\b(?:indpro|industrial production|production)\b.{0,80}\b(?:delta|change|growth|contract|expand|decline)", re.IGNORECASE)),
)

_FORWARD_REPLAY_CONTEXT_RE = re.compile(
    r"\b(?:what happened next|forward|subsequent|lookahead|look-ahead|next\s+\d+|"
    r"\d+\s*(?:m|month|months)|after\s+\d+|analog|analogue|replay|prior cycle)\b",
    re.IGNORECASE,
)
_NEGATED_FORWARD_OUTCOME_RE = re.compile(
    r"\b(?:no|not|without)\b.{0,40}\bforward\b.{0,80}\b(?:available|outcome|projection|verified|validate|data)\b|"
    r"\bforward\b.{0,80}\b(?:not available|unavailable|not verified|no data)\b|"
    r"\blatest observed\b",
    re.IGNORECASE,
)


def _forward_replay_claim_lines(markdown: str) -> str:
    """Return only markdown lines that look like historical replay outcome claims.

    Forecast reports can legitimately discuss forward-looking model projections
    for UNRATE or current changes in INDPRO outside the replay payload. The
    unsupported-outcome blocker is intended only for invented "what happened
    next" / analog forward outcomes that are absent from replay rows.
    """

    candidate_lines: list[str] = []
    in_replay_section = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            in_replay_section = bool(_FORWARD_REPLAY_CONTEXT_RE.search(heading))
            continue
        if _NEGATED_FORWARD_OUTCOME_RE.search(line):
            continue
        if _FORWARD_REPLAY_CONTEXT_RE.search(line):
            candidate_lines.append(line)
            continue
        if in_replay_section and "|" in line:
            candidate_lines.append(line)
    return "\n".join(candidate_lines)


def _historical_replay_payload(summary: dict[str, object]) -> dict[str, object] | None:
    replay = summary.get("what_happened_next")
    if isinstance(replay, dict) and replay:
        return replay
    replay = summary.get("historical_replay")
    if isinstance(replay, dict) and replay:
        return replay
    return None


def _unsupported_forward_outcome_claim_blocker(
    summary: dict[str, object], markdown: str
) -> str | None:
    replay = _historical_replay_payload(summary)
    if not replay:
        return None

    design = replay.get("simulation_design")
    outcome_variable = None
    if isinstance(design, dict) and design.get("outcome_variable") is not None:
        outcome_variable = str(design.get("outcome_variable")).upper()

    replay_text = json.dumps(replay, ensure_ascii=False).upper()
    replay_claim_text = _forward_replay_claim_lines(markdown)
    if not replay_claim_text:
        return None

    unsupported = [
        label
        for label, pattern in _UNSUPPORTED_FORWARD_OUTCOMES
        if label != outcome_variable
        and label not in replay_text
        and pattern.search(replay_claim_text)
    ]
    if not unsupported:
        return None

    return (
        "Report claims forward what-happened-next outcomes for "
        f"{', '.join(unsupported)}, but execution_summary.json replay rows do not "
        "contain those outcome variables. Regenerate the report from the replay "
        "payload, or state that those forward outcomes were unavailable instead "
        "of substituting unsupported benchmarks."
    )


def _execution_summary_fidelity_blockers(
    report_data: dict[str, object], report_path: Path
) -> list[str]:
    summary = _load_execution_summary_payload(report_path)
    if not summary:
        return []

    markdown = str(report_data.get("markdown", ""))
    blockers: list[str] = []
    unsupported_forward = _unsupported_forward_outcome_claim_blocker(summary, markdown)
    if unsupported_forward:
        blockers.append(unsupported_forward)
    blockers.extend(_state_comparison_fidelity_blockers(summary, markdown))
    blockers.extend(_tech_earnings_fidelity_blockers(summary, markdown))

    top_analog = summary.get("top_analog")
    if top_analog is not None:
        expected = str(top_analog)
        match = _CLOSEST_ANALOG_RE.search(markdown)
        if match and match.group(1) != expected:
            blockers.append(
                "Report claims the closest historical analog is "
                f"{match.group(1)}, but execution_summary.json top_analog is "
                f"{expected}. Regenerate the report from the quantitative "
                "handoff instead of using stale or invented analog rankings."
            )

    risk = summary.get("composite_recession_risk")
    current_risk = risk.get("current") if isinstance(risk, dict) else None
    if current_risk is not None and re.search(
        r"(recession[- ]risk|composite recession|risk score)", markdown, re.IGNORECASE
    ):
        variants = _numeric_text_variants(current_risk)
        if variants and not any(variant in markdown for variant in variants):
            blockers.append(
                "Report cites a composite recession-risk score but does not include "
                f"the current value from execution_summary.json ({float(current_risk):.1f}). "
                "Regenerate prose and chart captions from execution_summary.json."
            )

    similarity_scores = summary.get("similarity_scores")
    if isinstance(similarity_scores, dict) and "similarity score" in markdown.lower():
        top_score = similarity_scores.get(str(top_analog)) if top_analog is not None else None
        variants = _numeric_text_variants(top_score)
        if variants and not any(variant in markdown for variant in variants):
            blockers.append(
                "Report discusses similarity scores but omits the top analog score "
                "from execution_summary.json. Use the exact similarity_scores "
                "payload instead of stale or inferred values."
            )
    return blockers


def _parse_report_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text[:10]}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_data_freshness_blocker(report_data: dict[str, object], report_path: Path) -> str | None:
    query = str(report_data.get("query", "")).lower()
    if not any(
        marker in query
        for marker in (
            "current",
            "latest",
            "today",
            "right now",
            "now",
            "scenario",
            "outlook",
        )
    ):
        return None

    summary_path = report_path.with_name("execution_summary.json")
    try:
        parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None

    stats = parsed.get("statistical_summary")
    if not isinstance(stats, dict):
        return None
    current_stack = stats.get("current_signal_stack")
    if not isinstance(current_stack, dict):
        return None

    as_of = _parse_report_datetime(current_stack.get("as_of_date"))
    if as_of is None:
        return None
    report_dt = _parse_report_datetime(report_data.get("created_at")) or datetime.now(timezone.utc)
    age_days = (report_dt - as_of).days
    if age_days <= 370:
        return None
    return (
        "Report answers a current/latest macro question using stale quantitative "
        f"current_signal_stack.as_of_date={as_of.date().isoformat()}, which is "
        f"{age_days} days before report creation. Rerun data-engineer without a "
        "historical observation_end cutoff for current/latest FRED series, then "
        "regenerate the quantitative artifacts and report."
    )


def _query_requires_quant_artifacts(query: str) -> bool:
    lowered = query.lower()
    return any(
        keyword in lowered
        for keyword in (
            "chart",
            "charts",
            "quantitative",
            "signal stack",
            "recession-risk framework",
            "recession risk framework",
            "recession-risk",
            "recession risk",
            "forecast",
            "outlook",
            "scenario",
            "scenarios",
            "stress test",
            "regime classification",
            "regime",
        )
    )



def _query_requires_econometric_validation(query: str) -> bool:
    lowered = query.lower()
    return any(
        keyword in lowered
        for keyword in (
            "econometric",
            "econometrics",
            "forecast",
            "outlook",
            "predict",
            "predictive",
            "backtest",
            "historical simulation",
            "historic simulation",
            "historical replay",
            "prior downturn",
            "prior downturns",
            "earlier downturn",
            "earlier downturns",
            "past downturn",
            "past downturns",
            "cried wolf",
            "false positive",
            "false-positive",
            "compare the current cycle",
        )
    )


def _approval_blockers(report_path: str) -> list[str]:
    data, error = load_report_json(report_path)
    if error:
        return [f"Cannot load report artifact: {error}"]
    query = str(data.get("query", ""))
    charts = data.get("charts", [])
    if isinstance(charts, dict):
        chart_count = len(charts)
    elif isinstance(charts, list):
        chart_count = len([chart for chart in charts if isinstance(chart, dict)])
    else:
        chart_count = 0

    summary = _load_sibling_execution_summary(Path(report_path))
    blockers: list[str] = []
    freshness_blocker = _current_data_freshness_blocker(data, Path(report_path))
    if freshness_blocker:
        blockers.append(freshness_blocker)
    blockers.extend(_execution_summary_fidelity_blockers(data, Path(report_path)))
    if summary.get("status") in {"failed", "error", "missing"}:
        blockers.append(
            "Required quantitative artifacts are missing or failed; rerun "
            "quant-developer with a compact helper-driven script."
        )
        if chart_count == 0:
            blockers.append(
                "The sibling execution_summary.json reports a failed quantitative "
                "handoff and report.json contains zero chart definitions."
            )
        return blockers

    markdown = str(data.get("markdown", "")).lower()
    if (
        summary.get("composite_predictive_indicator_backtest")
        and "recession" in markdown
        and ("probability" in markdown or "near term" in markdown or "risk score" in markdown)
        and not any(
            term in markdown
            for term in ("backtest", "precision", "recall", "false negative", "false-positive")
        )
    ):
        blockers.append(
            "Report cites a recession-risk probability or score but omits available composite-indicator backtest diagnostics such as precision, recall, or false negatives."
        )
    if not _query_requires_quant_artifacts(query):
        return blockers

    if chart_count == 0 and ("chart" in query.lower() or "charts" in query.lower()):
        blockers.append(
            "The user explicitly requested charts, but report.json contains zero chart definitions."
        )
    if not summary.get("chart_ids") and chart_count == 0:
        blockers.append(
            "No computed chart_ids were available for QA to verify against the quantitative handoff."
        )
    scenario_check = _scenario_requirement(query, data.get("scenario_table"))
    if not scenario_check.get("valid", True):
        missing = ", ".join(str(item) for item in scenario_check.get("missing_required_rows", []))
        blockers.append(
            "Scenario/stress request lacks required structured scenario_table rows "
            f"for: {missing}."
        )
    if _query_requires_econometric_validation(query) and summary.get("status") not in {
        "failed",
        "error",
        "missing",
    }:
        if not summary.get("backtest_summary") and not summary.get("model_comparison"):
            blockers.append(
                "Econometric or predictive report lacks out-of-sample validation, backtest_summary, or model_comparison in execution_summary.json."
            )
        if (
            (
                "historical" in query.lower()
                or "prior downturn" in query.lower()
                or "earlier downturn" in query.lower()
                or "past downturn" in query.lower()
                or "cried wolf" in query.lower()
            )
            and not summary.get("historical_simulations")
        ):
            blockers.append(
                "Historical comparison request lacks historical_simulations or replay rows in execution_summary.json."
            )
    return blockers


def _scenario_requirement(query: str, scenario_table: object) -> dict[str, object]:
    lowered = query.lower()
    required = any(
        keyword in lowered
        for keyword in (
            "scenario",
            "scenarios",
            "stress test",
            "stress testing",
            "base case",
            "base, upside, and downside",
            "base/upside/downside",
            "upside case",
            "downside case",
            "upside",
            "downside",
            "bull case",
            "bear case",
        )
    )
    rows = scenario_table if isinstance(scenario_table, list) else []
    aliases = {
        "base case": "base",
        "baseline": "base",
        "upside": "bull",
        "upside case": "bull",
        "bull case": "bull",
        "downside": "bear",
        "downside case": "bear",
        "bear case": "bear",
    }
    names = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("scenario", "")).strip().lower()
        names.append(aliases.get(raw_name, raw_name))
    if "upside" in lowered or "downside" in lowered:
        required_names = ("base", "bull", "bear")
        display_names = {"base": "base", "bull": "upside", "bear": "downside"}
    else:
        required_names = ("base", "bull", "bear")
        display_names = {"base": "base", "bull": "bull", "bear": "bear"}
    missing = [name for name in required_names if name not in names]
    return {
        "required": required,
        "valid": (not required) or not missing,
        "scenarios": names,
        "missing_required_rows": [display_names[name] for name in missing] if required else [],
    }
