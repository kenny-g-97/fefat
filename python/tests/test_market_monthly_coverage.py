"""A quality report's coverage by month (step 5.4, from `BACKLOG.md`): each month's sessions, those
with records, the days with records at each fidelity, the findings, and the sessions the vendor
flagged, which the report's markdown prints and the API sends for the catalog page's strip."""

from datetime import date
from pathlib import Path

import polars as pl

from fefat.market.monthly_coverage import MONTH_COLUMNS, coverage_by_month
from fefat.market.quality import assess_quality
from fefat.market.quality_report import (
    DAY_COLUMNS,
    FINDING_COLUMNS,
    stored_coverage_by_month,
    write_quality_report,
)
from fefat.market.store import Store

FIXTURES = Store(Path(__file__).resolve().parents[2] / "fixtures")


def test_each_month_counts_its_sessions_fidelities_findings_and_flagged_days() -> None:
    # A Friday of ticks, then a Monday without records, which the vendor called available and a
    # gap was found on, and a Tuesday of 1-minute bars the vendor flagged degraded.
    days = pl.DataFrame(
        {
            "trade_date": [date(2026, 2, 27), date(2026, 3, 2), date(2026, 3, 3)],
            "records": [10, 0, 5],
            "ticks": [10, 0, 0],
            "bars_1s": [0, 0, 0],
            "bars_1m": [0, 0, 5],
            "break_prints": [0, 0, 0],
            "halt_prints": [0, 0, 0],
            "bar_differences": [None, None, None],
            "vendor_condition": [None, "available", "degraded"],
            "held_back_bars": [0, 0, 0],
        },
        schema=DAY_COLUMNS,
    )
    findings = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, 2)],
            "kind": ["gap"],
            "schema": ["ohlcv-1m"],
            "contract": [None],
            "count": [1],
        },
        schema=FINDING_COLUMNS,
    )

    months = coverage_by_month(days, findings)

    assert months.schema == MONTH_COLUMNS
    assert months.rows() == [
        ("2026-02", 1, 1, 1, 0, 0, 0, 0),
        ("2026-03", 2, 1, 0, 0, 1, 1, 1),
    ]


def test_a_reports_months_read_back_and_none_while_it_is_unwritten(tmp_path: Path) -> None:
    # The fixtures' three sessions of ES in March, each with ticks and both sizes of bars, as the
    # report's markdown counts them.
    reports = tmp_path / "reports"
    unwritten = stored_coverage_by_month(reports, "synthetic", "ES")
    write_quality_report(assess_quality(FIXTURES, "synthetic", "ES", tmp_path / "cache"), reports)

    months = stored_coverage_by_month(reports, "synthetic", "ES")

    assert (unwritten.schema, unwritten.height) == (MONTH_COLUMNS, 0)
    assert months.rows() == [("2026-03", 3, 3, 3, 3, 3, 0, 0)]
