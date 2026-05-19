---
name: source-unit-fidelity
description: Preserve and validate source units before direct metric comparisons.
---

# Source Unit Fidelity

Use this skill when comparing values from different source files, especially
earnings, wages, prices, rates, or indexes.

- Import `source_unit_metadata` and `unit_comparison` from
  `agents.quant_macro_stats`.
- Create one `source_unit_metadata(...)` record per compared source. Prefer
  `source_file=DATA_FILES[...]` so the helper reads saved CSV metadata.
- Before computing a gap, difference, ratio, divergence, or direct overlay,
  create a `unit_comparison(...)` record and save it in
  `execution_summary["unit_comparisons"]`.
- If sources have incompatible units, convert to a common unit first and
  document the conversion in the comparison record; otherwise remove the direct
  comparison and state the limitation.
- For BLS wage series, hourly earnings and weekly earnings are not directly
  comparable. Use hourly-to-hourly or weekly-to-weekly comparisons unless you
  explicitly convert.

Minimal pattern:

```python
from agents.quant_macro_stats import source_unit_metadata, unit_comparison

all_hourly = source_unit_metadata("all_hourly", source_file=DATA_FILES["CES0500000003"])
prod_hourly = source_unit_metadata("prod_hourly", source_file=DATA_FILES["CES0500000008"])
unit_checks = [
    unit_comparison(
        "real_hourly_wage_gap",
        [all_hourly, prod_hourly],
        operation="difference",
    )
]
execution_summary["source_unit_metadata"] = [all_hourly, prod_hourly]
execution_summary["unit_comparisons"] = unit_checks
```
