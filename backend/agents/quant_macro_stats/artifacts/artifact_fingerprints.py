"""Content fingerprints for quant evidence artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .json_safety import to_json_safe

SELF_EXCLUDED_SHA256_PLACEHOLDER = "0" * 64


class ArtifactFingerprint(BaseModel):
    """Deterministic SHA-256 descriptor for an evidence artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    role: Literal["canonical_json", "source_file", "data_file", "source_snapshot"]
    path: str
    algorithm: Literal["sha256"] = "sha256"
    sha256: str
    byte_count: int = Field(ge=0)
    content_type: str = "application/octet-stream"
    source_key: str | None = None
    self_excluded: bool = False

    @field_validator("artifact_id", "path", "content_type")
    @classmethod
    def _text_required(cls, value: str, info: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{info.field_name} is required")
        return text

    @field_validator("sha256")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        text = str(value).strip().lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        return text

    @field_validator("source_key")
    @classmethod
    def _optional_source_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


def json_artifact_bytes(payload: Any) -> bytes:
    """Serialize a canonical quant JSON artifact exactly as the writer stores it."""

    return json.dumps(to_json_safe(payload), indent=2, allow_nan=False).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fingerprint_bytes(
    *,
    artifact_id: str,
    role: Literal["canonical_json", "source_file", "data_file", "source_snapshot"],
    path: str | Path,
    content: bytes,
    content_type: str,
    source_key: str | None = None,
    self_excluded: bool = False,
) -> ArtifactFingerprint:
    return ArtifactFingerprint(
        artifact_id=artifact_id,
        role=role,
        path=str(path),
        sha256=sha256_bytes(content),
        byte_count=len(content),
        content_type=content_type,
        source_key=source_key,
        self_excluded=self_excluded,
    )


def fingerprint_file(
    *,
    artifact_id: str,
    role: Literal["source_file", "data_file", "source_snapshot"],
    path: str | Path,
    base_dir: Path,
    source_key: str,
) -> ArtifactFingerprint:
    resolved = resolve_fingerprint_path(path, base_dir=base_dir)
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise ValueError(
            f"Cannot fingerprint {artifact_id!r}; file is unreadable: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(
            f"Cannot fingerprint {artifact_id!r}; path is not a file: {resolved}"
        )
    return fingerprint_bytes(
        artifact_id=artifact_id,
        role=role,
        path=resolved,
        content=content,
        content_type=_content_type_for_path(resolved),
        source_key=source_key,
    )


def build_artifact_fingerprints(
    *,
    charts_path: str | Path,
    execution_summary_path: str | Path,
    evidence_bundle_path: str | Path,
    charts_bytes: bytes,
    execution_summary_bytes: bytes,
    source_files: dict[str, str],
    data_files: dict[str, str],
    base_dir: Path,
    source_snapshots: dict[str, Any] | None = None,
) -> list[ArtifactFingerprint]:
    """Build fingerprints for canonical quant outputs and referenced input files."""

    fingerprints = [
        fingerprint_bytes(
            artifact_id="charts_json",
            role="canonical_json",
            path=charts_path,
            content=charts_bytes,
            content_type="application/json",
        ),
        fingerprint_bytes(
            artifact_id="execution_summary_json",
            role="canonical_json",
            path=execution_summary_path,
            content=execution_summary_bytes,
            content_type="application/json",
        ),
    ]
    for source_key, path in sorted(source_files.items()):
        fingerprints.append(
            fingerprint_file(
                artifact_id=f"source_files:{source_key}",
                role="source_file",
                path=path,
                base_dir=base_dir,
                source_key=source_key,
            )
        )
    for source_key, path in sorted(data_files.items()):
        fingerprints.append(
            fingerprint_file(
                artifact_id=f"data_files:{source_key}",
                role="data_file",
                path=path,
                base_dir=base_dir,
                source_key=source_key,
            )
        )
    for source_key, descriptor in sorted((source_snapshots or {}).items()):
        path = _source_snapshot_path(descriptor)
        if not path:
            raise ValueError(
                f"Cannot fingerprint source snapshot {source_key!r}; descriptor missing path"
            )
        fingerprints.append(
            fingerprint_file(
                artifact_id=f"source_snapshots:{source_key}",
                role="source_snapshot",
                path=path,
                base_dir=base_dir,
                source_key=source_key,
            )
        )
    fingerprints.append(
        ArtifactFingerprint(
            artifact_id="evidence_bundle_json",
            role="canonical_json",
            path=str(evidence_bundle_path),
            sha256=SELF_EXCLUDED_SHA256_PLACEHOLDER,
            byte_count=0,
            content_type="application/json",
            self_excluded=True,
        )
    )
    return fingerprints


def finalize_evidence_bundle_fingerprint_bytes(bundle: Any) -> bytes:
    """Attach the bundle's self-excluded digest and return final JSON bytes.

    ``evidence_bundle_json`` cannot hash its literal final bytes because the hash
    lives inside those bytes. Its digest is computed from the final semantic
    payload after replacing only that descriptor's ``sha256`` and ``byte_count``
    with fixed sentinels. The stored ``byte_count`` still records the literal
    final file size and is checked by QA.
    """

    fingerprints = list(bundle.artifacts.fingerprints)
    self_index = next(
        (
            index
            for index, fingerprint in enumerate(fingerprints)
            if fingerprint.artifact_id == "evidence_bundle_json"
        ),
        None,
    )
    if self_index is None:
        raise ValueError("artifact fingerprints must include evidence_bundle_json")

    payload = bundle.model_dump(mode="json", exclude_none=True)
    self_digest = sha256_bytes(evidence_bundle_self_excluded_bytes(payload))
    fingerprints[self_index] = fingerprints[self_index].model_copy(
        update={
            "sha256": self_digest,
            "byte_count": 0,
            "self_excluded": True,
        }
    )
    bundle.artifacts.fingerprints = fingerprints

    previous_size = -1
    final_bytes = b""
    for _ in range(8):
        final_bytes = json_artifact_bytes(bundle.model_dump(mode="json", exclude_none=True))
        byte_count = len(final_bytes)
        if byte_count == previous_size:
            return final_bytes
        previous_size = byte_count
        fingerprints[self_index] = fingerprints[self_index].model_copy(
            update={"byte_count": byte_count}
        )
        bundle.artifacts.fingerprints = fingerprints
    return json_artifact_bytes(bundle.model_dump(mode="json", exclude_none=True))


def evidence_bundle_self_excluded_bytes(payload: dict[str, Any]) -> bytes:
    clean_payload = copy.deepcopy(to_json_safe(payload))
    artifacts = clean_payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return json_artifact_bytes(clean_payload)
    fingerprints = artifacts.get("fingerprints")
    if not isinstance(fingerprints, list):
        return json_artifact_bytes(clean_payload)
    for fingerprint in fingerprints:
        if not isinstance(fingerprint, dict):
            continue
        if fingerprint.get("artifact_id") != "evidence_bundle_json":
            continue
        fingerprint["sha256"] = SELF_EXCLUDED_SHA256_PLACEHOLDER
        fingerprint["byte_count"] = 0
        fingerprint["self_excluded"] = True
    return json_artifact_bytes(clean_payload)


def artifact_fingerprint_mismatches(
    bundle_payload: dict[str, Any],
    *,
    base_dir: Path,
    evidence_bundle_path: Path,
) -> list[str]:
    artifacts = bundle_payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    fingerprints = artifacts.get("fingerprints")
    if not fingerprints:
        return []
    if not isinstance(fingerprints, list):
        return ["artifacts.fingerprints must be a list"]

    by_id = {
        str(item.get("artifact_id")): item
        for item in fingerprints
        if isinstance(item, dict) and item.get("artifact_id")
    }
    missing_required = [
        artifact_id
        for artifact_id in (
            "charts_json",
            "execution_summary_json",
            "evidence_bundle_json",
        )
        if artifact_id not in by_id
    ]
    mismatches = [
        f"{artifact_id} missing fingerprint descriptor"
        for artifact_id in missing_required
    ]

    for item in fingerprints:
        if not isinstance(item, dict):
            mismatches.append("fingerprint descriptor must be an object")
            continue
        artifact_id = str(item.get("artifact_id") or "").strip()
        path_text = str(item.get("path") or "").strip()
        expected_sha = str(item.get("sha256") or "").strip().lower()
        expected_bytes = item.get("byte_count")
        if not artifact_id or not path_text or not expected_sha:
            mismatches.append(f"{artifact_id or '<missing>'} incomplete descriptor")
            continue
        if artifact_id == "evidence_bundle_json" and item.get("self_excluded"):
            content = evidence_bundle_path.read_bytes()
            actual_sha = sha256_bytes(
                evidence_bundle_self_excluded_bytes(bundle_payload)
            )
        else:
            resolved = resolve_fingerprint_path(path_text, base_dir=base_dir)
            try:
                content = resolved.read_bytes()
            except OSError:
                mismatches.append(f"{artifact_id} missing or unreadable at {resolved}")
                continue
            actual_sha = sha256_bytes(content)
        if actual_sha != expected_sha:
            mismatches.append(f"{artifact_id} sha256 changed")
        if isinstance(expected_bytes, int) and len(content) != expected_bytes:
            mismatches.append(
                f"{artifact_id} byte_count changed "
                f"(expected {expected_bytes}, got {len(content)})"
            )
    return mismatches


def resolve_fingerprint_path(path: str | Path, *, base_dir: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    base_candidate = base_dir / candidate
    if base_candidate.exists():
        return base_candidate
    return candidate


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    return "application/octet-stream"


def _source_snapshot_path(descriptor: Any) -> str | None:
    if hasattr(descriptor, "model_dump"):
        descriptor = descriptor.model_dump(mode="json", exclude_none=True)
    if not isinstance(descriptor, Mapping):
        return None
    path = descriptor.get("path")
    if path is None:
        return None
    text = str(path).strip()
    return text or None
