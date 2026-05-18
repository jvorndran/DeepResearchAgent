"""
Deep Research Agent runner for improver-loop trace collection.

Executes the Deep Research Agent pipeline for a given query and writes
machine-readable trace artifacts under outputs/{job_id}/:

- phoenix_spans.jsonl: exported span records, preferably fetched back from Phoenix.
- trace_diagnostics.json: metrics computed from the exported span records.
- trace-digest.md: concise agent-readable summary of the trace signal.
- runner_status.json: final status, traceback text when fatal, and artifact paths.

Usage (from backend/ directory):
    python tests/runner.py --query "Research query here..."
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import sys
import time
import traceback
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Keep the standalone improver runner focused on local agent behavior. Local
# .env files may enable LangSmith tracing, which adds unrelated network noise.
os.environ.setdefault("LANGCHAIN_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# Suppress noisy framework logging
logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

from dotenv import load_dotenv

load_dotenv()

from agents.orchestrator import stream_research

# Ensure stdout handles Unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


TRACE_PROJECT_NAME = "deep-research-agent-improver"
PHOENIX_SPANS_FILENAME = "phoenix_spans.jsonl"
TRACE_DIAGNOSTICS_FILENAME = "trace_diagnostics.json"
TRACE_DIGEST_FILENAME = "trace-digest.md"
RUNNER_STATUS_FILENAME = "runner_status.json"
TRACE_EXPORT_LIMIT = int(os.getenv("RUNNER_TRACE_EXPORT_LIMIT", "10000"))


def _truncate(s: str, n: int = 400) -> str:
    s = str(s).replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value.astimezone(timezone.utc))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    try:
        if value != value:  # noqa: PLR0124 - portable NaN check without pandas import.
            return None
    except Exception:
        pass
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_dumps_compact(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


def _otel_safe_attrs(attributes: dict[str, Any]) -> dict[str, str | bool | int | float]:
    safe: dict[str, str | bool | int | float] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, str | bool | int):
            safe[key] = value
        elif isinstance(value, float):
            if math.isfinite(value):
                safe[key] = value
        else:
            safe[key] = _truncate(_json_dumps_compact(value), 4000)
    return safe


def format_log_entry(label: str, node: str, text: str, elapsed: float) -> str:
    return f"[{elapsed:5.1f}s] [{label:<12}] [{node:<15}] {text}"


class TraceExportError(RuntimeError):
    """Raised when Phoenix trace export is required but unavailable."""


@dataclass
class PendingModelMessage:
    """Aggregate streamed text chunks into one logical model message."""

    node: str | None = None
    chunks: list[str] = field(default_factory=list)

    def add(self, node: str, text: str) -> None:
        self.node = node
        self.chunks.append(text)

    def flush(
        self,
        trace: "RunnerTrace",
        elapsed: float,
        watchdog: "Watchdog",
    ) -> str | None:
        if not self.chunks:
            return None
        node = self.node or "model"
        text = "".join(self.chunks)
        self.node = None
        self.chunks.clear()
        if not text.strip():
            return None

        summary = _truncate(text)
        entry = format_log_entry("MESSAGE", node, summary, elapsed)
        trace.record_event(
            "model_message",
            node=node,
            elapsed=elapsed,
            text=summary,
            attributes={
                "message.length": len(text),
                "message.text": summary,
            },
        )
        print(entry)
        return watchdog.observe_model_message(elapsed)


APPROVAL_MESSAGES = [
    {
        "role": "user",
        "content": "Commence Deep Research",
        "metadata": {"action": "commence_research"},
    }
]


def format_update_summary(update: Any) -> str:
    if isinstance(update, dict):
        return f"Keys: {list(update.keys())}"
    return f"{type(update).__name__}: {_truncate(update)}"


def extract_message_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content)


def is_approval_interrupt_update(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    interrupts = data.get("__interrupt__")
    if not isinstance(interrupts, tuple):
        return False
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        if isinstance(value, dict) and value.get("type") == "research_approval_needed":
            return True
    return False


def format_stream_error(error: dict[str, Any]) -> str:
    error_type = error.get("type", "error")
    error_message = error.get("message", str(error))
    details = []
    if error.get("phase"):
        details.append(f"phase={error['phase']}")
    if "retryable" in error:
        details.append(f"retryable={error['retryable']}")
    if "agent_recoverable" in error:
        details.append(f"agent_recoverable={error['agent_recoverable']}")
    if error.get("hint"):
        details.append(f"hint={error['hint']}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{error_type}: {error_message}{suffix}"


def format_fatal_exception(exc: BaseException) -> tuple[str, str]:
    """Return a compact stop reason plus traceback for runner-level failures."""
    exc_type = type(exc).__name__
    exc_text = str(exc).strip()
    if exc_text:
        reason = f"ERROR: {exc_type}: {exc_text}"
    else:
        reason = f"ERROR: {exc_type}: {exc!r}"
    return reason, "".join(traceback.format_exception(exc))


def is_setup_error(error: dict[str, Any] | None) -> bool:
    return isinstance(error, dict) and error.get("phase") == "setup"


def is_incomplete_streaming_tool_call(name: Any, args: Any) -> bool:
    """Return True for partial AIMessageChunk tool-call fragments.

    Some streaming providers emit placeholder tool-call chunks before the
    complete tool call is assembled. Those fragments have no tool name and no
    args; counting them as real calls creates false identical-call watchdog
    stops.
    """
    return not name and (args is None or args == {})


EMPTY_ARG_REQUIRED_TOOLS = frozenset(
    {
        "bls_get_series",
        "bls_search_known_series",
        "census_get_table",
        "edit_file",
        "execute",
        "fred_get_series",
        "read_file",
        "sec_get_company_facts",
        "write_file",
        "worldbank_get_indicator",
    }
)


def has_uninformative_tool_args(name: str, args: Any) -> bool:
    """Return True when logged args cannot distinguish repeated calls.

    Some streamed tool-call events arrive with empty args even when the
    executed command or provider request differs. The total tool-call budget
    still catches loops, but the identical-call watchdog should not treat
    required-argument data calls like ``fred_get_series({})`` as the same
    request repeated when the stream omitted the actual arguments.
    """
    return name in EMPTY_ARG_REQUIRED_TOOLS and (args is None or args == {})


@dataclass
class Watchdog:
    """Detect inefficient or suspicious agent behavior from the event stream."""

    max_runtime_seconds: float
    max_tool_calls: int
    max_identical_tool_calls: int
    max_fred_search_calls: int
    max_model_messages: int
    tool_calls: int = 0
    model_messages: int = 0
    fred_search_calls: int = 0
    repeated_call_exempt_tools: frozenset[str] = frozenset({"fred_search"})
    identical_tool_calls: Counter[str] = field(default_factory=Counter)

    def observe_tool_call(self, name: str, args: Any, elapsed: float) -> str | None:
        self.tool_calls += 1
        if name == "fred_search":
            self.fred_search_calls += 1

        try:
            normalized_args = json.dumps(args, sort_keys=True, default=str)
        except TypeError:
            normalized_args = str(args)

        signature = f"{name}:{normalized_args}"
        if not has_uninformative_tool_args(name, args):
            self.identical_tool_calls[signature] += 1

        return None

    def observe_model_message(self, elapsed: float) -> str | None:
        self.model_messages += 1
        return None


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _required_fixes_from_payload(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
        return [value]
    return []


@dataclass
class RunnerQualityDecision:
    status: str
    report_path: str
    reason: str = ""
    required_fixes: list[str] = field(default_factory=list)


def _quality_decision_from_task_result(content: str) -> RunnerQualityDecision | None:
    payload = _json_object_from_text(content)
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status not in {"approved", "rejected", "failed"}:
        return None
    report_path = payload.get("report_path") or payload.get("report_json")
    if not isinstance(report_path, str) or not report_path.endswith("/report.json"):
        return None
    required_fixes = _required_fixes_from_payload(payload.get("required_fixes"))
    if status == "rejected" and not required_fixes:
        return None
    if status == "failed" and not (
        required_fixes or payload.get("required_upstream") or payload.get("reason")
    ):
        return None
    return RunnerQualityDecision(
        status=status,
        report_path=report_path,
        reason=str(payload.get("reason") or ""),
        required_fixes=required_fixes,
    )


@dataclass
class RunnerQualityStatus:
    latest: RunnerQualityDecision | None = None
    rejection_count: int = 0
    max_rejections: int = 3

    def observe_tool_result(self, tool_name: str | None, content: str) -> None:
        if tool_name != "task":
            return
        decision = _quality_decision_from_task_result(content)
        if decision is None:
            return
        self.latest = decision
        if decision.status in {"rejected", "failed"}:
            self.rejection_count += 1

    def terminal_failure_stop_reason(self) -> str | None:
        if (
            self.latest is None
            or self.latest.status not in {"rejected", "failed"}
            or self.rejection_count < self.max_rejections
        ):
            return None
        parts = [
            f"QA repair budget exhausted after latest {self.latest.status} decision",
        ]
        if self.latest.reason:
            parts.append(self.latest.reason)
        if self.latest.required_fixes:
            parts.append(
                "Required fixes: " + "; ".join(self.latest.required_fixes[:3])
            )
        return ". ".join(parts)

    def attributes(self) -> dict[str, Any]:
        latest = self.latest
        return {
            "qa.latest_status": latest.status if latest else "",
            "qa.latest_report_path": latest.report_path if latest else "",
            "qa.rejection_count": self.rejection_count,
            "qa.max_rejections": self.max_rejections,
        }


class RunnerTrace:
    """Owns runner-observed spans and trace artifact export."""

    def __init__(self, query: str, job_id: str, output_dir: Path, start_monotonic: float):
        self.query = query
        self.job_id = job_id
        self.output_dir = output_dir
        self.start_monotonic = start_monotonic
        self.query_hash = _query_hash(query)
        self.project_name = os.getenv("PHOENIX_PROJECT_NAME", TRACE_PROJECT_NAME)
        os.environ.setdefault("PHOENIX_WORKING_DIR", str(output_dir / ".phoenix"))
        self.loop_run_id = os.getenv("LOOP_RUN_ID", os.getenv("RUN_ID", ""))
        self.loop_pass = os.getenv("LOOP_PASS", "")
        self.loop_focus = os.getenv("LOOP_FOCUS", "")
        self.loop_mode = os.getenv("LOOP_MODE", "")
        self.mode = os.getenv("RUNNER_TRACE_EXPORT_MODE", "auto").lower()
        self.require_phoenix = os.getenv("RUNNER_REQUIRE_PHOENIX", "").lower() in {
            "1",
            "true",
            "yes",
        }
        self.phoenix_base_url = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
        self.local_records: list[dict[str, Any]] = []
        self.trace_export_errors: list[str] = []
        self.trace_export_source = "local"
        self._last_elapsed = 0.0
        self._provider: Any = None
        self._tracer: Any = None
        self._root_cm: Any = None
        self._root_span: Any = None
        self._root_started_at = _utc_now()
        self._root_attrs: dict[str, Any] = {}

    @property
    def trace_artifact_paths(self) -> dict[str, str]:
        return {
            "phoenix_spans_jsonl": str(self.output_dir / PHOENIX_SPANS_FILENAME),
            "trace_diagnostics_json": str(self.output_dir / TRACE_DIAGNOSTICS_FILENAME),
            "trace_digest_md": str(self.output_dir / TRACE_DIGEST_FILENAME),
            "runner_status_json": str(self.output_dir / RUNNER_STATUS_FILENAME),
        }

    def start(self) -> None:
        self._root_started_at = _utc_now()
        self._init_otel()
        self._root_attrs = self._base_attrs(
            {
                "event_type": "job",
                "node": "runner",
                "query.text": self.query,
                "query.hash": self.query_hash,
                "output_dir": str(self.output_dir),
            }
        )
        if self._tracer is None:
            return
        try:
            self._root_cm = self._tracer.start_as_current_span(
                "runner.job",
                attributes=_otel_safe_attrs(self._root_attrs),
            )
            self._root_span = self._root_cm.__enter__()
        except Exception as exc:  # pragma: no cover - defensive around tracing libraries.
            self.trace_export_errors.append(f"root span start failed: {type(exc).__name__}: {exc}")
            if self.require_phoenix or self.mode == "phoenix":
                raise TraceExportError(self.trace_export_errors[-1]) from exc
            self._root_cm = None
            self._root_span = None

    def _init_otel(self) -> None:
        if self.mode in {"local", "off", "disabled"}:
            self.trace_export_source = "local"
            return
        if self.mode == "auto" and not self.require_phoenix and not os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT"
        ):
            self.trace_export_source = "local"
            return

        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            try:
                from openinference.semconv.resource import ResourceAttributes

                project_attr = ResourceAttributes.PROJECT_NAME
            except Exception:
                project_attr = "openinference.project.name"

            endpoint = self.phoenix_base_url.rstrip("/")
            if not endpoint.endswith("/v1/traces"):
                endpoint = f"{endpoint}/v1/traces"
            resource = Resource.create(
                {
                    "service.name": "deep-research-agent-runner",
                    project_attr: self.project_name,
                }
            )
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            self._provider = provider
            self._tracer = provider.get_tracer("deep_research_agent.tests.runner")
            self.trace_export_source = "phoenix"
        except Exception as exc:
            message = f"Phoenix tracing setup failed: {type(exc).__name__}: {exc}"
            self.trace_export_errors.append(message)
            if self.require_phoenix or self.mode == "phoenix":
                raise TraceExportError(message) from exc
            self.trace_export_source = "local"

    def _base_attrs(self, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "loop_run_id": self.loop_run_id,
            "loop_pass": self.loop_pass,
            "loop_focus": self.loop_focus,
            "loop_mode": self.loop_mode,
            "query.hash": self.query_hash,
        }
        if attributes:
            payload.update(attributes)
        return _json_safe(payload)

    def record_event(
        self,
        event_type: str,
        *,
        node: str,
        elapsed: float | None = None,
        text: str | None = None,
        attributes: dict[str, Any] | None = None,
        status_code: str = "OK",
        status_message: str | None = None,
        exception: BaseException | None = None,
    ) -> None:
        event_elapsed = elapsed
        if event_elapsed is None:
            event_elapsed = time.monotonic() - self.start_monotonic
        delta = max(0.0, event_elapsed - self._last_elapsed)
        self._last_elapsed = max(self._last_elapsed, event_elapsed)
        attrs = self._base_attrs(
            {
                "event_type": event_type,
                "node": node,
                "runner.elapsed_seconds": round(event_elapsed, 6),
                "runner.delta_seconds": round(delta, 6),
            }
        )
        if text is not None:
            attrs["event.summary"] = text
        if attributes:
            attrs.update(_json_safe(attributes))

        start = _utc_now()
        trace_id = ""
        span_id = ""
        span_name = f"runner.{event_type}"
        if self._tracer is not None:
            try:
                from opentelemetry.trace import Status, StatusCode

                with self._tracer.start_as_current_span(
                    span_name,
                    attributes=_otel_safe_attrs(attrs),
                ) as span:
                    if status_code.upper() == "ERROR":
                        span.set_status(Status(StatusCode.ERROR, status_message or "error"))
                    if exception is not None:
                        span.record_exception(exception)
                    span_context = span.get_span_context()
                    trace_id = f"{span_context.trace_id:032x}"
                    span_id = f"{span_context.span_id:016x}"
            except Exception as exc:  # pragma: no cover - defensive around tracing libraries.
                self.trace_export_errors.append(
                    f"span export failed for {event_type}: {type(exc).__name__}: {exc}"
                )
        end = _utc_now()
        self.local_records.append(
            {
                "name": span_name,
                "context": {"trace_id": trace_id, "span_id": span_id},
                "parent_id": "runner.job",
                "start_time": _iso(start),
                "end_time": _iso(end),
                "duration_ms": round((end - start).total_seconds() * 1000.0, 6),
                "status_code": status_code.upper(),
                "status_message": status_message or "",
                "attributes": attrs,
            }
        )

    def finish(
        self,
        *,
        status: str,
        stop_reason: str | None,
        duration_seconds: float,
        artifact_paths: dict[str, str],
    ) -> tuple[list[dict[str, Any]], str]:
        final_attrs = self._base_attrs(
            {
                "status": status,
                "stop_reason": stop_reason or "",
                "duration_seconds": round(duration_seconds, 6),
                "output_dir": str(self.output_dir),
                "trace_artifact_paths": self.trace_artifact_paths,
                "artifact_paths": artifact_paths,
            }
        )
        self._root_attrs.update(final_attrs)
        if self._root_span is not None:
            try:
                for key, value in _otel_safe_attrs(final_attrs).items():
                    self._root_span.set_attribute(key, value)
            except Exception as exc:  # pragma: no cover
                self.trace_export_errors.append(
                    f"root span attribute update failed: {type(exc).__name__}: {exc}"
                )

        root_ended_at = _utc_now()
        if self._root_cm is not None:
            try:
                self._root_cm.__exit__(None, None, None)
            except Exception as exc:  # pragma: no cover
                self.trace_export_errors.append(f"root span end failed: {type(exc).__name__}: {exc}")

        self.local_records.append(
            {
                "name": "runner.job",
                "context": {"trace_id": "", "span_id": "runner.job"},
                "parent_id": "",
                "start_time": _iso(self._root_started_at),
                "end_time": _iso(root_ended_at),
                "duration_ms": round((root_ended_at - self._root_started_at).total_seconds() * 1000.0, 6),
                "status_code": "ERROR"
                if status in {"FATAL_ERROR", "SETUP_FAILED", "QA_REJECTED"}
                else "OK",
                "status_message": stop_reason or "",
                "attributes": self._root_attrs,
            }
        )

        if self._provider is not None:
            try:
                self._provider.force_flush(timeout_millis=30000)
            except Exception as exc:  # pragma: no cover
                self.trace_export_errors.append(f"trace force_flush failed: {type(exc).__name__}: {exc}")

        records, source = self._export_records()
        spans_path = self.output_dir / PHOENIX_SPANS_FILENAME
        with spans_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(_json_safe(record), sort_keys=True) + "\n")
        return records, source

    def _export_records(self) -> tuple[list[dict[str, Any]], str]:
        if self._provider is None:
            return self.local_records, self.trace_export_source

        try:
            phoenix_records = self._fetch_phoenix_records()
        except Exception as exc:
            message = f"Phoenix span dataframe export failed: {type(exc).__name__}: {exc}"
            self.trace_export_errors.append(message)
            phoenix_records = []

        if phoenix_records:
            return phoenix_records, "phoenix"

        message = f"Phoenix exported no spans for job_id={self.job_id}"
        self.trace_export_errors.append(message)
        if self.require_phoenix or self.mode == "phoenix":
            raise TraceExportError(message)
        return self.local_records, "local_fallback"

    def _fetch_phoenix_records(self) -> list[dict[str, Any]]:
        from phoenix.client import Client

        base_url = self.phoenix_base_url.rstrip("/")
        if base_url.endswith("/v1/traces"):
            base_url = base_url.removesuffix("/v1/traces")
        client = Client(base_url=base_url)
        dataframes = []
        try:
            dataframes.append(
                client.spans.get_spans_dataframe(
                    project_identifier=self.project_name,
                    limit=TRACE_EXPORT_LIMIT,
                )
            )
        except TypeError:
            dataframes.append(client.spans.get_spans_dataframe(project_identifier=self.project_name))
        except Exception:
            dataframes.append(client.spans.get_spans_dataframe(limit=TRACE_EXPORT_LIMIT))

        records: list[dict[str, Any]] = []
        for dataframe in dataframes:
            if dataframe is None:
                continue
            try:
                raw_records = dataframe.to_dict(orient="records")
            except Exception:
                continue
            records.extend(_json_safe(record) for record in raw_records)

        return [record for record in records if _span_attr(record, "job_id") == self.job_id]


def _span_attributes(record: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    raw_attrs = record.get("attributes")
    if isinstance(raw_attrs, dict):
        attrs.update(raw_attrs)
    elif isinstance(raw_attrs, str):
        try:
            parsed = json.loads(raw_attrs)
            if isinstance(parsed, dict):
                attrs.update(parsed)
        except json.JSONDecodeError:
            pass

    for key, value in record.items():
        if key.startswith("attributes."):
            attrs[key.removeprefix("attributes.")] = value
        elif key.startswith("attributes[") and key.endswith("]"):
            attrs[key.removeprefix("attributes[").removesuffix("]").strip("'\"")] = value
        elif key in {
            "job_id",
            "loop_run_id",
            "loop_pass",
            "loop_focus",
            "loop_mode",
            "event_type",
            "node",
            "status",
            "stop_reason",
        }:
            attrs.setdefault(key, value)
    return attrs


def _span_attr(record: dict[str, Any], key: str, default: Any = None) -> Any:
    attrs = _span_attributes(record)
    return attrs.get(key, record.get(key, default))


def _span_name(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("span_name") or record.get("span.name") or "")


def _span_status_code(record: dict[str, Any]) -> str:
    value = (
        record.get("status_code")
        or record.get("status.status_code")
        or record.get("status")
        or _span_attr(record, "status_code")
        or ""
    )
    return str(value).upper()


def _span_duration_ms(record: dict[str, Any]) -> float:
    for key in ("duration_ms", "latency_ms", "duration"):
        value = record.get(key)
        if isinstance(value, int | float):
            if key == "duration" and value < 10:
                return float(value) * 1000.0
            return float(value)
    start = record.get("start_time")
    end = record.get("end_time")
    if isinstance(start, str) and isinstance(end, str):
        try:
            parsed_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            parsed_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return max(0.0, (parsed_end - parsed_start).total_seconds() * 1000.0)
        except ValueError:
            return 0.0
    return 0.0


def _as_float(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _generated_script_path(output_dir: Path, summary_path: Path) -> Path | None:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    generated_by = summary.get("generated_by")
    if not isinstance(generated_by, dict):
        return None
    raw_script_path = generated_by.get("script_path")
    if not isinstance(raw_script_path, str) or not raw_script_path.strip():
        return None

    try:
        script_path = Path(raw_script_path).expanduser().resolve()
        script_path.relative_to((output_dir / "code").resolve())
    except (OSError, ValueError):
        return None
    if not script_path.exists():
        return None
    return script_path


def discover_artifacts(output_dir: Path) -> dict[str, str]:
    summary_path = output_dir / "execution_summary.json"
    analysis_path = _generated_script_path(output_dir, summary_path)
    if analysis_path is None:
        analysis_path = output_dir / "code" / "analysis.py"

    candidates = {
        "report_json": output_dir / "report.json",
        "execution_summary_json": summary_path,
        "charts_json": output_dir / "charts.json",
        "analysis_py": analysis_path,
    }
    return {name: str(path) for name, path in candidates.items() if path.exists()}


def compute_trace_diagnostics(
    *,
    records: list[dict[str, Any]],
    job_id: str,
    status: str,
    stop_reason: str | None,
    duration_seconds: float,
    artifact_paths: dict[str, str],
    trace_artifact_paths: dict[str, str],
    trace_export_source: str,
    trace_export_errors: list[str],
) -> dict[str, Any]:
    tool_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    update_counts: Counter[str] = Counter()
    tool_result_counts: Counter[str] = Counter()
    repeated_signatures: Counter[str] = Counter()
    node_latency: dict[str, list[float]] = defaultdict(list)
    error_spans: list[dict[str, Any]] = []
    retryable_stream_errors = 0
    retry_related_spans = 0

    for record in records:
        attrs = _span_attributes(record)
        event_type = str(attrs.get("event_type", ""))
        node = str(attrs.get("node") or "unknown")
        name = _span_name(record)
        delta_seconds = _as_float(attrs.get("runner.delta_seconds"))
        if event_type and event_type != "job":
            node_latency[node].append(delta_seconds)

        if event_type == "tool_call":
            tool_name = str(attrs.get("tool.name") or "?")
            tool_counts[tool_name] += 1
            signature = str(attrs.get("tool.signature") or "")
            if signature:
                repeated_signatures[signature] += 1
        elif event_type == "model_message":
            model_counts[node] += 1
        elif event_type == "update":
            update_counts[node] += 1
        elif event_type == "tool_result":
            tool_result_counts[str(attrs.get("tool.name") or "?")] += 1
        if event_type == "stream_error" and _as_bool(attrs.get("error.retryable")):
            retryable_stream_errors += 1
        searchable = " ".join(
            [
                event_type,
                name,
                str(attrs.get("event.summary") or ""),
                str(attrs.get("stop_reason") or ""),
            ]
        ).lower()
        if "retry" in searchable:
            retry_related_spans += 1

        if _span_status_code(record) == "ERROR" or event_type in {"stream_error", "fatal_error"}:
            error_spans.append(
                {
                    "name": name,
                    "event_type": event_type,
                    "node": node,
                    "elapsed_seconds": attrs.get("runner.elapsed_seconds"),
                    "message": attrs.get("event.summary")
                    or attrs.get("error.message")
                    or attrs.get("stop_reason")
                    or record.get("status_message")
                    or "",
                }
            )

    latency_summary = []
    for node, deltas in node_latency.items():
        if not deltas:
            continue
        latency_summary.append(
            {
                "node": node,
                "event_count": len(deltas),
                "total_delta_seconds": round(sum(deltas), 6),
                "max_delta_seconds": round(max(deltas), 6),
                "avg_delta_seconds": round(sum(deltas) / len(deltas), 6),
            }
        )
    latency_summary.sort(key=lambda item: item["max_delta_seconds"], reverse=True)

    repeated = [
        {"signature": signature, "count": count}
        for signature, count in repeated_signatures.most_common()
        if count > 1
    ]

    longest_spans = []
    for record in sorted(records, key=_span_duration_ms, reverse=True)[:10]:
        attrs = _span_attributes(record)
        longest_spans.append(
            {
                "name": _span_name(record),
                "event_type": attrs.get("event_type", ""),
                "node": attrs.get("node", ""),
                "duration_ms": round(_span_duration_ms(record), 6),
            }
        )

    diagnostics = {
        "job_id": job_id,
        "status": status,
        "stop_reason": stop_reason,
        "duration_seconds": round(duration_seconds, 6),
        "span_count": len(records),
        "trace_export_source": trace_export_source,
        "trace_export_errors": trace_export_errors,
        "tool_counts": dict(tool_counts.most_common()),
        "model_counts": dict(model_counts.most_common()),
        "model_message_count": sum(model_counts.values()),
        "tool_result_counts": dict(tool_result_counts.most_common()),
        "update_counts": dict(update_counts.most_common()),
        "repeated_tool_signatures": repeated,
        "node_latency": latency_summary,
        "retry_churn": {
            "retryable_stream_errors": retryable_stream_errors,
            "retry_related_spans": retry_related_spans,
            "error_spans": len(error_spans),
        },
        "error_spans": error_spans,
        "artifact_paths": artifact_paths,
        "trace_artifact_paths": trace_artifact_paths,
        "longest_spans": longest_spans,
    }
    diagnostics["primary_trace_signal"] = classify_primary_trace_signal(diagnostics)
    return diagnostics


def classify_primary_trace_signal(diagnostics: dict[str, Any]) -> str:
    stop_reason = str(diagnostics.get("stop_reason") or "").lower()
    repeated = diagnostics.get("repeated_tool_signatures") or []
    retry_churn = diagnostics.get("retry_churn") or {}
    error_spans = diagnostics.get("error_spans") or []
    node_latency = diagnostics.get("node_latency") or []
    artifact_paths = diagnostics.get("artifact_paths") or {}
    status = diagnostics.get("status")

    if status == "FATAL_ERROR":
        return "fatal runner error"
    if status == "SETUP_FAILED":
        return "setup failure"
    if status == "QA_REJECTED":
        return "qa rejection terminal failure"
    if "identical tool call repeated" in stop_reason or repeated:
        return "repeated tool loop"
    if retry_churn.get("retryable_stream_errors") or retry_churn.get("retry_related_spans"):
        return "retry churn"
    if error_spans:
        return "stream error"
    if node_latency and node_latency[0].get("max_delta_seconds", 0) >= 30:
        return f"slow node: {node_latency[0]['node']}"
    if status == "COMPLETED" and "report_json" not in artifact_paths:
        return "shallow artifact generation"
    return "completed trace"


def write_trace_digest(diagnostics: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Trace Digest: {diagnostics['job_id']}",
        "",
        f"- Status: {diagnostics['status']}",
        f"- Primary trace signal: {diagnostics['primary_trace_signal']}",
        f"- Stop reason: {diagnostics.get('stop_reason') or 'none'}",
        f"- Span count: {diagnostics['span_count']} ({diagnostics['trace_export_source']})",
        f"- Duration: {diagnostics['duration_seconds']:.2f}s",
        "",
        "## Trace Artifacts",
    ]
    for label, artifact_path in diagnostics.get("trace_artifact_paths", {}).items():
        lines.append(f"- {label}: {artifact_path}")

    artifact_paths = diagnostics.get("artifact_paths", {})
    lines.extend(["", "## Report Artifacts"])
    if artifact_paths:
        for label, artifact_path in artifact_paths.items():
            lines.append(f"- {label}: {artifact_path}")
    else:
        lines.append("- none discovered")

    lines.extend(["", "## Counts"])
    tool_counts = diagnostics.get("tool_counts") or {}
    if tool_counts:
        lines.append(
            "- Tool calls: "
            + ", ".join(f"{name}={count}" for name, count in list(tool_counts.items())[:8])
        )
    else:
        lines.append("- Tool calls: none observed")
    model_counts = diagnostics.get("model_counts") or {}
    if model_counts:
        lines.append(
            "- Model messages: "
            + ", ".join(f"{name}={count}" for name, count in list(model_counts.items())[:8])
        )
    else:
        lines.append("- Model messages: none observed")

    repeated = diagnostics.get("repeated_tool_signatures") or []
    lines.extend(["", "## Repeated Tool Signatures"])
    if repeated:
        for item in repeated[:5]:
            lines.append(f"- {item['count']}x {item['signature']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Slowest Nodes"])
    latency = diagnostics.get("node_latency") or []
    if latency:
        for item in latency[:5]:
            lines.append(
                f"- {item['node']}: max_delta={item['max_delta_seconds']:.2f}s, "
                f"events={item['event_count']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Errors"])
    errors = diagnostics.get("error_spans") or []
    if errors:
        for item in errors[:8]:
            lines.append(
                f"- {item['event_type'] or item['name']} [{item['node']}]: "
                f"{_truncate(str(item['message']), 240)}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Read Order"])
    lines.append("1. trace-digest.md")
    lines.append("2. trace_diagnostics.json")
    lines.append("3. phoenix_spans.jsonl")
    lines.append("4. report artifacts, if present")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_research_loop(
    query: str,
    job_id: str,
    watchdog: Watchdog,
):
    output_dir = Path(os.getenv("OUTPUT_DIR", "outputs")) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Executing Query: {query}")
    print(f"Job ID: {job_id}")
    print(f"Trace digest: {output_dir / TRACE_DIGEST_FILENAME}")

    start_time = time.monotonic()
    trace = RunnerTrace(query, job_id, output_dir, start_time)
    trace.start()
    trace.record_event(
        "runner_start",
        node="runner",
        elapsed=0.0,
        text="Runner initialized",
        attributes={"output_dir": str(output_dir)},
    )

    stop_reason = None
    setup_failed = False
    fatal_traceback = ""
    fatal_error = False
    approval_requested = False
    execution_seen = False
    force_execute_sent = False
    pending_message = PendingModelMessage()
    quality_status = RunnerQualityStatus()

    try:
        stream_messages = None
        max_stream_passes = 3
        for stream_pass in range(max_stream_passes):
            approval_requested = False
            execution_seen = stream_messages == APPROVAL_MESSAGES
            elapsed = time.monotonic() - start_time
            trace.record_event(
                "stream_pass",
                node="stream",
                elapsed=elapsed,
                text=f"Starting stream pass {stream_pass + 1}",
                attributes={
                    "stream.pass": stream_pass + 1,
                    "stream.messages_mode": "approval_resume"
                    if stream_messages == APPROVAL_MESSAGES
                    else "initial",
                },
            )
            async for event in stream_research(
                query=query,
                job_id=job_id,
                messages=stream_messages,
            ):
                elapsed = time.monotonic() - start_time

                if isinstance(event, dict) and "error" in event:
                    error = event["error"] or {}
                    stop_reason = pending_message.flush(trace, elapsed, watchdog)
                    if stop_reason:
                        break
                    setup_failed = is_setup_error(error)
                    stop_reason = format_stream_error(error)
                    trace.record_event(
                        "stream_error",
                        node="system",
                        elapsed=elapsed,
                        text=stop_reason,
                        attributes={
                            "error.type": error.get("type", "error"),
                            "error.message": error.get("message", str(error)),
                            "error.phase": error.get("phase", ""),
                            "error.retryable": error.get("retryable", False),
                            "error.agent_recoverable": error.get("agent_recoverable", ""),
                            "error.hint": error.get("hint", ""),
                        },
                        status_code="ERROR",
                        status_message=stop_reason,
                    )
                    print(format_log_entry("ERROR", "system", stop_reason, elapsed))
                    break

                # Normalize LangGraph v2 events
                if isinstance(event, dict) and "type" in event and "data" in event:
                    chunk_type = event["type"]
                    if chunk_type == "messages":
                        msg, meta = event["data"]
                        node = meta.get("langgraph_node", "model")

                        if type(msg).__name__ == "ToolMessage":
                            stop_reason = pending_message.flush(
                                trace,
                                elapsed,
                                watchdog,
                            )
                            if stop_reason:
                                break
                            content = getattr(msg, "content", "")
                            tool_name = getattr(msg, "name", "?")
                            quality_status.observe_tool_result(
                                tool_name,
                                str(content),
                            )
                            summary = f"{tool_name} -> {_truncate(str(content))}"
                            trace.record_event(
                                "tool_result",
                                node="tool_result",
                                elapsed=elapsed,
                                text=summary,
                                attributes={
                                    "tool.name": tool_name,
                                    "tool.result.length": len(str(content)),
                                    "tool.result.preview": _truncate(str(content)),
                                },
                            )
                            print(format_log_entry("TOOL RESULT", "tool_result", summary, elapsed))
                            continue

                        # Handle tool calls
                        tool_calls = getattr(msg, "tool_calls", [])
                        if tool_calls:
                            stop_reason = pending_message.flush(
                                trace,
                                elapsed,
                                watchdog,
                            )
                            if stop_reason:
                                break
                            for tc in tool_calls:
                                tc_name = tc.get("name", "?")
                                tc_args = tc.get("args", {})
                                if is_incomplete_streaming_tool_call(tc_name, tc_args):
                                    continue
                                normalized_args = _json_dumps_compact(tc_args)
                                trace.record_event(
                                    "tool_call",
                                    node=node,
                                    elapsed=elapsed,
                                    text=f"{tc_name}({normalized_args})",
                                    attributes={
                                        "tool.name": tc_name,
                                        "tool.args": tc_args,
                                        "tool.signature": f"{tc_name}:{normalized_args}",
                                        "tool.args_uninformative": has_uninformative_tool_args(
                                            tc_name, tc_args
                                        ),
                                    },
                                )
                                print(
                                    format_log_entry(
                                        "TOOL CALL",
                                        node,
                                        f"{tc_name}({json.dumps(tc_args, default=str)})",
                                        elapsed,
                                    )
                                )
                                stop_reason = watchdog.observe_tool_call(
                                    tc_name,
                                    tc_args,
                                    elapsed,
                                )
                                if stop_reason:
                                    break
                            if stop_reason:
                                break

                        # Handle content
                        content = getattr(msg, "content", "")
                        if content and not tool_calls:
                            text = extract_message_text(content)
                            if text.strip():
                                if pending_message.chunks and pending_message.node != node:
                                    stop_reason = pending_message.flush(
                                        trace,
                                        elapsed,
                                        watchdog,
                                    )
                                    if stop_reason:
                                        break
                                pending_message.add(node, text)

                    elif chunk_type == "updates":
                        stop_reason = pending_message.flush(trace, elapsed, watchdog)
                        if stop_reason:
                            break
                        data = event["data"]
                        if is_approval_interrupt_update(data):
                            approval_requested = True
                        if isinstance(data, dict):
                            if "execute" in data:
                                execution_seen = True
                            for node_name, update in data.items():
                                trace.record_event(
                                    "update",
                                    node=node_name,
                                    elapsed=elapsed,
                                    text=format_update_summary(update),
                                    attributes={
                                        "update.summary": format_update_summary(update),
                                        "update.is_approval_interrupt": node_name == "__interrupt__",
                                    },
                                )

            if stop_reason or setup_failed:
                break
            stop_reason = pending_message.flush(
                trace,
                time.monotonic() - start_time,
                watchdog,
            )
            if stop_reason:
                break
            if approval_requested:
                elapsed = time.monotonic() - start_time
                trace.record_event(
                    "approval_auto_resume",
                    node="approval_gate",
                    elapsed=elapsed,
                    text="Resuming approval interrupt for improver execution.",
                )
                print(
                    format_log_entry(
                        "AUTO APPROVE",
                        "approval_gate",
                        "Resuming approval interrupt for improver execution.",
                        elapsed,
                    )
                )
                stream_messages = APPROVAL_MESSAGES
                continue
            if not execution_seen and not force_execute_sent:
                force_execute_sent = True
                elapsed = time.monotonic() - start_time
                message = (
                    "Intake ended without approval; resuming directly into execution "
                    "for improver coverage."
                )
                trace.record_event(
                    "forced_execution",
                    node="intake",
                    elapsed=elapsed,
                    text=message,
                )
                print(format_log_entry("FORCE EXECUTE", "intake", message, elapsed))
                stream_messages = APPROVAL_MESSAGES
                continue
            break

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        fatal_error = True
        stop_reason, fatal_traceback = format_fatal_exception(exc)
        trace.record_event(
            "fatal_error",
            node="system",
            elapsed=elapsed,
            text=stop_reason,
            attributes={
                "error.type": type(exc).__name__,
                "error.message": str(exc),
                "error.traceback": fatal_traceback,
            },
            status_code="ERROR",
            status_message=stop_reason,
            exception=exc,
        )
        print(format_log_entry("FATAL ERROR", "system", stop_reason, elapsed))

    elapsed_total = time.monotonic() - start_time
    qa_terminal_failure = None
    if not fatal_error and not setup_failed and not stop_reason:
        qa_terminal_failure = quality_status.terminal_failure_stop_reason()
    if fatal_error:
        status = "FATAL_ERROR"
    elif setup_failed:
        status = "SETUP_FAILED"
    elif qa_terminal_failure:
        stop_reason = qa_terminal_failure
        status = "QA_REJECTED"
    else:
        status = "STOPPED_EARLY" if stop_reason else "COMPLETED"

    if qa_terminal_failure:
        trace.record_event(
            "qa_terminal_failure",
            node="runner",
            elapsed=elapsed_total,
            text=qa_terminal_failure,
            attributes=quality_status.attributes(),
            status_code="ERROR",
            status_message=qa_terminal_failure,
        )

    artifact_paths = discover_artifacts(output_dir)
    trace.record_event(
        "artifact_discovery",
        node="runner",
        elapsed=elapsed_total,
        text=f"Discovered {len(artifact_paths)} report artifacts",
        attributes={"artifact.paths": artifact_paths, "artifact.count": len(artifact_paths)},
    )

    status_path = output_dir / RUNNER_STATUS_FILENAME
    try:
        records, trace_export_source = trace.finish(
            status=status,
            stop_reason=stop_reason,
            duration_seconds=elapsed_total,
            artifact_paths=artifact_paths,
        )
        diagnostics = compute_trace_diagnostics(
            records=records,
            job_id=job_id,
            status=status,
            stop_reason=stop_reason,
            duration_seconds=elapsed_total,
            artifact_paths=artifact_paths,
            trace_artifact_paths=trace.trace_artifact_paths,
            trace_export_source=trace_export_source,
            trace_export_errors=trace.trace_export_errors,
        )
        _write_json(output_dir / TRACE_DIAGNOSTICS_FILENAME, diagnostics)
        write_trace_digest(diagnostics, output_dir / TRACE_DIGEST_FILENAME)
        runner_status = {
            "job_id": job_id,
            "query": query,
            "query_hash": trace.query_hash,
            "status": status,
            "stop_reason": stop_reason,
            "traceback": fatal_traceback,
            "duration_seconds": round(elapsed_total, 6),
            "trace_export_source": trace_export_source,
            "trace_export_errors": trace.trace_export_errors,
            "trace_artifacts": trace.trace_artifact_paths,
            "artifact_paths": artifact_paths,
        }
        _write_json(status_path, runner_status)
    except TraceExportError as exc:
        runner_status = {
            "job_id": job_id,
            "query": query,
            "query_hash": trace.query_hash,
            "status": "TRACE_EXPORT_FAILED",
            "stop_reason": str(exc),
            "traceback": fatal_traceback,
            "duration_seconds": round(elapsed_total, 6),
            "trace_export_source": trace.trace_export_source,
            "trace_export_errors": trace.trace_export_errors,
            "trace_artifacts": trace.trace_artifact_paths,
            "artifact_paths": artifact_paths,
        }
        _write_json(status_path, runner_status)
        raise

    print(f"{status} in {elapsed_total:.2f}s")
    if stop_reason:
        print(f"STOP_REASON: {stop_reason}")
    print(f"Trace digest: {output_dir / TRACE_DIGEST_FILENAME}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--max-runtime-seconds", type=float, default=2400)
    parser.add_argument("--max-tool-calls", type=int, default=300)
    parser.add_argument("--max-identical-tool-calls", type=int, default=25)
    parser.add_argument("--max-fred-search-calls", type=int, default=100)
    parser.add_argument("--max-model-messages", type=int, default=5000)
    args = parser.parse_args()

    job_id = f"improver-{uuid.uuid4().hex[:8]}"
    asyncio.run(
        run_research_loop(
            args.query,
            job_id,
            Watchdog(
                max_runtime_seconds=args.max_runtime_seconds,
                max_tool_calls=args.max_tool_calls,
                max_identical_tool_calls=args.max_identical_tool_calls,
                max_fred_search_calls=args.max_fred_search_calls,
                max_model_messages=args.max_model_messages,
            ),
        )
    )
