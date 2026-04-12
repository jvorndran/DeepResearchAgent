---
name: qa-rejection-recovery
description: Concise rules for handling report rejections
triggers: [rejection, rejected, qa, fix, retry]
---

# QA Recovery Rules

1. **Rule of Three:** Max 3 retries per subagent. If the 3rd retry still fails or gets rejected, abort.
2. **Analysis:** Read `required_fixes` from the `reject_report` result.
3. **Re-delegate:**
   - **Prose/Formatting:** Send back to `technical-writer`.
   - **Data/Logic:** Send back to `quant-developer` if findings were wrong.
4. **Context:** Pass the `reason` and `required_fixes` to the subagent explicitly in the `task()`.
