"""A feature's preview in the runner (step 4.5): the feature its code defines, built with
`ff.features.from_source` and computed with `ff.features.compute`, whose cache serves a repeated
preview, over the bars its spec names; each output's statistics over its finite values; and each
output's series downsampled, the glossary's way, to at most `SERIES_POINTS` points that keep its
highs and lows, written to `series.parquet`."""

import warnings
from pathlib import Path

import polars as pl

import fefat as ff
from fefat.features.runtime import slot_columns
from fefat_app.execution import (
    ExecutionProgress,
    FeaturePreviewSpec,
    ProgressReport,
    SeriesStatistics,
)
from fefat_app.executor.protocol import (
    SERIES_FILE,
    SERIES_POINTS,
    SERIES_SCHEMA,
    PreviewSummary,
)

SLOT = "preview"
"""The slot a preview computes its feature in, named apart from the bars' columns."""


def preview(spec: FeaturePreviewSpec, folder: Path, report: ProgressReport) -> PreviewSummary:
    """Compute `spec`'s feature (module docstring), leaving its series in `folder`; its
    statistics, and what the bars' loading warned of."""
    definition = ff.features.from_source(spec.code)
    feature = definition(**spec.parameters)
    report(ExecutionProgress(percent=10, message=f"Built {definition.name}", details={}))
    bars = spec.bars
    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        computed = ff.features.compute(
            {SLOT: feature},
            bars.instrument,
            bars.timeframe,
            bars.start,
            bars.end,
            provider=bars.provider,
        ).collect()
    report(
        ExecutionProgress(
            percent=70,
            message=f"Computed {definition.name} on {computed.height:,} bars",
            details={"bars": computed.height},
        )
    )
    columns = slot_columns(SLOT, feature)
    series = pl.concat(
        [downsampled(computed, output, column) for output, column in columns.items()]
    )
    series.write_parquet(folder / SERIES_FILE)
    report(
        ExecutionProgress(
            percent=90,
            message=f"Kept {series.height:,} points of the series",
            details={"points": series.height},
        )
    )
    return PreviewSummary(
        statistics={output: statistics_of(computed, column) for output, column in columns.items()},
        warnings=tuple(str(warning.message) for warning in warned),
    )


def statistics_of(computed: pl.DataFrame, column: str) -> SeriesStatistics:
    """The figures of `column` over its finite values, its share of values null, NaN, or infinite
    among all its bars."""
    value = pl.col(column).cast(pl.Float64)
    finite = value.filter(value.is_finite())
    figures = computed.select(
        count=finite.count(),
        missing_share=1 - finite.count() / pl.len(),
        min=finite.min(),
        max=finite.max(),
        mean=finite.mean(),
        std=finite.std(),
        last=finite.last(),
    )
    return SeriesStatistics.model_validate(figures.row(0, named=True))


def downsampled(computed: pl.DataFrame, output: str, column: str) -> pl.DataFrame:
    """The finite values of `column`, the output `output`, by the close of their bars, in the
    columns of `SERIES_SCHEMA`: all of them up to `SERIES_POINTS`, else the lowest and the highest,
    the first of equals, of each of half as many buckets of as many bars."""
    finite = computed.select(
        output=pl.lit(output, dtype=pl.String),
        ts_close=pl.col("ts_close").cast(pl.Int64),
        value=pl.col(column).cast(pl.Float64),
    ).filter(pl.col("value").is_finite())
    if finite.height <= SERIES_POINTS:
        return finite
    buckets = SERIES_POINTS // 2
    numbered = finite.with_row_index("row").with_columns(
        bucket=pl.col("row").cast(pl.Int64) * buckets // finite.height
    )
    row = pl.col("row")
    lowest = row == row.get(pl.col("value").arg_min()).over("bucket")
    highest = row == row.get(pl.col("value").arg_max()).over("bucket")
    return numbered.filter(lowest | highest).select(SERIES_SCHEMA.names())
