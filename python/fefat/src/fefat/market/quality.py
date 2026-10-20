"""The data-quality report of a root's trades and bars from one provider, session by session
(`02-engine-and-data.md` §1.1, step 1.8). What a report holds and where it is kept is
`fefat.market.quality_report`; the checks that read every record are
`fefat.market.quality_checks`.

Every trades, TBBO, and bars dataset of the root is read once, partition by partition. The
report finds, per dataset, contract, and trade date:

- a **gap**: a session between the dataset's first and last trade date without a record of
  any contract (a minute without trades is no gap: bars are sparse);
- **duplicates**: a record repeated exactly (ticks), or a second bar of an instrument opening
  at the same instant (bars);
- **out-of-session** records: before their session's open, from the next session's open on,
  or on a date without a session, such as ticks filed under the wrong trade date;
- **clock decreases** between the stored rows of a partition, in their stored order;
- **non-positive prices**: a price, or a bar's open, high, low, or close, of zero or below,
  where `fefat.market.quality_checks.NEGATIVE_PRICES_ALLOWED` allows none;
- **bar differences**: bars that differ from those rebuilt from the finer data the store holds
  (`fefat.market.bars_check.verify_bars`), on each trade date whose records hold no other
  finding, so that one wrong record is found once.

It also counts, per session, the records at each fidelity; those received in the break after
the close, which keep its trade date (D-43), and inside its halts, neither of them wrong; the
worst condition the vendor gives a UTC day the session touches (the `condition.json` kept
with each Databento batch download); and, on the last trade date, the one-minute buckets after
the end of the data, which bars and the session grid hold back until later data completes
them (`fefat.market.bars`). Out-of-session prints on real data often point at the calendar,
such as an early close its holiday rules lack: fix its override table
(`fefat.market.builtin_calendars.OVERRIDES`), not the data. Rebuilding bars lists the store
and reads a trade date's finer data once per trade date, so a long history of ticks takes
minutes.

    paths = resolve_paths(os.environ)
    report = assess_quality(Store(paths.data_dir), "databento", "MES", paths.cache_dir)
    write_quality_report(report, paths.reports_dir)
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path

import polars as pl

from fefat.market.bars_check import STORED_FROM_FINER, BarsReport, ComparedBars, verify_bars
from fefat.market.calendar import sessions_of
from fefat.market.coverage import DatasetCoverage, dataset_coverage, session_datasets
from fefat.market.importers.databento import PROVIDER as DATABENTO
from fefat.market.importers.databento import vendor_conditions
from fefat.market.importers.report import ConditionDay, VendorCondition
from fefat.market.layout import Dataset
from fefat.market.quality_checks import RECORD_FINDINGS, checked_records, gaps
from fefat.market.quality_report import (
    DAY_COLUMNS,
    FINDING_COLUMNS,
    QualityFinding,
    QualityReport,
)
from fefat.market.saved_instruments import instrument_table
from fefat.market.store import Store

_TICK_SCHEMAS = ("trades", "tbbo")
_MINUTE = 60_000_000_000
_DAY = 86_400_000_000_000
_WORST_LAST = (
    VendorCondition.AVAILABLE,
    VendorCondition.DEGRADED,
    VendorCondition.PENDING,
    VendorCondition.MISSING,
)
_SEVERITY = {str(condition): rank for rank, condition in enumerate(_WORST_LAST)}
_DIFFERENCE_COLUMNS = pl.Schema(
    {"trade_date": pl.Date, "schema": pl.String, "instrument_id": pl.UInt32, "count": pl.Int64}
)
_VENDOR_DAY_COLUMNS = pl.Schema({"date": pl.Date, "condition": pl.String})


def assess_quality(store: Store, provider: str, root: str, cache_folder: Path) -> QualityReport:
    """The quality report of `root`'s trades, TBBO, and bars from `provider` in `store`, in
    the sessions of the root's calendar, whose table is kept in `cache_folder`. A root without
    such data from the provider, or missing from the instrument table, is refused."""
    covered = _covered_datasets(store, provider, root)
    # shortcut: the calendar of the root's newest instrument version, as the calendar check
    # takes it; split the report by version when a root's calendar changes over time.
    instrument = instrument_table(store.folder).get(root)
    sessions = sessions_of(instrument.session_calendar(), cache_folder)
    first = min(coverage.first_trade_date for coverage in covered.values())
    last = max(coverage.last_trade_date for coverage in covered.values())
    received_until = max(coverage.received_until for coverage in covered.values())
    bounds = sessions.between_with_next_opens(first, last)
    records = checked_records(store, covered, bounds, root)
    differences = _bar_differences(store, provider, root, covered, records, bounds, cache_folder)
    vendor_days = _vendor_days(store, provider)
    contracts = {contract for coverage in covered.values() for contract in coverage.contracts}
    return QualityReport(
        provider=provider,
        root=root,
        contracts=tuple(sorted(contracts)),
        received_until=received_until,
        vendor_days=_flagged(vendor_days, bounds),
        days=_days(bounds, records, differences, _conditions(bounds, vendor_days), received_until),
        findings=_findings(records, gaps(records, covered, bounds), differences),
    )


def _covered_datasets(store: Store, provider: str, root: str) -> dict[Dataset, DatasetCoverage]:
    """The provider's trades, TBBO, and bars datasets of the root that hold partitions, with
    their coverage; none is refused."""
    checked = (
        dataset
        for dataset in session_datasets(store)
        if dataset.provider == provider and dataset.root == root
    )
    covered = {
        dataset: coverage
        for dataset in checked
        if (coverage := dataset_coverage(store, dataset)) is not None
    }
    if not covered:
        raise ValueError(
            f"Expected trades or bars of {root} from {provider} in the store, got none."
        )
    return covered


def _bar_differences(
    store: Store,
    provider: str,
    root: str,
    covered: Mapping[Dataset, DatasetCoverage],
    records: pl.DataFrame,
    bounds: pl.DataFrame,
    cache_folder: Path,
) -> pl.DataFrame:
    """For each trade date whose bars were rebuilt from the provider's finer data, a row
    without a schema and a count of 0, and a row per schema and contract with differences;
    none when the provider holds no finer data than its bars."""
    held = {str(dataset.schema_name) for dataset in covered}
    rebuilt = (str(finer) in held and str(bars) in held for finer, bars in STORED_FROM_FINER)
    if not any(rebuilt):
        return pl.DataFrame(schema={**_DIFFERENCE_COLUMNS, "contract": pl.String})
    found = [
        row
        for day in _days_to_rebuild(records, bounds)
        for row in _differences_on(verify_bars(store, root, day, cache_folder), provider, day)
    ]
    contracts = (
        records.select("trade_date", "contract", instrument_id="instrument_ids")
        .explode("instrument_id")
        .unique()
    )
    return (
        pl.DataFrame(found, schema=_DIFFERENCE_COLUMNS, orient="row")
        .join(contracts, on=["trade_date", "instrument_id"], how="left")
        .group_by("trade_date", "schema", "contract")
        .agg(pl.col("count").sum())
    )


def _days_to_rebuild(records: pl.DataFrame, bounds: pl.DataFrame) -> list[date]:
    """The sessions with records, none of which holds a finding."""
    found = pl.any_horizontal(pl.col(column) > 0 for column in RECORD_FINDINGS)
    by_day = records.group_by("trade_date").agg(flagged=found.any())
    return (
        bounds.select("trade_date")
        .join(by_day.filter(~pl.col("flagged")), on="trade_date")
        .sort("trade_date")
        .get_column("trade_date")
        .to_list()
    )


def _differences_on(
    report: BarsReport, provider: str, day: date
) -> list[tuple[date, str | None, int | None, int]]:
    """Nothing when no stored bars of `provider` were rebuilt on `day`; else the day's mark of
    being compared, then each difference, as the stored schema and the bar's instrument."""
    compared = [
        comparison
        for comparison in report.comparisons
        if isinstance(comparison, ComparedBars)
        and comparison.provider == provider
        and len(comparison.reference) == 1
    ]
    if not compared:
        return []
    differences = [
        (day, str(comparison.reference[0]), difference.instrument_id, 1)
        for comparison in compared
        for difference in comparison.differences
    ]
    return [(day, None, None, 0), *differences]


def _vendor_days(store: Store, provider: str) -> pl.DataFrame:
    """The condition the vendor gives each UTC day of the provider's batch downloads, from
    their `condition.json`, the newest revision of a day winning and the worse condition among
    revisions of one date; none for a provider that gives none."""
    jobs = sorted(
        {
            file.batch_job.job_id
            for file in store.raw_manifest().files
            if file.provider == provider and file.batch_job is not None
        }
    )
    if provider != DATABENTO or not jobs:
        return pl.DataFrame(schema=_VENDOR_DAY_COLUMNS)
    # shortcut: every batch's conditions apply to every root of the provider; read a batch's
    # products from its metadata.json when a provider's batches hold different products.
    revisions = pl.concat([vendor_conditions(store, job) for job in jobs])
    severity = pl.col("condition").replace_strict(_SEVERITY, return_dtype=pl.Int8)
    return (
        revisions.sort("date", "last_modified_date", severity)
        .unique(subset="date", keep="last", maintain_order=True)
        .select("date", "condition")
    )


def _conditions(bounds: pl.DataFrame, vendor_days: pl.DataFrame) -> pl.DataFrame:
    """Each session's worst condition among the vendor's UTC days it touches, from its open to
    the next session's; sessions the vendor gives no day of are left out."""
    start = pl.col("date").cast(pl.Int64) * _DAY
    days = vendor_days.select(
        start=start,
        end=start + _DAY,
        severity=pl.col("condition").replace_strict(_SEVERITY, return_dtype=pl.Int8),
    )
    worst = (
        bounds.select("trade_date", "open", "next_open")
        .join_where(days, pl.col("open") < pl.col("end"), pl.col("next_open") > pl.col("start"))
        .group_by("trade_date")
        .agg(pl.col("severity").max())
    )
    named = {rank: str(condition) for rank, condition in enumerate(_WORST_LAST)}
    return worst.select(
        "trade_date",
        vendor_condition=pl.col("severity").replace_strict(named, return_dtype=pl.String),
    )


def _flagged(vendor_days: pl.DataFrame, bounds: pl.DataFrame) -> tuple[ConditionDay, ...]:
    """The vendor's days other than available that touch the sessions of `bounds`, in order: a
    batch download covers every product it holds, from the first one's first day."""
    first_open, last_open = bounds.select(pl.col("open").min(), pl.col("next_open").max()).row(0)
    start = pl.col("date").cast(pl.Int64) * _DAY
    flagged = (
        vendor_days.filter(
            pl.col("condition") != str(VendorCondition.AVAILABLE),
            start < last_open,
            start + _DAY > first_open,
        )
        .unique()
        .sort("date", "condition")
    )
    return tuple(
        ConditionDay(day=day, condition=VendorCondition(condition))
        for day, condition in flagged.iter_rows()
    )


def _days(
    bounds: pl.DataFrame,
    records: pl.DataFrame,
    differences: pl.DataFrame,
    conditions: pl.DataFrame,
    received_until: int,
) -> pl.DataFrame:
    """A row per session with the columns of `DAY_COLUMNS`."""
    counts = records.group_by("trade_date").agg(
        records=pl.col("records").sum(),
        ticks=pl.col("records").filter(pl.col("schema").is_in(_TICK_SCHEMAS)).sum(),
        bars_1s=pl.col("records").filter(pl.col("schema") == "ohlcv-1s").sum(),
        bars_1m=pl.col("records").filter(pl.col("schema") == "ohlcv-1m").sum(),
        break_prints=pl.col("break_prints").sum(),
        halt_prints=pl.col("halt_prints").sum(),
    )
    compared = differences.group_by("trade_date").agg(bar_differences=pl.col("count").sum())
    counted = ("records", "ticks", "bars_1s", "bars_1m", "break_prints", "halt_prints")
    return (
        bounds.select("trade_date", "open", "close")
        .join(counts, on="trade_date", how="left")
        .join(compared, on="trade_date", how="left")
        .join(conditions, on="trade_date", how="left")
        .with_columns(
            *(pl.col(column).fill_null(0) for column in counted),
            held_back_bars=_held_back(bounds.item(-1, "trade_date"), received_until),
        )
        .sort("trade_date")
        .select(DAY_COLUMNS.names())
    )


def _held_back(last: date, received_until: int) -> pl.Expr:
    """The one-minute buckets of the last session that close after `received_until`, the end
    of the data, which wait for later data (`fefat.market.bars`); none in other sessions."""
    inside = (
        (pl.col("trade_date") == last)
        & (pl.col("open") < received_until)
        & (pl.col("close") > received_until)
    )
    buckets = (pl.col("close") - received_until + _MINUTE - 1) // _MINUTE
    return pl.when(inside).then(buckets).otherwise(0).cast(pl.Int64)


def _findings(
    records: pl.DataFrame, gaps_found: pl.DataFrame, differences: pl.DataFrame
) -> pl.DataFrame:
    """Every finding with the columns of `FINDING_COLUMNS`, sorted by trade date, kind, schema,
    and contract."""
    kinds = {column: str(finding) for column, finding in RECORD_FINDINGS.items()}
    in_records = (
        records.unpivot(
            on=list(RECORD_FINDINGS),
            index=["trade_date", "schema", "contract"],
            variable_name="kind",
            value_name="count",
        )
        .filter(pl.col("count") > 0)
        .with_columns(pl.col("kind").replace_strict(kinds))
    )
    in_bars = differences.filter(pl.col("count") > 0).with_columns(
        kind=pl.lit(str(QualityFinding.BAR_DIFFERENCES))
    )
    found = [frame.select(FINDING_COLUMNS.names()) for frame in (in_records, gaps_found, in_bars)]
    return pl.concat(found).sort("trade_date", "kind", "schema", "contract")
