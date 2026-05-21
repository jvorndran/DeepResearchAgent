"""Report and execution-summary fidelity checks."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable

from pydantic import ValidationError

from core.report_schema import ResearchReport

from ..artifact_fact_consistency import (
    artifact_fact_consistency_blocker,
    artifact_fact_consistency_dict,
)
from ..requested_coverage import (
    assess_requested_geography_coverage,
    numeric_fact_geography_entity_keys,
    numeric_fact_has_requested_geography_evidence,
    query_requests_geography_coverage,
    requested_geography_entity_keys,
    requested_geography_minimum_entity_count,
    structured_geography_row_entity_key,
    structured_geography_row_metric_items,
)
from agents.quant_macro_stats.artifacts.numeric_fact_contracts import (
    normalize_numeric_facts,
    numeric_fact_current_state_duration_misuse,
    numeric_fact_literal_required,
)
from agents.quant_macro_stats.artifacts.execution_summary_normalization import (
    current_scalar_fact_slots,
    current_scalar_semantic_tokens,
    normalize_quant_execution_summary,
)
from agents.quant_macro_stats.company.sec_company_facts_evidence import (
    requested_company_tickers,
)
from agents.quant_macro_stats.share_count_diagnostics import (
    split_affected_share_count_diagnostics,
)
from agents.quant_macro_stats.artifacts.artifact_fingerprints import (
    artifact_fingerprint_mismatches,
)
from ..report_artifacts import (
    chart_handoff_blocker,
    chart_handoff_dict,
    load_sibling_evidence_bundle_json,
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
_MARKET_VALUATION_CLAIM_RE = re.compile(
    r"\b(?:valuation|market\s+cap(?:italization)?|share\s+price|stock\s+price|"
    r"price\s+target|target\s+price|trading\s+at|trades\s+at|priced\s+at|"
    r"p/e|pe\s+ratio|ev/ebitda|ev/sales|enterprise\s+value|"
    r"valuation\s+multiple|multiples?|analyst\s+estimates?|"
    r"estimate\s+revisions?|forward\s+estimates?|upside|downside)\b",
    re.IGNORECASE,
)
_MARKET_VALUATION_LIMITATION_RE = re.compile(
    r"\b(?:unavailable|not\s+available|not\s+covered|insufficient|excluded|"
    r"missing|not\s+included|outside|without|no\s+(?:paid|market|valuation|"
    r"analyst|price)|cannot|can't|lacks?|limitation|not\s+used)\b",
    re.IGNORECASE,
)
_MARKET_VALUATION_AFFIRMATIVE_RE = re.compile(
    r"(?:\$\s?\d|\b\d+(?:\.\d+)?\s?(?:x|times|%|billion|bn|million|m)\b|"
    r"\b(?:premium|discount|undervalued|overvalued|cheap|expensive|"
    r"attractive|rich|reasonable|upside|downside)\b)",
    re.IGNORECASE,
)
_SHARE_COUNT_SUBJECT_RE = re.compile(
    r"\b(?:share\s+count|shares?\s+outstanding|outstanding\s+shares|"
    r"share\s+base|diluted\s+shares|weighted[-\s]+average\s+shares)\b",
    re.IGNORECASE,
)
_SHARE_COUNT_DIRECTION_RE = re.compile(
    r"\b(?:buybacks?|repurchas(?:e|es|ed|ing)|dilut(?:e|es|ed|ion|ive)|"
    r"issu(?:e|es|ed|ance|ing)|increas(?:e|es|ed|ing)|rose|rising|"
    r"expand(?:s|ed|ing)?|decreas(?:e|es|ed|ing)|"
    r"declin(?:e|es|ed|ing)|fell|fall(?:en|ing)?|"
    r"reduc(?:e|es|ed|ing|tion)|shrink(?:s|ing)?|"
    r"retir(?:e|es|ed|ing)|trend(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
_SHARE_ACTIVITY_RE = re.compile(
    r"\b(?:buybacks?|repurchas(?:e|es|ed|ing)|dilut(?:e|es|ed|ion|ive)|"
    r"issuance|issued)\b",
    re.IGNORECASE,
)
_FULL_PERIOD_SHARE_CONTEXT_RE = re.compile(
    r"\b(?:full[-\s]?(?:period|window|series)|full\s+raw\s+series|"
    r"raw\s+(?:share[-\s]?count\s+)?series|whole\s+period|"
    r"across\s+the\s+(?:full\s+)?(?:period|window|series)|"
    r"over\s+the\s+(?:full\s+)?(?:period|window|series)|"
    r"multi[-\s]?year|since\s+(?:fy\s*)?\d{4}|"
    r"from\s+(?:fy\s*)?\d{4}\s+(?:to|through|-)\s+(?:fy\s*)?\d{4}|"
    r"\d{4}\s*(?:-|to|through)\s*\d{4}|trend(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
_SHARE_COUNT_LIMITATION_ACK_RE = re.compile(
    r"\b(?:split|split[-\s]?adjust(?:ed|ment)?|unadjusted|raw|not\s+comparable|"
    r"uncomparable|basis\s+change|basis\s+discontinuity|"
    r"share[-\s]?count\s+diagnostics?|comparable\s+segment)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_QUERY_RE = re.compile(
    r"\b(?:specific\s+groups?|groups?|subgroups?|cohorts?|"
    r"consumer\s+segments?|places?|"
    r"geograph(?:y|ic|ical)?|regions?|regionally|"
    r"regional\s+(?:comparisons?|rankings?|break(?:out|down)s?|"
    r"coverage|context|data|evidence|conditions?|stress|health|"
    r"econom(?:y|ies)|labor\s+markets?|housing\s+markets?|"
    r"consumer(?:s)?|households?)|states|state[-\s]level|"
    r"metros?|cities|"
    r"counties|zip\s*codes?|localities)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_DIMENSION_RE = re.compile(
    r"\b(?:groups?|subgroups?|cohorts?|consumer\s+segments?|demographics?|places?|"
    r"geograph(?:y|ic|ical)?|regions?|regional|states|state[-\s]level|"
    r"counties|metros?|"
    r"cities|zip\s*codes?|income\s+(?:quintile|quartile|tercile|bracket|"
    r"group)|low[-\s]income|lower[-\s]income|middle[-\s]income|"
    r"high[-\s]income|renters?|homeowners?|borrowers?|subprime|prime|"
    r"younger|older|age\s+(?:group|cohort)|racial|ethnic|black|hispanic|"
    r"asian|white|rural|urban|northeast|midwest|south|west)\b",
    re.IGNORECASE,
)
_SPECIFIC_GROUP_PLACE_DIMENSION_RE = re.compile(
    r"\b(?:states?|state[-\s]level|counties|county[-\s]level|metros?|"
    r"metro[-\s]level|cities|zip\s*codes?|income\s+(?:quintile|quartile|"
    r"tercile|bracket|group)|low[-\s]income|lower[-\s]income|"
    r"middle[-\s]income|high[-\s]income|renters?|homeowners?|borrowers?|"
    r"subprime|prime|younger|older|age\s+(?:group|cohort)|racial|ethnic|"
    r"black|hispanic|asian|white|rural|urban|northeast|midwest|"
    r"south(?:ern)?|west(?:ern)?|sun\s+belt|rust\s+belt|coastal)\b",
    re.IGNORECASE,
)
_US_STATE_PLACE_TERMS = (
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
    "d.c.",
    "dc",
)
_US_STATE_PLACE_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term) for term in _US_STATE_PLACE_TERMS)
    + r")\b",
    re.IGNORECASE,
)
_GROUP_PLACE_PROVIDER_NAME_RE = re.compile(
    r"\b(?:university\s+of\s+michigan|new\s+york\s+fed|ny\s+fed|"
    r"federal\s+reserve\s+bank\s+of\s+new\s+york|"
    r"new\s+york\s+federal\s+reserve)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_NON_SPECIFIC_PLACE_RE = re.compile(
    r"\b(?:united\s+states|u\.s\.|us)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_EVIDENCE_RE = re.compile(
    r"\b(?:census|acs|cps|survey|bea|bls|new\s+york\s+fed|ny\s+fed|"
    r"equifax|transunion|table|chart|source|dataset|state[-\s]level|"
    r"county[-\s]level|metro[-\s]level|regional)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_EVIDENCE_DISCLAIMER_RE = re.compile(
    r"\b(?:does\s+not|doesn't|did\s+not|didn't|not|no|without|lacks?|lack)\b"
    r"[^\n.]{0,80}\b(?:provide|include|show|contain|evidence|data|source|"
    r"table|breakout|break\s*out|segment|state[-\s]level|regional|cohort|"
    r"group|subgroup|place[-\s]specific)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_NON_ASSERTIVE_LIMITATION_RE = re.compile(
    r"(?:\b(?:cannot|can't|can\s+not|could\s+not|unable\s+to)\b"
    r"[^\n.]{0,100}\b(?:state|stated|say|claim|infer|rank|map|"
    r"breakout|breakdown|show|report|estimate|determine|assess|"
    r"reliable|reliably)\b|\bnot\s+(?:possible|feasible)\b)",
    re.IGNORECASE,
)
_GROUP_PLACE_SELF_MISSING_RE = re.compile(
    r"\b(?:this\s+)?(?:report|analysis)\b[^\n.]{0,60}\b"
    r"(?:lacks?|does\s+not|doesn't|without|not\s+include|not\s+provide)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_SCOPE_DRIFT_RE = re.compile(
    r"\b(?:outside\s+(?:of\s+)?(?:the\s+)?(?:report(?:'s)?\s+)?scope|"
    r"not\s+(?:covered|included)\s+(?:by|in)\s+(?:this\s+)?"
    r"(?:report|analysis)|(?:this\s+)?(?:report|analysis)\s+"
    r"(?:does\s+not|doesn't|did\s+not|didn't|will\s+not|won't)\s+"
    r"(?:cover|include))\b",
    re.IGNORECASE,
)
_GROUP_PLACE_UNAVAILABLE_RE = re.compile(
    r"\b(?:unavailable|not\s+available|not\s+covered|missing|failed|"
    r"insufficient|could\s+not|unable\s+to|no\s+reliable|lacks?|"
    r"limitation|not\s+included)\b|"
    r"\bno\b[^\n.]{0,80}\b(?:data|breakdown|break\s*out|evidence|"
    r"source|table)\b[^\n.]{0,40}\bavailable\b",
    re.IGNORECASE,
)
_GROUP_PLACE_AVAILABILITY_CONTEXT_RE = re.compile(
    r"\b(?:data|dataset|source|coverage|table|breakout|break\s*out|"
    r"breakdown|ranking|map|request|fetch|query|evidence|census|acs|"
    r"cps|survey|bea|bls|equifax|transunion|state[-\s]level|"
    r"county[-\s]level|metro[-\s]level|regional|place[-\s]specific|"
    r"group[-\s]specific)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_METADATA_SOURCE_OR_DIMENSION_RE = re.compile(
    r"\b(?:census|acs|cps|new\s+york\s+fed|ny\s+fed|equifax|transunion|"
    r"state|county|metro|geograph(?:y|ic|ical)?|regional|cohort|subgroup|"
    r"segment|demographic|income|borrower|renter|homeowner|housing\s+tenure|"
    r"subprime|prime|younger|older|age|race|racial|ethnic|ethnicity|black|"
    r"hispanic|asian|white|rural|urban)\b",
    re.IGNORECASE,
)
_GROUP_PLACE_UNAVAILABLE_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("census", re.compile(r"\b(?:census|acs)\b", re.IGNORECASE)),
    ("cps", re.compile(r"\bcps\b", re.IGNORECASE)),
    ("bls", re.compile(r"\bbls\b", re.IGNORECASE)),
    (
        "ny_fed",
        re.compile(
            r"\b(?:new\s+york\s+fed|ny\s+fed|"
            r"federal\s+reserve\s+bank\s+of\s+new\s+york)\b",
            re.IGNORECASE,
        ),
    ),
    ("equifax", re.compile(r"\bequifax\b", re.IGNORECASE)),
    ("transunion", re.compile(r"\btransunion\b", re.IGNORECASE)),
    ("bea", re.compile(r"\bbea\b", re.IGNORECASE)),
)
_GROUP_PLACE_UNAVAILABLE_DIMENSION_PATTERNS: tuple[
    tuple[str, re.Pattern[str]],
    ...
] = (
    ("state", re.compile(r"\bstate(?:s|[\s-]+level)?\b", re.IGNORECASE)),
    ("county", re.compile(r"\bcount(?:y|ies|y[\s-]+level)\b", re.IGNORECASE)),
    ("metro", re.compile(r"\bmetros?\b|\bmetro[\s-]+level\b", re.IGNORECASE)),
    ("city", re.compile(r"\bcities\b|\bcity\b|\bzip\s*codes?\b", re.IGNORECASE)),
    (
        "regional",
        re.compile(
            r"\b(?:regions?|regional|northeast|midwest|south(?:ern)?|"
            r"west(?:ern)?|sun\s+belt|rust\s+belt|coastal)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "place",
        re.compile(r"\bplaces?\b|\bgeograph(?:y|ic|ical)?\b", re.IGNORECASE),
    ),
    (
        "income",
        re.compile(
            r"\bincome\s+(?:quintiles?|quartiles?|terciles?|brackets?|"
            r"groups?|segments?)\b|\b(?:low|lower|middle|high)[-\s]income\b",
            re.IGNORECASE,
        ),
    ),
    (
        "housing_tenure",
        re.compile(r"\b(?:housing\s+tenure|renters?|homeowners?)\b", re.IGNORECASE),
    ),
    (
        "borrower_segment",
        re.compile(r"\b(?:borrowers?|subprime|prime)\b", re.IGNORECASE),
    ),
    (
        "age",
        re.compile(
            r"\b(?:younger|older|age(?:\s+(?:groups?|cohorts?))?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "race_ethnicity",
        re.compile(
            r"\b(?:race|racial|ethnic|ethnicity|black|hispanic|asian|white)\b",
            re.IGNORECASE,
        ),
    ),
    ("rural_urban", re.compile(r"\b(?:rural|urban)\b", re.IGNORECASE)),
    (
        "group",
        re.compile(
            r"\b(?:groups?|subgroups?|cohorts?|segments?|demographics?|"
            r"borrowers?|renters?|homeowners?)\b",
            re.IGNORECASE,
        ),
    ),
)
_GROUP_PLACE_UNAVAILABLE_PLACE_DIMENSIONS = {
    "place",
    "state",
    "county",
    "metro",
    "city",
    "regional",
}
_GROUP_PLACE_UNAVAILABLE_GROUP_DIMENSIONS = {
    "group",
    "income",
    "housing_tenure",
    "borrower_segment",
    "age",
    "race_ethnicity",
    "rural_urban",
}
_GROUP_PLACE_UNAVAILABLE_STATUS_VALUES = {
    "failed",
    "failure",
    "error",
    "missing",
    "not_available",
    "not_covered",
    "unavailable",
}
_GROUP_PLACE_UNAVAILABLE_ERROR_LEVEL_VALUES = {"error", "failed", "failure"}
_GROUP_PLACE_METADATA_RECORD_KEYS = {
    "available",
    "availability",
    "coverage",
    "dataset",
    "dimension",
    "dimensions",
    "error",
    "errors",
    "fetch_error",
    "fetch_errors",
    "granularity",
    "level",
    "provider",
    "reason",
    "scope",
    "source",
    "source_key",
    "status",
}
_GROUP_PLACE_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+|\s*[;|:]\s*|\s+(?:--?|-)\s+|"
    r"\s+\b(?:but|however|nevertheless|nonetheless|yet|so|therefore|thus)\b\s+",
    re.IGNORECASE,
)
_STRUCTURED_GEOGRAPHY_ROW_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+|\s*[;|]\s*|\s+(?:--?|-)\s+|"
    r"\s+\b(?:and|while|whereas|but|however|versus|vs\.?)\b\s+|"
    r",\s+(?=[A-Za-z])",
    re.IGNORECASE,
)
_REAL_WAGE_NEGATIVE_CLAIM_RE = re.compile(
    r"\breal\s+(?:average\s+hourly\s+)?(?:wages?|earnings|pay)\b"
    r"[^\n.]{0,120}\b(?:erod(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|"
    r"fell|fall(?:en|ing)?|drop(?:ped|s|ping)?|compress(?:ed|ion)|"
    r"lag(?:ged|ging)?|negative|lost\s+purchasing\s+power)\b|"
    r"\breal[-\s]wage\s+erosion\b",
    re.IGNORECASE,
)
_REAL_WAGE_POSITIVE_CLAIM_RE = re.compile(
    r"\breal\s+(?:average\s+hourly\s+)?(?:wages?|earnings|pay)\b"
    r"[^\n.]{0,120}\b(?:rose|risen|increas(?:e|es|ed|ing)|grew|growth|"
    r"gain(?:ed|s|ing)?|up|positive|outpac(?:e|es|ed|ing)|ahead\s+of\s+"
    r"inflation)\b",
    re.IGNORECASE,
)
_REAL_WAGE_SUBJECT_RE = re.compile(
    r"\breal\s+(?:average\s+hourly\s+)?(?:wages?|earnings|pay)\b|"
    r"\breal[-\s]wage\b",
    re.IGNORECASE,
)
_REAL_WAGE_ALTERNATE_PERIOD_RE = re.compile(
    r"\b(?:peak|pandemic|2020|2021|2022)\b",
    re.IGNORECASE,
)
_REAL_WAGE_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s*(?:;|\b(?:but|while|although|though|whereas)\b|"
    r"\band\s+(?=(?:are|is|was|were|has|have|had|rose|risen|"
    r"increas(?:e|es|ed|ing)|grew|gain(?:ed|s|ing)?|up|fell|"
    r"fall(?:en|ing)?|declin(?:e|es|ed|ing)|erod(?:e|es|ed|ing)|"
    r"drop(?:ped|s|ping)?|compress(?:ed|ion)|lag(?:ged|ging)?)\b))\s*",
    re.IGNORECASE,
)
_SIGNED_POSITIVE_STATE_RE = re.compile(
    r"\b(?:positive|above\s+zero|greater\s+than\s+zero|over\s+zero|"
    r"in\s+positive\s+territory)\b|"
    r"\b(?:is|are|was|were|remain(?:s|ed|ing)?|still|continues?\s+to|"
    r"continued\s+to)\s+(?:still\s+|currently\s+|now\s+|again\s+)?"
    r"(?:grow(?:s|ing)?|increas(?:e|es|ed|ing)|expand(?:s|ed|ing)?|"
    r"improv(?:e|es|ed|ing)|outpac(?:e|es|ed|ing))\b",
    re.IGNORECASE,
)
_SIGNED_NEGATIVE_STATE_RE = re.compile(
    r"\b(?:negative|below\s+zero|less\s+than\s+zero|under\s+zero|"
    r"in\s+negative\s+territory|lost\s+purchasing\s+power)\b|"
    r"\b(?:is|are|was|were|remain(?:s|ed|ing)?|still|continues?\s+to|"
    r"continued\s+to)\s+(?:still\s+|currently\s+|now\s+|again\s+)?"
    r"(?:contract(?:s|ed|ing)?|shrink(?:s|ing)?|erod(?:e|es|ed|ing)|"
    r"deteriorat(?:e|es|ed|ing)|lag(?:s|ged|ging)?)\b",
    re.IGNORECASE,
)
_SIGNED_DIRECTION_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+|\s*(?:;|\||:)\s*|"
    r"\s+\b(?:but|while|although|though|whereas|however|yet)\b\s+",
    re.IGNORECASE,
)
_SIGNED_DIRECTION_FACT_TOKENS = {
    "chg",
    "change",
    "changed",
    "growth",
    "grow",
    "yoy",
    "qoq",
    "mom",
    "wow",
    "delta",
    "spread",
    "gap",
    "return",
}
_YIELD_CURVE_NEGATIVE_STATE_RE = re.compile(
    r"\b(?:invert(?:ed|s|ing)?|inversion)\b",
    re.IGNORECASE,
)
_YIELD_CURVE_POSITIVE_STATE_RE = re.compile(
    r"\b(?:normaliz(?:e|es|ed|ing|ation)|normal\s+shape)\b",
    re.IGNORECASE,
)
_YIELD_CURVE_FACT_MARKER_RE = re.compile(
    r"\b(?:yield\s+curve|yield\s+spread|spread|curve|10y[\s-]*(?:fed|2y))\b",
    re.IGNORECASE,
)
_YIELD_CURVE_STATE_TERM = (
    r"(?:invert(?:ed|s|ing)?|inversion|"
    r"normaliz(?:e|es|ed|ing|ation)|normal\s+shape)"
)
_YIELD_CURVE_CURRENT_STATE_ASSERTION_RE = re.compile(
    rf"\b(?:yield\s+curve|yield\s+spread|spread|curve|10y[\s-]*(?:fed|2y))\b"
    rf"[^\n.]{{0,80}}\b(?:is|are|has|have|remain(?:s|ed|ing)?|"
    rf"stays?|stay(?:ed|ing)?|continues?\s+to|continued\s+to|"
    rf"currently|current|latest|now|today|still)\b"
    rf"[^\n.]{{0,80}}\b{_YIELD_CURVE_STATE_TERM}\b|"
    rf"\b(?:currently|current|latest|now|today|still|"
    rf"remain(?:s|ed|ing)?|has|have)\b"
    rf"[^\n.]{{0,80}}\b{_YIELD_CURVE_STATE_TERM}\b"
    rf"[^\n.]{{0,80}}\b(?:yield\s+curve|yield\s+spread|spread|curve)\b|"
    rf"\b{_YIELD_CURVE_STATE_TERM}\b"
    rf"[^\n.]{{0,80}}\b(?:yield\s+curve|yield\s+spread|spread|curve)\b"
    rf"[^\n.]{{0,80}}\b(?:persist(?:s|ed|ing)?|remain(?:s|ed|ing)?|"
    rf"continues?|stays?|still)\b",
    re.IGNORECASE,
)
_YIELD_CURVE_CURRENT_STATE_CONTEXT_RE = re.compile(
    r"\b(?:current(?:ly)?|latest|now|today|still|remain(?:s|ed|ing)?|"
    r"has|have|is|are|stays?|stay(?:ed|ing)?|continues?\s+to|"
    r"continued\s+to)\b",
    re.IGNORECASE,
)
_YIELD_CURVE_STATE_NEGATION_RE = re.compile(
    r"\b(?:not|no|does\s+not|doesn't|did\s+not|didn't|is\s+not|isn't|"
    r"are\s+not|aren't|was\s+not|wasn't|were\s+not|weren't|without)\b"
    r"[^\n.]{0,60}\b(?:invert(?:ed|s|ing)?|inversion|"
    r"normaliz(?:e|es|ed|ing|ation)|normal\s+shape)\b",
    re.IGNORECASE,
)
_GENERIC_FACT_MARKER_TOKENS = _SIGNED_DIRECTION_FACT_TOKENS | {
    "annualized",
    "avg",
    "average",
    "billion",
    "billions",
    "bps",
    "current",
    "dollar",
    "dollars",
    "index",
    "indexed",
    "latest",
    "level",
    "million",
    "millions",
    "nominal",
    "pp",
    "pct",
    "percent",
    "percentage",
    "point",
    "points",
    "rate",
    "real",
    "recent",
    "seasonally",
    "thousand",
    "thousands",
    "today",
    "usd",
    "value",
}
_GENERIC_FACT_WINDOW_TOKEN_RE = re.compile(
    r"^\d+(?:mo|m|month|months|q|quarter|quarters|yr|year|years)$"
)
_UNAVAILABLE_CURRENT_LIMITATION_RE = re.compile(
    r"\b(?:unavailable|not\s+available|not\s+covered|missing|failed|"
    r"insufficient|could\s+not|unable\s+to|no\s+reliable|not\s+reported|"
    r"not\s+included|not\s+fetched|limitation)\b",
    re.IGNORECASE,
)
_UNAVAILABLE_CURRENT_AFFIRMATIVE_RE = re.compile(
    r"\b(?:stands?|stood|sits?|sat)\s+at\b|"
    r"\b(?:rose|risen|rising|fell|fall(?:en|ing)?|declin(?:e|es|ed|ing)|"
    r"increas(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|surged?|"
    r"drop(?:ped|s|ping)?)\b|"
    r"\b(?:outnumber(?:s|ed|ing)?|exceed(?:s|ed|ing)?|above|below|"
    r"higher|lower)\b|"
    r"\b(?:is|are|was|were|remain(?:s|ed|ing)?|still|stays?|"
    r"stay(?:ed|ing)?)\s+(?:well\s+|still\s+|currently\s+|near\s+)?"
    r"(?:above|below|higher|lower|elevated|high|low|tight|strong|weak|"
    r"positive|negative)\b|"
    r"\b\d[\d,.]*\s?(?:%|million|m|thousand|k|pp)?\b",
    re.IGNORECASE,
)
_UNAVAILABLE_CURRENT_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+|\s*(?:;|\||:)\s*|"
    r"\s+\b(?:but|while|although|though|whereas|however|yet|so|therefore|thus)\b\s+",
    re.IGNORECASE,
)
_SOURCE_TOKEN_MARKERS = {
    "jtsjol": ("jtsjol", "job openings", "openings"),
    "openings": ("job openings", "openings"),
    "jtsqur": ("jtsqur", "quits", "quit rate", "quits rate"),
    "unrate": ("unrate", "unemployment"),
    "payems": ("payems", "payroll", "payrolls"),
    "civpart": ("civpart", "labor force participation", "participation rate"),
    "participation": ("labor force participation", "participation rate"),
    "icsa": ("icsa", "initial claims", "jobless claims"),
    "uempm": ("uempm", "unemployment duration", "weeks unemployed"),
    "usrec": ("usrec", "nber", "recession indicator"),
}
_CURRENT_SCALAR_SEMANTIC_MARKERS = {
    "ahe": ("average hourly earnings", "hourly earnings", "wage", "wages"),
    "ces0500000003": (
        "average hourly earnings",
        "hourly earnings",
        "wage",
        "wages",
    ),
    "lns12032195": (
        "underemployment",
        "part-time for economic reasons",
        "part time for economic reasons",
        "labor market slack",
    ),
    "slack": ("labor market slack",),
    "uempmean": ("uempmean", "unemployment duration", "weeks unemployed"),
    "underemployment": (
        "underemployment",
        "part-time for economic reasons",
        "part time for economic reasons",
        "labor market slack",
    ),
}
_UNAVAILABLE_CURRENT_FIELD_PHRASE_MARKERS = (
    (("job", "openings"), ("job openings", "openings")),
    (
        ("labor", "force", "participation"),
        ("labor force participation", "participation rate"),
    ),
    (("initial", "claims"), ("initial claims", "jobless claims")),
    (("jobless", "claims"), ("jobless claims", "initial claims")),
    (("unemployment", "duration"), ("unemployment duration", "weeks unemployed")),
    (("yield", "curve"), ("yield curve", "yield spread")),
)
_UNAVAILABLE_CURRENT_SINGLE_MARKER_TOKENS = {
    "civpart",
    "icsa",
    "jtsjol",
    "jtsqur",
    "openings",
    "payems",
    "payroll",
    "payrolls",
    "quits",
    "ahe",
    "underemployment",
    "unemployment",
    "unrate",
    "usrec",
}
_UNAVAILABLE_SOURCE_COVERAGE_STATUSES = {
    "error",
    "failed",
    "insufficient",
    "missing",
    "no_data",
    "not_available",
    "not_covered",
    "not_fetched",
    "unavailable",
}
_OPENINGS_WORKERS_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+|\s*(?:;|\||:)\s*|"
    r"\s+\b(?:but|while|although|though|whereas|however|yet|so|therefore|thus)\b\s+",
    re.IGNORECASE,
)
_OPENINGS_WORKERS_OPENINGS_RE = re.compile(
    r"\b(?:jolts|job\s+openings?|openings?|vacanc(?:y|ies))\b",
    re.IGNORECASE,
)
_OPENINGS_WORKERS_WORKER_RE = re.compile(
    r"\b(?:available\s+workers?|unemployed(?:\s+(?:workers?|people|persons?))?|"
    r"job\s*seekers?|labor\s+supply|worker\s+supply)\b",
    re.IGNORECASE,
)
_OPENINGS_WORKERS_COMPARISON_RE = re.compile(
    r"\b(?:outnumber(?:s|ed|ing)?|exceed(?:s|ed|ing)?|more\s+than|"
    r"greater\s+than|above|higher\s+than|per|ratio)\b",
    re.IGNORECASE,
)
_OPENINGS_WORKERS_LIMITATION_RE = re.compile(
    r"\b(?:no|not|without|missing|unavailable|insufficient|lacks?|lack|"
    r"does\s+not|doesn't|could\s+not|unable\s+to)\b[^\n.]{0,80}"
    r"\b(?:ratio|comparison|available\s+workers?|unemployed|job\s*seekers?)\b",
    re.IGNORECASE,
)
_OPENINGS_WORKERS_FACT_OPENINGS_TOKENS = {
    "jtsjol",
    "opening",
    "openings",
    "vacancy",
    "vacancies",
}
_OPENINGS_WORKERS_FACT_WORKER_TOKENS = {
    "jobseeker",
    "jobseekers",
    "unemploy",
    "unemployed",
    "unemployment",
    "unrate",
    "worker",
    "workers",
}
_OPENINGS_WORKERS_FACT_COMPARISON_TOKENS = {
    "comparison",
    "compared",
    "divide",
    "divided",
    "exceed",
    "exceeds",
    "gap",
    "leverage",
    "multiple",
    "outnumber",
    "per",
    "ratio",
    "relative",
    "spread",
    "to",
    "versus",
    "vs",
}
_OPENINGS_WORKERS_FACT_COMPARISON_UNITS = {
    "multiple",
    "ratio",
}


def _current_scalar_source_markers(*values: object) -> tuple[str, ...]:
    markers: list[str] = []
    for token in sorted(current_scalar_semantic_tokens(*values)):
        markers.extend(_SOURCE_TOKEN_MARKERS.get(token, ()))
        markers.extend(_CURRENT_SCALAR_SEMANTIC_MARKERS.get(token, ()))
    return tuple(dict.fromkeys(marker for marker in markers if len(marker) > 2))


_PCE_AHEAD_OF_DPI_CLAIM_RE = re.compile(
    r"\b(?:pce|consumption|spending|expenditures?)\b[^\n.]{0,120}\b"
    r"(?:out(?:run|runs|ran|pace|paces|paced)|running\s+ahead|runs?\s+ahead|"
    r"grew\s+faster|grown\s+faster|exceeds?|above|larger\s+than)\b"
    r"[^\n.]{0,120}\b(?:dpi|disposable\s+personal\s+income|income)\b|"
    r"\b(?:dpi|disposable\s+personal\s+income|income)\b[^\n.]{0,120}\b"
    r"(?:lags?|lagging|trails?|behind|below|not\s+sustainably\s+supported)\b"
    r"[^\n.]{0,120}\b(?:pce|consumption|spending|expenditures?)\b",
    re.IGNORECASE,
)
_DPI_AHEAD_OF_PCE_CLAIM_RE = re.compile(
    r"\b(?:dpi|disposable\s+personal\s+income|income)\b[^\n.]{0,120}\b"
    r"(?:out(?:run|runs|ran|pace|paces|paced)|running\s+ahead|runs?\s+ahead|"
    r"grew\s+faster|grown\s+faster|exceeds?|above|larger\s+than)\b"
    r"[^\n.]{0,120}\b(?:pce|consumption|spending|expenditures?)\b|"
    r"\b(?:pce|consumption|spending|expenditures?)\b[^\n.]{0,120}\b"
    r"(?:lags?|lagging|trails?|behind|below)\b[^\n.]{0,120}\b"
    r"(?:dpi|disposable\s+personal\s+income|income)\b",
    re.IGNORECASE,
)
_DIRECTION_NEGATION_RE = re.compile(
    r"\b(?:not|no|does\s+not|doesn't|did\s+not|didn't|is\s+not|isn't|"
    r"are\s+not|aren't|without)\b[^\n.]{0,60}\b(?:"
    r"rose|risen|rising|increas(?:e|es|ed|ing)|grew|grown|growing|"
    r"growth|gain(?:ed|s|ing)?|positive|improv(?:e|es|ed|ing)|"
    r"negative|contract(?:s|ed|ing|ion)|shrink(?:s|ing)?|"
    r"erod(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|fell|fall(?:en|ing)?|"
    r"drop(?:ped|s|ping)?|compress(?:ed|ion)|lag(?:ged|ging)?|"
    r"deteriorat(?:e|es|ed|ing)|"
    r"out(?:run|runs|ran)|outpac(?:e|es|ed|ing)|"
    r"running\s+ahead|runs?\s+ahead|"
    r"ahead|exceed(?:s|ed|ing)?|above|below)\b",
    re.IGNORECASE,
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
        "evidence_bundle_json",
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
        "current_signal_facts",
        "signal_design",
        "lead_time_rows",
        "scenario_score_rows",
        "replay_rows",
        "replay_design",
        "latest_fundamentals",
        "company_history_rows",
        "trend_diagnostics",
        "share_count_diagnostics",
        "macro_overlay",
        "company_macro_sensitivity",
        "diagnostics",
        "source_coverage",
        "source_snapshots",
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


def _load_sibling_evidence_bundle(report_path: Path) -> dict[str, object]:
    """Return compact evidence_bundle.json metadata when available."""
    bundle_path = report_path.with_name("evidence_bundle.json")
    parsed, error = load_sibling_evidence_bundle_json(report_path)
    if error:
        return {
            "status": "error",
            "path": str(bundle_path),
            "error": error,
        }
    if parsed is None:
        return {
            "status": "missing",
            "path": str(bundle_path),
            "note": "No sibling evidence_bundle.json was found.",
        }

    compact: dict[str, object] = {
        "status": "success",
        "path": str(bundle_path),
        "schema_version": parsed.get("schema_version"),
        "bundle_type": parsed.get("bundle_type"),
        "fact_ids": _bundle_item_ids(parsed.get("facts"), "fact_id"),
        "chart_ids": _bundle_item_ids(parsed.get("charts"), "chart_id"),
        "source_ids": _bundle_item_ids(parsed.get("sources"), "source_id"),
    }

    artifacts = parsed.get("artifacts")
    if isinstance(artifacts, dict):
        compact["artifacts"] = {
            key: str(value)
            for key in (
                "charts_json",
                "execution_summary_json",
                "evidence_bundle_json",
            )
            if (value := artifacts.get(key)) is not None
        }
        source_snapshots = artifacts.get("source_snapshots")
        if isinstance(source_snapshots, dict):
            compact["artifacts"]["source_snapshot_keys"] = list(source_snapshots)[:20]

    validation = parsed.get("validation")
    if isinstance(validation, dict):
        diagnostics = validation.get("diagnostics")
        compact_validation: dict[str, object] = {
            "valid": validation.get("valid"),
            "dropped_chart_ids": validation.get("dropped_chart_ids") or [],
        }
        if isinstance(diagnostics, list):
            compact_validation["diagnostics"] = [
                {
                    "level": item.get("level"),
                    "code": item.get("code"),
                    "message": _truncate(str(item.get("message") or ""), 300),
                }
                for item in diagnostics[:12]
                if isinstance(item, dict)
            ]
        compact["validation"] = compact_validation

    for key in ("methods", "limitations"):
        value = parsed.get(key)
        if isinstance(value, list):
            compact[key] = [str(item) for item in value[:20]]
    return compact


def _bundle_item_ids(value: Any, key: str) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get(key) or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _load_execution_summary_payload(report_path: Path) -> dict[str, object] | None:
    parsed, _ = load_sibling_execution_summary_json(report_path)
    return parsed


def _unique_string_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip() if item is not None else ""
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _report_chart_ids(data: dict[str, object]) -> list[str]:
    charts = data.get("charts")
    if isinstance(charts, dict):
        return _unique_string_ids(list(charts.keys()))
    if not isinstance(charts, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        for key in ("id", "chart_id", "name"):
            value = chart.get(key)
            text = str(value).strip() if value is not None else ""
            if text:
                break
        else:
            text = ""
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _chart_ids_from_charts_payload(payload: object) -> list[str]:
    if isinstance(payload, dict):
        nested = payload.get("charts")
        if isinstance(nested, list):
            return _chart_ids_from_charts_payload(nested)
        return [
            str(chart_id)
            for chart_id, chart in payload.items()
            if chart_id and chart
        ]
    if isinstance(payload, list):
        return [
            str(chart["id"])
            for chart in payload
            if isinstance(chart, dict) and chart.get("id")
        ]
    return []


def _load_sibling_charts_json_chart_ids(report_path: Path) -> list[str] | None:
    charts_path = report_path.with_name("charts.json")
    if not charts_path.is_file():
        return None
    try:
        parsed = json.loads(charts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _chart_ids_from_charts_payload(parsed)


def _artifact_path_matches(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = expected.parent / candidate
    try:
        return candidate.resolve(strict=False) == expected.expanduser().resolve(
            strict=False
        )
    except OSError:
        return str(candidate) == str(expected)


def _evidence_bundle_artifact_mismatches(
    bundle: dict[str, object],
    report_path: Path,
) -> list[str]:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        return ["artifacts must contain canonical sibling artifact paths"]
    expected = {
        "charts_json": report_path.with_name("charts.json"),
        "execution_summary_json": report_path.with_name("execution_summary.json"),
        "evidence_bundle_json": report_path.with_name("evidence_bundle.json"),
    }
    mismatches: list[str] = []
    for key, expected_path in expected.items():
        if not _artifact_path_matches(artifacts.get(key), expected_path):
            mismatches.append(f"{key} expected {expected_path}")
    return mismatches


def _evidence_bundle_fact_blocker(
    bundle: dict[str, object],
    summary: dict[str, object],
) -> str | None:
    summary_facts = _numeric_facts_from_summary(summary)
    bundle_facts = [
        item
        for item in bundle.get("facts", [])
        if isinstance(item, dict) and str(item.get("fact_id") or "").strip()
    ]
    summary_fact_ids = [str(fact["id"]) for fact in summary_facts]
    bundle_fact_ids = [str(fact["fact_id"]) for fact in bundle_facts]
    if summary_fact_ids != bundle_fact_ids:
        return (
            "evidence_bundle.json fact_ids do not match "
            "execution_summary.json numeric_facts: "
            f"bundle={bundle_fact_ids} execution_summary={summary_fact_ids}. "
            "Rerun quant-developer so the canonical evidence bundle is "
            "regenerated from the current numeric facts."
        )

    summary_by_id = {
        str(fact["id"]): _numeric_fact_signature(fact)
        for fact in summary_facts
    }
    bundle_by_id = {
        str(fact["fact_id"]): _bundle_fact_signature(fact)
        for fact in bundle_facts
    }
    mismatches: list[str] = []
    for fact_id in summary_fact_ids:
        changed_fields = [
            field
            for field, value in summary_by_id[fact_id].items()
            if bundle_by_id.get(fact_id, {}).get(field) != value
        ]
        if changed_fields:
            mismatches.append(f"{fact_id} ({', '.join(changed_fields)})")
    if not mismatches:
        return None
    return (
        "evidence_bundle.json facts do not match execution_summary.json "
        f"numeric_facts for {', '.join(mismatches[:6])}. Rerun "
        "quant-developer so the canonical evidence bundle is regenerated from "
        "the current numeric facts."
    )


def _numeric_fact_signature(fact: dict[str, object]) -> dict[str, object]:
    return {
        "label": str(fact.get("label") or ""),
        "raw_value": _float_signature(fact.get("raw_value")),
        "display_value": str(fact.get("display_value") or ""),
        "unit": str(fact.get("unit") or ""),
        "precision": _int_signature(fact.get("precision")),
        "tolerance": _float_signature(fact.get("tolerance")),
        "source_key": str(fact.get("source_key") or ""),
        "as_of_date": _optional_text(fact.get("as_of_date")),
        "subject": _optional_text(fact.get("subject")),
        "metric": _optional_text(fact.get("metric")),
        "semantic_role": _optional_text(fact.get("semantic_role")),
        "literal_required": fact.get("literal_required")
        if isinstance(fact.get("literal_required"), bool)
        else None,
        "state_description": _optional_text(fact.get("state_description")),
        "transform_basis": _optional_text(
            fact.get("transform_basis")
            or fact.get("correlation_basis")
            or fact.get("correlation_transform")
            or fact.get("value_transform")
            or fact.get("calculation_basis")
        ),
    }


def _bundle_fact_signature(fact: dict[str, object]) -> dict[str, object]:
    return {
        "label": str(fact.get("label") or ""),
        "raw_value": _float_signature(fact.get("raw_value")),
        "display_value": str(fact.get("display_value") or ""),
        "unit": str(fact.get("unit") or ""),
        "precision": _int_signature(fact.get("precision")),
        "tolerance": _float_signature(fact.get("tolerance")),
        "source_key": str(fact.get("source_key") or ""),
        "as_of_date": _optional_text(fact.get("as_of_date")),
        "subject": _optional_text(fact.get("subject")),
        "metric": _optional_text(fact.get("metric")),
        "semantic_role": _optional_text(fact.get("semantic_role")),
        "literal_required": fact.get("literal_required")
        if isinstance(fact.get("literal_required"), bool)
        else None,
        "state_description": _optional_text(fact.get("state_description")),
        "transform_basis": _optional_text(fact.get("transform_basis")),
    }


def _float_signature(value: object) -> float | None:
    try:
        return round(float(value), 12)
    except (TypeError, ValueError):
        return None


def _int_signature(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_bundle_expected(summary: dict[str, object] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    if str(summary.get("status") or "success") in {"failed", "error", "missing"}:
        return False
    return isinstance(summary.get("evidence_bundle_json"), str)


def _evidence_bundle_consistency_blocker(
    bundle: dict[str, object],
    report_path: Path,
    *,
    summary: dict[str, object] | None,
    report_data: dict[str, object] | None,
) -> str | None:
    mismatches = _evidence_bundle_artifact_mismatches(bundle, report_path)
    if mismatches:
        return (
            "evidence_bundle.json artifact paths do not match sibling quant "
            f"artifacts: {', '.join(mismatches)}. Rerun quant-developer so the "
            "canonical evidence bundle is regenerated from the current artifacts."
        )
    fingerprint_mismatches = artifact_fingerprint_mismatches(
        bundle,
        base_dir=report_path.parent,
        evidence_bundle_path=report_path.with_name("evidence_bundle.json"),
    )
    if fingerprint_mismatches:
        return (
            "evidence_bundle.json artifact fingerprints do not match current "
            f"files: {', '.join(fingerprint_mismatches[:8])}. Rerun "
            "quant-developer so the canonical evidence bundle is regenerated "
            "from the current artifacts and source files."
        )

    bundle_chart_ids = _bundle_item_ids(bundle.get("charts"), "chart_id")
    if isinstance(summary, dict):
        summary_chart_ids = _unique_string_ids(summary.get("chart_ids"))
        if summary_chart_ids and bundle_chart_ids != summary_chart_ids:
            return (
                "evidence_bundle.json chart_ids do not match "
                "execution_summary.json chart_ids: "
                f"bundle={bundle_chart_ids} execution_summary={summary_chart_ids}. "
                "Rerun quant-developer so the canonical evidence bundle is "
                "regenerated from the current summary and charts."
            )
        fact_blocker = _evidence_bundle_fact_blocker(bundle, summary)
        if fact_blocker:
            return fact_blocker

    charts_json_chart_ids = _load_sibling_charts_json_chart_ids(report_path)
    if charts_json_chart_ids is not None and bundle_chart_ids != charts_json_chart_ids:
        return (
            "evidence_bundle.json chart_ids do not match charts.json chart IDs: "
            f"bundle={bundle_chart_ids} charts_json={charts_json_chart_ids}. "
            "Rerun quant-developer so the canonical evidence bundle is "
            "regenerated from the current chart artifact."
        )

    if isinstance(report_data, dict):
        report_chart_ids = _report_chart_ids(report_data)
        missing_report_chart_ids = [
            chart_id for chart_id in report_chart_ids if chart_id not in bundle_chart_ids
        ]
        if missing_report_chart_ids:
            return (
                "report.json references chart IDs missing from evidence_bundle.json: "
                f"{missing_report_chart_ids}. Regenerate the report from the "
                "current canonical evidence bundle."
            )
    return None


def _evidence_bundle_approval_blocker(report_path: Path) -> str | None:
    summary = _load_execution_summary_payload(report_path)
    parsed, error = load_sibling_evidence_bundle_json(report_path)
    if error:
        return (
            "Invalid evidence_bundle.json sibling artifact: "
            f"{error}. Rerun quant-developer so the canonical evidence bundle "
            "validates before QA approval."
        )
    if parsed is None:
        if _evidence_bundle_expected(summary):
            return (
                "Missing evidence_bundle.json sibling artifact referenced by "
                "execution_summary.json. Rerun quant-developer so the canonical "
                "evidence bundle exists and validates before QA approval."
            )
        return None
    validation = parsed.get("validation")
    if isinstance(validation, dict) and validation.get("valid") is False:
        return (
            "evidence_bundle.json reports failed evidence validation; rerun "
            "quant-developer so the canonical evidence bundle is valid before "
            "QA approval."
        )
    report_data, report_error = load_report_json(str(report_path))
    blocker = _evidence_bundle_consistency_blocker(
        parsed,
        report_path,
        summary=summary,
        report_data=report_data if report_error is None else None,
    )
    if blocker:
        return blocker
    return None


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
    return bool(variants) and any(
        re.search(rf"(?<![\w.]){re.escape(variant)}(?![\w]|\.\d)", text)
        for variant in variants
    )


_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?(?![\w]|\.\d)")


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
    source_key = str(fact.get("source_key") or "").lower()
    fact_id = str(fact.get("id") or "").lower()
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
        "real_ahe_12mo_chg_pct": (
            "real wage",
            "real wages",
            "real hourly earnings",
            "real earnings",
        ),
        "real_wage_12mo_chg_pct": (
            "real wage",
            "real wages",
            "real hourly earnings",
            "real earnings",
        ),
        "yield_curve_spread": ("yield curve", "yield spread"),
        "yield_curve_value": ("yield curve", "yield spread"),
    }
    markers = list(marker_map.get(metric, ()))
    markers.extend(token for token in re.split(r"[^a-z0-9]+", metric) if len(token) > 2)
    markers.extend(token for token in re.split(r"[^a-z0-9]+", label) if len(token) > 2)
    markers.extend(_current_scalar_source_markers(source_key, fact_id))
    return tuple(dict.fromkeys(markers))


def _marker_tokens(marker: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", marker.lower()) if token)


def _text_contains_marker(text: str, marker: str) -> bool:
    text_tokens = _marker_tokens(text)
    marker_tokens = _marker_tokens(marker)
    if not text_tokens or not marker_tokens:
        return False
    if len(marker_tokens) == 1:
        return marker_tokens[0] in set(text_tokens)
    return " ".join(marker_tokens) in " ".join(text_tokens)


def _is_generic_fact_marker(marker: str) -> bool:
    tokens = _marker_tokens(marker)
    return bool(tokens) and all(
        token in _GENERIC_FACT_MARKER_TOKENS
        or _GENERIC_FACT_WINDOW_TOKEN_RE.fullmatch(token)
        for token in tokens
    )


def _fact_markers_for_matching(fact: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        marker
        for marker in _metric_markers_for_fact(fact)
        if len(marker) > 2 and not _is_generic_fact_marker(marker)
    )


def _text_mentions_fact(text: str, fact: dict[str, object]) -> bool:
    text_tokens = _marker_tokens(text)
    if not text_tokens:
        return False
    normalized_text = " ".join(text_tokens)
    for marker in _fact_markers_for_matching(fact):
        if _text_contains_marker(normalized_text, marker):
            return True
    return False


def _fact_tokens_for_direction(fact: dict[str, object]) -> set[str]:
    return {
        token
        for token in re.split(
            r"[^a-z0-9]+",
            " ".join(
                str(fact.get(key) or "").lower()
                for key in ("id", "metric", "label", "source_key", "operation")
            ),
        )
        if token
    }


def _is_signed_directional_fact(fact: dict[str, object]) -> bool:
    value = _finite_number(fact.get("raw_value", fact.get("value")))
    if value is None:
        return False
    tolerance = abs(_finite_number(fact.get("tolerance")) or 0.0)
    if abs(value) <= max(tolerance, 1e-9):
        return False
    tokens = _fact_tokens_for_direction(fact)
    unit = str(fact.get("unit") or "").strip().lower()
    return bool(tokens & _SIGNED_DIRECTION_FACT_TOKENS) or unit == "correlation"


def _line_mentions_fact(line: str, fact: dict[str, object]) -> bool:
    return _text_mentions_fact(line, fact)


def _numeric_fact_signed_direction_reversal(
    fact: dict[str, object],
    lines: Iterable[str],
) -> bool:
    if not _is_signed_directional_fact(fact):
        return False
    value = _finite_number(fact.get("raw_value", fact.get("value")))
    if value is None:
        return False
    for line in lines:
        for clause in _SIGNED_DIRECTION_CLAUSE_BOUNDARY_RE.split(line):
            clause = clause.strip()
            if not clause or not _line_mentions_fact(clause, fact):
                continue
            if _DIRECTION_NEGATION_RE.search(clause) or (
                _is_yield_curve_fact(fact)
                and _YIELD_CURVE_STATE_NEGATION_RE.search(clause)
            ):
                continue
            if _yield_curve_state_direction_reversal(fact, clause, value):
                return True
            if value < 0 and _SIGNED_POSITIVE_STATE_RE.search(clause):
                return True
            if value > 0 and _SIGNED_NEGATIVE_STATE_RE.search(clause):
                return True
    return False


def _is_yield_curve_fact(fact: dict[str, object]) -> bool:
    tokens = _fact_tokens_for_direction(fact)
    return "yield" in tokens and (
        "curve" in tokens or "spread" in tokens or "10y2y" in tokens
    )


def _yield_curve_state_direction_reversal(
    fact: dict[str, object],
    clause: str,
    value: float,
) -> bool:
    if not _is_yield_curve_fact(fact):
        return False
    if (
        value > 0
        and _YIELD_CURVE_NEGATIVE_STATE_RE.search(clause)
        and _yield_curve_state_clause_asserts_current_state(fact, clause)
    ):
        return True
    if (
        value < 0
        and _YIELD_CURVE_POSITIVE_STATE_RE.search(clause)
        and _yield_curve_state_clause_asserts_current_state(fact, clause)
    ):
        return True
    return False


def _yield_curve_state_clause_asserts_current_state(
    fact: dict[str, object],
    clause: str,
) -> bool:
    if _YIELD_CURVE_CURRENT_STATE_ASSERTION_RE.search(clause):
        return True
    return (
        _YIELD_CURVE_FACT_MARKER_RE.search(clause) is not None
        and _YIELD_CURVE_CURRENT_STATE_CONTEXT_RE.search(clause) is not None
        and _contains_numeric_fact_value(clause, fact)
    )


def _numeric_fact_fidelity_blockers(
    summary: dict[str, object], markdown: str
) -> list[str]:
    facts = _numeric_facts_from_summary(summary)
    if not facts:
        return []

    markdown_lower = markdown.lower()
    missing: list[str] = []
    semantic_misuse: list[str] = []
    direction_reversals: list[str] = []
    review_lines = _markdown_review_lines(markdown)
    for fact in facts:
        subject = str(fact.get("subject") or "").strip()
        metric = str(fact.get("metric") or fact.get("id") or fact.get("source_key") or "").strip()
        if subject and subject.lower() not in markdown_lower:
            continue
        markers = _fact_markers_for_matching(fact)
        if markers and not _text_mentions_fact(markdown_lower, fact):
            continue
        label = " ".join(part for part in (subject, metric) if part)
        label = label or str(
            fact.get("label") or fact.get("id") or fact.get("source_key") or "numeric fact"
        )
        if numeric_fact_current_state_duration_misuse(markdown, fact):
            semantic_misuse.append(label)
            continue
        if _numeric_fact_signed_direction_reversal(fact, review_lines):
            direction_reversals.append(label)
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
    if direction_reversals:
        return [
            "Report reverses helper-produced signed numeric_facts direction for "
            f"{', '.join(direction_reversals[:8])}. Regenerate the affected "
            "prose from display_value, raw_value, and metric direction in "
            "execution_summary.json."
        ]
    if not missing:
        return []
    return [
        "Report omits or contradicts helper-produced numeric_facts from "
        f"execution_summary.json for {', '.join(missing[:8])}. Regenerate the "
        "affected prose from display_value fields in the quantitative handoff."
    ]


def _valuation_market_data_unavailable(summary: dict[str, object]) -> bool:
    source_coverage = summary.get("source_coverage")
    if not isinstance(source_coverage, dict):
        return False
    valuation_coverage = source_coverage.get("valuation_market_data")
    if not isinstance(valuation_coverage, dict):
        return False
    return str(valuation_coverage.get("status") or "").strip().lower() in {
        "not_available",
        "disabled",
    }


def _has_market_valuation_numeric_facts(summary: dict[str, object]) -> bool:
    markers = (
        "valuation_market_data",
        "market_data",
        "market_valuation",
        "market_cap",
        "valuation_multiple",
        "pe_ratio",
        "ev_ebitda",
        "price_target",
        "analyst_estimate",
        "estimate_revision",
    )
    for fact in _numeric_facts_from_summary(summary):
        text = " ".join(
            str(fact.get(key) or "").lower()
            for key in ("id", "source_key", "metric", "semantic_role", "label")
        )
        if any(marker in text for marker in markers):
            return True
    return False


def _line_claims_market_valuation(line: str) -> bool:
    if not _MARKET_VALUATION_CLAIM_RE.search(line):
        return False
    if _MARKET_VALUATION_LIMITATION_RE.search(line):
        return False
    return bool(_MARKET_VALUATION_AFFIRMATIVE_RE.search(line))


def _unsupported_market_valuation_claim_blocker(
    summary: dict[str, object],
    report_data: dict[str, object],
) -> str | None:
    if not _valuation_market_data_unavailable(summary):
        return None
    if _has_market_valuation_numeric_facts(summary):
        return None

    text = "\n".join(
        str(report_data.get(key) or "")
        for key in ("title", "executive_summary", "markdown")
    )
    claimed_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and _line_claims_market_valuation(line)
    ]
    if not claimed_lines:
        return None
    return (
        "Report makes equity valuation or market-data claims while "
        "execution_summary.source_coverage.valuation_market_data.status="
        "not_available and no market valuation numeric_facts exist. State the "
        "market-data limitation or remove price, market cap, multiple, analyst "
        "estimate, estimate-revision, price-target, and upside/downside claims."
    )


def _line_mentions_share_diagnostic_ticker(
    line: str,
    ticker: str,
    *,
    available_tickers: set[str],
) -> bool:
    if re.search(rf"\b{re.escape(ticker)}\b", line, re.IGNORECASE):
        return True
    return ticker in requested_company_tickers(
        line,
        available_tickers=available_tickers,
    )


def _line_claims_uncaveated_share_count_trend(line: str) -> bool:
    if _SHARE_COUNT_LIMITATION_ACK_RE.search(line):
        return False
    if _SHARE_COUNT_SUBJECT_RE.search(line) and _SHARE_COUNT_DIRECTION_RE.search(line):
        return True
    return bool(
        _SHARE_ACTIVITY_RE.search(line)
        and _FULL_PERIOD_SHARE_CONTEXT_RE.search(line)
    )


def _unsupported_split_affected_share_claim_blocker(
    summary: dict[str, object],
    report_data: dict[str, object],
) -> str | None:
    diagnostics = split_affected_share_count_diagnostics(
        summary.get("share_count_diagnostics")
    )
    if not diagnostics:
        return None

    lines = _report_review_lines(report_data)
    available_tickers = set(diagnostics)
    unsupported: list[str] = []
    for ticker in sorted(diagnostics):
        for line in lines:
            if not _line_mentions_share_diagnostic_ticker(
                line,
                ticker,
                available_tickers=available_tickers,
            ):
                continue
            if _line_claims_uncaveated_share_count_trend(line):
                unsupported.append(f"{ticker}: {line}")
                break

    if not unsupported:
        return None
    return (
        "Report makes buyback, dilution, or share-count trend claims for "
        "tickers whose SEC raw share-count diagnostics mark the full raw series "
        "as split-affected/uncomparable. Qualify those claims with split/raw "
        "share-count limitations, use the latest comparable segment from "
        "share_count_diagnostics, or remove the full-period share trend claim. "
        "Examples: "
        + "; ".join(unsupported[:3])
    )


def _report_claim_text(report_data: dict[str, object]) -> str:
    return "\n".join(
        str(report_data.get(key) or "")
        for key in ("title", "executive_summary", "markdown")
    )


def _markdown_review_lines(markdown: object) -> list[str]:
    lines: list[str] = []
    in_research_query = False
    for raw_line in str(markdown or "").splitlines():
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
        lines.append(line)
    return lines


def _report_review_lines(report_data: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key in ("title", "executive_summary"):
        for raw_line in str(report_data.get(key) or "").splitlines():
            line = raw_line.strip()
            if line:
                lines.append(line)
    lines.extend(_markdown_review_lines(report_data.get("markdown")))
    return lines


def _query_requests_group_place_coverage(query: object) -> bool:
    return bool(
        _GROUP_PLACE_QUERY_RE.search(str(query or ""))
        or query_requests_geography_coverage(query)
    )


def _strip_group_place_provider_names(text: str) -> str:
    return _GROUP_PLACE_PROVIDER_NAME_RE.sub(" ", text)


def _strip_non_specific_group_place_terms(text: str) -> str:
    return _GROUP_PLACE_NON_SPECIFIC_PLACE_RE.sub(" ", text)


def _line_mentions_group_place_dimension(line: str) -> bool:
    scan_line = _strip_non_specific_group_place_terms(
        _strip_group_place_provider_names(line),
    )
    return bool(
        _GROUP_PLACE_DIMENSION_RE.search(scan_line)
        or _US_STATE_PLACE_RE.search(scan_line)
    )


def _line_mentions_specific_group_place_dimension(line: str) -> bool:
    scan_line = _strip_non_specific_group_place_terms(
        _strip_group_place_provider_names(line),
    )
    return bool(
        _SPECIFIC_GROUP_PLACE_DIMENSION_RE.search(scan_line)
        or _US_STATE_PLACE_RE.search(scan_line)
    )


def _line_has_group_place_evidence(line: str) -> bool:
    if not _line_mentions_group_place_dimension(line):
        return False
    if _GROUP_PLACE_SCOPE_DRIFT_RE.search(line):
        return False
    if _GROUP_PLACE_UNAVAILABLE_RE.search(line):
        return False
    if _GROUP_PLACE_EVIDENCE_DISCLAIMER_RE.search(line):
        return False
    return bool(_NUMERIC_TOKEN_RE.search(line) or _GROUP_PLACE_EVIDENCE_RE.search(line))


def _group_place_fact_text(fact: dict[str, object]) -> str:
    return " ".join(
        str(fact.get(key) or "")
        for key in ("id", "label", "subject", "metric", "source_key")
    )


def _numeric_fact_mentions_group_place_dimension(fact: dict[str, object]) -> bool:
    return _line_mentions_group_place_dimension(_group_place_fact_text(fact))


def _line_matches_group_place_numeric_fact(
    line: str,
    fact: dict[str, object],
) -> bool:
    if not _numeric_fact_mentions_group_place_dimension(fact):
        return False

    candidate_segments = [line]
    if _GROUP_PLACE_UNAVAILABLE_RE.search(line):
        candidate_segments = _split_group_place_claim_clauses(line)

    for segment in candidate_segments:
        if not _line_has_group_place_evidence(segment):
            continue
        if not _contains_numeric_fact_value(segment, fact):
            continue
        subject = str(fact.get("subject") or "").strip()
        if subject and _line_mentions_group_place_dimension(subject):
            if subject.lower() not in segment.lower():
                continue
        return True
    return False


def _report_has_artifact_backed_group_place_evidence(
    summary: dict[str, object],
    lines: list[str],
) -> bool:
    facts = _numeric_facts_from_summary(summary)
    if not facts:
        return False
    return any(
        _line_matches_group_place_numeric_fact(line, fact)
        for fact in facts
        for line in lines
    )


def _normalized_requested_geography_entity_key(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return re.sub(r"[-\s]+", "_", text)


def _report_used_requested_geography_entity_keys(
    summary: dict[str, object],
    lines: list[str],
    evidence_keys: tuple[str, ...],
    requested_dimensions: tuple[str, ...],
    minimum_entity_count: int,
) -> set[str]:
    entity_keys: set[str] = set()
    if "numeric_facts" in evidence_keys:
        for fact in _numeric_facts_from_summary(summary):
            if not numeric_fact_has_requested_geography_evidence(
                fact,
                requested_dimensions,
            ):
                continue
            if not any(
                _line_matches_group_place_numeric_fact(line, fact) for line in lines
            ):
                continue
            keys = numeric_fact_geography_entity_keys(fact)
            if keys:
                entity_keys.update(keys)
                continue
            if minimum_entity_count <= 1 and not entity_keys:
                fallback_key = _normalized_requested_geography_entity_key(
                    fact.get("subject")
                    or fact.get("label")
                    or fact.get("id")
                    or fact.get("source_key")
                )
                if fallback_key:
                    entity_keys.add(fallback_key)

    for row in _iter_structured_geography_evidence_rows(summary, evidence_keys):
        if not any(
            _line_matches_structured_geography_row(line, row) for line in lines
        ):
            continue
        entity_key = structured_geography_row_entity_key(row)
        if entity_key:
            entity_keys.add(entity_key)
            continue
        fallback_key = _normalized_requested_geography_entity_key(
            _structured_geography_row_name(row)
        )
        if fallback_key:
            entity_keys.add(fallback_key)
    return entity_keys


_GEOGRAPHY_ROW_NAME_KEYS = (
    "state",
    "state_name",
    "region",
    "region_name",
    "name",
    "subject",
)


def _iter_structured_geography_rows(value: object) -> Iterable[dict[str, object]]:
    if isinstance(value, dict):
        if any(str(value.get(key) or "").strip() for key in _GEOGRAPHY_ROW_NAME_KEYS):
            yield value
        for child in value.values():
            if isinstance(child, (dict, list, tuple)):
                yield from _iter_structured_geography_rows(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_structured_geography_rows(child)


def _structured_geography_row_name(row: dict[str, object]) -> str | None:
    for key in _GEOGRAPHY_ROW_NAME_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_STRUCTURED_GEOGRAPHY_METRIC_MARKER_MAP = {
    "income": (
        "income",
        "median income",
        "per capita income",
        "personal income",
    ),
    "median_income": ("median income", "income"),
    "per_capita_personal_income": (
        "per capita personal income",
        "personal income",
        "per capita income",
        "income",
    ),
    "unemployment_rate": (
        "unemployment rate",
        "unemployment",
        "jobless rate",
        "joblessness",
    ),
}
_STRUCTURED_GEOGRAPHY_GENERIC_METRIC_TOKENS = {
    "current",
    "display",
    "latest",
    "metric",
    "pct",
    "percent",
    "raw",
    "rate",
    "value",
}


def _structured_geography_metric_markers(metric_key: object) -> tuple[str, ...]:
    metric_text = str(metric_key or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", metric_text).strip("_")
    markers = list(_STRUCTURED_GEOGRAPHY_METRIC_MARKER_MAP.get(normalized, ()))
    phrase = normalized.replace("_", " ").strip()
    if phrase and phrase not in _STRUCTURED_GEOGRAPHY_GENERIC_METRIC_TOKENS:
        markers.append(phrase)
    for token in re.split(r"[^a-z0-9]+", metric_text):
        if (
            len(token) > 2
            and token not in _STRUCTURED_GEOGRAPHY_GENERIC_METRIC_TOKENS
        ):
            markers.append(token)
    return tuple(dict.fromkeys(markers))


def _text_mentions_structured_geography_metric(
    text: str,
    metric_key: object,
) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text, re.IGNORECASE)
        for marker in _structured_geography_metric_markers(metric_key)
    )


def _text_mentions_any_structured_geography_metric(
    text: str,
    metric_items: tuple[tuple[str, object], ...],
) -> bool:
    return any(
        _text_mentions_structured_geography_metric(text, metric_key)
        for metric_key, _ in metric_items
    )


def _structured_geography_numeric_values(value: object) -> tuple[float, ...]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        candidates = [float(value)]
    else:
        candidates = _numeric_candidates(str(value or ""))

    values: set[float] = set()
    for candidate in candidates:
        values.update({candidate, round(candidate, 1), round(candidate, 2)})
        if abs(candidate) < 1:
            percent_candidate = candidate * 100
            values.update(
                {
                    percent_candidate,
                    round(percent_candidate, 1),
                    round(percent_candidate, 2),
                }
            )
    return tuple(values)


def _line_contains_structured_geography_value(line: str, value: object) -> bool:
    expected_values = _structured_geography_numeric_values(value)
    if not expected_values:
        return False
    return any(
        abs(candidate - expected) <= 1e-9
        for candidate in _numeric_candidates(line)
        for expected in expected_values
    )


def _line_contains_structured_geography_name(line: str, name: str) -> bool:
    return bool(
        re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", line, re.IGNORECASE)
    )


def _structured_geography_metric_value_is_unique(
    metric_items: tuple[tuple[str, object], ...],
    metric_index: int,
    value: object,
) -> bool:
    expected_values = set(_structured_geography_numeric_values(value))
    if not expected_values:
        return False
    for other_index, (_, other_value) in enumerate(metric_items):
        if other_index == metric_index:
            continue
        if expected_values & set(_structured_geography_numeric_values(other_value)):
            return False
    return True


def _structured_geography_row_candidate_segments(
    line: str,
    name: str,
) -> tuple[str, ...]:
    segments = [
        segment.strip(" ,:-")
        for segment in _STRUCTURED_GEOGRAPHY_ROW_CLAUSE_BOUNDARY_RE.split(line)
        if segment.strip(" ,:-")
    ]
    matching_segments = tuple(
        segment
        for segment in segments
        if _line_contains_structured_geography_name(segment, name)
    )
    if matching_segments:
        return matching_segments
    return (line,) if _line_contains_structured_geography_name(line, name) else ()


def _line_matches_structured_geography_row(
    line: str,
    row: dict[str, object],
    *,
    context_line: str | None = None,
) -> bool:
    name = _structured_geography_row_name(row)
    if not name or not _line_contains_structured_geography_name(line, name):
        return False
    metric_items = structured_geography_row_metric_items(row)
    if not metric_items:
        return False
    context = context_line or line
    for segment in _structured_geography_row_candidate_segments(line, name):
        if not _line_has_group_place_evidence(segment):
            continue
        segment_mentions_metric = _text_mentions_any_structured_geography_metric(
            segment,
            metric_items,
        )
        context_mentions_metric = _text_mentions_any_structured_geography_metric(
            context,
            metric_items,
        )
        for metric_index, (metric_key, value) in enumerate(metric_items):
            if not _line_contains_structured_geography_value(segment, value):
                continue
            if _text_mentions_structured_geography_metric(segment, metric_key):
                return True
            if (
                not segment_mentions_metric
                and context_mentions_metric
                and _text_mentions_structured_geography_metric(context, metric_key)
                and _structured_geography_metric_value_is_unique(
                    metric_items,
                    metric_index,
                    value,
                )
            ):
                return True
    return False


def _iter_structured_geography_evidence_rows(
    summary: dict[str, object],
    evidence_keys: tuple[str, ...] | None,
) -> Iterable[dict[str, object]]:
    enabled_keys = (
        set(evidence_keys)
        if evidence_keys is not None
        else {"state_comparison", "regional_top10", "consumer_stress.regional_context"}
    )
    table_payloads: list[object] = []
    if "state_comparison" in enabled_keys:
        table_payloads.append(summary.get("state_comparison"))
    if "regional_top10" in enabled_keys:
        table_payloads.append(summary.get("regional_top10"))
    if "consumer_stress.regional_context" in enabled_keys:
        consumer = summary.get("consumer_stress")
        if isinstance(consumer, dict):
            table_payloads.append(consumer.get("regional_context"))

    for payload in table_payloads:
        yield from _iter_structured_geography_rows(payload)


def _line_matches_structured_geography_evidence(
    line: str,
    summary: dict[str, object],
    evidence_keys: tuple[str, ...] | None,
    *,
    context_line: str | None = None,
) -> bool:
    return any(
        _line_matches_structured_geography_row(
            line,
            row,
            context_line=context_line,
        )
        for row in _iter_structured_geography_evidence_rows(summary, evidence_keys)
    )


def _report_uses_requested_geography_evidence(
    query: object,
    summary: dict[str, object],
    lines: list[str],
    evidence_keys: tuple[str, ...],
    requested_dimensions: tuple[str, ...],
) -> bool:
    minimum_entity_count = requested_geography_minimum_entity_count(
        query,
        requested_dimensions,
    )
    used_entities = _report_used_requested_geography_entity_keys(
        summary,
        lines,
        evidence_keys,
        requested_dimensions,
        minimum_entity_count,
    )
    required_entities = requested_geography_entity_keys(query)
    if required_entities and not set(required_entities).issubset(used_entities):
        return False
    return len(used_entities) >= minimum_entity_count


def _normalized_group_place_metadata_key(value: object) -> str:
    return re.sub(r"[-\s]+", "_", str(value).strip().lower())


def _group_place_metadata_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _normalized_group_place_metadata_text(label: str, value: object) -> str:
    text = f"{label} {_group_place_metadata_text(value)}"
    return re.sub(r"[_-]+", " ", text)


def _group_place_metadata_label_parts(label: str) -> set[str]:
    return {
        _normalized_group_place_metadata_key(part)
        for part in re.split(r"[.\[\]\s]+", label)
        if part
    }


def _group_place_metadata_mapping_is_record(value: dict[Any, Any]) -> bool:
    normalized_keys = {
        _normalized_group_place_metadata_key(key)
        for key in value
        if str(key).strip()
    }
    return bool(normalized_keys & _GROUP_PLACE_METADATA_RECORD_KEYS)


def _group_place_metadata_value_is_nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = _normalized_group_place_metadata_key(value)
        return bool(normalized) and normalized not in {
            "available",
            "covered",
            "false",
            "none",
            "null",
            "ok",
            "success",
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_group_place_metadata_value_is_nonempty(item) for item in value)
    if isinstance(value, dict):
        return any(
            _group_place_metadata_value_is_nonempty(child)
            for child in value.values()
        )
    return True


def _group_place_unavailable_key_value_signal(key: str, value: object) -> bool:
    normalized_value = _normalized_group_place_metadata_key(value)
    if key == "status":
        return normalized_value in _GROUP_PLACE_UNAVAILABLE_STATUS_VALUES
    if isinstance(value, bool):
        unavailable = not value
    else:
        unavailable = normalized_value in {
            "false",
            "no",
            "error",
            "failed",
            "failure",
            "missing",
            "not_available",
            "not_covered",
            "unavailable",
        }
    if key in {"available", "availability"}:
        return unavailable
    if key in {"level", "severity"}:
        return normalized_value in _GROUP_PLACE_UNAVAILABLE_ERROR_LEVEL_VALUES
    if key in {"error", "errors", "fetch_error", "fetch_errors"}:
        return _group_place_metadata_value_is_nonempty(value)
    return False


def _group_place_metadata_record_has_unavailable_signal(
    label: str,
    value: object,
) -> bool:
    if isinstance(value, dict):
        for key, child_value in value.items():
            if _group_place_unavailable_key_value_signal(
                _normalized_group_place_metadata_key(key),
                child_value,
            ):
                return True
    label_parts = _group_place_metadata_label_parts(label)
    if any(
        _group_place_unavailable_key_value_signal(key, value)
        for key in label_parts
    ):
        return True
    if "limitations" in label_parts:
        return bool(
            _GROUP_PLACE_UNAVAILABLE_RE.search(
                _normalized_group_place_metadata_text(label, value),
            )
        )
    return False


def _iter_group_place_metadata_records(
    label: str,
    value: object,
) -> Iterable[tuple[str, object, str]]:
    if value is None:
        return
    if isinstance(value, dict):
        if _group_place_metadata_mapping_is_record(value):
            yield label, value, _normalized_group_place_metadata_text(label, value)
        for key, child_value in value.items():
            child_label = f"{label}.{key}"
            if isinstance(child_value, (dict, list)):
                yield from _iter_group_place_metadata_records(
                    child_label,
                    child_value,
                )
            else:
                yield (
                    child_label,
                    child_value,
                    _normalized_group_place_metadata_text(child_label, child_value),
                )
        return
    if isinstance(value, list):
        for index, child_value in enumerate(value):
            child_label = f"{label}[{index}]"
            if isinstance(child_value, (dict, list)):
                yield from _iter_group_place_metadata_records(
                    child_label,
                    child_value,
                )
            else:
                yield (
                    child_label,
                    child_value,
                    _normalized_group_place_metadata_text(child_label, child_value),
                )
        return
    yield label, value, _normalized_group_place_metadata_text(label, value)


def _metadata_text_mentions_group_place_source_or_dimension(text: str) -> bool:
    return bool(
        _line_mentions_group_place_dimension(text)
        or _GROUP_PLACE_METADATA_SOURCE_OR_DIMENSION_RE.search(text)
    )


def _group_place_unavailable_signature(text: str) -> tuple[set[str], set[str]]:
    normalized = re.sub(r"[_-]+", " ", text.lower())
    sources = {
        source
        for source, pattern in _GROUP_PLACE_UNAVAILABLE_SOURCE_PATTERNS
        if pattern.search(normalized)
    }
    dimension_text = _strip_non_specific_group_place_terms(
        _strip_group_place_provider_names(normalized),
    )
    dimensions = {
        dimension
        for dimension, pattern in _GROUP_PLACE_UNAVAILABLE_DIMENSION_PATTERNS
        if pattern.search(dimension_text)
    }
    if _US_STATE_PLACE_RE.search(dimension_text):
        dimensions.update({"place", "state"})
    if dimensions & {"state", "county", "metro", "city", "regional"}:
        dimensions.add("place")
    return sources, dimensions


def _group_place_unavailable_dimensions_match(
    caveat_dimensions: set[str],
    metadata_dimensions: set[str],
) -> bool:
    if not caveat_dimensions:
        return True
    if not metadata_dimensions:
        return False
    caveat_specific_dimensions = caveat_dimensions - {"place"}
    if caveat_specific_dimensions:
        if (
            "group" in caveat_specific_dimensions
            and metadata_dimensions & _GROUP_PLACE_UNAVAILABLE_GROUP_DIMENSIONS
        ):
            return True
        return bool(
            caveat_specific_dimensions & (metadata_dimensions - {"place"})
        )
    if "place" in caveat_dimensions:
        return bool(
            metadata_dimensions & _GROUP_PLACE_UNAVAILABLE_PLACE_DIMENSIONS
        )
    return bool(caveat_dimensions & metadata_dimensions)


def _group_place_unavailable_metadata_matches_caveat(
    caveat_line: str,
    metadata_text: str,
) -> bool:
    caveat_sources, caveat_dimensions = _group_place_unavailable_signature(
        caveat_line,
    )
    metadata_sources, metadata_dimensions = _group_place_unavailable_signature(
        metadata_text,
    )
    if not (caveat_sources or caveat_dimensions):
        return False
    if not (metadata_sources or metadata_dimensions):
        return False
    if (
        caveat_sources
        and metadata_sources
        and not caveat_sources & metadata_sources
    ):
        return False
    if not _group_place_unavailable_dimensions_match(
        caveat_dimensions,
        metadata_dimensions,
    ):
        return False
    return bool(
        (not caveat_sources or caveat_sources & metadata_sources)
        and (not caveat_dimensions or metadata_dimensions)
    )


def _summary_has_artifact_backed_group_place_unavailable(
    summary: dict[str, object],
    caveat_line: str,
) -> bool:
    candidates: list[tuple[str, object]] = [
        ("source_coverage", summary.get("source_coverage")),
        ("diagnostics", summary.get("diagnostics")),
        ("limitations", summary.get("limitations")),
    ]
    metadata = summary.get("metadata")
    if isinstance(metadata, dict):
        candidates.append(("metadata.fetch_errors", metadata.get("fetch_errors")))

    for label, value in candidates:
        for record_label, record_value, text in _iter_group_place_metadata_records(
            label,
            value,
        ):
            if not text.strip():
                continue
            if not _metadata_text_mentions_group_place_source_or_dimension(text):
                continue
            if not _group_place_metadata_record_has_unavailable_signal(
                record_label,
                record_value,
            ):
                continue
            if _group_place_unavailable_metadata_matches_caveat(caveat_line, text):
                return True
    return False


def _line_has_group_place_unavailable_caveat(line: str) -> bool:
    if _GROUP_PLACE_SCOPE_DRIFT_RE.search(line):
        return False
    if not _GROUP_PLACE_UNAVAILABLE_RE.search(line):
        return False
    if not _GROUP_PLACE_AVAILABILITY_CONTEXT_RE.search(line):
        return False
    if _GROUP_PLACE_SELF_MISSING_RE.search(line):
        return False
    return bool(
        _line_mentions_group_place_dimension(line)
        or _GROUP_PLACE_EVIDENCE_RE.search(line)
    )


def _strip_markdown_heading_marker(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip()
    return stripped


def _group_place_clause_is_non_assertive_limitation(clause: str) -> bool:
    return bool(
        _line_has_group_place_unavailable_caveat(clause)
        or _GROUP_PLACE_EVIDENCE_DISCLAIMER_RE.search(clause)
        or _GROUP_PLACE_NON_ASSERTIVE_LIMITATION_RE.search(clause)
        or _GROUP_PLACE_SCOPE_DRIFT_RE.search(clause)
        or _GROUP_PLACE_SELF_MISSING_RE.search(clause)
    )


def _split_group_place_claim_clauses(line: str) -> list[str]:
    stripped = _strip_markdown_heading_marker(line).strip(" |")
    if not stripped:
        return []
    clauses: list[str] = []
    for clause in _GROUP_PLACE_CLAUSE_BOUNDARY_RE.split(stripped):
        clause = clause.strip(" ,:-")
        if not clause:
            continue
        comma_parts = [
            part.strip(" ,:-")
            for part in clause.split(",")
            if part.strip(" ,:-")
        ]
        if (
            len(comma_parts) > 1
            and any(
                _group_place_clause_is_non_assertive_limitation(part)
                for part in comma_parts
            )
        ):
            clauses.extend(comma_parts)
            continue
        if _group_place_clause_is_non_assertive_limitation(clause):
            making_parts = [
                part.strip(" ,:-")
                for part in re.split(r"\s+\bmaking\b\s+", clause)
                if part.strip(" ,:-")
            ]
            if len(making_parts) > 1:
                clauses.extend(making_parts)
                continue
            and_match = re.search(r"\s+\band\b\s+", clause)
            if and_match:
                left = clause[: and_match.start()].strip(" ,:-")
                right = clause[and_match.end() :].strip(" ,:-")
                if (
                    left
                    and right
                    and _group_place_clause_is_non_assertive_limitation(left)
                ):
                    clauses.extend([left, right])
                    continue
        clauses.append(clause)
    return clauses


def _unsupported_specific_group_place_claim_lines(
    lines: list[str],
    summary: dict[str, object],
    evidence_keys: tuple[str, ...] | None = None,
) -> list[str]:
    unsupported: list[str] = []
    facts = _numeric_facts_from_summary(summary)
    for line in lines:
        for clause in _split_group_place_claim_clauses(line):
            if _group_place_clause_is_non_assertive_limitation(clause):
                continue
            if not _line_mentions_specific_group_place_dimension(clause):
                continue
            if any(
                _line_matches_group_place_numeric_fact(clause, fact)
                for fact in facts
            ):
                continue
            if _line_matches_structured_geography_evidence(
                clause,
                summary,
                evidence_keys,
                context_line=line,
            ):
                continue
            unsupported.append(clause)
            break
    return unsupported


def _requested_group_place_coverage_blocker(
    report_data: dict[str, object],
    summary: dict[str, object],
) -> str | None:
    if not _query_requests_group_place_coverage(report_data.get("query")):
        return None

    geography_coverage = assess_requested_geography_coverage(
        report_data.get("query"),
        summary,
    )
    lines = _report_review_lines(report_data)
    caveat_lines = [
        line for line in lines if _line_has_group_place_unavailable_caveat(line)
    ]
    if geography_coverage.required:
        if geography_coverage.status == "missing":
            if caveat_lines:
                unsupported_lines = _unsupported_specific_group_place_claim_lines(
                    lines,
                    summary,
                    geography_coverage.evidence_keys,
                )
                if unsupported_lines:
                    examples = "; ".join(unsupported_lines[:3])
                    return (
                        "Report pairs an unavailable-data caveat with unsupported "
                        "specific group/place claims. Remove or qualify the unsupported "
                        f"claims before approval. Examples: {examples}"
                    )
            return geography_coverage.blocker

        if geography_coverage.status == "unavailable":
            if not caveat_lines:
                return (
                    "User query asks for state, regional, or place-specific "
                    "coverage and execution_summary.json preserves structured "
                    "unavailable-source evidence, but the report does not state "
                    "the matching regional-data caveat. Add the artifact-backed "
                    "unavailable-data caveat or regenerate with usable regional "
                    "evidence."
                )
            unsupported_lines = _unsupported_specific_group_place_claim_lines(
                lines,
                summary,
                geography_coverage.evidence_keys,
            )
            if unsupported_lines:
                examples = "; ".join(unsupported_lines[:3])
                return (
                    "Report pairs an unavailable-data caveat with unsupported "
                    "specific group/place claims. Remove or qualify the unsupported "
                    f"claims before approval. Examples: {examples}"
                )
            return None

        if geography_coverage.status in {"covered", "partial"}:
            if not _report_uses_requested_geography_evidence(
                report_data.get("query"),
                summary,
                lines,
                geography_coverage.evidence_keys,
                geography_coverage.requested_dimensions,
            ):
                evidence = ", ".join(geography_coverage.evidence_keys[:4])
                return (
                    "User query asks for state, regional, or place-specific "
                    "coverage and execution_summary.json has structured geography "
                    f"evidence ({evidence}), but the report does not use enough "
                    "artifact-backed regional/state structured geography evidence. "
                    "Regenerate the report from the requested geography evidence "
                    "instead of delivering a national-only substitute."
                )
            if not caveat_lines:
                if any(
                    (
                        _GROUP_PLACE_SELF_MISSING_RE.search(line)
                        or _GROUP_PLACE_SCOPE_DRIFT_RE.search(line)
                    )
                    and _line_mentions_group_place_dimension(line)
                    for line in lines
                ):
                    pass
                else:
                    return None
            if geography_coverage.unavailable_sources:
                unsupported_lines = _unsupported_specific_group_place_claim_lines(
                    lines,
                    summary,
                    geography_coverage.evidence_keys,
                )
                if unsupported_lines:
                    examples = "; ".join(unsupported_lines[:3])
                    return (
                        "Report pairs an unavailable-data caveat with unsupported "
                        "specific group/place claims. Remove or qualify the unsupported "
                        f"claims before approval. Examples: {examples}"
                    )
                return None
            if caveat_lines:
                unsupported_lines = _unsupported_specific_group_place_claim_lines(
                    lines,
                    summary,
                    geography_coverage.evidence_keys,
                )
                if unsupported_lines:
                    examples = "; ".join(unsupported_lines[:3])
                    return (
                        "Report pairs an unavailable-data caveat with unsupported "
                        "specific group/place claims. Remove or qualify the unsupported "
                        f"claims before approval. Examples: {examples}"
                    )
                return (
                    "Report pairs structured geography evidence with an "
                    "unavailable-data caveat, but execution_summary.json does not "
                    "preserve matching structured unavailable-source evidence in "
                    "source_coverage or metadata.fetch_errors. Preserve the matching "
                    "source failure metadata or remove the unavailable-data caveat."
                )
            return None
        else:
            return None

    if caveat_lines:
        unsupported_lines = _unsupported_specific_group_place_claim_lines(
            lines,
            summary,
        )
        if unsupported_lines:
            examples = "; ".join(unsupported_lines[:3])
            return (
                "Report pairs an unavailable-data caveat with unsupported "
                "specific group/place claims. Remove or qualify the unsupported "
                f"claims before approval. Examples: {examples}"
            )
        unbacked_caveat_lines = [
            line
            for line in caveat_lines
            if not _summary_has_artifact_backed_group_place_unavailable(
                summary,
                line,
            )
        ]
        if not unbacked_caveat_lines:
            return None
        return (
            "User query asks for stress hidden in specific groups or places, "
            "but the report relies on an unavailable-data caveat that is not "
            "backed by matching execution_summary.json source_coverage, "
            "diagnostics, limitations, or metadata.fetch_errors. Preserve the "
            "matching source failure metadata or regenerate with "
            "artifact-backed group/place evidence."
        )

    if _report_has_artifact_backed_group_place_evidence(summary, lines):
        return None

    return (
        "User query asks for stress hidden in specific groups or places, but "
        "the report includes neither artifact-backed group/place evidence nor "
        "an artifact-backed unavailable-data caveat. Regenerate the report "
        "with cohort, regional, state, metro, county, or other place-specific "
        "evidence from execution_summary.json numeric_facts, or explicitly "
        "state that the requested group/place data was unavailable using "
        "preserved source_coverage, diagnostics, limitations, or "
        "metadata.fetch_errors."
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


def _real_wage_direction_clauses(line: str) -> list[str]:
    subject_match = _REAL_WAGE_SUBJECT_RE.search(line)
    subject = subject_match.group(0) if subject_match else ""
    clauses: list[str] = []
    for raw_clause in _REAL_WAGE_CLAUSE_BOUNDARY_RE.split(line):
        clause = raw_clause.strip(" ,")
        if not clause:
            continue
        if subject and not _REAL_WAGE_SUBJECT_RE.search(clause):
            clause = f"{subject} {clause}"
        clauses.append(clause)
    return clauses


def _line_matches_direction_claim(
    line: str,
    pattern: re.Pattern[str],
    *,
    ignore_alternate_real_wage_period: bool = False,
) -> bool:
    if not pattern.search(line):
        return False
    if _DIRECTION_NEGATION_RE.search(line):
        return False
    if (
        ignore_alternate_real_wage_period
        and _REAL_WAGE_ALTERNATE_PERIOD_RE.search(line)
    ):
        claim_clauses = [
            clause
            for clause in _real_wage_direction_clauses(line)
            if pattern.search(clause) and not _DIRECTION_NEGATION_RE.search(clause)
        ]
        if claim_clauses:
            return any(
                "2019" in clause
                or not _REAL_WAGE_ALTERNATE_PERIOD_RE.search(clause)
                for clause in claim_clauses
            )
        if "2019" not in line:
            return False
    return True


def _statistical_summary_direction_blockers(
    summary: dict[str, object],
    report_data: dict[str, object],
) -> list[str]:
    stats = summary.get("statistical_summary")
    if not isinstance(stats, dict):
        return []

    lines = _report_review_lines(report_data)
    blockers: list[str] = []

    real_wage_change = _finite_number(
        stats.get("real_wage_change_pct_2019_to_latest")
    )
    if real_wage_change is not None:
        if real_wage_change > 0:
            claim_lines = [
                line
                for line in lines
                if _line_matches_direction_claim(
                    line,
                    _REAL_WAGE_NEGATIVE_CLAIM_RE,
                    ignore_alternate_real_wage_period=True,
                )
            ]
            if claim_lines:
                blockers.append(
                    "Report reverses execution_summary.json statistical_summary "
                    "direction for real_wage_change_pct_2019_to_latest "
                    f"({real_wage_change:+.2f}): it describes real-wage "
                    "erosion or decline. Regenerate the affected wage prose "
                    "from statistical_summary, or qualify the claim with "
                    "separate subgroup/period evidence."
                )
        elif real_wage_change < 0:
            claim_lines = [
                line
                for line in lines
                if _line_matches_direction_claim(
                    line,
                    _REAL_WAGE_POSITIVE_CLAIM_RE,
                    ignore_alternate_real_wage_period=True,
                )
            ]
            if claim_lines:
                blockers.append(
                    "Report reverses execution_summary.json statistical_summary "
                    "direction for real_wage_change_pct_2019_to_latest "
                    f"({real_wage_change:+.2f}): it describes real-wage "
                    "growth. Regenerate the affected wage prose from "
                    "statistical_summary, or qualify the claim with separate "
                    "subgroup/period evidence."
                )

    dpi_pce_gap = _finite_number(stats.get("dpi_pce_gap_latest_billions"))
    if dpi_pce_gap is not None:
        if dpi_pce_gap > 0:
            claim_lines = [
                line
                for line in lines
                if _line_matches_direction_claim(line, _PCE_AHEAD_OF_DPI_CLAIM_RE)
            ]
            if claim_lines:
                blockers.append(
                    "Report reverses execution_summary.json statistical_summary "
                    "direction for dpi_pce_gap_latest_billions "
                    f"({dpi_pce_gap:+.1f}): it says PCE, consumption, or "
                    "spending is ahead of disposable personal income even "
                    "though the latest DPI-PCE gap is positive. Regenerate "
                    "the affected income/spending prose from statistical_summary."
                )
        elif dpi_pce_gap < 0:
            claim_lines = [
                line
                for line in lines
                if _line_matches_direction_claim(line, _DPI_AHEAD_OF_PCE_CLAIM_RE)
            ]
            if claim_lines:
                blockers.append(
                    "Report reverses execution_summary.json statistical_summary "
                    "direction for dpi_pce_gap_latest_billions "
                    f"({dpi_pce_gap:+.1f}): it says disposable personal income "
                    "is ahead of PCE, consumption, or spending even though the "
                    "latest DPI-PCE gap is negative. Regenerate the affected "
                    "income/spending prose from statistical_summary."
                )

    return blockers


def _statistical_summary_assessment_blocker(
    summary: dict[str, object],
) -> str | None:
    stats = summary.get("statistical_summary")
    if not isinstance(stats, dict):
        return None
    assessment = stats.get("assessment")
    if not isinstance(assessment, str) or not assessment.strip():
        return None
    return (
        "execution_summary.json includes freeform statistical_summary.assessment "
        "prose. Regenerate quant artifacts with report-facing current claims as "
        "typed numeric_facts and keep statistical_summary to computed values."
    )


def _current_scalar_field_markers(field: str) -> tuple[str, ...]:
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", str(field).lower())
        if token and token not in {"current", "latest", "last", "value", "rate", "pct"}
    ]
    markers: list[str] = []
    for token in tokens:
        markers.extend(_SOURCE_TOKEN_MARKERS.get(token, (token,)))
    markers.extend(_current_scalar_source_markers(*tokens))
    token_set = set(tokens)
    for required_tokens, phrase_markers in _UNAVAILABLE_CURRENT_FIELD_PHRASE_MARKERS:
        if set(required_tokens) <= token_set:
            markers.extend(phrase_markers)
    filtered_markers = []
    for marker in markers:
        marker_tokens = _marker_tokens(marker)
        if not marker_tokens:
            continue
        if (
            len(marker_tokens) > 1
            or marker_tokens[0] in _UNAVAILABLE_CURRENT_SINGLE_MARKER_TOKENS
        ):
            filtered_markers.append(marker)
    return tuple(
        dict.fromkeys(marker for marker in filtered_markers if len(marker) > 2)
    )


def _source_coverage_current_markers(marker_seed: str) -> tuple[str, ...]:
    return _current_scalar_source_markers(marker_seed)


def _unavailable_source_coverage_targets(
    summary: dict[str, object],
) -> list[tuple[str, tuple[str, ...]]]:
    coverage = summary.get("source_coverage")
    if not isinstance(coverage, dict):
        return []

    targets: list[tuple[str, tuple[str, ...]]] = []

    def walk(
        value: object,
        path: tuple[str, ...],
        depth: int = 0,
    ) -> None:
        if depth > 4 or not isinstance(value, dict):
            return
        status = str(
            value.get("status") or value.get("availability") or ""
        ).strip().lower()
        if status in _UNAVAILABLE_SOURCE_COVERAGE_STATUSES:
            marker_seed = " ".join(
                str(part)
                for part in (
                    *path,
                    value.get("source_key"),
                    value.get("series_id"),
                    value.get("metric"),
                    value.get("field"),
                    value.get("label"),
                    value.get("name"),
                )
                if part
            )
            markers = _source_coverage_current_markers(marker_seed)
            if markers:
                label = "source_coverage." + ".".join(path or ("<root>",))
                targets.append((label, markers))
        for child_key, child_value in value.items():
            if isinstance(child_value, dict):
                walk(child_value, (*path, str(child_key)), depth + 1)

    walk(coverage, ())
    return targets


def _unavailable_current_scalar_claim_blocker(
    summary: dict[str, object],
    report_data: dict[str, object],
) -> str | None:
    targets: list[tuple[str, tuple[str, ...]]] = []
    for container, fields in current_scalar_fact_slots(summary).items():
        for field, value in fields.items():
            if value is not None:
                continue
            markers = _current_scalar_field_markers(field)
            if markers:
                targets.append((f"{container}.{field}", markers))
    targets.extend(_unavailable_source_coverage_targets(summary))
    if not targets:
        return None
    lines = _report_review_lines(report_data)
    unsupported: list[str] = []
    for label, markers in targets:
        for line in lines:
            clauses = _UNAVAILABLE_CURRENT_CLAUSE_BOUNDARY_RE.split(line)
            for clause in clauses:
                if not any(_text_contains_marker(clause, marker) for marker in markers):
                    continue
                if _UNAVAILABLE_CURRENT_LIMITATION_RE.search(clause):
                    continue
                if not _UNAVAILABLE_CURRENT_AFFIRMATIVE_RE.search(clause):
                    continue
                unsupported.append(label)
                break
            if unsupported and unsupported[-1] == label:
                break
    if not unsupported:
        return None
    return (
        "Report makes affirmative claims about unavailable current/latest "
        "execution_summary scalar evidence for "
        + ", ".join(unsupported[:8])
        + ". State the source coverage limitation or remove the unsupported "
        "current-value, direction, or comparison claim."
    )


def _line_claims_openings_workers_comparison(line: str) -> bool:
    for clause in _OPENINGS_WORKERS_CLAUSE_BOUNDARY_RE.split(line):
        clause = clause.strip()
        if not clause or _OPENINGS_WORKERS_LIMITATION_RE.search(clause):
            continue
        if not _OPENINGS_WORKERS_OPENINGS_RE.search(clause):
            continue
        if not _OPENINGS_WORKERS_WORKER_RE.search(clause):
            continue
        if _OPENINGS_WORKERS_COMPARISON_RE.search(clause):
            return True
    return False


def _openings_workers_fact_tokens(fact: dict[str, object]) -> set[str]:
    text = " ".join(
        str(fact.get(key) or "").lower()
        for key in (
            "id",
            "metric",
            "label",
            "source_key",
            "operation",
            "semantic_role",
            "transform_basis",
        )
    )
    return {
        token
        for token in re.split(r"[^a-z0-9]+", text)
        if token
    }


def _has_openings_workers_comparison_fact(summary: dict[str, object]) -> bool:
    for fact in _numeric_facts_from_summary(summary):
        tokens = _openings_workers_fact_tokens(fact)
        unit = str(fact.get("unit") or "").strip().lower()
        has_openings = bool(tokens & _OPENINGS_WORKERS_FACT_OPENINGS_TOKENS)
        has_workers = (
            bool(tokens & _OPENINGS_WORKERS_FACT_WORKER_TOKENS)
            or {"labor", "supply"} <= tokens
            or {"worker", "supply"} <= tokens
        )
        has_comparison = bool(
            tokens & _OPENINGS_WORKERS_FACT_COMPARISON_TOKENS
        ) or unit in _OPENINGS_WORKERS_FACT_COMPARISON_UNITS
        if has_openings and has_workers and has_comparison:
            return True
    return False


def _unsupported_openings_workers_comparison_blocker(
    summary: dict[str, object],
    report_data: dict[str, object],
) -> str | None:
    if _has_openings_workers_comparison_fact(summary):
        return None
    if not any(
        _line_claims_openings_workers_comparison(line)
        for line in _report_review_lines(report_data)
    ):
        return None
    return (
        "Report makes a job-openings-vs-available-workers comparison without "
        "an execution_summary.json numeric_fact that combines openings with "
        "unemployed or available workers as a ratio/comparison. Add a typed "
        "comparison fact or remove the openings-vs-workers leverage claim."
    )


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
    assessment_blocker = _statistical_summary_assessment_blocker(summary)
    if assessment_blocker:
        blockers.append(assessment_blocker)
    unavailable_current_claim = _unavailable_current_scalar_claim_blocker(
        summary,
        report_data,
    )
    if unavailable_current_claim:
        blockers.append(unavailable_current_claim)
    unsupported_openings_workers = _unsupported_openings_workers_comparison_blocker(
        summary,
        report_data,
    )
    if unsupported_openings_workers:
        blockers.append(unsupported_openings_workers)
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
    unsupported_valuation = _unsupported_market_valuation_claim_blocker(summary, report_data)
    if unsupported_valuation:
        blockers.append(unsupported_valuation)
    unsupported_share_claim = _unsupported_split_affected_share_claim_blocker(
        summary,
        report_data,
    )
    if unsupported_share_claim:
        blockers.append(unsupported_share_claim)
    blockers.extend(_source_unit_fidelity_blockers(summary, markdown, report_data))
    blockers.extend(_state_comparison_fidelity_blockers(summary, markdown))
    requested_coverage = _requested_group_place_coverage_blocker(
        report_data,
        summary,
    )
    if requested_coverage:
        blockers.append(requested_coverage)
    blockers.extend(_statistical_summary_direction_blockers(summary, report_data))
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
    evidence_bundle_blocker = _evidence_bundle_approval_blocker(Path(report_path))
    if evidence_bundle_blocker:
        blockers.append(evidence_bundle_blocker)
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
    if _evidence_bundle_approval_blocker(Path(report_path)):
        return {
            "failure_category": "evidence_bundle_invalid",
            "required_upstream": "quant-developer",
        }
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
    if _unsupported_market_valuation_claim_blocker(summary, data):
        return {
            "failure_category": "unsupported_valuation_claim",
            "required_upstream": "technical-writer",
        }
    if _unsupported_split_affected_share_claim_blocker(summary, data):
        return {
            "failure_category": "unsupported_share_count_claim",
            "required_upstream": "technical-writer",
        }
    requested_coverage = _requested_group_place_coverage_blocker(data, summary)
    if requested_coverage:
        geography_coverage = assess_requested_geography_coverage(
            data.get("query"),
            summary,
        )
        return {
            "failure_category": "requested_coverage_missing",
            "required_upstream": (
                "quant-developer"
                if geography_coverage.required and geography_coverage.status == "missing"
                else "technical-writer"
            ),
        }
    if _statistical_summary_assessment_blocker(summary):
        return {
            "failure_category": "execution_summary_contract",
            "required_upstream": "quantitative-developer",
        }
    if _unavailable_current_scalar_claim_blocker(summary, data):
        return {
            "failure_category": "unsupported_current_scalar_claim",
            "required_upstream": "technical-writer",
        }
    if _unsupported_openings_workers_comparison_blocker(summary, data):
        return {
            "failure_category": "unsupported_comparison_claim",
            "required_upstream": "technical-writer",
        }
    if _statistical_summary_direction_blockers(summary, data):
        return {
            "failure_category": "statistical_summary_mismatch",
            "required_upstream": "technical-writer",
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
