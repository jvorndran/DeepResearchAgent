"""
ResearchReport Schema (v1)

Single source of truth for the canonical report artifact produced by the
technical writer and consumed by the frontend, quality analyst, and any
future PDF export pipeline.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, field_validator

# =============================================================================
# CHART MODELS
# =============================================================================


class ReferenceLine(BaseModel):
    y: float | str | None = None
    x: float | str | None = None
    label: str | None = None
    color: str | None = None
    strokeDasharray: str | None = None


class ReferenceArea(BaseModel):
    x1: float | str | None = None
    x2: float | str | None = None
    y1: float | str | None = None
    y2: float | str | None = None
    label: str | None = None
    fill: str | None = None
    fillOpacity: float | None = None


class AxisSeries(BaseModel):
    dataKey: str
    label: str
    color: str
    type: str | None = None
    yAxisId: str | None = None
    stackId: str | None = None
    shape: str | None = None
    strokeDasharray: str | None = None


class AxisChartDef(BaseModel):
    id: str
    type: Literal["line", "bar", "area", "composed"]
    title: str
    description: str
    xAxisKey: str
    series: list[AxisSeries]
    data: list[dict]
    layout: Literal["horizontal", "vertical"] | None = None
    referenceLines: list[ReferenceLine] | None = None
    referenceAreas: list[ReferenceArea] | None = None


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
    sizeKey: str | None = None
    colorKey: str | None = None
    nameKey: str | None = None


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
    innerRadius: float | str | None = None


class RadarChartDef(BaseModel):
    id: str
    type: Literal["radar"]
    title: str
    description: str
    angleKey: str
    series: list[AxisSeries]
    data: list[dict]


class SegmentDatum(BaseModel):
    name: str
    value: float
    color: str | None = None
    fill: str | None = None


class RadialBarChartDef(BaseModel):
    id: str
    type: Literal["radialBar"]
    title: str
    description: str
    data: list[SegmentDatum]
    dataKey: str | None = None
    innerRadius: float | str | None = None
    outerRadius: float | str | None = None


class FunnelChartDef(BaseModel):
    id: str
    type: Literal["funnel"]
    title: str
    description: str
    data: list[SegmentDatum]
    dataKey: str | None = None
    nameKey: str | None = None


class HierarchyDatum(BaseModel):
    name: str
    value: float | None = None
    size: float | None = None
    color: str | None = None
    fill: str | None = None
    children: list["HierarchyDatum"] | None = None


class TreemapChartDef(BaseModel):
    id: str
    type: Literal["treemap"]
    title: str
    description: str
    data: list[HierarchyDatum]
    valueKey: Literal["size", "value"] | None = None


class SankeyNode(BaseModel):
    name: str
    color: str | None = None
    fill: str | None = None


class SankeyLink(BaseModel):
    source: int
    target: int
    value: float
    color: str | None = None
    fill: str | None = None


class SankeyData(BaseModel):
    nodes: list[SankeyNode]
    links: list[SankeyLink]


class SankeyChartDef(BaseModel):
    id: str
    type: Literal["sankey"]
    title: str
    description: str
    data: SankeyData


class SunburstChartDef(BaseModel):
    id: str
    type: Literal["sunburst"]
    title: str
    description: str
    data: HierarchyDatum
    valueKey: Literal["value", "size"] | None = None


ChartDef = Annotated[
    Union[
        AxisChartDef,
        ScatterChartDef,
        PieChartDef,
        RadarChartDef,
        RadialBarChartDef,
        FunnelChartDef,
        TreemapChartDef,
        SankeyChartDef,
        SunburstChartDef,
    ],
    Field(discriminator="type"),
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
# SCENARIO TABLE
# =============================================================================


class ScenarioRow(BaseModel):
    scenario: Literal["base", "bull", "bear"]
    assumptions: list[str] = Field(min_length=1)
    indicator_triggers: list[str] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    uncertainty_notes: str = Field(min_length=1)

    @field_validator("assumptions", "indicator_triggers")
    @classmethod
    def _non_empty_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("must include at least one non-empty item")
        return cleaned

    @field_validator("uncertainty_notes")
    @classmethod
    def _non_empty_note(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("uncertainty_notes must be non-empty")
        return cleaned


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
    scenario_table: list[ScenarioRow] | None = None
    data_sources: list[DataSource]
    metadata: ReportMetadata


__all__ = [
    "ReferenceLine",
    "ReferenceArea",
    "AxisSeries",
    "AxisChartDef",
    "ScatterChartDef",
    "PieSlice",
    "PieChartDef",
    "RadarChartDef",
    "SegmentDatum",
    "RadialBarChartDef",
    "FunnelChartDef",
    "HierarchyDatum",
    "TreemapChartDef",
    "SankeyNode",
    "SankeyLink",
    "SankeyData",
    "SankeyChartDef",
    "SunburstChartDef",
    "ChartDef",
    "DataSource",
    "ScenarioRow",
    "ReportMetadata",
    "ResearchReport",
]
