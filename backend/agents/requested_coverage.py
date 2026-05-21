"""Shared contracts for requested geography coverage."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


_QUERY_GEOGRAPHY_DIMENSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "state",
        re.compile(
            r"\b(?:state[-\s]?level|by\s+state|state[-\s]?by[-\s]?state|"
            r"(?:u\.s\.|us|50)\s+states|across\s+(?:the\s+)?states|"
            r"(?:compare|rank|ranking|ranked|sort|sorted|order|ordered)\s+"
            r"(?:the\s+)?states(?:\s+by)?|"
            r"(?:which|what|where)\s+states|"
            r"(?:top|bottom|best|worst|healthiest|weakest|strongest)\s+"
            r"(?:\d+\s+)?states|"
            r"states\s+(?:by|ranked?\s+by|sorted?\s+by|ordered?\s+by|"
            r"look|are|have|with|where|that|rank|lead|lag|outperform|"
            r"underperform))\b",
            re.I,
        ),
    ),
    (
        "regional",
        re.compile(
            r"\b(?:regions?|regionally|"
            r"regional\s+(?:comparisons?|rankings?|break(?:out|down)s?|"
            r"coverage|context|data|evidence|conditions?|stress|health|"
            r"econom(?:y|ies)|labor\s+markets?|housing\s+markets?|"
            r"consumer(?:s)?|households?)|"
            r"midwest|sun\s+belt|rust\s+belt|"
            r"(?:northeast|south|west|southern|western|coastal)\s+"
            r"(?:regions?|states?|counties|metros?|cities|localities|"
            r"geograph(?:y|ies|ic|ical)?|econom(?:y|ies)|labor\s+markets?|"
            r"housing\s+markets?|consumer(?:s)?|households?)|"
            r"(?:the\s+)?(?:northeast|south|west|midwest)\s+"
            r"(?:vs\.?|versus)\s+(?:the\s+)?"
            r"(?:northeast|south|west|midwest))\b",
            re.I,
        ),
    ),
    ("county", re.compile(r"\b(?:counties|county|county[-\s]?level)\b", re.I)),
    ("metro", re.compile(r"\b(?:metros?|metro[-\s]?level)\b", re.I)),
    ("city", re.compile(r"\b(?:cities|city|zip\s*codes?)\b", re.I)),
    (
        "place",
        re.compile(
            r"\b(?:places|place[-\s]specific|place[-\s]level|by\s+place|"
            r"across\s+(?:the\s+)?places|geograph(?:y|ies|ic|ical)?)\b",
            re.I,
        ),
    ),
)
_STRUCTURED_GEOGRAPHY_DIMENSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "state",
        re.compile(r"\b(?:states?|state[-_\s]?level|by[-_\s]?state)\b", re.I),
    ),
    (
        "regional",
        re.compile(
            r"\b(?:regions?|regional|northeast|midwest|south(?:ern)?|"
            r"west(?:ern)?|sun[-_\s]?belt|rust[-_\s]?belt|coastal)\b",
            re.I,
        ),
    ),
    (
        "county",
        re.compile(r"\b(?:counties|county|county[-_\s]?level)\b", re.I),
    ),
    ("metro", re.compile(r"\b(?:metros?|metro[-_\s]?level)\b", re.I)),
    ("city", re.compile(r"\b(?:cities|city|zip[-_\s]*codes?)\b", re.I)),
    ("place", re.compile(r"\b(?:places?|geograph(?:y|ic|ical)?)\b", re.I)),
)
_US_STATE_TERMS = (
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "district of columbia",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
)
_US_STATE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in _US_STATE_TERMS) + r")\b",
    re.I,
)
_NON_SPECIFIC_US_RE = re.compile(r"\b(?:united\s+states|u\.s\.|us)\b", re.I)
_PROVIDER_PLACE_NAME_RE = re.compile(
    r"\b(?:university\s+of\s+michigan|new\s+york\s+fed|ny\s+fed|"
    r"federal\s+reserve\s+bank\s+of\s+new\s+york|"
    r"new\s+york\s+federal\s+reserve)\b",
    re.I,
)
_NON_GEOGRAPHIC_STATE_NAME_RE = re.compile(
    r"\b(?:west\s+texas\s+intermediate|wti|texas\s+instruments)\b",
    re.I,
)
_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?(?![\w]|\.\d)")
_STATE_COMPARISON_QUERY_RE = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|between|rank|ranking|ranked|"
    r"sort|sorted|order|ordered)\b",
    re.I,
)
_STATE_ECONOMIC_CONTEXT_RE = re.compile(
    r"\b(?:econom(?:y|ic|ies)|labor\s+markets?|jobs?|payrolls?|"
    r"unemployment|employment|inflation|prices?|wages?|income|housing|"
    r"homes?|rents?|consumers?|households?|stress|health(?:y|iest)?|"
    r"conditions?|outlook|growth|gdp|recession|credit|delinquenc(?:y|ies)|"
    r"migration|population|manufacturing|retail)\b",
    re.I,
)
_COMPARATIVE_GEOGRAPHY_QUERY_RE = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|between|rank|ranking|ranked|"
    r"sort|sorted|order|ordered|top|bottom|best|worst|healthiest|weakest|"
    r"strongest|lead|lag|outperform|underperform)\b",
    re.I,
)
_PLURAL_GEOGRAPHY_QUERY_RE = re.compile(
    r"\b(?:which|what|where)\s+(?:\w+\s+){0,5}"
    r"(?:regions|states|counties|metros|cities|places|geographies)\b|"
    r"\bacross\s+(?:the\s+)?"
    r"(?:regions|states|counties|metros|cities|places|geographies)\b|"
    r"\b(?:regions|states|counties|metros|cities|places|geographies)\s+"
    r"(?:look|are|have|with|where|that|rank|lead|lag|outperform|underperform)\b",
    re.I,
)
_REGION_ENTITY_RE = re.compile(
    r"\b(?:northeast|midwest|south|southern|west|western|sun\s+belt|"
    r"rust\s+belt|coastal)\b",
    re.I,
)
_UNAVAILABLE_STATUS_VALUES = {
    "disabled",
    "error",
    "failed",
    "failure",
    "insufficient",
    "missing",
    "no_data",
    "not_available",
    "not_covered",
    "not_fetched",
    "unavailable",
}
_STRUCTURED_GEOGRAPHY_KEY_DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    "regional_top10": ("regional", "state"),
    "state_comparison": ("state", "regional"),
    "consumer_stress.regional_context": ("regional", "state"),
}
_GEOGRAPHY_ROW_NAME_KEY_ORDER = (
    "state",
    "state_name",
    "region",
    "region_name",
    "county",
    "city",
    "geography",
    "name",
    "subject",
)
_GEOGRAPHY_ROW_NAME_KEYS = set(_GEOGRAPHY_ROW_NAME_KEY_ORDER)
_GEOGRAPHY_ROW_METADATA_KEYS = {
    "as_of",
    "as_of_date",
    "city_code",
    "county_code",
    "date",
    "fips",
    "geo_id",
    "geoid",
    "id",
    "period",
    "region_code",
    "source",
    "source_key",
    "state_code",
}
_GEOGRAPHY_ROW_METRIC_LABEL_KEYS = {
    "indicator",
    "indicator_name",
    "measure",
    "measure_name",
    "metric",
    "metric_key",
    "metric_name",
}
_GEOGRAPHY_ROW_GENERIC_VALUE_KEYS = {
    "current_value",
    "display_value",
    "latest_value",
    "raw_value",
    "value",
}
_DIMENSION_COMPATIBILITY: Mapping[str, tuple[str, ...]] = {
    "state": ("state",),
    "regional": ("regional", "state"),
    "county": ("county",),
    "metro": ("metro",),
    "city": ("city",),
    "place": ("state", "regional", "county", "metro", "city", "place"),
}


@dataclass(frozen=True)
class RequestedCoverageAssessment:
    """Compact result shared by writer, QA, and quant handoff code."""

    required: bool
    scope: str
    requested_dimensions: tuple[str, ...]
    status: str
    requested_entities: tuple[str, ...] = ()
    evidence_keys: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    blocker: str | None = None

    @property
    def satisfied(self) -> bool:
        return not self.required or self.status in {"covered", "unavailable", "partial"}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "required": self.required,
            "scope": self.scope,
            "requested_dimensions": list(self.requested_dimensions),
            "requested_entities": list(self.requested_entities),
            "status": self.status,
            "evidence_keys": list(self.evidence_keys),
            "unavailable_sources": list(self.unavailable_sources),
        }
        if self.blocker:
            payload["blocker"] = self.blocker
        return payload


def requested_geography_dimensions(query: object) -> tuple[str, ...]:
    """Return requested geography dimensions inferred from the user query."""

    text = _strip_non_specific_places(str(query or ""))
    dimensions = [
        dimension
        for dimension, pattern in _QUERY_GEOGRAPHY_DIMENSION_PATTERNS
        if pattern.search(text)
    ]
    if _query_mentions_named_state_dimension(text):
        dimensions.append("state")
    if "regional" in dimensions:
        dimensions.append("place")
    if "state" in dimensions:
        dimensions.append("place")
    return tuple(dict.fromkeys(dimensions))


def query_requests_geography_coverage(query: object) -> bool:
    """Whether the query asks for state, regional, or place-specific coverage."""

    return bool(requested_geography_dimensions(query))


def requested_geography_entity_keys(query: object) -> tuple[str, ...]:
    """Return normalized named geography entities requested by the query."""

    return _requested_geography_entity_keys(query)


def requested_geography_minimum_entity_count(
    query: object,
    requested_dimensions: tuple[str, ...],
) -> int:
    """Return how many compatible geography entities the request needs."""

    return _minimum_requested_geography_entity_count(
        query,
        requested_dimensions,
        requested_entities=_requested_geography_entity_keys(query),
    )


def assess_requested_geography_coverage(
    query: object,
    summary: Mapping[str, Any] | None,
) -> RequestedCoverageAssessment:
    """Assess whether requested geography coverage is structurally satisfied."""

    payload: Mapping[str, Any] = summary if isinstance(summary, Mapping) else {}
    contract = _contract_payload(payload.get("requested_geography_coverage"))
    dimensions = requested_geography_dimensions(query)
    contract_dimensions = _contract_items(contract, "requested_dimensions")
    requested_entities = _requested_geography_entity_keys(query)
    required = (
        bool(dimensions)
        or query_requests_geography_coverage(query)
        or bool(contract.get("required"))
    )
    if not dimensions and contract_dimensions:
        dimensions = contract_dimensions
    if not required:
        return RequestedCoverageAssessment(
            required=False,
            scope="geography",
            requested_dimensions=(),
            requested_entities=(),
            status="not_required",
        )

    minimum_entity_count = _minimum_requested_geography_entity_count(
        query,
        dimensions,
        requested_entities=requested_entities,
    )
    evidence_keys = _structured_geography_evidence_keys(
        payload,
        dimensions,
        minimum_entity_count=minimum_entity_count,
        requested_entity_keys=requested_entities,
    )
    unavailable_sources = _structured_unavailable_sources(payload, dimensions)

    if evidence_keys:
        status = "partial" if unavailable_sources else "covered"
    elif unavailable_sources:
        status = "unavailable"
    else:
        status = "missing"

    blocker = None
    if status == "missing":
        blocker = (
            "User query asks for state, regional, or place-specific coverage, "
            "but execution_summary.json has neither enough matching structured "
            "geography evidence for the requested dimension (regional_top10, "
            "state_comparison, consumer_stress.regional_context, or geography "
            "numeric_facts; comparative/ranking requests need at least two "
            "compatible geography entities) nor matching structured "
            "unavailable-source evidence in source_coverage or "
            "metadata.fetch_errors. Regenerate the quantitative handoff with "
            "requested_geography_coverage before writing a national substitute."
        )

    return RequestedCoverageAssessment(
        required=True,
        scope="geography",
        requested_dimensions=dimensions,
        requested_entities=requested_entities,
        status=status,
        evidence_keys=evidence_keys,
        unavailable_sources=unavailable_sources,
        blocker=blocker,
    )


def requested_geography_coverage(
    query: object,
    execution_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable requested-geography coverage contract."""

    return assess_requested_geography_coverage(query, execution_summary).to_dict()


def requested_geography_coverage_blocker(
    query: object,
    summary: Mapping[str, Any] | None,
) -> str | None:
    """Return a quant-owned blocker when required geography coverage is absent."""

    assessment = assess_requested_geography_coverage(query, summary)
    return None if assessment.satisfied else assessment.blocker


def compact_requested_geography_coverage(
    query: object,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a compact contract only when it is relevant or already present."""

    payload: Mapping[str, Any] = summary if isinstance(summary, Mapping) else {}
    assessment = assess_requested_geography_coverage(query, payload)
    if assessment.required or isinstance(payload.get("requested_geography_coverage"), Mapping):
        return assessment.to_dict()
    return None


def structured_geography_row_metric_values(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return numeric metric values from a named geography evidence row."""

    return tuple(value for _, value in structured_geography_row_metric_items(row))


def structured_geography_row_metric_items(
    row: Mapping[str, Any],
) -> tuple[tuple[str, Any], ...]:
    """Return ``(metric_label, value)`` items from a named geography evidence row."""

    values: list[tuple[str, Any]] = []
    row_metric_label = _metric_label_from_mapping(row)
    for key, value in row.items():
        normalized_key = _normalize_token(key)
        if (
            normalized_key in _GEOGRAPHY_ROW_NAME_KEYS
            or normalized_key in _GEOGRAPHY_ROW_METADATA_KEYS
            or normalized_key in _GEOGRAPHY_ROW_METRIC_LABEL_KEYS
        ):
            continue
        metric_label = (
            row_metric_label
            if row_metric_label and normalized_key in _GEOGRAPHY_ROW_GENERIC_VALUE_KEYS
            else str(key)
        )
        values.extend(_structured_geography_metric_items(metric_label, value))
    return tuple(values)


def structured_geography_row_has_metric_value(row: Any) -> bool:
    """Whether a structured geography row has a name and a metric value."""

    if not isinstance(row, Mapping):
        return False
    return _row_has_geography_name(row) and bool(
        structured_geography_row_metric_values(row)
    )


def structured_geography_row_entity_key(row: Mapping[str, Any]) -> str | None:
    """Return a normalized geography entity key for a structured evidence row."""

    return _structured_geography_row_entity_key(row)


def numeric_fact_geography_entity_keys(fact: Any) -> tuple[str, ...]:
    """Return normalized geography entities represented by a numeric fact."""

    return _numeric_fact_geography_entity_keys(fact)


def _contract_payload(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _contract_items(contract: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = contract.get(key)
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, Iterable) or isinstance(value, Mapping):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _structured_geography_evidence_keys(
    summary: Mapping[str, Any],
    requested_dimensions: tuple[str, ...],
    *,
    minimum_entity_count: int = 1,
    requested_entity_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    keys: list[str] = []
    for key, dimensions in _STRUCTURED_GEOGRAPHY_KEY_DIMENSIONS.items():
        if key == "consumer_stress.regional_context":
            continue
        has_metric_rows = _has_enough_metric_bearing_structured_geography_payload(
            summary.get(key),
            minimum_entity_count=minimum_entity_count,
            requested_entity_keys=requested_entity_keys,
        )
        if has_metric_rows and _dimensions_match_request(
            requested_dimensions,
            dimensions,
        ):
            keys.append(key)

    consumer = summary.get("consumer_stress")
    if (
        isinstance(consumer, Mapping)
        and _has_enough_metric_bearing_structured_geography_payload(
            consumer.get("regional_context"),
            minimum_entity_count=minimum_entity_count,
            requested_entity_keys=requested_entity_keys,
        )
        and _dimensions_match_request(
            requested_dimensions,
            _STRUCTURED_GEOGRAPHY_KEY_DIMENSIONS["consumer_stress.regional_context"],
        )
    ):
        keys.append("consumer_stress.regional_context")

    facts = summary.get("numeric_facts")
    if isinstance(facts, Iterable) and not isinstance(facts, (str, bytes, Mapping)):
        if _has_enough_requested_geography_numeric_fact_evidence(
            facts,
            requested_dimensions,
            minimum_entity_count=minimum_entity_count,
            requested_entity_keys=requested_entity_keys,
        ):
            keys.append("numeric_facts")

    return _unique(keys)


def _has_enough_metric_bearing_structured_geography_payload(
    value: Any,
    *,
    minimum_entity_count: int,
    requested_entity_keys: tuple[str, ...],
) -> bool:
    entity_keys = _structured_geography_entity_keys(value)
    if requested_entity_keys:
        return (
            set(requested_entity_keys).issubset(entity_keys)
            and len(entity_keys) >= minimum_entity_count
        )
    if minimum_entity_count <= 1:
        return any(
            structured_geography_row_has_metric_value(row)
            for row in _iter_structured_geography_rows(value)
        )
    return len(entity_keys) >= minimum_entity_count


def _structured_geography_entity_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    for row in _iter_structured_geography_rows(value):
        if not structured_geography_row_has_metric_value(row):
            continue
        entity_key = _structured_geography_row_entity_key(row)
        if entity_key:
            keys.add(entity_key)
    return keys


def _structured_geography_row_entity_key(row: Mapping[str, Any]) -> str | None:
    for key in _GEOGRAPHY_ROW_NAME_KEY_ORDER:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_token(value)
    return None


def _iter_structured_geography_rows(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if _row_has_geography_name(value):
            yield value
        for child in value.values():
            if isinstance(child, (Mapping, list, tuple)):
                yield from _iter_structured_geography_rows(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_structured_geography_rows(child)


def _row_has_geography_name(row: Mapping[str, Any]) -> bool:
    return any(str(row.get(key) or "").strip() for key in _GEOGRAPHY_ROW_NAME_KEYS)


def _structured_geography_metric_items(
    metric_label: str,
    value: Any,
) -> tuple[tuple[str, Any], ...]:
    if isinstance(value, bool) or value is None:
        return ()
    if isinstance(value, (int, float)):
        return ((metric_label, value),)
    if isinstance(value, str):
        return ((metric_label, value),) if _NUMERIC_TOKEN_RE.search(value) else ()
    if isinstance(value, Mapping):
        mapping_metric_label = _metric_label_from_mapping(value)
        base_label = mapping_metric_label or metric_label
        values: list[tuple[str, Any]] = []
        for key, child in value.items():
            normalized_key = _normalize_token(key)
            if (
                normalized_key in _GEOGRAPHY_ROW_METADATA_KEYS
                or normalized_key in _GEOGRAPHY_ROW_METRIC_LABEL_KEYS
            ):
                continue
            child_label = (
                base_label
                if normalized_key in _GEOGRAPHY_ROW_GENERIC_VALUE_KEYS
                else " ".join(part for part in (base_label, str(key)) if part)
            )
            values.extend(_structured_geography_metric_items(child_label, child))
        return tuple(values)
    if isinstance(value, (list, tuple)):
        values: list[tuple[str, Any]] = []
        for child in value:
            values.extend(_structured_geography_metric_items(metric_label, child))
        return tuple(values)
    return ()


def _metric_label_from_mapping(value: Mapping[str, Any]) -> str | None:
    for key in _GEOGRAPHY_ROW_METRIC_LABEL_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def numeric_fact_has_requested_geography_evidence(
    fact: Any,
    requested_dimensions: tuple[str, ...],
) -> bool:
    """Whether a numeric fact can satisfy requested geography coverage."""

    if not isinstance(fact, Mapping):
        return False
    if not (
        _has_non_empty_value(fact.get("display_value"))
        or _has_non_empty_value(fact.get("raw_value"))
        or _has_non_empty_value(fact.get("value"))
    ):
        return False
    text = " ".join(
        str(fact.get(key) or "")
        for key in ("id", "label", "subject", "metric", "source_key")
    )
    dimensions = _structured_geography_dimensions(text)
    if _US_STATE_RE.search(_strip_non_specific_places(text)):
        dimensions = _unique((*dimensions, "state"))
    return _dimensions_match_request(requested_dimensions, dimensions)


def _has_enough_requested_geography_numeric_fact_evidence(
    facts: Iterable[Any],
    requested_dimensions: tuple[str, ...],
    *,
    minimum_entity_count: int,
    requested_entity_keys: tuple[str, ...],
) -> bool:
    matching_facts = [
        fact
        for fact in facts
        if numeric_fact_has_requested_geography_evidence(
            fact,
            requested_dimensions,
        )
    ]
    entity_keys: set[str] = set()
    for fact in matching_facts:
        entity_keys.update(_numeric_fact_geography_entity_keys(fact))
    if requested_entity_keys:
        return (
            set(requested_entity_keys).issubset(entity_keys)
            and len(entity_keys) >= minimum_entity_count
        )
    if minimum_entity_count <= 1:
        return bool(matching_facts)
    return len(entity_keys) >= minimum_entity_count


def _numeric_fact_geography_entity_keys(fact: Any) -> tuple[str, ...]:
    if not isinstance(fact, Mapping):
        return ()
    text = _strip_non_specific_places(
        " ".join(
            str(fact.get(key) or "")
            for key in ("id", "label", "subject", "metric", "source_key")
        )
    )
    keys = [_normalize_token(match.group(0)) for match in _US_STATE_RE.finditer(text)]
    keys.extend(
        _normalize_token(match.group(0))
        for match in _REGION_ENTITY_RE.finditer(text)
    )
    return _unique(keys)


def _structured_unavailable_sources(
    summary: Mapping[str, Any],
    requested_dimensions: tuple[str, ...],
) -> tuple[str, ...]:
    sources: list[str] = []
    sources.extend(
        _unavailable_records(
            "source_coverage",
            summary.get("source_coverage"),
            requested_dimensions,
        )
    )

    metadata = summary.get("metadata")
    if isinstance(metadata, Mapping):
        sources.extend(
            _unavailable_records(
                "metadata.fetch_errors",
                metadata.get("fetch_errors"),
                requested_dimensions,
            )
        )
    return _unique(sources)


def _unavailable_records(
    label: str,
    value: Any,
    requested_dimensions: tuple[str, ...],
) -> list[str]:
    records: list[str] = []
    for record_label, record_value, text in _iter_records(label, value):
        if not text.strip():
            continue
        record_dimensions = _record_geography_dimensions(
            record_label,
            record_value,
            text,
        )
        if not _dimensions_match_request(requested_dimensions, record_dimensions):
            continue
        if _record_marks_unavailable(record_label, record_value):
            records.append(record_label)
    return records


def _iter_records(label: str, value: Any) -> Iterable[tuple[str, Any, str]]:
    if value is None:
        return
    if isinstance(value, Mapping):
        if _mapping_is_record(value):
            yield label, value, _normalized_text(label, value)
        for key, child in value.items():
            child_label = f"{label}.{key}"
            if isinstance(child, (Mapping, list, tuple)):
                yield from _iter_records(child_label, child)
            else:
                yield child_label, child, _normalized_text(child_label, child)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_label = f"{label}[{index}]"
            if isinstance(child, (Mapping, list, tuple)):
                yield from _iter_records(child_label, child)
            else:
                yield child_label, child, _normalized_text(child_label, child)
        return
    yield label, value, _normalized_text(label, value)


def _mapping_is_record(value: Mapping[str, Any]) -> bool:
    keys = {_normalize_token(key) for key in value}
    return bool(
        keys
        & {
            "available",
            "availability",
            "dimension",
            "dimensions",
            "error",
            "errors",
            "error_type",
            "fetch_error",
            "fetch_errors",
            "geography",
            "provider",
            "reason",
            "source",
            "source_key",
            "status",
        }
    )


def _record_marks_unavailable(label: str, value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = _normalize_token(key)
            normalized_value = _normalize_token(child)
            if normalized_key == "status" and normalized_value in _UNAVAILABLE_STATUS_VALUES:
                return True
            if normalized_key in {"available", "availability"}:
                if isinstance(child, bool):
                    return not child
                if normalized_value in {"false", "no", "unavailable"}:
                    return True
            if normalized_key in {"error", "errors", "error_type", "fetch_error", "fetch_errors"}:
                return _has_non_empty_value(child)
    label_tokens = {_normalize_token(part) for part in re.split(r"[.\[\]\s]+", label) if part}
    return bool(
        label_tokens & {"error", "errors", "fetch_error", "fetch_errors"}
    ) and _has_non_empty_value(value)


def _text_mentions_geography(text: str) -> bool:
    stripped = _strip_non_specific_places(text)
    return bool(requested_geography_dimensions(stripped) or _US_STATE_RE.search(stripped))


def _record_geography_dimensions(
    label: str,
    value: Any,
    text: str,
) -> tuple[str, ...]:
    snippets = [label]
    if isinstance(value, Mapping):
        for key in (
            "dimension",
            "dimensions",
            "geography",
            "geographies",
            "level",
            "scope",
            "source",
            "source_key",
            "provider",
            "reason",
            "error",
        ):
            if key in value:
                snippets.append(_value_text(value.get(key)))
    else:
        snippets.append(text)
    return _structured_geography_dimensions(" ".join(snippets))


def _structured_geography_dimensions(text: str) -> tuple[str, ...]:
    stripped = _strip_non_specific_places(re.sub(r"[_-]+", " ", text))
    dimensions = [
        dimension
        for dimension, pattern in _STRUCTURED_GEOGRAPHY_DIMENSION_PATTERNS
        if pattern.search(stripped)
    ]
    return _unique(dimensions)


def _query_mentions_named_state_dimension(text: str) -> bool:
    if not _US_STATE_RE.search(text):
        return False
    if _STATE_COMPARISON_QUERY_RE.search(text):
        return True
    return bool(_STATE_ECONOMIC_CONTEXT_RE.search(text))


def _requested_geography_entity_keys(query: object) -> tuple[str, ...]:
    text = _strip_non_specific_places(str(query or ""))
    keys = [_normalize_token(match.group(0)) for match in _US_STATE_RE.finditer(text)]
    if requested_geography_dimensions(query):
        keys.extend(
            _normalize_token(match.group(0))
            for match in _REGION_ENTITY_RE.finditer(text)
        )
    return _unique(keys)


def _minimum_requested_geography_entity_count(
    query: object,
    requested_dimensions: tuple[str, ...],
    *,
    requested_entities: tuple[str, ...] = (),
) -> int:
    if not requested_dimensions:
        return 1
    text = _strip_non_specific_places(str(query or ""))
    if (
        _COMPARATIVE_GEOGRAPHY_QUERY_RE.search(text)
        or _PLURAL_GEOGRAPHY_QUERY_RE.search(text)
    ):
        return max(2, len(requested_entities))
    return max(1, len(requested_entities))


def _dimensions_match_request(
    requested_dimensions: tuple[str, ...],
    evidence_dimensions: tuple[str, ...],
) -> bool:
    if not evidence_dimensions:
        return False
    if not requested_dimensions:
        return True
    requested_specific = tuple(
        dimension for dimension in requested_dimensions if dimension != "place"
    ) or requested_dimensions
    evidence = set(evidence_dimensions)
    for requested in requested_specific:
        compatible = set(_DIMENSION_COMPATIBILITY.get(requested, (requested,)))
        if evidence & compatible:
            return True
    return False


def _strip_non_specific_places(text: str) -> str:
    text = _PROVIDER_PLACE_NAME_RE.sub(" ", text)
    text = _NON_GEOGRAPHIC_STATE_NAME_RE.sub(" ", text)
    return _NON_SPECIFIC_US_RE.sub(" ", text)


def _normalized_text(label: str, value: Any) -> str:
    return re.sub(r"[_-]+", " ", f"{label} {_value_text(value)}")


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _normalize_token(value: Any) -> str:
    return re.sub(r"[-\s]+", "_", str(value or "").strip().lower())


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = _normalize_token(value)
        return bool(normalized) and normalized not in {
            "available",
            "covered",
            "false",
            "n_a",
            "na",
            "no",
            "none",
            "null",
            "ok",
            "success",
            "succeeded",
        }
    if isinstance(value, Mapping):
        return any(_has_non_empty_value(child) for child in value.values())
    if isinstance(value, Iterable):
        return any(_has_non_empty_value(child) for child in value)
    return True


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
