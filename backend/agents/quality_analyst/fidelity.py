"""Report and execution-summary fidelity checks."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable

from pydantic import ValidationError

from core.report_schema import ResearchReport

from ..artifact_fact_consistency import (
    artifact_fact_consistency_blocker,
    artifact_fact_consistency_dict,
)
from agents.quant_macro_stats.artifacts.numeric_fact_contracts import (
    normalize_numeric_facts,
    numeric_fact_current_state_duration_misuse,
    numeric_fact_literal_required,
)
from agents.quant_macro_stats.artifacts.execution_summary_normalization import (
    normalize_quant_execution_summary,
)
from ..report_artifacts import (
    chart_handoff_blocker,
    chart_handoff_dict,
    load_report_json,
    load_sibling_execution_summary_json,
)
from ..technical_writer.chart_audit import chart_semantics_dict
from ..quant_macro_stats.artifacts.source_unit_fidelity import (
    attach_source_unit_metadata,
    failed_unit_comparison_messages,
    has_passing_mixed_wage_unit_comparison,
    mixed_wage_period_sources,
    normalize_source_unit_metadata,
)
from .utils import _truncate

_SEC_COMPANY_FACTS_REF_MARKERS = (
    "sec_facts",
    "sec_company_facts",
    "sec_edgar_company_facts",
    "edgar_company_facts",
)


def _looks_like_sec_company_facts_ref(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return False
    upper = text.upper()
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    path_name = Path(text).name.lower().replace("-", "_").replace(" ", "_")
    return (
        upper.startswith("SEC_")
        or upper.endswith("_SEC")
        or any(
            marker in normalized or marker in path_name
            for marker in _SEC_COMPANY_FACTS_REF_MARKERS
        )
    )


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
    try:
        parsed = normalize_quant_execution_summary(parsed)
    except ValueError:
        pass

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
        "dropped_chart_ids",
        "validation_window",
        "state_comparison",
        "numeric_facts",
        "forecast_rows",
        "forecast_table",
        "walk_forward_backtest_rows",
        "model_validation_rows",
        "model_comparison_by_horizon",
        "model_comparison_rows",
        "historical_failure_episodes",
        "predictor_contributions",
        "forecast_band_rows",
        "historical_window_coverage",
        "analog_similarity_ranking",
        "analog_profiles",
        "analog_profile_rows",
        "comparison_design",
        "composite_current_row",
        "composite_score_rows",
        "composite_validation_metrics",
        "composite_validation_design",
        "feature_coverage",
        "composite_recession_risk",
        "current_regime_row",
        "regime_evidence_rows",
        "regime_history_rows",
        "regime_analog_rows",
        "missing_indicator_rows",
        "regime_design",
        "event_backtest_metrics",
        "signal_score_rows",
        "signal_event_rows",
        "signal_false_positive_windows",
        "signal_validation_metrics",
        "latest_signal_observation",
        "signal_design",
        "lead_time_rows",
        "scenario_score_rows",
        "replay_rows",
        "replay_design",
        "latest_fundamentals",
        "company_history_rows",
        "trend_diagnostics",
        "macro_overlay",
        "company_macro_sensitivity",
        "diagnostics",
        "source_coverage",
        "source_files",
        "source_unit_metadata",
        "unit_comparisons",
        "source_unit_errors",
        "data_files",
    ):
        value = parsed.get(key)
        if value is not None:
            if (
                key in {"chart_ids", "dropped_chart_ids", "methods_used", "limitations"}
                and isinstance(value, list)
            ):
                compact[key] = [str(chart_id) for chart_id in value]
            elif isinstance(value, (dict, list)):
                compact[key] = _truncate(json.dumps(value, ensure_ascii=False), 4000)
            else:
                compact[key] = _truncate(str(value), 4000)
    return compact


def _load_execution_summary_payload(report_path: Path) -> dict[str, object] | None:
    parsed, _ = load_sibling_execution_summary_json(report_path)
    return parsed


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


_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?(?![\w.])")


def _numeric_candidates(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMERIC_TOKEN_RE.finditer(text):
        token = match.group(0).replace("$", "").replace(",", "").replace("%", "")
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _contains_numeric_fact_value(text: str, fact: dict[str, object]) -> bool:
    display = str(fact.get("display_value") or "").strip()
    if display:
        if display in text:
            return True
        without_currency = display.replace("$", "").strip()
        if without_currency and without_currency in text:
            return True

    try:
        raw_value = float(fact.get("raw_value"))
    except (TypeError, ValueError):
        return False
    try:
        tolerance = abs(float(fact.get("tolerance", 0)))
    except (TypeError, ValueError):
        tolerance = 0.0
    for candidate in _numeric_candidates(text):
        if abs(candidate - raw_value) <= tolerance:
            return True
    return False


def _numeric_facts_from_summary(summary: dict[str, object]) -> list[dict[str, object]]:
    candidates: list[object] = [summary.get("numeric_facts")]

    facts: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        for item in normalize_numeric_facts(candidate):
            fact_id = str(item.get("id") or item.get("source_key") or "")
            if not fact_id or fact_id in seen:
                continue
            seen.add(fact_id)
            facts.append(item)
    return facts


def _state_income_facts(summary: dict[str, object]) -> list[dict[str, object]]:
    return [
        fact
        for fact in _numeric_facts_from_summary(summary)
        if str(fact.get("metric") or "") == "per_capita_personal_income"
        and str(fact.get("subject") or "").strip()
    ]


def _state_comparison_fidelity_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    state_income_facts = _state_income_facts(summary)
    if state_income_facts:
        mentioned_state_count = 0
        missing_income_states: list[str] = []
        markdown_lower = markdown.lower()
        for fact in state_income_facts:
            state = str(fact.get("subject") or "").strip()
            if not state or state.lower() not in markdown_lower:
                continue
            mentioned_state_count += 1
            if not _contains_numeric_fact_value(markdown, fact):
                missing_income_states.append(state)

        if mentioned_state_count < 3 or not missing_income_states:
            return []
        return [
            "Report discusses the execution_summary.json state_comparison table but "
            "does not include helper-produced per-capita personal-income display "
            "values within tolerance for "
            f"{', '.join(missing_income_states[:6])}. Regenerate state prose and "
            "tables from top-level numeric_facts instead of substituting "
            "stale Census, public-memory, or differently rounded figures."
        ]

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
        "does not include the exact per-capita personal-income values for "
        f"{', '.join(missing_income_states[:6])}. Regenerate state prose and "
        "tables from execution_summary.json instead of substituting stale Census "
        "or public-memory figures."
    ]


def _metric_markers_for_fact(fact: dict[str, object]) -> tuple[str, ...]:
    metric = str(fact.get("metric") or "").lower()
    label = str(fact.get("label") or "").lower()
    marker_map = {
        "revenue_b": ("revenue", "sales", "growth narrative"),
        "net_income_b": ("net income", "profit", "earnings"),
        "net_margin_pct": ("margin", "profitability"),
        "gross_margin_pct": ("gross margin", "margin"),
        "operating_margin_pct": ("operating margin", "margin"),
        "operating_cash_flow_b": ("cash flow", "cash-flow"),
        "free_cash_flow_b": ("free cash flow", "cash-flow"),
        "cash_and_securities_b": ("balance sheet", "cash", "liquidity"),
        "long_term_debt_b": ("balance sheet", "debt", "leverage"),
        "diluted_eps": ("eps", "earnings per share"),
    }
    markers = list(marker_map.get(metric, ()))
    markers.extend(token for token in re.split(r"[^a-z0-9]+", metric) if len(token) > 2)
    markers.extend(token for token in re.split(r"[^a-z0-9]+", label) if len(token) > 2)
    return tuple(dict.fromkeys(markers))


def _numeric_fact_fidelity_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    facts = _numeric_facts_from_summary(summary)
    if not facts:
        return []

    markdown_lower = markdown.lower()
    missing: list[str] = []
    semantic_misuse: list[str] = []
    for fact in facts:
        subject = str(fact.get("subject") or "").strip()
        metric = str(fact.get("metric") or fact.get("id") or fact.get("source_key") or "").strip()
        if subject and subject.lower() not in markdown_lower:
            continue
        markers = _metric_markers_for_fact(fact)
        if markers and not any(marker in markdown_lower for marker in markers):
            continue
        label = " ".join(part for part in (subject, metric) if part)
        label = label or str(
            fact.get("label") or fact.get("id") or fact.get("source_key") or "numeric fact"
        )
        if numeric_fact_current_state_duration_misuse(markdown, fact):
            semantic_misuse.append(label)
            continue
        if not numeric_fact_literal_required(fact):
            continue
        if not _contains_numeric_fact_value(markdown, fact):
            missing.append(label)

    if semantic_misuse:
        return [
            "Report treats current-state zero-duration numeric_facts as historical "
            f"durations for {', '.join(semantic_misuse[:8])}. Regenerate the "
            "affected prose from state_description instead of saying an episode "
            "lasted 0 months."
        ]
    if not missing:
        return []
    return [
        "Report omits or contradicts helper-produced numeric_facts from "
        f"execution_summary.json for {', '.join(missing[:8])}. Regenerate the "
        "affected prose from display_value fields in the quantitative handoff."
    ]


def _report_claim_text(report_data: dict[str, object]) -> str:
    return "\n".join(
        str(report_data.get(key) or "")
        for key in ("title", "executive_summary", "markdown")
    )


def _report_claims_company_fundamental_analysis(report_data: dict[str, object]) -> bool:
    lowered = _report_claim_text(report_data).lower()
    return any(
        marker in lowered
        for marker in (
            "stock-specific",
            "public-company",
            "public company",
            "business fundamentals",
            "fundamentals support",
            "growth narrative",
            "revenue",
            "margin",
            "cash-flow",
            "cash flow",
            "balance-sheet",
            "balance sheet",
        )
    )


def _has_reusable_company_evidence(summary: dict[str, object]) -> bool:
    if _sec_company_files_present(summary):
        return _has_complete_sec_company_helper_evidence(summary)
    if _numeric_facts_from_summary(summary):
        return True
    latest = summary.get("latest_fundamentals")
    if isinstance(latest, dict) and latest:
        return True
    source_coverage = summary.get("source_coverage")
    if isinstance(source_coverage, dict):
        coverage = source_coverage.get("sec_company_facts")
        if isinstance(coverage, dict) and coverage.get("status") == "covered":
            return True
    return False


def _has_complete_sec_company_helper_evidence(summary: dict[str, object]) -> bool:
    latest = summary.get("latest_fundamentals")
    if not isinstance(latest, dict) or not latest:
        return False

    source_coverage = summary.get("source_coverage")
    if not isinstance(source_coverage, dict):
        return False
    sec_coverage = source_coverage.get("sec_company_facts")
    if not isinstance(sec_coverage, dict) or sec_coverage.get("status") != "covered":
        return False

    return any(
        _is_sec_company_helper_fact(fact)
        for fact in _numeric_facts_from_summary(summary)
    )


def _is_sec_company_helper_fact(fact: dict[str, object]) -> bool:
    fact_id = str(fact.get("id") or "")
    source_key = str(fact.get("source_key") or "")
    return fact_id.startswith("sec_company_facts.") and source_key.startswith(
        "sec_company_facts.latest_fundamentals."
    )


def _missing_helper_evidence_blocker(
    report_data: dict[str, object],
    summary: dict[str, object],
) -> str | None:
    if not _report_claims_company_fundamental_analysis(report_data):
        return None
    if not _sec_company_files_present(summary):
        return None
    if _has_reusable_company_evidence(summary):
        return None
    return (
        "Report includes stock-specific company-fundamentals claims and SEC "
        "company-facts files are present in the quantitative handoff, but "
        "execution_summary.json lacks complete reusable SEC helper evidence: "
        "latest_fundamentals, source_coverage.sec_company_facts=covered, and "
        "sec_company_facts.* numeric_facts from sec_company_facts_evidence(...). "
        "Rerun quantitative-developer so analysis.py composes the SEC helper "
        "output before writer synthesis."
    )


_CLOSEST_ANALOG_RE = re.compile(
    r"(?:closest|most similar|best|top)[^\n.]{0,100}?\b((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_ANALOG_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ANALOG_TOPIC_RE = re.compile(r"\b(?:analog|analogue)\b", re.IGNORECASE)
_ANALOG_ANALYTIC_CLAIM_RE = re.compile(
    r"\b(?:closest|most similar|similarity|distance|ranked|ranking)\b|"
    r"\b(?:best|top)\s+(?:analog|analogue|match|fit|window|episode)\b|"
    r"\b(?:resembles?|look(?:s|ed)?\s+(?:more\s+|most\s+)?like)\b",
    re.IGNORECASE,
)
_ANALOG_LIMITATION_RE = re.compile(
    r"\b(?:unavailable|not\s+available|not\s+covered|insufficient|excluded|missing|"
    r"not\s+present)\b",
    re.IGNORECASE,
)
_ANALOG_COVERAGE_CONTEXT_RE = re.compile(
    r"\b(?:data|dataset|sample|series|coverage|available|availability|"
    r"observations?|history)\b[^\n.]{0,80}\b(?:from|since|starting|starts?|"
    r"begins?|onward|through|limited|only|excludes?|excluded|missing)\b|"
    r"\b(?:from|since|starting|starts?|begins?|onward|through|limited)\b"
    r"[^\n.]{0,80}\b(?:data|dataset|sample|series|coverage|available|"
    r"availability|observations?|history)\b",
    re.IGNORECASE,
)


def _analog_years(text: object) -> set[str]:
    return set(_ANALOG_YEAR_RE.findall(str(text)))


def _analog_labels_match(claimed: object, expected: object) -> bool:
    claimed_text = str(claimed).strip().lower()
    expected_text = str(expected).strip().lower()
    if not claimed_text or not expected_text:
        return False
    if claimed_text == expected_text:
        return True
    claimed_years = _analog_years(claimed_text)
    expected_years = _analog_years(expected_text)
    return bool(claimed_years and expected_years and claimed_years == expected_years)


def _line_claims_historical_analog_evidence(line: str) -> bool:
    if _ANALOG_LIMITATION_RE.search(line):
        return False
    if _ANALOG_COVERAGE_CONTEXT_RE.search(line):
        return bool(_ANALOG_ANALYTIC_CLAIM_RE.search(line))
    return bool(
        _ANALOG_TOPIC_RE.search(line) or _ANALOG_ANALYTIC_CLAIM_RE.search(line)
    )


def _execution_summary_analog_years(summary: dict[str, object]) -> set[str]:
    labels: list[object] = []
    for key in ("analog_profiles",):
        values = summary.get(key)
        if isinstance(values, dict):
            labels.extend(values.keys())
    for key in (
        "historical_window_coverage",
        "replay_rows",
        "analog_similarity_ranking",
        "analog_profile_rows",
        "regime_analog_rows",
    ):
        rows = summary.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                labels.append(row.get("label") or row.get("analog") or row.get("date"))
    design = summary.get("comparison_design")
    if isinstance(design, dict):
        for key in ("named_windows", "excluded_windows"):
            windows = design.get(key)
            if not isinstance(windows, list):
                continue
            for row in windows:
                if isinstance(row, dict):
                    labels.append(row.get("label") or row.get("name"))
    years: set[str] = set()
    for label in labels:
        years.update(_analog_years(label))
    return years


def _claimed_historical_analog_years(markdown: str) -> set[str]:
    claimed: set[str] = set()
    in_research_query = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            in_research_query = heading == "research query"
            if in_research_query:
                continue
        if in_research_query:
            continue
        if not _line_claims_historical_analog_evidence(line):
            continue
        for match in _ANALOG_YEAR_RE.finditer(line):
            before = line[max(0, match.start() - 32) : match.start()].lower()
            if re.search(r"\bcurrent\b[^\n.]{0,32}$", before):
                continue
            claimed.add(match.group(0))
    return claimed


def _historical_window_coverage_map(
    summary: dict[str, object],
) -> dict[str, dict[str, object]]:
    rows = summary.get("historical_window_coverage")
    if not isinstance(rows, list):
        return {}
    coverage: dict[str, dict[str, object]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("label"):
            coverage[str(row["label"])] = row
    return coverage


def _unsupported_historical_analog_claim_blocker(
    summary: dict[str, object], markdown: str
) -> str | None:
    claimed_years = _claimed_historical_analog_years(markdown)
    if claimed_years:
        missing_years = sorted(claimed_years - _execution_summary_analog_years(summary))
        if missing_years:
            return (
                "Report claims historical analog evidence for year(s) missing from "
                f"execution_summary.json: {', '.join(missing_years)}. Use only "
                "computed analog windows or state unavailable coverage."
            )

    coverage = _historical_window_coverage_map(summary)
    if not coverage:
        return None
    unsupported = [
        label
        for label, row in coverage.items()
        if str(row.get("status") or "").lower() != "covered"
    ]
    if not unsupported:
        return None

    claimed: list[str] = []
    for label in unsupported:
        label_lower = label.lower()
        years = _analog_years(label)
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line_lower = line.lower()
            if not (
                label_lower in line_lower or any(year in line for year in years)
            ):
                continue
            if _line_claims_historical_analog_evidence(line_lower):
                claimed.append(label)
                break
    if not claimed:
        return None
    return (
        "Report claims historical analog evidence for window(s) without covered "
        "source history: "
        f"{', '.join(claimed[:6])}. Use only historical_window_coverage rows "
        "with status=covered for analog ranking/charts, and state unavailable "
        "coverage for the excluded windows."
    )


def _analog_similarity_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    rows = summary.get("analog_similarity_ranking")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _ranking_similarity_score(
    summary: dict[str, object], analog_label: object
) -> object:
    for row in _analog_similarity_rows(summary):
        label = row.get("label") or row.get("analog")
        if label is None or not _analog_labels_match(label, analog_label):
            continue
        for key in ("normalized_similarity", "similarity_score", "score"):
            if row.get(key) is not None:
                return row.get(key)
    return None


def _top_ranked_analog_label(summary: dict[str, object]) -> object:
    for row in _analog_similarity_rows(summary):
        label = row.get("label") or row.get("analog")
        if not label:
            continue
        if str(row.get("status") or "ok").lower() in {
            "ok",
            "covered",
            "descriptive_replay",
            "included",
        }:
            return label
    return None


def _has_reusable_historical_evidence(summary: dict[str, object]) -> bool:
    historical_failures = summary.get("historical_failure_episodes")
    if isinstance(historical_failures, list) and historical_failures:
        return True
    for key in (
        "replay_rows",
        "signal_event_rows",
        "signal_false_positive_windows",
        "signal_score_rows",
        "lead_time_rows",
        "analog_profile_rows",
        "analog_similarity_ranking",
        "regime_analog_rows",
    ):
        rows = summary.get(key)
        if isinstance(rows, list) and rows:
            return True
    return False


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _metric_mismatch(
    metrics: dict[str, object],
    key: str,
    expected: float | int | None,
    *,
    tolerance: float = 1e-6,
) -> bool:
    if expected is None:
        return False
    observed = _finite_number(metrics.get(key))
    if observed is None:
        return False
    return abs(observed - float(expected)) > tolerance


def _signal_validation_metric_mismatches(summary: dict[str, object]) -> list[str]:
    metrics = summary.get("signal_validation_metrics")
    if not isinstance(metrics, dict):
        return []

    event_rows = _dict_rows(summary.get("signal_event_rows"))
    false_positive_rows = _dict_rows(summary.get("signal_false_positive_windows"))
    mismatches: list[str] = []

    if event_rows:
        event_count = len(event_rows)
        events_met_threshold = sum(row.get("met_threshold") is True for row in event_rows)
        events_below_threshold = sum(row.get("met_threshold") is False for row in event_rows)
        if _metric_mismatch(metrics, "event_count", event_count):
            mismatches.append("event_count")
        if _metric_mismatch(metrics, "events_met_threshold", events_met_threshold):
            mismatches.append("events_met_threshold")
        if _metric_mismatch(metrics, "events_below_threshold", events_below_threshold):
            mismatches.append("events_below_threshold")
        if _metric_mismatch(
            metrics,
            "true_positive_rate",
            events_met_threshold / event_count if event_count else None,
        ):
            mismatches.append("true_positive_rate")

    false_positive_count = len(false_positive_rows)
    if false_positive_rows and _metric_mismatch(
        metrics,
        "false_positive_windows",
        false_positive_count,
    ):
        mismatches.append("false_positive_windows")

    if event_rows or false_positive_rows:
        events_met_threshold = sum(row.get("met_threshold") is True for row in event_rows)
        precision_denominator = events_met_threshold + false_positive_count
        expected_precision = (
            events_met_threshold / precision_denominator
            if precision_denominator
            else None
        )
        if _metric_mismatch(metrics, "precision", expected_precision):
            mismatches.append("precision")

    return mismatches


def _helper_diagnostic_consistency_blockers(summary: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    signal_mismatches = _signal_validation_metric_mismatches(summary)
    if signal_mismatches:
        blockers.append(
            "signal_validation_metrics contradict reusable signal evidence rows for "
            f"{', '.join(signal_mismatches[:8])}. Regenerate execution_summary.json "
            "so validation metrics, replay rows, and numeric facts share one "
            "auditable source of truth."
        )

    score_rows = summary.get("scenario_score_rows")
    if isinstance(score_rows, list) and score_rows:
        finite_scores = [
            _finite_number(row.get("score"))
            for row in score_rows
            if isinstance(row, dict)
        ]
        if finite_scores and all((score or 0.0) == 0.0 for score in finite_scores):
            blockers.append(
                "scenario_score_rows contains only zero scores. Recompute scenario "
                "deltas from the current helper inputs instead of emitting "
                "placeholder base/upside/downside values."
            )
    return blockers


def _sec_company_files_present(summary: dict[str, object]) -> bool:
    status = summary.get("company_context_status")
    if isinstance(status, dict) and status.get("sec_source_keys"):
        return True
    if _data_files_used_has_sec_company_facts(summary.get("data_files_used")):
        return True
    for key, path in _iter_sec_company_data_file_candidates(summary):
        if (
            _is_sec_company_file_reference(key, path)
            or _looks_like_sec_company_facts_ref(key)
            or _looks_like_sec_company_facts_ref(path)
        ):
            return True
    return False


def _iter_sec_company_data_file_candidates(
    summary: dict[str, object],
) -> Iterable[tuple[object, object]]:
    for container_key in ("source_files", "data_files"):
        container = summary.get(container_key)
        if isinstance(container, dict):
            yield from container.items()

    manifest = summary.get("quant_input_manifest")
    data_files = manifest.get("data_files") if isinstance(manifest, dict) else None
    if isinstance(data_files, dict):
        yield from data_files.items()


def _is_sec_company_file_reference(key: object, path: object) -> bool:
    key_upper = str(key).upper()
    path_name = Path(str(path)).name.lower()
    return key_upper.endswith("_SEC") or "sec_edgar_company_facts" in path_name


def _data_files_used_has_sec_company_facts(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _looks_like_sec_company_facts_ref(key)
            or _data_files_used_has_sec_company_facts(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_data_files_used_has_sec_company_facts(item) for item in value)
    return _looks_like_sec_company_facts_ref(value)


_MODEL_CLAIM_RE = re.compile(
    r"\b(?:ols|ordinary\s+least\s+squares|forecast(?:s|ed|ing)?|"
    r"projection(?:s)?|projects?|projected|prediction\s+interval|confidence\s+bands?|"
    r"confidence\s+intervals?|low\s+band|high\s+band|baseline\s+(?:comparison|forecast|model)|"
    r"out-of-sample\s+forecast)\b",
    re.IGNORECASE,
)
_UNAVAILABLE_MODEL_RE = re.compile(
    r"\b(?:not\s+(?:computed|available|covered|supported)|unavailable|insufficient|"
    r"did\s+not\s+compute|does\s+not\s+include|no\s+(?:forecast|projection|model)|"
    r"without\s+(?:forecast|projection|model))\b",
    re.IGNORECASE,
)


def _normalized_numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for value in _numeric_candidates(text):
        tokens.add(f"{value:g}")
    return tokens


def _model_claim_lines(markdown: str) -> list[str]:
    claim_lines: list[str] = []
    in_research_query = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            in_research_query = heading == "research query"
            if in_research_query:
                continue
        if in_research_query or _UNAVAILABLE_MODEL_RE.search(line):
            continue
        if _MODEL_CLAIM_RE.search(line):
            claim_lines.append(line)
    return claim_lines


def _has_generic_model_evidence(summary: dict[str, object]) -> bool:
    for key in (
        "forecast_rows",
        "forecast_table",
        "walk_forward_backtest_rows",
        "model_validation_rows",
        "model_comparison_by_horizon",
        "model_comparison_rows",
        "forecast_band_rows",
        "composite_score_rows",
    ):
        value = summary.get(key)
        if isinstance(value, (dict, list)) and bool(value):
            return True

    for key in (
        "diagnostics",
        "event_backtest_metrics",
        "signal_validation_metrics",
        "latest_signal_observation",
        "composite_current_row",
        "composite_validation_metrics",
        "composite_validation_design",
        "numeric_facts",
        "source_coverage",
        "methods_used",
        "limitations",
    ):
        value = summary.get(key)
        if isinstance(value, (dict, list)) and bool(value):
            return True
    return False


def _has_generic_validation_evidence(summary: dict[str, object]) -> bool:
    for key in (
        "walk_forward_backtest_rows",
        "model_validation_rows",
        "model_comparison_by_horizon",
        "model_comparison_rows",
        "historical_failure_episodes",
        "replay_rows",
        "historical_window_coverage",
        "analog_similarity_ranking",
        "analog_profile_rows",
        "regime_analog_rows",
        "lead_time_rows",
        "signal_score_rows",
        "signal_event_rows",
        "signal_false_positive_windows",
        "composite_score_rows",
    ):
        value = summary.get(key)
        if isinstance(value, list) and value:
            return True

    for key in (
        "diagnostics",
        "event_backtest_metrics",
        "signal_validation_metrics",
        "latest_signal_observation",
        "composite_current_row",
        "composite_validation_metrics",
        "composite_validation_design",
        "numeric_facts",
        "source_coverage",
        "methods_used",
        "limitations",
    ):
        value = summary.get(key)
        if isinstance(value, (dict, list)) and value:
            return True
    return False


def _model_claim_evidence_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    if not _model_claim_lines(markdown):
        return []
    if _has_generic_model_evidence(summary):
        return []
    return [
        "Report makes model, projection, or forecast claims, but "
        "execution_summary.json lacks generic helper evidence such as "
        "forecast rows, model validation rows, backtest diagnostics, methods, "
        "chart IDs, source coverage, limitations, or numeric_facts. Regenerate "
        "the report from helper-produced tables and diagnostics, or state that "
        "the model evidence was unavailable."
    ]


_WAGE_GAP_CLAIM_RE = re.compile(
    r"\b(wage|earnings|pay)\b.{0,80}\b(gap|diverg|difference|spread|versus|vs\.?|compare|comparison)\b"
    r"|\b(gap|diverg|difference|spread|versus|vs\.?|compare|comparison)\b.{0,80}\b(wage|earnings|pay)\b",
    re.IGNORECASE | re.DOTALL,
)


def _summary_contains_wage_gap_metric(value: object, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if (
                any(token in key_text for token in ("wage", "earnings", "pay"))
                and any(
                    token in key_text
                    for token in ("gap", "diverg", "difference", "spread", "compare")
                )
            ):
                return True
            if _summary_contains_wage_gap_metric(child, depth=depth + 1):
                return True
    elif isinstance(value, list):
        return any(_summary_contains_wage_gap_metric(item, depth=depth + 1) for item in value)
    return False


def _chart_text_for_wage_unit_review(report_data: dict[str, object]) -> str:
    pieces: list[str] = []
    for chart in _iter_report_charts(report_data):
        for key in ("id", "title", "description"):
            value = chart.get(key)
            if isinstance(value, str):
                pieces.append(value)
        series = chart.get("series")
        if isinstance(series, list):
            for item in series:
                if not isinstance(item, dict):
                    continue
                for key in ("dataKey", "label", "name"):
                    value = item.get(key)
                    if isinstance(value, str):
                        pieces.append(value)
    return "\n".join(pieces)


def _iter_report_charts(report_data: dict[str, object]) -> list[dict[str, object]]:
    charts = report_data.get("charts")
    if isinstance(charts, dict):
        chart_items = charts.values()
    elif isinstance(charts, list):
        chart_items = charts
    else:
        return []
    return [chart for chart in chart_items if isinstance(chart, dict)]


def _chart_series_count(chart: dict[str, object]) -> int:
    series = chart.get("series")
    if isinstance(series, list):
        return len([item for item in series if isinstance(item, dict)])

    data = chart.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return 0
    x_axis_key = str(chart.get("xAxisKey") or chart.get("x_axis_key") or "").strip()
    excluded = {"date", "period", "year", "month", "quarter", "label", "name", x_axis_key}
    return len(
        [
            key
            for key, value in data[0].items()
            if str(key).strip().lower() not in excluded and isinstance(value, (int, float))
        ]
    )


def _mixed_wage_unit_chart_overlays(
    report_data: dict[str, object],
    source_unit_metadata: object,
) -> list[str]:
    source_basis_by_token = _wage_source_basis_by_token(source_unit_metadata)
    if len(set(source_basis_by_token.values())) < 2:
        return []

    overlays: list[str] = []
    for chart in _iter_report_charts(report_data):
        chart_tokens = _chart_source_tokens(chart)
        matched_bases = {
            source_basis_by_token[token]
            for token in chart_tokens
            if token in source_basis_by_token
        }
        if _chart_series_count(chart) < 2 or len(matched_bases) < 2:
            continue
        label = str(chart.get("id") or chart.get("title") or "unnamed chart")
        title = str(chart.get("title") or "").strip()
        overlays.append(f"{label} ({title})" if title and title != label else label)
    return overlays


def _wage_source_basis_by_token(source_unit_metadata: object) -> dict[str, str]:
    basis_by_token: dict[str, str] = {}
    for record in normalize_source_unit_metadata(source_unit_metadata):
        family = str(record.get("unit_family") or "").lower()
        basis = str(record.get("unit_basis") or "").strip().lower()
        measure = str(record.get("measure") or "").lower()
        text = f"{record.get('title') or ''} {record.get('units') or ''}".lower()
        if family != "currency_per_time" or not basis:
            continue
        if measure != "wage" and "wage" not in text and "earnings" not in text:
            continue
        for key in ("source_key", "series_id"):
            token = _source_unit_token(record.get(key))
            if token:
                basis_by_token[token] = basis
        source_file = record.get("source_file")
        if isinstance(source_file, str) and source_file.strip():
            token = _source_unit_token(Path(source_file).stem)
            if token:
                basis_by_token[token] = basis
    return basis_by_token


def _chart_source_tokens(chart: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    for key in ("id",):
        token = _source_unit_token(chart.get(key))
        if token:
            tokens.add(token)

    series = chart.get("series")
    if isinstance(series, list):
        for item in series:
            if not isinstance(item, dict):
                continue
            for key in ("dataKey", "label", "name", "source_key", "series_id"):
                token = _source_unit_token(item.get(key))
                if token:
                    tokens.add(token)

    data = chart.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        for key in data[0]:
            token = _source_unit_token(key)
            if token:
                tokens.add(token)

    provenance = chart.get("provenance")
    if isinstance(provenance, dict):
        for key in ("source_series", "source_files"):
            _add_source_unit_tokens(tokens, provenance.get(key))
    return tokens


def _add_source_unit_tokens(tokens: set[str], value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            for item in (key, child):
                token = _source_unit_token(Path(item).stem if isinstance(item, str) else item)
                if token:
                    tokens.add(token)
    elif isinstance(value, list):
        for item in value:
            token = _source_unit_token(Path(item).stem if isinstance(item, str) else item)
            if token:
                tokens.add(token)
    else:
        token = _source_unit_token(value)
        if token:
            tokens.add(token)


def _source_unit_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _source_unit_fidelity_blockers(
    summary: dict[str, object],
    markdown: str,
    report_data: dict[str, object],
) -> list[str]:
    if not summary:
        return []

    enriched_summary = dict(summary)
    attach_source_unit_metadata(enriched_summary)

    blockers = [
        f"execution_summary.json source-unit comparison failed: {message}"
        for message in failed_unit_comparison_messages(enriched_summary)
    ]

    mixed_wage_sources = mixed_wage_period_sources(
        enriched_summary.get("source_unit_metadata")
    )
    if len(mixed_wage_sources) < 2:
        return blockers
    if has_passing_mixed_wage_unit_comparison(enriched_summary):
        return blockers

    chart_overlays = _mixed_wage_unit_chart_overlays(
        report_data,
        enriched_summary.get("source_unit_metadata"),
    )
    review_text = "\n".join(
        (
            markdown,
            _chart_text_for_wage_unit_review(report_data),
        )
    )
    mentions_wage_gap = bool(_WAGE_GAP_CLAIM_RE.search(review_text))
    mentions_summary_gap = _summary_contains_wage_gap_metric(enriched_summary)
    if not chart_overlays and not mentions_wage_gap and not mentions_summary_gap:
        return blockers

    basis_details = "; ".join(
        f"{basis}: {', '.join(labels[:4])}"
        for basis, labels in sorted(mixed_wage_sources.items())
    )
    comparison_context = "wage gap/divergence claims"
    if chart_overlays:
        comparison_context = "direct wage chart overlays"
        chart_details = ", ".join(chart_overlays[:4])
        if mentions_wage_gap or mentions_summary_gap:
            comparison_context += " and wage gap/divergence claims"
        comparison_context += f" ({chart_details})"
    blockers.append(
        f"Report or execution_summary.json contains {comparison_context} while "
        "using wage sources with incompatible unit bases and no passing "
        f"unit_comparisons contract ({basis_details}). Regenerate quant artifacts "
        "after converting to a common unit, or remove the direct wage gap claim."
    )
    return blockers


def _execution_summary_fidelity_blockers(
    report_data: dict[str, object], report_path: Path
) -> list[str]:
    summary = _load_execution_summary_payload(report_path)
    if not summary:
        return []

    markdown = str(report_data.get("markdown", ""))
    blockers: list[str] = []
    unsupported_analog = _unsupported_historical_analog_claim_blocker(summary, markdown)
    if unsupported_analog:
        blockers.append(unsupported_analog)
    blockers.extend(_model_claim_evidence_blockers(summary, markdown))
    blockers.extend(_helper_diagnostic_consistency_blockers(summary))
    missing_helper_evidence = _missing_helper_evidence_blocker(
        report_data,
        summary,
    )
    if missing_helper_evidence:
        blockers.append(missing_helper_evidence)
    blockers.extend(_source_unit_fidelity_blockers(summary, markdown, report_data))
    blockers.extend(_state_comparison_fidelity_blockers(summary, markdown))
    blockers.extend(_numeric_fact_fidelity_blockers(summary, markdown))

    ranked_analog = _top_ranked_analog_label(summary)
    if ranked_analog is not None:
        expected = str(ranked_analog)
        match = _CLOSEST_ANALOG_RE.search(markdown)
        if match and not _analog_labels_match(match.group(1), expected):
            blockers.append(
                "Report claims the closest historical analog is "
                f"{match.group(1)}, but analog_similarity_ranking is led by "
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

    if ranked_analog is not None and "similarity score" in markdown.lower():
        top_score = _ranking_similarity_score(summary, ranked_analog)
        variants = _numeric_text_variants(top_score)
        if variants and not any(variant in markdown for variant in variants):
            blockers.append(
                "Report discusses similarity scores but omits the leading ranked "
                "analog score from analog_similarity_ranking. Regenerate the "
                "analog prose from helper-produced ranking rows."
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


_CURRENT_EVIDENCE_TERMS = {"current", "latest"}
_CURRENT_EVIDENCE_DATE_FIELDS = {
    "date",
    "as_of_date",
    "latest_date",
    "latest_observation_date",
    "observation_date",
}
_HISTORICAL_DATE_FIELD_MARKERS = {
    "event",
    "fiscal",
    "max",
    "min",
    "prediction",
    "prior",
    "start",
    "target",
    "window",
}


def _is_current_evidence_container(path: tuple[str, ...]) -> bool:
    for part in path:
        tokens = {token for token in re.split(r"[^a-z0-9]+", part.lower()) if token}
        if tokens & _CURRENT_EVIDENCE_TERMS:
            return True
    return False


def _is_current_evidence_date_field(field_name: str, in_current_container: bool) -> bool:
    normalized = field_name.lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}
    if tokens & _HISTORICAL_DATE_FIELD_MARKERS:
        return False
    if in_current_container and normalized in _CURRENT_EVIDENCE_DATE_FIELDS:
        return True
    return bool(tokens & _CURRENT_EVIDENCE_TERMS) and "date" in tokens


def _current_evidence_dates(
    value: object,
    *,
    path: tuple[str, ...] = (),
    in_current_container: bool = False,
) -> list[datetime]:
    if isinstance(value, list):
        dates: list[datetime] = []
        for item in value:
            dates.extend(
                _current_evidence_dates(
                    item,
                    path=path,
                    in_current_container=in_current_container,
                )
            )
        return dates
    if not isinstance(value, dict):
        return []

    current_container = in_current_container or _is_current_evidence_container(path)
    dates: list[datetime] = []
    for key, item in value.items():
        key_text = str(key)
        if _is_current_evidence_date_field(key_text, current_container):
            parsed = _parse_report_datetime(item)
            if parsed is not None:
                dates.append(parsed)
        if isinstance(item, (dict, list)):
            dates.extend(
                _current_evidence_dates(
                    item,
                    path=(*path, key_text),
                    in_current_container=current_container,
                )
            )
    return dates


def _current_helper_evidence_freshness_blocker(
    report_data: dict[str, object], summary: dict[str, object]
) -> str | None:
    current_dates = _current_evidence_dates(summary)
    if not current_dates:
        return None
    as_of = max(current_dates)
    report_dt = _parse_report_datetime(report_data.get("created_at")) or datetime.now(timezone.utc)
    age_days = (report_dt - as_of).days
    if age_days <= 370:
        return None
    return (
        "Report uses stale current helper evidence: the freshest current/latest "
        f"helper row date is {as_of.date().isoformat()}, which is {age_days} "
        "days before report creation. Rerun data-engineer without a historical "
        "observation_end cutoff for current/latest source series, then regenerate "
        "the quantitative artifacts and report."
    )


def _chart_semantics_approval_blockers(data: dict[str, object]) -> list[str]:
    try:
        report = ResearchReport(**data)
    except ValidationError:
        return []
    semantics = chart_semantics_dict(report)
    if semantics.get("valid", True):
        return []
    return [
        "Report fails the static chart data semantics audit used by "
        "validate_research_report_file: "
        f"{semantics.get('blockers')}. Regenerate the quantitative chart data "
        "or repair the report before QA approval."
    ]


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
    full_summary = _load_execution_summary_payload(Path(report_path)) or {}
    blockers: list[str] = []
    freshness_blocker = _current_helper_evidence_freshness_blocker(data, full_summary)
    if freshness_blocker:
        blockers.append(freshness_blocker)
    handoff_blocker = chart_handoff_blocker(chart_handoff_dict(data, full_summary))
    if handoff_blocker:
        blockers.append(handoff_blocker)
    fact_blocker = artifact_fact_consistency_blocker(
        artifact_fact_consistency_dict(
            execution_summary=full_summary,
            report_data=data,
        )
    )
    if fact_blocker:
        blockers.append(fact_blocker)
    blockers.extend(_chart_semantics_approval_blockers(data))
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
        summary.get("composite_validation_metrics")
        and "recession" in markdown
        and ("probability" in markdown or "near term" in markdown or "risk score" in markdown)
        and not any(
            term in markdown
            for term in ("backtest", "precision", "recall", "false negative", "false-positive")
        )
    ):
        blockers.append(
            "Report cites a recession-risk probability or score but omits available composite-indicator validation diagnostics such as precision, recall, or false negatives."
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
    if _query_requires_econometric_validation(query) and summary.get("status") not in {
        "failed",
        "error",
        "missing",
    }:
        if not _has_generic_validation_evidence(full_summary):
            blockers.append(
                "Econometric or predictive report lacks generic helper validation evidence in execution_summary.json: expected numeric_facts, source coverage, methods, chart IDs, tables, diagnostics, limitations, forecast rows, or model validation rows."
            )
        if (
            (
                "historical" in query.lower()
                or "prior downturn" in query.lower()
                or "earlier downturn" in query.lower()
                or "past downturn" in query.lower()
                or "cried wolf" in query.lower()
            )
            and not summary.get("replay_rows")
            and not _has_reusable_historical_evidence(full_summary)
        ):
            blockers.append(
                "Historical comparison request lacks reusable replay rows, analog rows, or helper-produced historical failure rows in execution_summary.json."
            )
    return blockers


def _approval_failure_metadata(report_path: str) -> dict[str, str]:
    data, error = load_report_json(report_path)
    if error:
        return {}
    summary = _load_execution_summary_payload(Path(report_path))
    if not summary:
        return {}
    markdown = str(data.get("markdown", ""))
    if _source_unit_fidelity_blockers(summary, markdown, data):
        return {
            "failure_category": "source_unit_mismatch",
            "required_upstream": "quantitative-developer",
        }
    chart_handoff = chart_handoff_dict(data, summary)
    if chart_handoff_blocker(chart_handoff):
        required_upstream = (
            "quant-developer"
            if chart_handoff.get("missing_report_chart_ids")
            else "technical-writer"
        )
        return {
            "failure_category": "chart_handoff_mismatch",
            "required_upstream": required_upstream,
        }
    if artifact_fact_consistency_blocker(
        artifact_fact_consistency_dict(execution_summary=summary, report_data=data)
    ):
        return {
            "failure_category": "artifact_fact_mismatch",
            "required_upstream": "quant-developer",
        }
    if _chart_semantics_approval_blockers(data):
        return {
            "failure_category": "chart_semantics_mismatch",
            "required_upstream": "quantitative-developer",
        }
    if _model_claim_evidence_blockers(summary, markdown):
        return {
            "failure_category": "missing_helper_evidence",
            "required_upstream": "quantitative-developer",
        }
    if _helper_diagnostic_consistency_blockers(summary):
        return {
            "failure_category": "helper_diagnostic_mismatch",
            "required_upstream": "quantitative-developer",
        }
    if _missing_helper_evidence_blocker(data, summary):
        return {
            "failure_category": "missing_helper_evidence",
            "required_upstream": "quantitative-developer",
        }
    if _numeric_fact_fidelity_blockers(summary, markdown):
        return {
            "failure_category": "numeric_fact_mismatch",
            "required_upstream": "technical-writer",
        }
    unsupported_analog = _unsupported_historical_analog_claim_blocker(
        summary,
        str(data.get("markdown", "")),
    )
    if unsupported_analog:
        return {
            "failure_category": "unsupported_historical_analog_claim",
            "required_upstream": "technical-writer",
        }
    return {}
