import pandas as pd
import numpy as np
from scipy import stats
import json
from pathlib import Path
from datetime import datetime

# Paths
GDP_PATH = r"C:\\projects\\DeepResearchAgent\\backend\\data\\gdp_unemployment_20yr\\GDPC1_real_gdp_quarterly_gdp_unemployment_20yr.csv"
UNRATE_PATH = r"C:\\projects\\DeepResearchAgent\\backend\\data\\gdp_unemployment_20yr\\UNRATE_unemployment_rate_monthly_gdp_unemployment_20yr.csv"
OUTPUT_ROOT = Path(r"C:\\projects\\DeepResearchAgent\\backend\\outputs") / "gdp_unemployment_20yr"

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

# Load data
gdp_df = pd.read_csv(GDP_PATH)
unrate_df = pd.read_csv(UNRATE_PATH)

# Parse dates
gdp_df["date"] = pd.to_datetime(gdp_df["date"])
unrate_df["date"] = pd.to_datetime(unrate_df["date"])

# Assume primary value column is named 'value' as per schema description
if "value" not in gdp_df.columns:
    raise ValueError("GDP file must contain a 'value' column")
if "value" not in unrate_df.columns:
    raise ValueError("Unemployment file must contain a 'value' column")

# Set index
gdp_df = gdp_df.sort_values("date").set_index("date")
unrate_df = unrate_df.sort_values("date").set_index("date")

# Compute YoY real GDP growth (quarterly)
# Use pct_change with 4-quarter lag (since data is quarterly)
#gdp_df['gdp_growth_yoy'] = gdp_df['value'].pct_change(4) * 100
# To be safer, ensure quarterly frequency by resampling to Q and using last observation
quarterly_gdp = gdp_df["value"].resample("QE").last()
quarterly_gdp_growth_yoy = quarterly_gdp.pct_change(4) * 100

# Resample unemployment rate to quarterly (mean of months in quarter)
quarterly_unrate = unrate_df["value"].resample("QE").mean()

# Quarterly change in unemployment rate (percentage points)
quarterly_unrate_change = quarterly_unrate.diff(1)

# Align series for analysis
analysis_df = pd.concat([
    quarterly_gdp_growth_yoy.rename("gdp_growth_yoy"),
    quarterly_unrate.rename("unemployment_rate"),
    quarterly_unrate_change.rename("unemployment_change")
], axis=1).dropna()

# Correlation analysis between YoY GDP growth and unemployment rate (Okun-style)
# 1) Level of unemployment vs YoY GDP growth
valid_level = analysis_df[["gdp_growth_yoy", "unemployment_rate"]].dropna()
if len(valid_level) < 3:
    raise ValueError("Not enough data points for correlation (levels)")

r_level, p_level = stats.pearsonr(valid_level["gdp_growth_yoy"], valid_level["unemployment_rate"])

# 2) Change in unemployment vs YoY GDP growth (Okun's Law)
valid_change = analysis_df[["gdp_growth_yoy", "unemployment_change"]].dropna()
if len(valid_change) < 3:
    raise ValueError("Not enough data points for correlation (changes)")

r_change, p_change = stats.pearsonr(valid_change["gdp_growth_yoy"], valid_change["unemployment_change"])

# Identify periods where GDP contracted (negative YoY growth)
contraction_df = analysis_df[analysis_df["gdp_growth_yoy"] < 0].copy()
# For each contraction quarter, record unemployment level and change
contraction_periods = []
for idx, row in contraction_df.iterrows():
    contraction_periods.append({
        "quarter": idx.to_period("Q").strftime("%YQ%q"),
        "gdp_growth_yoy": float(row["gdp_growth_yoy"]),
        "unemployment_rate": float(row["unemployment_rate"]),
        "unemployment_change": float(row["unemployment_change"]),
    })

# Prepare data for charts
# 1) Time-series: GDP YoY growth and unemployment rate
trend_data = []
for idx, row in analysis_df.iterrows():
    trend_data.append({
        "quarter": idx.to_period("Q").strftime("%YQ%q"),
        "gdp_growth_yoy": float(row["gdp_growth_yoy"]),
        "unemployment_rate": float(row["unemployment_rate"]),
    })

# 2) Scatter: YoY GDP growth (X) vs quarterly change in unemployment (Y)
okun_scatter_data = []
for idx, row in valid_change.iterrows():
    okun_scatter_data.append({
        "gdp_growth_yoy": float(row["gdp_growth_yoy"]),
        "unemployment_change": float(row["unemployment_change"]),
    })

# Build charts dict
charts = {
    "gdp_unemployment_trends": {
        "id": "gdp_unemployment_trends",
        "type": "line",
        "title": "US Real GDP YoY Growth and Unemployment Rate (Quarterly)",
        "description": "Quarterly YoY real GDP growth and average unemployment rate over the past 20 years.",
        "xAxisKey": "quarter",
        "series": [
            {"dataKey": "gdp_growth_yoy", "label": "Real GDP YoY Growth (%)", "color": "#3b82f6"},
            {"dataKey": "unemployment_rate", "label": "Unemployment Rate (%)", "color": "#f59e0b"}
        ],
        "data": trend_data,
    },
    "okuns_law_scatter": {
        "id": "okuns_law_scatter",
        "type": "scatter",
        "title": "Okun's Law: GDP Growth vs Change in Unemployment",
        "description": "Relationship between quarterly YoY real GDP growth and quarterly change in the unemployment rate.",
        "xKey": "gdp_growth_yoy",
        "yKey": "unemployment_change",
        "xLabel": "Real GDP YoY Growth (%)",
        "yLabel": "Quarterly Change in Unemployment Rate (p.p.)",
        "color": "#10b981",
        "data": okun_scatter_data,
    },
}

# Validate chart structure
REQUIRED_KEYS = {"id", "type", "title", "description"}
for chart_id, chart_def in charts.items():
    missing = REQUIRED_KEYS - set(chart_def.keys())
    if missing:
        raise ValueError(f"Chart '{chart_id}' missing required fields: {missing}")
    if not isinstance(chart_def.get("id"), str) or not isinstance(chart_def.get("type"), str):
        raise ValueError(f"Chart '{chart_id}': 'id' and 'type' must be strings at top level")
print("charts.json validation passed")

charts_path = OUTPUT_ROOT / "charts.json"
charts_path.parent.mkdir(parents=True, exist_ok=True)
with open(charts_path, "w") as f:
    json.dump(charts, f)

# Build compact JSON summary
summary = {
    "correlation_gdp_growth_vs_unemployment_level": float(r_level),
    "p_value_level": float(p_level),
    "correlation_gdp_growth_vs_unemployment_change": float(r_change),
    "p_value_change": float(p_change),
    "num_quarters": int(len(analysis_df)),
    "num_contraction_quarters": int(len(contraction_periods)),
    "chart_ids": ["gdp_unemployment_trends", "okuns_law_scatter"],
}

# Add a key finding text
if r_change < 0:
    key_finding = "Stronger real GDP growth is associated with declines in the unemployment rate, consistent with Okun's Law."
else:
    key_finding = "Stronger real GDP growth is associated with increases in the unemployment rate, contrary to standard Okun's Law expectations."
summary["key_finding"] = key_finding

print(json.dumps(summary))
