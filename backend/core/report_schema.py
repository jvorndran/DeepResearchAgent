"""
ResearchReport Schema (v1)

Single source of truth for the canonical report artifact produced by the
technical writer and consumed by the frontend, quality analyst, and any
future PDF export pipeline.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


# =============================================================================
# CHART MODELS
# =============================================================================

class AxisSeries(BaseModel):
    dataKey: str
    label: str
    color: str


class AxisChartDef(BaseModel):
    id: str
    type: Literal["line", "bar", "area"]
    title: str
    description: str
    xAxisKey: str
    series: list[AxisSeries]
    data: list[dict]


class ScatterChartDef(BaseModel):
    id: str
    type: Literal["scatter"]
    title: str
    description: str
    xKey: str
    yKey: str
    xLabel: str
    yLabel: str
    color: str
    data: list[dict]


class PieSlice(BaseModel):
    name: str
    value: float
    color: str | None = None


class PieChartDef(BaseModel):
    id: str
    type: Literal["pie"]
    title: str
    description: str
    data: list[PieSlice]


ChartDef = Annotated[
    Union[AxisChartDef, ScatterChartDef, PieChartDef],
    Field(discriminator="type")
]


# =============================================================================
# DATA SOURCE
# =============================================================================

class DataSource(BaseModel):
    provider: str
    description: str
    tickers: list[str] | None = None
    series_ids: list[str] | None = None
    date_range: dict[str, str] | None = None
    row_count: int | None = None


# =============================================================================
# REPORT METADATA
# =============================================================================

class ReportMetadata(BaseModel):
    analysis_type: str
    chart_count: int
    word_count: int


# =============================================================================
# TOP-LEVEL REPORT OBJECT
# =============================================================================

class ResearchReport(BaseModel):
    schema_version: Literal[1] = 1
    job_id: str
    created_at: str
    query: str
    title: str
    executive_summary: str
    markdown: str
    charts: dict[str, ChartDef]
    data_sources: list[DataSource]
    metadata: ReportMetadata


__all__ = [
    "AxisSeries",
    "AxisChartDef",
    "ScatterChartDef",
    "PieSlice",
    "PieChartDef",
    "ChartDef",
    "DataSource",
    "ReportMetadata",
    "ResearchReport",
]
