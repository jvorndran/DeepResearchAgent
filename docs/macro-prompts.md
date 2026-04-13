## 1. Credit Cycle & Liquidity Analysis
These questions test the agent's ability to calculate spreads and identify "cracks" in the financial system.

* **Prompt:** *"Calculate the 12-month rolling correlation between the **High Yield Corporate Bond Spread (BAMLH0A0HYM2)** and the **KBW Bank Index**. How does this correlation shift during periods where the **Net Percentage of Banks Tightening Standards for C&I Loans (DRTSCILM)** exceeds 20%?"*
* **Prompt:** *"Analyze the 'Financial Conditions Impulse.' Retrieve the **Chicago Fed National Financial Conditions Index (NFCI)** and compare its 3-month rate of change against the **S&P 500 Forward P/E ratio** (or proxy). Does a tightening impulse historically lead equity drawdowns by more than 2 quarters?"*

## 2. Inflation & Monetary Policy Efficacy
These focus on the "Real" vs "Nominal" gap, which is crucial for valuation models.

* **Prompt:** *"Decompose the current **Consumer Price Index (CPIAUCSL)**. Pull the **Sticky-Price CPI (STICKCPIM157SFRBATL)** and compare it to the **Flexible-Price CPI**. Based on the last 6 months of data, is the 'disinflation' narrative driven by volatile components or structural shifts in the service economy?"*
* **Prompt:** *"Calculate the 'Real Fed Funds Rate' by subtracting the **1-Year Expected Inflation (MICH)** from the **Effective Federal Funds Rate (FEDFUNDS)**. Cross-reference this with the **Sahm Rule Recession Indicator (SAHMREALTIME)** to identify if the current 'Real' rate is at a restrictive level historically associated with labor market cooling."*

## 3. The "Yield Curve" & Macro Forecasting
Instead of just asking for the curve, ask for the *timing* of the inversion vs. the trough.

* **Prompt:** *"Retrieve the **10-Year Treasury Constant Maturity Minus 2-Year Treasury (T10Y2Y)**. Identify every instance of 're-steepening' after an inversion since 1980. What is the median lead time between the curve returning to positive territory and the start of an **NBER-defined recession (USREC)**?"*
* **Prompt:** *"Analyze the 'Term Premium' proxy. Pull the **10-Year Treasury Yield (DGS10)** and the **2-Year Treasury Yield (DGS2)**. Calculate the butterfly spread $(10Y - 5Y) - (5Y - 2Y)$ and explain what the current curvature suggests about market expectations for a 'soft landing' vs. 'hard landing'."*

## 4. Labor Market & Consumer Health
Crucial for Retail and Consumer Discretionary sector coverage.

* **Prompt:** *"Compare the **Personal Saving Rate (PSAVERT)** against the **Total Consumer Credit Owned and Secularized (TOTALSL)**. Is the current consumer spending being funded by organic income growth or by a rapid expansion in revolving credit? Provide the debt-to-savings ratio trend over the last 24 months."*
* **Prompt:** *"Create a 'Labor Market Tightness Index' by dividing **Job Openings (JTSJOL)** by the **Number of Unemployed Persons (UNEMPLOY)**. At what level has this ratio historically peaked before a meaningful rise in the **Continued Claims for Unemployment Insurance (CCSA)**?"*
