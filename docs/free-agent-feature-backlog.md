# Free Agent Feature Backlog

This backlog is designed for `scripts/codex_feature_loop.sh`. Every feature must
be free, no-key, no-signup, optional, and gracefully disabled when unavailable.
Do not re-enable FMP for these features.

## Integration Features

### SEC EDGAR Company Facts
- Owner: data-engineer
- Source: SEC `data.sec.gov` company submissions and XBRL companyfacts APIs.
- Why: Adds free public-company fundamentals without FMP.
- No-key proof: SEC docs state `data.sec.gov` APIs require no authentication or API keys.
- Low-overlap check: FRED covers macro series, not issuer-level SEC filings.
- Acceptance signal: An equity report can fetch revenue, net income, assets, liabilities, shares, and filing metadata for a ticker or CIK, then cite SEC as the source.
- Evaluation query: Compare Apple's revenue, net income, assets, liabilities, and share count trend from SEC filings against the macro inflation and fed funds backdrop. Use only free/no-key data sources and cite sources.
- Suggested implementation: Thin optional client under `backend/mcp_clients/` or `backend/agents/data_engineer/`, registered only with data-engineer.
- Required tests: Mock SEC responses, no-network failure, User-Agent header, malformed ticker/CIK, graceful disabled path.

### BLS Public Data
- Owner: data-engineer
- Source: BLS Public Data API.
- Why: Adds labor, wages, CPI/PPI, employment, and productivity series directly from source.
- No-key proof: BLS says the public API does not require registration and is open for public use.
- Low-overlap check: Some overlap with FRED, but useful for source reconciliation, detailed labor categories, and direct BLS citations.
- Acceptance signal: A labor-market report can compare a FRED series with direct BLS series metadata and explain source differences.
- Evaluation query: Is the US labor market weakening? Use FRED plus direct BLS public data where useful, compare source definitions, and explain what changed across the last few years.
- Suggested implementation: Optional `bls_get_series` and `bls_search_known_series` tools with a tiny curated series map.
- Required tests: Mock single-series and multi-series responses, year-window validation, rate-limit/error payload handling.

### Census Public Data
- Owner: data-engineer
- Source: Census Data API, no key for low-volume use.
- Why: Adds demographics, income, housing, population, regional context, county/state breakdowns.
- No-key proof: Census documents public API usage and permits up to 500 queries per IP per day without a key.
- Low-overlap check: FRED has aggregate macro series, not flexible geography/demographic tables.
- Acceptance signal: A regional macro report can pull state population, median income, or housing variables and merge them with FRED macro context.
- Evaluation query: Are US consumers under stress regionally? Combine FRED macro context with Census income, population, or housing variables for state-level context where feasible.
- Suggested implementation: Optional `census_get_table` with strict dataset/geography/variable allowlists.
- Required tests: Mock two-dimensional JSON table parsing, 50-variable limit, 500-query warning, bad geography handling.

### World Bank Indicators
- Owner: data-engineer
- Source: World Bank Indicators API.
- Why: Adds global macro context without paid providers.
- No-key proof: World Bank publishes public Indicators API documentation for programmatic access.
- Low-overlap check: FRED is US-centric; World Bank is useful for cross-country macro comparisons.
- Acceptance signal: A report can compare US inflation/growth to other countries with World Bank indicators and FRED where appropriate.
- Evaluation query: Compare US inflation and growth to Canada, Germany, Japan, and Mexico using World Bank annual indicators plus FRED US context. Explain cross-country limitations.
- Suggested implementation: Optional `worldbank_get_indicator` tool with country and indicator validation.
- Required tests: Mock paginated responses, missing country/indicator, annual-to-monthly handoff guidance.

## Local Analysis Features

### Advanced Macro Statistics Pack
- Owner: quant-developer
- Tools: Existing `pandas`, `numpy`, `scipy`; optionally `statsmodels` only if already installed or added as an optional backend dependency.
- Why: Adds rolling correlations, lead-lag tests, regressions, z-scores, drawdowns, recession-window summaries, and simple Granger/VAR-style workflows when available.
- Acceptance signal: `charts.json` and `execution_summary.json` include a `methods_used` list and statistically defensible outputs for lead-lag or regime questions.
- Evaluation query: Analyze whether the 10-year minus 3-month yield spread leads unemployment and industrial production. Include rolling correlations, lag tests, recession-window summaries, and method caveats.
- Suggested implementation: Add a local helper module for deterministic calculations instead of relying only on prompt instructions.
- Required tests: Known-input rolling correlation, lag selection, missing-data behavior, method labels in summaries.

### Statsmodels Forecasting And Econometrics
- Owner: quant-developer
- Tools: Optional local `statsmodels` only. If unavailable, degrade to `scipy`/`numpy` regression helpers and emit a clear `statsmodels_unavailable` method note.
- Why: Adds serious econometric workflows: OLS with robust errors, ARIMA/SARIMAX, VAR, Granger causality, stationarity checks, impulse response summaries, and simple forecast intervals.
- Acceptance signal: For forecasting or causal-lead prompts, `execution_summary.json` includes `model_spec`, `estimation_window`, `target_variable`, `features`, `diagnostics`, `forecast_table` or `test_results`, and plain-English caveats against causal overclaiming.
- Evaluation query: Build an econometric model that forecasts the US unemployment rate six months ahead using yield curve, claims, payrolls, and industrial production. Include model specification, diagnostics, forecast table, and caveats.
- Suggested implementation: Add a local quant helper module with narrow wrappers and stable JSON outputs; do not let the agent hand-roll large statsmodels scripts every time.
- Required tests: Synthetic OLS coefficients, unavailable-statsmodels fallback, forecast output schema, stationarity-warning behavior, and no raw model objects in JSON.

### Composite Predictive Indicator Builder
- Owner: quant-developer with data-engineer support
- Tools: Local Python only; source data may come from FRED plus optional no-key integrations.
- Why: Lets the agent combine many sources into an index that attempts to predict a target such as recession risk, unemployment direction, inflation pressure, earnings stress, credit stress, or consumer stress.
- Acceptance signal: `execution_summary.json` includes `target`, `prediction_horizon`, `input_features`, `feature_transforms`, `normalization_method`, `weights_or_model`, `backtest_summary`, `latest_index_value`, `thresholds`, and limitations. Reports must clearly say "predictive indicator" rather than guaranteed forecast.
- Evaluation query: Build a composite recession-risk indicator from rates, labor, credit, inflation, output, and consumption series. Backtest it against historical recession windows and explain latest signal thresholds.
- Suggested implementation: Deterministic helper for feature alignment, z-scoring/ranking, lagging predictors, train/test split, simple scoring/weighting, and backtest metrics. Prefer transparent weighting or regularized/logistic models only when dependencies are already available.
- Required tests: Mixed-frequency alignment, no-lookahead lagging, missing feature handling, deterministic weights, threshold classification, and backtest metric schema.

### Scenario And Stress Testing
- Owner: quant-developer and technical-writer
- Tools: Local Python only.
- Why: Produces base/bull/bear scenario tables for recession risk, inflation, labor, credit, and earnings reports.
- Acceptance signal: `report.json` includes a scenario table with assumptions, indicator triggers, and confidence/uncertainty notes.
- Evaluation query: Build a recession risk dashboard with base, bull, and bear scenarios. Include assumptions, trigger indicators, and confidence/uncertainty notes.
- Suggested implementation: Quant writes scenario JSON; writer renders required scenario section; QA rejects missing scenario tables for scenario prompts.
- Required tests: Scenario schema validation, writer rendering, QA rejection for missing required scenario section.

### Recession And Regime Classifier
- Owner: quant-developer
- Tools: Local Python only, FRED recession indicator series when available.
- Why: Converts many macro signals into interpretable regimes: expansion, slowdown, recession, recovery, reacceleration.
- Acceptance signal: Macro reports include a regime label, evidence table, historical analogs, and false-positive caveat.
- Evaluation query: Classify the current US macro regime as expansion, slowdown, recession, recovery, or reacceleration using rates, labor, inflation, credit, and output indicators. Include transparent scoring.
- Suggested implementation: Deterministic scoring helper with transparent weights and no black-box model.
- Required tests: Synthetic indicator fixtures for each regime, missing-series fallback, score explanation.

## Loop Rules

- `docs/free-agent-feature-backlog.md` is the source of truth for feature ideas,
  constraints, acceptance signals, and evaluation queries. The shell loop may
  choose feature headings, but it must not duplicate or override feature specs.
- Implement at most one coherent feature slice per pass.
- Use separate Codex sessions for build, verification, and improvement so each
  phase starts with cleared model context.
- If a feature needs a new dependency, prefer proposal-only unless the dependency is already in the project or is clearly local/open-source and optional.
- For public HTTP integrations, add a disabled/failure path and tests that mock network responses.
- For public no-key HTTP integrations, add a tiny live integration smoke test
  under `backend/tests/integration/`. It must be skipped unless
  `RUN_LIVE_INTEGRATION_TESTS=1`, make only one narrow provider call when
  possible, assert response shape/source metadata rather than exact volatile
  values, and treat provider/network unavailability as a separately reported
  live-smoke failure rather than evidence that mocked contract tests are wrong.
- For local analysis features, add fixture-driven integration tests instead of
  live HTTP tests. They should run realistic CSV/JSON fixtures through the
  helper or agent-owned artifact path and assert output schemas such as
  `execution_summary.json`, `charts.json`, `methods_used`, no-lookahead
  alignment, scenario tables, model diagnostics, or report validation gates.
- The verifier phase should run mocked unit/contract tests plus live integration
  smoke tests for public no-key providers when relevant:
  `RUN_LIVE_INTEGRATION_TESTS=1 UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/integration -q`.
  If there are no relevant integration tests yet, that is verifier evidence that
  the feature needs improvement.
- Keep each tool owned by one specialist.
- Add skill guidance for when to use the feature, when not to use it, call budgets, expected output shape, and fallback behavior.
- Do not add API keys, signup flows, OAuth, paid providers, hosted services, or mandatory background daemons.

## References

- SEC EDGAR APIs: https://www.sec.gov/edgar/sec-api-documentation
- BLS Public Data API: https://www.bls.gov/bls/api_features.htm
- Census Data API guide: https://www.census.gov/data/developers/guidance/api-user-guide.html
- World Bank Indicators API: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
- PyMuPDF docs: https://pymupdf.readthedocs.io/
