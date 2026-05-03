---
name: worldbank-indicators
description: Fetch no-key World Bank annual indicators for cross-country inflation and GDP-growth context
triggers: [World Bank, cross-country, Canada, Germany, Japan, Mexico, annual inflation, GDP growth]
---

# World Bank Indicators Workflow

Use `worldbank_get_indicator` only for cross-country annual macro comparisons where World Bank adds non-US context beyond FRED.

Supported scope:
- Countries: `USA`, `CAN`, `DEU`, `JPN`, `MEX` plus common aliases.
- Indicators: `inflation` / `FP.CPI.TOTL.ZG`, `gdp_growth` / `NY.GDP.MKTP.KD.ZG`.
- Authentication: none. Do not request keys, signups, OAuth, paid providers, hosted services, or FMP.

Call budget:
1. One call per indicator is usually enough: fetch all needed countries together.
2. For the evaluation query, call once for `inflation` and once for `gdp_growth`, then use FRED separately only for useful US monthly/quarterly context.
3. If a call returns `status:error`, correct country/indicator/year input once. If unavailable after that, return the compact error and do not switch providers.

Output handling:
- `worldbank_get_indicator` saves the CSV and returns `data_files`, `row_counts`, and metadata. Do not call `save_data` afterward.
- Return only paths and compact metadata to downstream agents. Never paste raw observations into chat.
- Preserve the `handoff_guidance` metadata so quant-developer knows the World Bank data is annual.

Frequency caveat:
World Bank annual indicators are not a drop-in replacement for monthly or quarterly FRED series. When combining them, tell quant-developer to align frequencies explicitly and to state limitations. Do not forward-fill annual values into monthly analysis without disclosing that assumption.
