from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.quality_analyst.tools import (
    load_report_for_review,
    submit_quality_decision,
)
from agents.quant_macro_stats.artifacts.evidence_bundle import EvidenceBundle
from agents.technical_writer.chart_audit import run_report_chart_audit
from agents.technical_writer.report_validation import run_report_static_gate


BENCHMARK_ROOT = Path(__file__).with_name("regression_benchmarks")
MANIFEST_PATH = BENCHMARK_ROOT / "manifest.json"


class StaticGateExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passes_gate: bool
    blocker_contains: str | None = None

    @model_validator(mode="after")
    def _failed_gate_names_blocker(self):
        if self.passes_gate and self.blocker_contains:
            raise ValueError("passing static gate expectations cannot name blockers")
        if not self.passes_gate and not self.blocker_contains:
            raise ValueError("failed static gate expectations require blocker_contains")
        return self


class ChartAuditExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passes_audit: bool
    blocker_contains: str | None = None

    @model_validator(mode="after")
    def _failed_audit_names_blocker(self):
        if self.passes_audit and self.blocker_contains:
            raise ValueError("passing chart audit expectations cannot name blockers")
        if not self.passes_audit and not self.blocker_contains:
            raise ValueError("failed chart audit expectations require blocker_contains")
        return self


class QADecisionExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    failure_category: str | None = None

    @model_validator(mode="after")
    def _rejected_decision_names_category(self):
        if self.status == "approved" and self.failure_category:
            raise ValueError("approved QA expectations cannot name failure_category")
        if self.status == "rejected" and not self.failure_category:
            raise ValueError("rejected QA expectations require failure_category")
        return self


class BenchmarkExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_chart_ids: list[str] = Field(default_factory=list)
    required_fact_ids: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)
    report_static_gate: StaticGateExpectation
    chart_audit: ChartAuditExpectation
    qa_decision: QADecisionExpectation


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    fixture_dir: str
    failure_mode: str | None = None
    expected: BenchmarkExpectations

    @field_validator("id", "title", "fixture_dir")
    @classmethod
    def _text_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("benchmark manifest text fields cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def _fixture_dir_is_manifest_relative(self):
        if Path(self.fixture_dir).is_absolute():
            raise ValueError("fixture_dir must be relative to regression_benchmarks")
        return self


class RegressionBenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _case_ids_are_unique(self):
        seen: set[str] = set()
        duplicates: list[str] = []
        for case in self.cases:
            if case.id in seen and case.id not in duplicates:
                duplicates.append(case.id)
            seen.add(case.id)
        if duplicates:
            raise ValueError(f"duplicate benchmark case ids: {duplicates}")
        return self


def _load_manifest() -> RegressionBenchmarkManifest:
    return RegressionBenchmarkManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


BENCHMARK_CASES = _load_manifest().cases


def _read_json(path: Path) -> dict:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), f"{path} root must be a JSON object"
    return parsed


def _unique_texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _chart_ids_from_charts_json(payload: dict) -> list[str]:
    nested = payload.get("charts")
    if isinstance(nested, list):
        return _unique_texts(
            [chart.get("id") for chart in nested if isinstance(chart, dict)]
        )
    return _unique_texts([chart_id for chart_id, chart in payload.items() if chart])


def _assert_expected_ids(label: str, expected_ids: list[str], observed_ids: list[str]):
    missing = [item for item in expected_ids if item not in observed_ids]
    assert not missing, f"{label} missing expected ids: {missing}"


def _assert_manifest_coverage(case: BenchmarkCase, artifact_dir: Path):
    summary = _read_json(artifact_dir / "execution_summary.json")
    charts_payload = _read_json(artifact_dir / "charts.json")
    bundle_payload = _read_json(artifact_dir / "evidence_bundle.json")
    bundle = EvidenceBundle.model_validate(bundle_payload)

    expected = case.expected
    summary_chart_ids = _unique_texts(summary.get("chart_ids"))
    charts_json_ids = _chart_ids_from_charts_json(charts_payload)
    bundle_chart_ids = [chart.chart_id for chart in bundle.charts]
    summary_fact_ids = [
        str(fact["id"])
        for fact in summary.get("numeric_facts", [])
        if isinstance(fact, dict) and fact.get("id")
    ]
    bundle_fact_ids = [fact.fact_id for fact in bundle.facts]
    bundle_source_ids = [source.source_id for source in bundle.sources]
    source_coverage = summary.get("source_coverage")
    if expected.required_source_ids:
        assert isinstance(source_coverage, dict), (
            "execution_summary.source_coverage must be present when "
            "required_source_ids are declared"
        )
        summary_source_ids = list(source_coverage)
    else:
        summary_source_ids = (
            list(source_coverage) if isinstance(source_coverage, dict) else []
        )

    _assert_expected_ids(
        "execution_summary.chart_ids",
        expected.required_chart_ids,
        summary_chart_ids,
    )
    _assert_expected_ids(
        "charts.json",
        expected.required_chart_ids,
        charts_json_ids,
    )
    _assert_expected_ids(
        "evidence_bundle.charts",
        expected.required_chart_ids,
        bundle_chart_ids,
    )
    _assert_expected_ids(
        "execution_summary.numeric_facts",
        expected.required_fact_ids,
        summary_fact_ids,
    )
    _assert_expected_ids(
        "evidence_bundle.facts",
        expected.required_fact_ids,
        bundle_fact_ids,
    )
    _assert_expected_ids(
        "evidence_bundle.sources",
        expected.required_source_ids,
        bundle_source_ids,
    )
    if expected.required_source_ids:
        _assert_expected_ids(
            "execution_summary.source_coverage",
            expected.required_source_ids,
            summary_source_ids,
        )


def _assert_static_gate_blocker_expectation(
    payload: dict, expected: StaticGateExpectation
):
    if expected.blocker_contains is None:
        return
    blocker_text = " ".join(str(item) for item in payload.get("blockers", []))
    assert expected.blocker_contains in blocker_text


def _assert_chart_audit_blocker_expectation(
    payload: dict, expected: ChartAuditExpectation
):
    if expected.blocker_contains is None:
        return
    blocker_text = " ".join(str(item) for item in payload.get("blockers", []))
    assert expected.blocker_contains in blocker_text


@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda item: item.id)
def test_regression_benchmark_manifest_cases_reuse_artifact_gates(
    case: BenchmarkCase,
    tmp_path: Path,
):
    fixture_dir = BENCHMARK_ROOT / case.fixture_dir
    assert fixture_dir.is_dir(), f"missing benchmark fixture dir: {fixture_dir}"
    artifact_dir = tmp_path / case.id
    shutil.copytree(fixture_dir, artifact_dir)
    report_path = artifact_dir / "report.json"

    for required_name in (
        "report.json",
        "charts.json",
        "execution_summary.json",
        "evidence_bundle.json",
    ):
        assert (artifact_dir / required_name).is_file()

    _assert_manifest_coverage(case, artifact_dir)

    static_gate = json.loads(
        run_report_static_gate(str(report_path), auto_patch=False)
    )
    assert static_gate["passes_gate"] is case.expected.report_static_gate.passes_gate
    _assert_static_gate_blocker_expectation(
        static_gate, case.expected.report_static_gate
    )

    chart_audit = json.loads(run_report_chart_audit(str(report_path)))
    assert chart_audit["passes_audit"] is case.expected.chart_audit.passes_audit
    _assert_chart_audit_blocker_expectation(chart_audit, case.expected.chart_audit)

    review_packet = json.loads(
        load_report_for_review.invoke({"report_path": str(report_path)})
    )
    assert review_packet["status"] == "success"
    assert review_packet["evidence_bundle"]["status"] == "success"

    qa_decision = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Regression benchmark approval probe.",
            }
        )
    )
    assert qa_decision["status"] == case.expected.qa_decision.status
    if case.expected.qa_decision.failure_category is not None:
        assert (
            qa_decision["failure_category"]
            == case.expected.qa_decision.failure_category
        )
