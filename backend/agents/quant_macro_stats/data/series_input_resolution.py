"""Shared input contracts for deterministic macro artifact builders."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import pandas as pd

from .period_alignment import align_period_features
from .series_io import find_data_file_key, read_value_series


@dataclass(frozen=True)
class SeriesSpec:
    """Declare how an artifact builder resolves one input series."""

    name: str
    candidates: tuple[str, ...]
    required: bool = True
    aliases: tuple[str, ...] = ()
    missing_label: str | None = None
    column: str | None = None
    use_source_key_as_column: bool = False
    fill_method: str | None = None
    fill_limit: int | None = None
    allow_prefix: bool | None = None
    search_path_stem: bool | None = None
    distinct_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", _as_tuple(self.candidates))
        object.__setattr__(self, "aliases", _as_tuple(self.aliases))
        object.__setattr__(self, "distinct_from", _as_tuple(self.distinct_from))

    @property
    def all_candidates(self) -> tuple[str, ...]:
        return (*self.candidates, *self.aliases)

    @property
    def label(self) -> str:
        return self.missing_label or self.name

    def panel_column(self, source_key: str | None) -> str:
        if self.use_source_key_as_column and source_key is not None:
            return str(source_key)
        return self.column or self.name


@dataclass(frozen=True)
class ResolvedSeries:
    """Resolution metadata for one declared input series."""

    name: str
    source_key: str | None
    source_path: str | None
    column: str
    required: bool
    missing_label: str
    candidates: tuple[str, ...]
    fill_method: str | None = None
    fill_limit: int | None = None

    @property
    def available(self) -> bool:
        return self.source_key is not None and self.source_path is not None


@dataclass(frozen=True)
class ArtifactInputResolution:
    """Resolved source keys and missing-input metadata for an artifact builder."""

    series: dict[str, ResolvedSeries]
    missing_required: tuple[str, ...]

    @property
    def resolved_sources(self) -> dict[str, str]:
        return {
            name: item.source_key
            for name, item in self.series.items()
            if item.source_key is not None
        }

    @property
    def resolved_columns(self) -> dict[str, str]:
        return {
            name: item.column
            for name, item in self.series.items()
            if item.source_key is not None
        }

    @property
    def proxy_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        for name, item in self.series.items():
            if item.source_key is None:
                continue
            if item.source_key != item.column or item.source_key != name:
                labels[name] = item.source_key
        return labels

    def source_key(self, name: str) -> str | None:
        item = self.series.get(name)
        return item.source_key if item else None

    def source_path(self, name: str) -> str | None:
        item = self.series.get(name)
        return item.source_path if item else None

    def column(self, name: str) -> str | None:
        item = self.series.get(name)
        return item.column if item and item.available else None

    def available(self, name: str) -> bool:
        item = self.series.get(name)
        return bool(item and item.available)


@dataclass(frozen=True)
class ArtifactInputPanel:
    """Aligned monthly panel plus the source-resolution contract used to build it."""

    panel: pd.DataFrame
    resolution: ArtifactInputResolution

    def source_key(self, name: str) -> str | None:
        return self.resolution.source_key(name)

    def source_path(self, name: str) -> str | None:
        return self.resolution.source_path(name)

    def column(self, name: str) -> str | None:
        return self.resolution.column(name)

    def available(self, name: str) -> bool:
        return self.resolution.available(name)


def resolve_series_sources(
    data_files: Mapping[str, str],
    specs: Sequence[SeriesSpec],
    *,
    allow_prefix: bool = False,
    search_path_stem: bool = False,
    require_any: Mapping[str, Sequence[str]] | None = None,
) -> ArtifactInputResolution:
    """Resolve declared series specs against a local data-file manifest."""

    resolved: dict[str, ResolvedSeries] = {}
    missing: list[str] = []
    for spec in specs:
        source_key = find_data_file_key(
            dict(data_files),
            spec.all_candidates,
            allow_prefix=allow_prefix if spec.allow_prefix is None else spec.allow_prefix,
            search_path_stem=(
                search_path_stem
                if spec.search_path_stem is None
                else spec.search_path_stem
            ),
        )
        source_path = str(data_files[source_key]) if source_key is not None else None
        resolved[spec.name] = ResolvedSeries(
            name=spec.name,
            source_key=source_key,
            source_path=source_path,
            column=spec.panel_column(source_key),
            required=spec.required,
            missing_label=spec.label,
            candidates=spec.all_candidates,
            fill_method=spec.fill_method,
            fill_limit=spec.fill_limit,
        )

    for spec in specs:
        item = resolved[spec.name]
        if not item.available:
            continue
        duplicate_of = [
            other_name
            for other_name in spec.distinct_from
            if resolved.get(other_name)
            and resolved[other_name].source_key == item.source_key
        ]
        if not duplicate_of:
            continue
        resolved[spec.name] = ResolvedSeries(
            name=item.name,
            source_key=None,
            source_path=None,
            column=spec.panel_column(None),
            required=item.required,
            missing_label=item.missing_label,
            candidates=item.candidates,
            fill_method=item.fill_method,
            fill_limit=item.fill_limit,
        )

    for item in resolved.values():
        if item.required and not item.available:
            _append_missing(missing, item.missing_label)
    for label, names in (require_any or {}).items():
        if not any(resolved.get(name) and resolved[name].available for name in names):
            _append_missing(missing, str(label))

    return ArtifactInputResolution(series=resolved, missing_required=tuple(missing))


def load_monthly_panel(
    data_files: Mapping[str, str],
    specs: Sequence[SeriesSpec],
    *,
    context: str,
    allow_prefix: bool = False,
    search_path_stem: bool = False,
    require_any: Mapping[str, Sequence[str]] | None = None,
    raise_on_missing: bool = True,
    missing_prefix: str = "missing required FRED series",
    frequency: str = "M",
    aggregation: str = "mean",
    how: str = "outer",
    max_date: str | pd.Timestamp | None = None,
) -> ArtifactInputPanel:
    """Load resolved local value series into one aligned monthly panel."""

    resolution = resolve_series_sources(
        data_files,
        specs,
        allow_prefix=allow_prefix,
        search_path_stem=search_path_stem,
        require_any=require_any,
    )
    if resolution.missing_required and raise_on_missing:
        raise ValueError(
            f"{missing_prefix} for {context}: {', '.join(resolution.missing_required)}"
        )

    frames: dict[str, pd.DataFrame] = {}
    resolved_series = dict(resolution.series)
    missing_required = list(resolution.missing_required)
    if max_date == "today":
        max_timestamp = pd.Timestamp.today().normalize()
    elif max_date is None:
        max_timestamp = None
    else:
        max_timestamp = pd.Timestamp(max_date).normalize()

    specs_by_name = {spec.name: spec for spec in specs}
    for item in resolution.series.values():
        if not item.available or item.source_path is None:
            continue
        frame = read_value_series(item.source_path, item.column)
        dates = pd.to_datetime(frame["date"], errors="coerce")
        values = pd.to_numeric(frame[item.column], errors="coerce")
        usable = dates.notna() & values.notna()
        if max_timestamp is not None:
            usable &= dates <= max_timestamp
        if not usable.any():
            if item.required:
                raise ValueError(
                    f"Series '{item.column}' has no usable numeric observations after cleaning"
                )
            spec = specs_by_name[item.name]
            resolved_series[item.name] = replace(
                item,
                source_key=None,
                source_path=None,
                column=spec.panel_column(None),
            )
            continue
        frames[item.column] = frame

    for label, names in (require_any or {}).items():
        if not any(
            resolved_series.get(name) and resolved_series[name].available
            for name in names
        ):
            _append_missing(missing_required, str(label))

    resolution = ArtifactInputResolution(
        series=resolved_series,
        missing_required=tuple(missing_required),
    )
    if resolution.missing_required and raise_on_missing:
        raise ValueError(
            f"{missing_prefix} for {context}: {', '.join(resolution.missing_required)}"
        )
    if not frames:
        raise ValueError(f"no usable local series resolved for {context}")
    panel = align_period_features(
        frames,
        frequency=frequency,
        aggregation=aggregation,
        how=how,
        max_date=max_date,
    )
    panel = panel.sort_values("date").reset_index(drop=True)
    for item in resolution.series.values():
        if not item.available or item.column not in panel or item.fill_method is None:
            continue
        if item.fill_method != "ffill":
            raise ValueError("SeriesSpec.fill_method must be None or 'ffill'")
        panel[item.column] = pd.to_numeric(panel[item.column], errors="coerce").ffill(
            limit=item.fill_limit
        )
    return ArtifactInputPanel(panel=panel, resolution=resolution)


def _append_missing(missing: list[str], label: str) -> None:
    if label not in missing:
        missing.append(label)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)
