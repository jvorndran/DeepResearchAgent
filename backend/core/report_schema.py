"""
ResearchReport Schema (v1)

Single source of truth for the canonical report artifact produced by the
technical writer and consumed by the frontend, quality analyst, and any
future PDF export pipeline.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

# =============================================================================
# CHART MODELS
# =============================================================================


class ReferenceLine(BaseModel):
    axis: Literal["x", "y"]
    value: float | str
    label: str | None = None
    color: str | None = None
    dashed: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_axis_value(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        axis = normalized.get("axis")
        if not isinstance(axis, str) or axis not in {"x", "y"}:
            if normalized.get("x") is not None:
                normalized["axis"] = "x"
                normalized["value"] = normalized.get("x")
            elif normalized.get("y") is not None:
                normalized["axis"] = "y"
                normalized["value"] = normalized.get("y")
        elif normalized.get("value") is None:
            legacy_value = normalized.get(axis)
            if legacy_value is not None:
                normalized["value"] = legacy_value

        if "dashed" not in normalized and normalized.get("strokeDasharray"):
            normalized["dashed"] = True

        return normalized


class ReferenceArea(BaseModel):
    x1: float | str | None = None
    x2: float | str | None = None
    y1: float | str | None = None
    y2: float | str | None = None
    label: str | None = None
    fill: str | None = None
    fillOpacity: float | None = None


class ChartProvenance(BaseModel):
    """Flexible chart lineage metadata.

    List fields are used for simple single-source or same-shape series
    inventories. Mapping fields are used when chart data keys or labels need to
    be tied back to distinct source series, files, or raw latest observations.
    Extra keys remain allowed so generated analysis scripts can attach
    provider-specific lineage without forcing a schema migration.
    """

    model_config = ConfigDict(extra="allow")

    source_series: list[str] | dict[str, Any] | None = None
    source_files: list[str] | dict[str, Any] | None = None
    raw_window: dict[str, Any] | None = None
    raw_latest_observation: str | dict[str, Any] | None = None
    displayed_window: dict[str, Any] | None = None
    displayed_latest_label: str | dict[str, Any] | None = None
    frequency: str | None = None
    resampling: str | dict[str, Any] | None = None
    normalization: dict[str, Any] | None = None
    limitations: list[str] | str | None = None


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
    provenance: ChartProvenance | None = None


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
    provenance: ChartProvenance | None = None


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
    provenance: ChartProvenance | None = None


class RadarChartDef(BaseModel):
    id: str
    type: Literal["radar"]
    title: str
    description: str
    angleKey: str
    series: list[AxisSeries]
    data: list[dict]
    provenance: ChartProvenance | None = None


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
    provenance: ChartProvenance | None = None


class FunnelChartDef(BaseModel):
    id: str
    type: Literal["funnel"]
    title: str
    description: str
    data: list[SegmentDatum]
    dataKey: str | None = None
    nameKey: str | None = None
    provenance: ChartProvenance | None = None


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
    provenance: ChartProvenance | None = None


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
    provenance: ChartProvenance | None = None


class SunburstChartDef(BaseModel):
    id: str
    type: Literal["sunburst"]
    title: str
    description: str
    data: HierarchyDatum
    valueKey: Literal["value", "size"] | None = None
    provenance: ChartProvenance | None = None


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
    "ReferenceLine",
    "ReferenceArea",
    "ChartProvenance",
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
    "ReportMetadata",
    "ResearchReport",
]
