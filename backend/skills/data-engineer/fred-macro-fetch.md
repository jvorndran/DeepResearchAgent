---
name: fred-macro-fetch
description: Concise workflow for fetching FRED macro data
triggers: [FRED, macro, GDP, inflation, CPI, unemployment, interest rates]
---

# FRED Workflow

Use FRED for GDP, CPI/inflation, unemployment, payrolls, rates, credit,
production, consumption, recession indicators, and related market proxies.

- `fred_get_series` auto-saves usable CSVs when it returns
  `status:auto_saved`; use that `file_path` directly and do not call
  `save_data`.
- For known IDs below, call `fred_get_series` directly. For unknown IDs, call
  `fred_search` once per distinct series, choose the best candidate, then fetch.
  Do not refine wording or double-check with repeated searches when a plausible
  candidate exists.
- If `fred_get_series` fails with an invalid ID, one clearer follow-up
  `fred_search` is allowed before the next fetch. Every FRED call counts toward
  the 3-attempt objective budget.

## Current/latest macro freshness

For current conditions, latest signals, recession risk, today/now, or scenario
outlook, do not set `observation_end` unless the user explicitly gives a
historical cutoff date. Fetch full history through the latest observation even
when the task also asks for backtests before earlier downturns. Include observed
date ranges or latest dates in metadata.

## Known IDs

`GDPC1` real GDP; `CPIAUCSL` CPI; `UNRATE` unemployment; `PAYEMS` payrolls;
`ICSA` claims; `JTSJOL` JOLTS openings; `CIVPART` participation;
`LNS14000060` prime-age unemployment; `FEDFUNDS` fed funds; `DGS10` 10Y
Treasury; `DGS2` = 2-year Treasury yield; `T10Y2Y` 10Y-2Y spread; `T10Y3M`
10Y-3M spread; `BAA10Y` Baa minus 10Y spread; `USREC` NBER recession;
`SP500` = S&P 500 daily close.

Never label `LNS14000003` as prime-age unemployment; it is "Unemployment Rate -
White." Do not use `TC2Y` for the 2-year Treasury yield; fetch `DGS2`
directly. Before returning success, compare each fetched title/metadata to the
requested concept; if the title contradicts the concept, fetch the correct
series or report the mismatch in `fetch_errors`.

## Real wage/earnings requests

For real wages or inflation-adjusted earnings, the chosen FRED earnings title or
units must explicitly say real/inflation-adjusted. Do not treat nominal earnings
series such as `AHETPI` as real. If needed, save nominal earnings plus a price
index such as `CPIAUCSL` and state that quant-developer must deflate it.

## Common consumer-stress IDs

Use `PSAVERT` = personal saving rate; `UMCSENT` = University of Michigan
consumer sentiment; `TOTALSL` = total consumer credit owned and securitized;
`DRCLACBS` = delinquency rate on consumer loans; `DRCCLACBS` = credit-card
delinquency rate; `DSPIC96` real disposable income; `DPCERA3M086SBEA` or
`PCEC96` = real personal consumption expenditures; `PCE` = nominal consumption
only when a nominal-spending proxy is explicitly useful. Do not use `TOTCI` for
consumer credit; it is commercial and industrial loans. Do not use `DRBLACBS`
for credit-card or household delinquency analysis.

## Common unemployment-forecast IDs

For unemployment forecast, forecast-band, false-alarm, or historical miss
requests, include `UNRATE` and `PAYEMS` plus useful predictor evidence when the
query does not name exact series: `ICSA` initial claims, `U6RATE` broad labor
underutilization, `DGS10` and `FEDFUNDS` for rate-spread context, `NROU` for
natural-rate gaps, and `USREC` for recession/backtest context. Add `CPIAUCSL`
or `GDPC1` only when inflation or growth predictors are analytically useful.

## Market proxy ID

FRED starts `SP500` in 2016. If the known `SP500` fetch succeeds, accept that
limited-history proxy, note the limitation in metadata, and do not spend extra
`fred_search`/`fred_browse` calls looking for a longer FRED S&P 500 index.

## Common large-state labor IDs

For California, Texas, Florida, New York, and Illinois comparisons, use:
unemployment `CAUR`, `TXUR`, `FLUR`, `NYUR`, `ILUR`; payrolls `CANA`, `TXNA`,
`FLNA`, `NYNA`, `ILNA`. Do not call nonexistent IDs such as `CANURN`,
`CES0600000001`, or `CES4800000001`. For other states, search once before the
first fetch.
