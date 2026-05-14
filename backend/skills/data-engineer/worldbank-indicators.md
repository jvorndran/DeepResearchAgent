---
name: worldbank-indicators
description: Fetch no-key World Bank annual indicators for cross-country inflation and GDP-growth context
triggers: [World Bank, cross-country, Canada, Germany, Japan, Mexico, annual inflation, GDP growth]
---

# World Bank Indicators Workflow

Cross-country annual inflation and GDP growth use World Bank annual indicators
via `worldbank_get_indicator`.

- **WORLD BANK CROSS-COUNTRY MACRO:** Use World Bank for inflation or growth
  comparisons across USA, Canada, Germany, Japan, or Mexico. It requires no API
  key; `worldbank_get_indicator` saves World Bank CSVs and returns `data_files`;
  do not call `save_data` afterward.
- Supported countries: `USA`, `CAN`, `DEU`, `JPN`, `MEX`. Supported indicators:
  `inflation`/`FP.CPI.TOTL.ZG` and `gdp_growth`/`NY.GDP.MKTP.KD.ZG`.
- World Bank data is annual. For US monthly/quarterly context use FRED
  separately and tell quant-developer to align frequencies explicitly. Do not
  forward-fill annual values into monthly analysis without calling out the
  limitation.
- If World Bank returns `status:disabled` or `status:error`, report that
  compactly; do not switch to paid providers and do not replace the
  peer-country request with guessed FRED/OECD series searches unless the user
  specifically asked for FRED international series.
