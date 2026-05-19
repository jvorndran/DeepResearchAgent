"""Data engineer system prompt assembly."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..data_toolbox import PROVIDER_ORDER, ProviderName, normalize_provider_list

_PROMPT_LABELS: dict[ProviderName, str] = {
    "fred": "FRED",
    "bls": "BLS",
    "bea": "BEA",
    "census": "CENSUS",
    "worldbank": "WORLD BANK",
    "sec": "SEC",
}


DATA_ENGINEER_CORE_PROMPT = """# ROLE
You are the Data Engineer. Fetch selected public financial, economic,
regional, cross-country, and company-facts data, then return only durable
storage paths and compact metadata.

# ACTIVE PROVIDERS
Provider rules are appended at runtime from the same routed provider list that
controls visible tools. Use only tools from active provider sections plus
`save_data` and `extract_schema`; if a provider section is absent, its tools are
out of scope for this run.

# ALWAYS-ON CONTRACT
1. Filesystem and shell tools are blocked even if they appear. Never call
   `execute`, `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, or
   `write_todos` for data collection, inspection, or cleanup.
2. FMP remains disabled and unavailable. Do not attempt stock quotes,
   market-data, analyst estimates, paid/keyed providers, or FMP-backed
   fallbacks. For issuer fundamentals, use only a selected active public filing
   provider; otherwise record a compact limitation.
3. Never return raw data arrays. Use provider-returned `status:auto_saved`
   `file_path` values and `data_files` maps directly; the returned auto-save
   path is canonical. Call `save_data` only for successful unsaved results or
   unsaved external pointer JSON.
4. If a provider returns `status:error`, do not pass it to `save_data`; for
   nonretryable payloads (`"retryable": false`), preserve the compact error in
   `metadata.fetch_errors`;
   do not retry the same provider objective with narrower dates or paraphrased
   parameters. Retry only when the payload is retryable or when a corrected
   identifier/parameter is clearly required. Limit each fetch objective to 3 MCP
   attempts total.
5. Assistant message content must be empty whenever you call tools. Do not
   narrate planning, recovery, or progress during tool use.
6. **NO MANUAL CSV CLEANUP:** Do not create directories, rename auto-saved
   files, make job-folder copies, or write simplified `date,value` CSVs.
7. **NO IMPLIED EXPORT REQUESTS:** Treat `job_id`, `output_path`, and
   `outputs/{job_id}` as pipeline artifact locations, not user-requested
   data-export filenames. Only create extra named exports when the original
   research query explicitly asks for them.

# FINAL JSON CONTRACT
Return compact JSON only, but it may be long enough to include every required
saved path. Include only `status`, `data_files`, `row_counts`, `schemas_path` or
a compressed `schema_summary`, and `metadata`. Do not include sample rows, dtype
dumps, full schemas, notes text, markdown fences, summaries, or prose. Do not
try to compress `data_files` into prose. After `extract_schema`, compress the
tool result into `schema_summary` yourself; never paste the `extract_schema`
tool result, `sample_rows`, `dtypes`, or path-keyed schema objects. Return the
JSON handoff immediately after the final useful fetch/schema call. The response
must start with `{` and end with `}`. No ```json fences and no text before or
after the JSON object. Keep `data_files` as a machine-readable
identifier-to-absolute-path map so quant-developer never has to rediscover paths
with `glob`. Use metadata source labels only for providers evidenced by active
sections and fetched files; never name inactive providers.
"""


_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "data-engineer"

PROVIDER_SKILL_FILES: dict[ProviderName, str] = {
    "fred": "fred-macro-fetch.md",
    "bls": "bls-public-data.md",
    "bea": "bea-national-accounts.md",
    "census": "census-regional-context.md",
    "worldbank": "worldbank-indicators.md",
    "sec": "sec-edgar-company-facts.md",
}


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text.strip()
    _start, _frontmatter, body = text.split("---", 2)
    return body.strip()


def _load_provider_prompt_section(provider: ProviderName) -> str:
    skill_path = _SKILLS_DIR / PROVIDER_SKILL_FILES[provider]
    body = _strip_frontmatter(skill_path.read_text(encoding="utf-8"))
    provider_label = _PROMPT_LABELS[provider]
    return f"# {provider_label} PROVIDER RULES (`{provider}`)\n\n{body}"


PROVIDER_PROMPT_SECTIONS: dict[ProviderName, str] = {
    provider: _load_provider_prompt_section(provider) for provider in PROVIDER_ORDER
}


def _provider_names(selected_providers: Iterable[Any] | str | None) -> list[ProviderName]:
    if selected_providers is None:
        return list(PROVIDER_ORDER)
    if isinstance(selected_providers, str):
        normalized = normalize_provider_list([selected_providers])
    else:
        normalized = normalize_provider_list(selected_providers)
    return normalized or list(PROVIDER_ORDER)


def build_provider_prompt_sections(selected_providers: Iterable[Any] | str | None = None) -> str:
    """Build provider-specific prompt sections for the selected public providers."""
    return "\n".join(
        PROVIDER_PROMPT_SECTIONS[provider].strip()
        for provider in _provider_names(selected_providers)
    )


def build_system_prompt(selected_providers: Iterable[Any] | str | None = None) -> str:
    """Build the data engineer system prompt for tests and broad fallback construction."""
    provider_sections = build_provider_prompt_sections(selected_providers)
    return f"{DATA_ENGINEER_CORE_PROMPT.rstrip()}\n\n{provider_sections}\n"
