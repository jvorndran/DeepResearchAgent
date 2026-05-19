"""QA rejection parsing and repair routing helpers for the orchestrator."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_PIPELINE_REPAIR_OWNERS = {
    "data-engineer",
    "quant-developer",
    "technical-writer",
    "quality-analyst",
}

_PIPELINE_REPAIR_OWNER_ALIASES = {
    "quantitative-developer": "quant-developer",
}

_PRE_WRITER_QUANT_FAILURE_CATEGORIES = {
    "quant_artifact_handoff_failed",
    "quant_artifact_handoff_invalid",
}


@dataclass(frozen=True)
class QualityDecision:
    """Compact structured QA/report-gate decision recovered from messages."""

    status: str
    report_path: str
    reason: str = ""
    required_fixes: tuple[str, ...] = ()
    required_upstream: str | None = None
    failure_category: str | None = None

    @property
    def repair_text(self) -> str:
        parts = [
            self.reason,
            self.required_upstream or "",
            self.failure_category or "",
            *self.required_fixes,
        ]
        return " ".join(part for part in parts if part).lower()


_QA_REFERENCE_MARKERS = (
    "qa rejected",
    "qa rejection",
    "quality-analyst rejected",
    "quality-analyst rejection",
    "quality analyst rejected",
    "quality analyst rejection",
    "qa says",
    "qa flagged",
    "qa asked",
    "qa is asking",
    "qa analyst says",
    "qa analyst flagged",
    "qa analyst asked",
    "qa analyst is asking",
    "quality analyst says",
    "quality analyst flagged",
    "quality analyst asked",
    "quality analyst is asking",
    "quality-analyst says",
    "quality-analyst flagged",
    "quality-analyst asked",
    "quality-analyst is asking",
    "required_fixes",
    "required fixes",
)

_QUANT_REPAIR_MARKERS = (
    "computed artifacts are missing",
    "quantitative artifacts are missing",
    "computed artifacts are stale",
    "quantitative artifacts are stale",
    "computed artifacts are invalid",
    "quantitative artifacts are invalid",
    "computed artifact failures",
    "computed artifact failure",
    "computed charts are missing",
    "computed charts are stale",
    "computed charts are invalid",
    "chart data rendering",
    "chart rendering",
    "chart render",
    "chart data issue",
    "charts.json data",
    "charts.json still has",
    "stale charts",
    "invalid charts",
    "missing charts",
    "missing chart family",
    "missing chart families",
    "missing chart marker",
    "missing chart markers",
    "missing chart definition",
    "missing chart definitions",
    "new chart definition",
    "new chart definitions",
    "chart definition needed",
    "chart definitions needed",
    "chart artifact missing",
    "chart artifacts missing",
    "non-finite",
    "no finite numeric values",
    "nan/inf",
    "nan or inf",
    "nan values",
    "infinite values",
    "chart markers are missing",
    "chart definitions are missing",
    "charts.json has zero",
    "charts.json has no",
    "chart_count:0",
    "chart_count=0",
    "chart_ids are empty",
    "chart ids are empty",
    "required quantitative artifacts are missing or failed",
    "execution_summary lacks",
    "execution_summary.json lacks",
    "execution_summary packet must include",
    "execution_summary metadata",
    "execution_summary.json metadata",
    "requested historical analog",
    "requested analog window",
    "missing requested analog",
    "missing requested window",
    "computed analog window",
    "backtest_summary",
    "model_comparison",
    "replay_rows",
    "structured json keys",
    "structured keys",
    "enrichment keys",
    "need recalculation",
    "needs recalculation",
    "require recalculation",
    "requires recalculation",
    "requires new analysis",
    "need new analysis",
    "rerun quant",
    "rerun quant-developer",
    "regenerate the analysis",
    "regenerate analysis",
)

_WRITER_REPAIR_MARKERS = (
    "report-vs-execution_summary",
    "report vs execution_summary",
    "report's composite",
    "report prose",
    "writer used",
    "report writer used",
    "narrative wording",
    "numerical discrepancies between report",
    "discrepancies between report",
    "fundamentally disagrees with the execution_summary",
    "disagrees with the execution_summary",
    "contradiction between report",
    "report fidelity",
)


def _parse_required_fixes(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return (value,)
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed if str(item).strip())
        return (value,)
    return ()


def _canonical_repair_owner(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    owner = value.strip()
    if not owner:
        return None
    owner = _PIPELINE_REPAIR_OWNER_ALIASES.get(owner, owner)
    if owner not in _PIPELINE_REPAIR_OWNERS:
        return None
    return owner


def _decision_from_payload(payload: object) -> QualityDecision | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status not in {"approved", "rejected", "failed"}:
        return None

    reason = str(payload.get("reason") or "")
    required_fixes = _parse_required_fixes(payload.get("required_fixes"))
    required_upstream = _canonical_repair_owner(payload.get("required_upstream"))
    failure_category = payload.get("failure_category")
    if not isinstance(failure_category, str):
        failure_category = None
    else:
        failure_category = failure_category.strip() or None

    report_path = payload.get("report_path") or payload.get("report_json")
    is_report_decision = isinstance(report_path, str) and report_path.endswith(
        "/report.json"
    )
    is_pre_writer_quant_route = (
        status == "failed"
        and payload.get("blocked_subagent") in {"technical-writer", "quality-analyst"}
        and required_upstream == "quant-developer"
        and failure_category in _PRE_WRITER_QUANT_FAILURE_CATEGORIES
    )
    if not is_report_decision:
        if not is_pre_writer_quant_route:
            return None
        report_path = ""

    if status == "rejected" and not required_fixes:
        return None
    if status == "failed" and not (required_fixes or required_upstream or reason):
        return None

    return QualityDecision(
        status=status,
        report_path=report_path,
        reason=reason,
        required_fixes=required_fixes,
        required_upstream=required_upstream,
        failure_category=failure_category,
    )


def iter_quality_decisions(messages: list[Any]) -> list[QualityDecision]:
    decisions: list[QualityDecision] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        decision = _decision_from_payload(payload)
        if decision is not None:
            decisions.append(decision)
    return decisions


def latest_quality_decision(messages: list[Any]) -> QualityDecision | None:
    decisions = iter_quality_decisions(messages)
    return decisions[-1] if decisions else None


def latest_pipeline_status(messages: list[Any]) -> str | None:
    decision = latest_quality_decision(messages)
    return decision.status if decision is not None else None


def latest_required_upstream(messages: list[Any]) -> str | None:
    decision = latest_quality_decision(messages)
    if decision is None or decision.status not in {"rejected", "failed"}:
        return None
    return decision.required_upstream


def is_report_fidelity_quant_misdirection(text: str) -> bool:
    lowered = text.lower()
    if not any(marker in lowered for marker in _WRITER_REPAIR_MARKERS):
        return False
    return not any(marker in lowered for marker in _QUANT_REPAIR_MARKERS)


def text_requires_quant_repair(text: str) -> bool:
    lowered = text.lower()
    if is_report_fidelity_quant_misdirection(lowered):
        return False
    return any(marker in lowered for marker in _QUANT_REPAIR_MARKERS)


def description_requests_qa_quant_fix(
    description: str, messages: list[Any] | None = None
) -> bool:
    """Return True when a repeat quant task is a QA-owned artifact repair.

    Prefer the latest structured QA decision when available so routing does not
    depend on the orchestrator repeating the exact magic words in its task text.
    """

    lowered = description.lower()
    if any(marker in lowered for marker in _QA_REFERENCE_MARKERS) and text_requires_quant_repair(
        lowered
    ):
        return True

    decision = latest_quality_decision(messages or [])
    if (
        decision
        and decision.status in {"rejected", "failed"}
        and decision.required_upstream == "quant-developer"
    ):
        return True
    return bool(
        decision
        and decision.status in {"rejected", "failed"}
        and text_requires_quant_repair(decision.repair_text)
    )


def qa_repair_budget_exhausted(messages: list[Any], max_rejections: int = 3) -> bool:
    decisions = iter_quality_decisions(messages)
    if not decisions or decisions[-1].status not in {"rejected", "failed"}:
        return False
    rejection_count = sum(
        1 for decision in decisions if decision.status in {"rejected", "failed"}
    )
    return rejection_count >= max_rejections
