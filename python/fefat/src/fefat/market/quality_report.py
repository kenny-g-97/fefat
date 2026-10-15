"""What a quality report holds, the files it is kept in, and the standing the catalog reads
back (step 1.8); `fefat.market.quality` assesses the store.

A report covers a root's trades and bars from one provider. It is kept in
`<FEFAT_DATA_DIR>/reports/<provider>/<root>/` as two tables and a summary for a person:
`days.parquet`, a row per session from the root's first trade date to its last
(`DAY_COLUMNS`); `findings.parquet`, a row per finding (`FINDING_COLUMNS`); and `quality.md`,
the coverage of each month beside what was found. No file is named `part.parquet`, and the
store never reads `reports` as a provider (`fefat.market.layout`).

    report = assess_quality(store, "databento", "MES", paths.cache_dir)
    folder = write_quality_report(report, paths.reports_dir)
    quality_standing(paths.reports_dir, "databento", "MES").status
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import polars as pl
from pydantic import model_validator

from fefat.market.calendar import utc_text
from fefat.market.importers.report import ConditionDay, VendorCondition
from fefat.market.schema import FrozenModel, require_columns
from fefat.market.store import write_atomically

DAYS_FILE_NAME = "days.parquet"
FINDINGS_FILE_NAME = "findings.parquet"
MARKDOWN_FILE_NAME = "quality.md"
DAY_COLUMNS = pl.Schema(
    {
        "trade_date": pl.Date,
        "records": pl.Int64,
        "ticks": pl.Int64,
        "bars_1s": pl.Int64,
        "bars_1m": pl.Int64,
        "break_prints": pl.Int64,
        "halt_prints": pl.Int64,
        "bar_differences": pl.Int64,
        "vendor_condition": pl.String,
        "held_back_bars": pl.Int64,
    }
)
"""A report's row per session: its trade date; its records of every schema, then those of
each fidelity (trades and TBBO, 1-second bars, 1-minute bars); the records received in the
break after its close and inside its halts, which keep its trade date (D-43); the differences
of its bars from bars rebuilt from finer data, null where none were rebuilt; the worst
condition the vendor gives a UTC day the session touches, null without the vendor's
conditions; and the one-minute buckets held back at the end of the data."""
FINDING_COLUMNS = pl.Schema(
    {
        "trade_date": pl.Date,
        "kind": pl.String,
        "schema": pl.String,
        "contract": pl.String,
        "count": pl.Int64,
    }
)
"""A report's row per finding: the trade date, the `QualityFinding`, the schema, the contract
(null for a gap, which no contract fills), and how many records or bars it counts."""

_LISTED_AT_MOST = 10
"""How many findings a summary, or dates a line, names before saying how many more there are."""
_TABLE_ROWS_AT_MOST = 200
_MONTH_HEADING = (
    "| Month | Sessions | With records | Tick days | 1s days | 1m days | Findings "
    "| Vendor-flagged days |"
)


class QualityFinding(StrEnum):
    """What a report finds wrong with a dataset on a trade date: a session without records,
    repeated records, records outside their session and its break, decreases of the clock
    between stored rows, prices of zero or below where none are allowed, and bars that differ
    from those rebuilt from finer data."""

    GAP = "gap"
    DUPLICATES = "duplicates"
    OUT_OF_SESSION = "out-of-session"
    CLOCK_DECREASES = "clock-decreases"
    NON_POSITIVE_PRICES = "non-positive-prices"
    BAR_DIFFERENCES = "bar-differences"


class QualityStatus(StrEnum):
    """A root's verdict from one provider: no finding, some, or no report yet."""

    CLEAN = "clean"
    FLAGGED = "flagged"
    UNCHECKED = "unchecked"


class QualityStanding(FrozenModel):
    """What the catalog shows of a root's report: its status and the last trade date it
    checked, which an unchecked root has none of."""

    status: QualityStatus
    checked_through: date | None

    @model_validator(mode="after")
    def _dated_once_checked(self) -> Self:
        unchecked = self.status is QualityStatus.UNCHECKED
        if unchecked == (self.checked_through is None):
            return self
        expected = "no last trade date" if unchecked else "the last trade date checked"
        raise ValueError(
            f"Expected {expected} for a {self.status} report, got {self.checked_through}."
        )


@dataclass(frozen=True, eq=False)
class QualityReport:
    """What `fefat.market.quality.assess_quality` found in a root's data from one provider:
    its contracts, the instant by which every record was received, the days its vendor marks
    other than available (UTC dates, as the vendor gives them), and the two tables, sorted."""

    provider: str
    root: str
    contracts: tuple[str, ...]
    received_until: int
    vendor_days: tuple[ConditionDay, ...]
    days: pl.DataFrame
    findings: pl.DataFrame

    def __post_init__(self) -> None:
        source = f"the quality report of {self.provider} {self.root}"
        require_columns(DAY_COLUMNS, self.days.schema, f"the days of {source}")
        require_columns(FINDING_COLUMNS, self.findings.schema, f"the findings of {source}")
        if self.days.is_empty():
            raise ValueError(f"Expected a session in {source}, got none.")

    def status(self) -> QualityStatus:
        """Clean without findings, flagged with any."""
        return QualityStatus.CLEAN if self.findings.is_empty() else QualityStatus.FLAGGED

    def summary(self) -> str:
        """A line with the trade dates and the status, then a line per finding, the first ten."""
        heading = f"Quality of {self.provider} {self.root}, {self._span()}: {self.status()}"
        if self.findings.is_empty():
            return f"{heading}."
        lines = [f"{heading}, {_counted(self.findings.height, 'finding')}."]
        listed = self.findings.head(_LISTED_AT_MOST).iter_rows(named=True)
        lines.extend(_finding_line(finding) for finding in listed)
        if self.findings.height > _LISTED_AT_MOST:
            lines.append(f"  and {self.findings.height - _LISTED_AT_MOST:,} more")
        return "\n".join(lines)

    def markdown(self) -> str:
        """The report for a person: what the data covers month by month, what was found, the
        vendor's flagged days, the prints in breaks and halts, the bars rebuilt, and where the
        data ends."""
        sections = (
            ("Coverage by month", _coverage_by_month(self)),
            ("Findings", _finding_table(self.findings)),
            ("Days the vendor flagged", [_vendor_line(self)]),
            ("Prints in breaks and halts", _break_and_halt_lines(self.days)),
            ("Bars against finer data", _rebuilt_lines(self.days)),
            ("Last session", [_last_session_line(self)]),
        )
        lines = [f"# Quality of {self.provider} {self.root}", "", self._overview()]
        lines.extend(["", self._status_line()])
        for title, body in sections:
            lines.extend(["", f"## {title}", "", *body])
        return "\n".join(lines) + "\n"

    def _span(self) -> str:
        dates = self.days.get_column("trade_date")
        return f"{dates.min()} to {dates.max()}"

    def _overview(self) -> str:
        sessions = _counted(self.days.height, "session")
        with_records = self.days.filter(pl.col("records") > 0).height
        contracts = _counted(len(self.contracts), "contract")
        return (
            f"Trade dates {self._span()}: {sessions}, {with_records:,} with records, {contracts}."
        )

    def _status_line(self) -> str:
        if self.findings.is_empty():
            return f"Status: {self.status()}, no findings."
        return f"Status: {self.status()}, {_counted(self.findings.height, 'finding')}."


def write_quality_report(report: QualityReport, reports_folder: Path) -> Path:
    """Write the report's two tables and its summary to `<reports_folder>/<provider>/<root>/`,
    each file replaced in one step, and return the folder."""
    folder = reports_folder / report.provider / report.root
    markdown = report.markdown().encode("utf-8")
    write_atomically(folder / DAYS_FILE_NAME, report.days.write_parquet)
    write_atomically(folder / FINDINGS_FILE_NAME, report.findings.write_parquet)
    write_atomically(folder / MARKDOWN_FILE_NAME, lambda temporary: temporary.write_bytes(markdown))
    return folder


def quality_standing(reports_folder: Path, provider: str, root: str) -> QualityStanding:
    """The status of the root's report from `provider` and the last trade date it checked;
    unchecked while no report is written. Tables whose columns differ are refused."""
    folder = reports_folder / provider / root
    days_path, findings_path = folder / DAYS_FILE_NAME, folder / FINDINGS_FILE_NAME
    if not (days_path.is_file() and findings_path.is_file()):
        return QualityStanding(status=QualityStatus.UNCHECKED, checked_through=None)
    days = pl.read_parquet(days_path)
    findings = pl.read_parquet(findings_path)
    require_columns(DAY_COLUMNS, days.schema, str(days_path))
    require_columns(FINDING_COLUMNS, findings.schema, str(findings_path))
    status = QualityStatus.CLEAN if findings.is_empty() else QualityStatus.FLAGGED
    checked_through = days.select(pl.col("trade_date").max()).item()
    return QualityStanding(status=status, checked_through=checked_through)


def _counted(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def _finding_line(finding: dict[str, Any]) -> str:
    contract = "" if finding["contract"] is None else f" {finding['contract']}"
    where = f"{finding['kind']} in {finding['schema']}{contract}"
    return f"  {finding['trade_date']} {where}: {finding['count']:,}"


def _dates(dates: pl.Series) -> str:
    named = ", ".join(str(day) for day in dates.head(_LISTED_AT_MOST).to_list())
    if dates.len() > _LISTED_AT_MOST:
        return f"{named}, and {dates.len() - _LISTED_AT_MOST:,} more trade dates"
    return named


def _flagged_by_the_vendor() -> pl.Expr:
    condition = pl.col("vendor_condition")
    return condition.is_not_null() & (condition != str(VendorCondition.AVAILABLE))


def _coverage_by_month(report: QualityReport) -> list[str]:
    """A table row per month: its sessions, those with records, the days with records at each
    fidelity, the findings, and the sessions the vendor flagged."""
    month = pl.col("trade_date").dt.strftime("%Y-%m").alias("month")
    findings = report.findings.group_by(month).agg(findings=pl.len())
    months = (
        report.days.group_by(month)
        .agg(
            sessions=pl.len(),
            with_records=(pl.col("records") > 0).sum(),
            tick_days=(pl.col("ticks") > 0).sum(),
            second_days=(pl.col("bars_1s") > 0).sum(),
            minute_days=(pl.col("bars_1m") > 0).sum(),
            flagged=_flagged_by_the_vendor().sum(),
        )
        .join(findings, on="month", how="left")
        .with_columns(pl.col("findings").fill_null(0))
        .sort("month")
    )
    order = ("month", "sessions", "with_records", "tick_days", "second_days", "minute_days")
    rows = months.select(*order, "findings", "flagged").iter_rows()
    table = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return [_MONTH_HEADING, "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |", *table]


def _finding_table(findings: pl.DataFrame) -> list[str]:
    """A table row per finding, the first 200, or a line saying there are none."""
    if findings.is_empty():
        return ["None."]
    table = [
        "| Trade date | Kind | Schema | Contract | Count |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for finding in findings.head(_TABLE_ROWS_AT_MOST).iter_rows(named=True):
        contract = "" if finding["contract"] is None else finding["contract"]
        cells = (finding["trade_date"], finding["kind"], finding["schema"], contract)
        table.append("| " + " | ".join(str(cell) for cell in cells) + f" | {finding['count']:,} |")
    if findings.height > _TABLE_ROWS_AT_MOST:
        more = findings.height - _TABLE_ROWS_AT_MOST
        table.extend(["", f"And {more:,} more, in {FINDINGS_FILE_NAME}."])
    return table


def _vendor_line(report: QualityReport) -> str:
    """The vendor's flagged days with the trade dates they touch, or why there are none."""
    touched = report.days.filter(_flagged_by_the_vendor()).get_column("trade_date")
    if report.vendor_days:
        flagged = ", ".join(f"{day.day} {day.condition}" for day in report.vendor_days)
        dates = _dates(touched) if not touched.is_empty() else "none of these sessions"
        return f"The vendor's UTC days {flagged}; the trade dates they touch: {dates}."
    if report.days.get_column("vendor_condition").is_null().all():
        return f"The provider {report.provider} gives no conditions."
    return "None: the vendor marks every day available."


def _break_and_halt_lines(days: pl.DataFrame) -> list[str]:
    in_the_break = _counted_on(days, "break_prints")
    return [
        f"Received in the break after a close, keeping their session's trade date: {in_the_break}.",
        f"Received inside a halt: {_counted_on(days, 'halt_prints')}.",
    ]


def _counted_on(days: pl.DataFrame, column: str) -> str:
    on = days.filter(pl.col(column) > 0)
    if on.is_empty():
        return "none"
    return f"{on.get_column(column).sum():,}, on {_dates(on.get_column('trade_date'))}"


def _rebuilt_lines(days: pl.DataFrame) -> list[str]:
    return [
        _rebuilt_line(days),
        "A trade date is compared when the store holds its bars and finer data and its records "
        "hold no finding.",
    ]


def _rebuilt_line(days: pl.DataFrame) -> str:
    compared = days.filter(pl.col("bar_differences").is_not_null())
    if compared.is_empty():
        return f"Rebuilt and compared on none of the {days.height:,} trade dates."
    differences = int(compared.get_column("bar_differences").sum())
    outcome = f"{_counted(differences, 'difference')}, in the findings"
    if differences == 0:
        outcome = "no differences"
    return f"Rebuilt and compared on {compared.height:,} of {days.height:,} trade dates: {outcome}."


def _last_session_line(report: QualityReport) -> str:
    last = report.days.row(-1, named=True)
    ends = f"The data ends at {utc_text(report.received_until)}"
    if last["held_back_bars"] == 0:
        return f"{ends}, with its last session, {last['trade_date']}, complete."
    held_back = f"its last {last['held_back_bars']:,} one-minute buckets are held back"
    return (
        f"{ends}, inside the session of {last['trade_date']}: {held_back} until later data "
        "completes it."
    )
