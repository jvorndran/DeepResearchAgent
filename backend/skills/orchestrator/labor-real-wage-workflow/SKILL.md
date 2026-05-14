---
name: labor-real-wage-workflow
description: Use for real wage, real wages, real average hourly earnings, inflation-adjusted earnings, and wage-gain source-fidelity requests.
---

# Real Wage Source Fidelity

Use this skill when the user asks about real wages, real average hourly earnings, wage gains after inflation, or inflation-adjusted earnings.

## Data Engineer

- Verify that any FRED earnings series title or units explicitly says real or inflation-adjusted.
- If only nominal earnings are available, require a FRED price index such as CPIAUCSL.
- Never let a nominal average-hourly-earnings series stand in for "real" wages.

## Quant Developer

- If data-engineer returns nominal earnings plus a price index, construct the real earnings measure before analyzing wage gains.
- Preserve the transformation in `execution_summary` so the writer can state whether the measure was directly real or inflation-adjusted locally.
