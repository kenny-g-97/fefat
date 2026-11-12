"""A quality report's coverage by month (steps 1.8 and 5.4): each month's sessions, those with
records, the days with records at each fidelity, the findings, and the sessions the vendor
flagged, which the report's markdown prints as a table (`fefat.market.quality_report`) and the
API sends with a dataset's quality, for the catalog page's coverage strip.

    coverage_by_month(report.days, report.findings)
"""

import polars as pl

from fefat.market.importers.report import VendorCondition

MONTH_COLUMNS = pl.Schema(
    {
        "month": pl.String,
        "sessions": pl.UInt32,
        "with_records": pl.UInt32,
        "tick_days": pl.UInt32,
        "second_days": pl.UInt32,
        "minute_days": pl.UInt32,
        "findings": pl.UInt32,
        "vendor_flagged": pl.UInt32,
    }
)
"""A month's row: the month, `2026-03`; its sessions, those with records of any schema, those
with ticks, with 1-second bars, and with 1-minute bars; its findings; and the sessions touching a
UTC day the vendor marks other than available."""


def coverage_by_month(days: pl.DataFrame, findings: pl.DataFrame) -> pl.DataFrame:
    """The months of a report's `days` and `findings` (`fefat.market.quality_report`'s
    `DAY_COLUMNS` and `FINDING_COLUMNS`), with the columns of `MONTH_COLUMNS`, in order."""
    month = pl.col("trade_date").dt.strftime("%Y-%m").alias("month")
    found = findings.group_by(month).agg(findings=pl.len())
    return (
        days.group_by(month)
        .agg(
            sessions=pl.len(),
            with_records=(pl.col("records") > 0).sum(),
            tick_days=(pl.col("ticks") > 0).sum(),
            second_days=(pl.col("bars_1s") > 0).sum(),
            minute_days=(pl.col("bars_1m") > 0).sum(),
            vendor_flagged=flagged_by_the_vendor().sum(),
        )
        .join(found, on="month", how="left")
        .with_columns(pl.col("findings").fill_null(0))
        .sort("month")
        .select(MONTH_COLUMNS.names())
        .cast(MONTH_COLUMNS)
    )


def flagged_by_the_vendor() -> pl.Expr:
    """Whether a report's day touches a UTC day its vendor marks other than available."""
    condition = pl.col("vendor_condition")
    return condition.is_not_null() & (condition != str(VendorCondition.AVAILABLE))
