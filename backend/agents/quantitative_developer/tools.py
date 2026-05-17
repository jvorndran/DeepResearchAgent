"""Custom quant-developer tools.

The quant developer now composes reports by writing and executing
``code/analysis.py`` with the reusable helper library. No report-specific
artifact tools are registered here.
"""

from __future__ import annotations

QUANT_DEVELOPER_TOOLS: tuple[object, ...] = ()

__all__ = ["QUANT_DEVELOPER_TOOLS"]
