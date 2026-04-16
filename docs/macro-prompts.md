## 1. Credit Cycle & Liquidity Analysis
These questions test the agent's ability to calculate spreads and identify "cracks" in the financial system.

* **Prompt:** *"Calculate the 12-month rolling correlation between the **High Yield Corporate Bond Spread (BAMLH0A0HYM2)** and the **KBW Bank Index**. How does this correlation shift during periods where the **Net Percentage of Banks Tightening Standards for C&I Loans (DRTSCILM)** exceeds 20%?"*
* **Prompt:** *"Analyze the 'Financial Conditions Impulse.' Retrieve the **Chicago Fed National Financial Conditions Index (NFCI)** and compare its 3-month rate of change against the **S&P 500 Forward P/E ratio** (or proxy). Does a tightening impulse historically lead equity drawdowns by more than 2 quarters?"*

## 2. Inflation & Monetary Policy Efficacy
These focus on the "Real" vs "Nominal" gap, which is crucial for valuation models.

* **Prompt:** *"Decompose the current **Consumer Price Index (CPIAUCSL)**. Pull the **Sticky-Price CPI (STICKCPIM157SFRBATL)** and compare it to the **Flexible-Price CPI**. Based on the last 6 months of data, is the 'disinflation' narrative driven by volatile components or structural shifts in the service economy?"*
* **Prompt:** *"Calculate the 'Real Fed Funds Rate' by subtracting the **1-Year Expected Inflation (MICH)** from the **Effective Federal Funds Rate (FEDFUNDS)**. Cross-reference this with the **Sahm Rule Recession Indicator (SAHMREALTIME)** to identify if the current 'Real' rate is at a restrictive level historically associated with labor market cooling."*
* **Prompt:** *"Compare the **5-Year, 5-Year Forward Inflation Expectation Rate (T5YIFR)** against the **10-Year Breakeven Inflation Rate (T10YIE)**. If the forward expectation is significantly higher than the 10-year breakeven, what does this 'De-anchoring' signal suggest about the market's confidence in the Fed's long-term inflation target?"*

## 3. The "Yield Curve" & Macro Forecasting
Instead of just asking for the curve, ask for the *timing* of the inversion vs. the trough.

* **Prompt:** *"Retrieve the **10-Year Treasury Constant Maturity Minus 2-Year Treasury (T10Y2Y)**. Identify every instance of 're-steepening' after an inversion since 1980. What is the median lead time between the curve returning to positive territory and the start of an **NBER-defined recession (USREC)**?"*
* **Prompt:** *"Analyze the 'Term Premium' proxy. Pull the **10-Year Treasury Yield (DGS10)** and the **2-Year Treasury Yield (DGS2)**. Calculate the butterfly spread $(10Y - 5Y) - (5Y - 2Y)$ and explain what the current curvature suggests about market expectations for a 'soft landing' vs. 'hard landing'."*
* **Prompt:** *"Retrieve the **10-Year Treasury Constant Maturity Minus 3-Month Treasury (T10Y3M)** and the **Excess Bond Premium (EBP)** from the Gilchrist and Zakrajšek paper (if available via proxy or FRED series). Compare the predictive power of the yield curve vs. credit risk premiums for recession onset over the next 12 months."*

## 4. Labor Market & Consumer Health
Crucial for Retail and Consumer Discretionary sector coverage.

* **Prompt:** *"Compare the **Personal Saving Rate (PSAVERT)** against the **Total Consumer Credit Owned and Secularized (TOTALSL)**. Is the current consumer spending being funded by organic income growth or by a rapid expansion in revolving credit? Provide the debt-to-savings ratio trend over the last 24 months."*
* **Prompt:** *"Create a 'Labor Market Tightness Index' by dividing **Job Openings (JTSJOL)** by the **Number of Unemployed Persons (UNEMPLOY)**. At what level has this ratio historically peaked before a meaningful rise in the **Continued Claims for Unemployment Insurance (CCSA)**?"*
* **Prompt:** *"Analyze the **Real Disposable Personal Income (DSPIC96)** against the **University of Michigan: Consumer Sentiment (UMCSENT)**. Identify 'Divergence Zones' where sentiment is falling despite rising real income. Does this divergence typically precede a contraction in **Real Personal Consumption Expenditures (PCECC96)**?"*

## 5. Equity Sector Rotation & Asset Allocation
These prompts bridge macro shifts to specific investment strategies and sector performance.

* **Prompt:** *"Retrieve the **10-Year Real Interest Rate (DFII10)** and the **NASDAQ 100 Index**. Calculate the rolling 6-month correlation between changes in real yields and the price-to-earnings multiple of the index. During which historical regimes did this correlation 'break', and what does the current real rate level imply for the 'valuation ceiling' of long-duration growth assets?"*
* **Prompt:** *"Analyze the 'Defensive vs. Cyclical' spread. Pull the performance of **Consumer Staples** and **Consumer Discretionary** sectors. Compare their relative performance ratio against the **ISM Manufacturing PMI** (or FRED proxy). Does the current ratio suggest the market is pricing in a 'Recession' or a 'Mid-Cycle Acceleration'?"*
* **Prompt:** *"Retrieve the **High Yield Corporate Bond Spread (BAMLH0A0HYM2)** and the **Russell 2000 Index**. Calculate the 'Credit-to-Equity Divergence' over the last 12 months. If credit spreads are widening while small-caps are rising, what does this historical anomaly suggest about the sustainability of the current rally in 'junk'-rated equities?"*
* **Prompt:** *"Compare the **Gold Price (GOLDAMGBD228NLBM)** against the **10-Year Real Interest Rate (DFII10)**. Calculate the 'Real Rate Adjusted Gold Price' (residual analysis). If gold is trading at a significant premium to its historical real-rate correlation, what does this imply about 'Central Bank Diversification' vs. 'Inflation Hedging' demand?"*

## 6. Global Macro & FX Implications
These prompts test the agent's ability to analyze the 'Dollar Smile' and cross-currency carry trades.

* **Prompt:** *"Retrieve the **US Dollar Index (DTWEXBGS)** and the **Japan/US Yield Spread (DGS10 - JPN10Y proxy or equivalent)**. Analyze the correlation between the Yen-Dollar exchange rate and the 10-year yield differential over the last 5 years. Does the current 'Carry Trade' unwind historical pattern suggest a volatility spike in US equities?"*
* **Prompt:** *"Compare the **Trade-Weighted US Dollar Index (TWEXBPA)** against the **S&P 500 Index**. Identify 'Strong Dollar Regimes' (more than 2 standard deviations above mean). Does the US dollar's strength historically serve as a headwind for S&P 500 earnings growth, and what is the current revenue-weighted sensitivity to a 'Dollar Breakout'?"*
* **Prompt:** *"Analyze the 'Emerging Markets Risk-On/Risk-Off' indicator. Retrieve the **MSCI Emerging Markets Index** (or FRED proxy like `EEM`) and the **VIX Index (VIXCLS)**. Calculate the beta of EM equities to the VIX during periods of 'USD Liquidity Tightening' (measured by **M2 Money Supply (M2SL)** growth rates below 5%)."*
