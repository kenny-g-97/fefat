"""The cross-check of FEFAT's engine against NautilusTrader and NinjaTrader 8 (step 2.14, `02` §8
item 5, D-51, D-59): the FEFAT side, and the orchestration of the other engines' sides, which
run in the test-only environment of `python/tests/external/`.

The same three strategies decide on 5-minute closes of MES in August 2026 (MESU2026, the front
all month) and fill on the store's Databento 1-minute bars under the compatibility profile of
the fill specification's §19: touch fills (F-LMT-02), no slippage ticks (F-SLP-01), no latency
(F-ACT-01), and FEFAT's own bar path. Each FEFAT run's trades, fills, and signal frame, the
1-minute bars it filled on, and `fefat.json` (the versions, the snapshot, the profile, and the
strategies' parameters) go under `<FEFAT_HOME>/workspaces/default/xcheck/<comparison>/fefat/`,
outside the repository. The month is cut from the raw Databento batch file into a zstd DBN file
beside them, which Nautilus's Databento adapter reads, the raw file only read. NinjaTrader 8
compares on the store's NinjaTrader MNQ import (MNQU2026) with the market strategy alone, its
trade list exported by hand to `<xcheck>/nt8/export/` (the runbook in
`python/tests/external/README.md`). The report lands in `docs/validation/nautilus-comparison.md`
once every difference has its class.

    uv run python scripts/xcheck.py    # as `just xcheck` runs it; slow, needs the real store
"""

import io
import json
import os
import shutil
import subprocess
import warnings
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl
from databento_dbn import Compression, DBNDecoder, Encoding, Metadata, Transcoder

import fefat as ff
from fefat.backtest import RunConfig
from fefat.config import resolve_paths
from fefat.market.fidelity import TickFidelity
from fefat.market.importers.dbn import CHUNK_BYTES, read_dbn
from fefat.market.raw_manifest import RawFile
from fefat.market.schema import Timeframe
from fefat.market.status import dataset_status
from fefat.market.store import Store
from fefat.market.store_files import hashed
from fefat.reference.settings import LimitFill, SlippageTicks

REPOSITORY = Path(__file__).resolve().parents[1]
EXTERNAL_PROJECT = REPOSITORY / "python" / "tests" / "external"
REPORT = REPOSITORY / "docs" / "validation" / "nautilus-comparison.md"
XCHECK_FOLDER = "xcheck"
EXPORT_FOLDER = "export"
"""Where the builder saves NinjaTrader 8's exported trades, under the nt8 comparison."""
ENTRY_WINDOW = ff.EntryWindow(start="08:35", end="14:30")
FLAT_BY = "15:00"
TIME_ZONE = "America/Chicago"
ONE_LOT = 1
NANOSECONDS_PER_DAY = 86_400_000_000_000
UNITS_PER_POINT = 1_000_000_000
ONE_MINUTE = Timeframe.parse("1m")


class EntryKind(StrEnum):
    """How a strategy enters: at the market, or with a limit or a stop ticks from the close."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass(frozen=True)
class CrossCheckStrategy:
    """One of the strategies every engine runs: long when the 5-minute close is above the
    previous close, short when below, one lot, a stop and a target at fixed levels from the
    signal bar's close, entries inside the window and flat-by (`fefat.strategy` time rules)."""

    name: str
    entry: EntryKind
    offset_ticks: int
    time_to_live_bars: int | None
    stop_ticks: int
    target_ticks: int

    def record(self) -> dict[str, Any]:
        """The parameters the other engines' sides read, from `fefat.json`."""
        return {
            **asdict(self),
            "window": [ENTRY_WINDOW.start, ENTRY_WINDOW.end],
            "flat_by": FLAT_BY,
            "tz": TIME_ZONE,
        }


@dataclass(frozen=True)
class Comparison:
    """One engine's comparison: its folder under `xcheck`, the contract and the provider's
    dataset both engines read, the trade dates, and the strategies."""

    name: str
    root: str
    contract: str
    raw_symbol: str
    provider: str
    first: date
    last: date
    strategies: tuple[CrossCheckStrategy, ...]


MES_STRATEGIES = (
    CrossCheckStrategy("market", EntryKind.MARKET, 0, None, 12, 12),
    CrossCheckStrategy("limit", EntryKind.LIMIT, 2, 1, 12, 12),
    CrossCheckStrategy("stop", EntryKind.STOP, 2, 1, 12, 12),
)
NAUTILUS = Comparison(
    name="nautilus",
    root="MES",
    contract="MESU2026",
    raw_symbol="MESU6",
    provider="databento",
    first=date(2026, 8, 3),
    last=date(2026, 8, 31),
    strategies=MES_STRATEGIES,
)
NINJATRADER = Comparison(
    name="nt8",
    root="MNQ",
    contract="MNQU2026",
    raw_symbol="MNQU6",
    provider="ninjatrader",
    first=date(2026, 8, 3),
    last=date(2026, 8, 31),
    strategies=(CrossCheckStrategy("market", EntryKind.MARKET, 0, None, 40, 40),),
)
CUT_FROM = date(2026, 7, 30)
"""The UTC day the cut starts on: two sessions before the window, for the previous close."""


def signal_strategy(root: str, definition: CrossCheckStrategy, tick: int) -> ff.SignalStrategy:
    """The strategy as FEFAT runs it: the levels are columns, so that an entry filled at another
    price than the other engine's leaves the exits comparable."""
    previous = pl.col("close").shift(1)
    long_entry = pl.col("close") > previous
    above = pl.col("close") + definition.stop_ticks * tick
    below = pl.col("close") - definition.stop_ticks * tick
    target_above = pl.col("close") + definition.target_ticks * tick
    target_below = pl.col("close") - definition.target_ticks * tick
    return ff.SignalStrategy(
        instrument=root,
        timeframe="5m",
        features={"signal_close": pl.col("close_raw"), "empty_bucket": pl.col("zero_volume")},
        long_entry=long_entry,
        short_entry=pl.col("close") < previous,
        stop_price=pl.when(long_entry).then(below).otherwise(above),
        target_price=pl.when(long_entry).then(target_above).otherwise(target_below),
        execution=ff.Execution(
            entry=_entry_order(definition),
            stop=ff.Stop(column=True),
            targets=[ff.Target(column=True)],
            time=ff.TimeRules(tz=TIME_ZONE, windows=[ENTRY_WINDOW], flat_by=FLAT_BY),
            sizing=ff.Fixed(ONE_LOT),
        ),
    )


def _entry_order(definition: CrossCheckStrategy) -> Any:
    if definition.entry == EntryKind.MARKET:
        return ff.Market()
    if definition.entry == EntryKind.LIMIT:
        return ff.Limit(
            offset_ticks=definition.offset_ticks,
            time_to_live_bars=definition.time_to_live_bars,
        )
    return ff.StopEntry(
        offset_ticks=definition.offset_ticks, time_to_live_bars=definition.time_to_live_bars
    )


def compatibility_profile(
    provider: str, contract: str, fidelity: TickFidelity | Timeframe = ONE_MINUTE
) -> RunConfig:
    """The fill specification's §19 profile, touch fills with no slippage ticks and no latency,
    at `fidelity`, 1-minute bars unless another is named, on one provider's one contract read
    unspliced (`RunConfig.contract`)."""
    return RunConfig(
        fidelity=fidelity,
        latency_ms=0,
        slippage_ticks=SlippageTicks(market=0, stop=0),
        limit_fill=LimitFill.TOUCH,
        provider=provider,
        contract=contract,
    )


def export_fefat_side(comparison: Comparison, folder: Path) -> dict[str, Any]:
    """Run the comparison's strategies through `ff.backtest.run` and write what the other
    engine's side and the report read under `folder/fefat`: each run's `trades`, `fills`, and
    `signals`, the 1-minute bars of the window, and `fefat.json`, which is returned."""
    out = folder / "fefat"
    out.mkdir(parents=True, exist_ok=True)
    instrument = ff.instruments.get(comparison.root)
    tick = int(instrument.tick_size * UNITS_PER_POINT)
    config = compatibility_profile(comparison.provider, comparison.contract)
    runs = {}
    for definition in comparison.strategies:
        strategy = signal_strategy(comparison.root, definition, tick)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            run = ff.backtest.run(strategy, comparison.first, comparison.last, config)
        window = (comparison.first, comparison.last)
        require_one_contract(run, comparison.root, comparison.contract, window)
        run.trades.write_parquet(out / f"trades_{definition.name}.parquet")
        run.fills.write_parquet(out / f"fills_{definition.name}.parquet")
        run.signals.write_parquet(out / f"signals_{definition.name}.parquet")
        runs[definition.name] = run
    _bars_of_the_window(comparison).write_parquet(out / "bars_1m.parquet")
    record = _record(comparison, runs, instrument, tick)
    (out / "fefat.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def require_one_contract(
    run: ff.backtest.Run, root: str, contract: str, window: tuple[date, date]
) -> None:
    """Refuse a run of the window with a fill on another contract than `contract`, or a
    roll: a comparison holds one contract's records alone."""
    contracts = run.fills["contract"].unique().to_list()
    if run.record.rolls or contracts not in ([], [contract]):
        raise ValueError(
            f"Expected every fill of {root} from {window[0]} to {window[1]} on {contract} "
            f"and no roll, got the contracts {contracts} and {len(run.record.rolls)} rolls "
            f"in run {run.id}."
        )


def _bars_of_the_window(comparison: Comparison) -> pl.DataFrame:
    """The stored 1-minute bars of the contract over the window, raw prices, the grid's empty
    buckets left out: what both engines fill on."""
    bars = ff.market.load(
        comparison.contract, "1m", comparison.first, comparison.last, provider=comparison.provider
    )
    return (
        bars.filter(~pl.col("zero_volume"))
        .select("ts_open", "ts_close", "open", "high", "low", "close", "volume")
        .sort("ts_close")
        .collect()
    )


def _record(
    comparison: Comparison, runs: dict[str, ff.backtest.Run], instrument: Any, tick: int
) -> dict[str, Any]:
    first = next(iter(runs.values()))
    if len(first.record.datasets) != 1:
        raise ValueError(
            f"Expected the run of {comparison.contract} to read one dataset, got "
            f"{[dataset.schema_name for dataset in first.record.datasets]} in run {first.id}."
        )
    (dataset,) = first.record.datasets
    profile = first.config
    return {
        "comparison": comparison.name,
        "versions": first.record.versions.model_dump(),
        "engine_version": ff.engine_info().version,
        "sdk_version": ff.__version__,
        "runs": {name: run.hash for name, run in runs.items()},
        "window": {"first": comparison.first.isoformat(), "last": comparison.last.isoformat()},
        "snapshot": {
            "dataset": f"{dataset.provider}/{dataset.schema_name}/root={dataset.root}",
            "first": dataset.first.isoformat(),
            "last": dataset.last.isoformat(),
            "sha256": dataset.snapshot,
        },
        "profile": {
            "fidelity": str(profile.fidelity),
            "latency_ms": profile.latency_ms,
            "slippage_ticks": profile.slippage_ticks.model_dump(),
            "limit_fill": str(profile.limit_fill),
        },
        "fee_table": {
            "name": first.record.fee_table.name,
            "schedules": [
                [effective_from.isoformat(), fee]
                for effective_from, fee in first.record.fee_table.schedules
            ],
        },
        "instrument": {
            "root": comparison.root,
            "contract": comparison.contract,
            "tick": tick,
            "point_value": str(instrument.point_value),
        },
        "strategies": [definition.record() for definition in comparison.strategies],
    }


def instrument_id_of(raw: Path, raw_symbol: str) -> int:
    """The vendor's instrument id of `raw_symbol` in the batch file's symbology."""
    metadata, _ = read_dbn(raw)
    ids = metadata.symbology.filter(pl.col("raw_symbol") == raw_symbol)["instrument_id"]
    found = ids.unique().to_list()
    if len(found) != 1:
        raise ValueError(f"Expected one instrument id of {raw_symbol} in {raw.name}, got {found}.")
    return found[0]


def cut_month(raw: Path, instrument_id: int, start: int, end: int, target: Path) -> Path:
    """Write the records of `instrument_id` with `ts_event` from `start` to `end` (nanoseconds
    UTC, `end` excluded) after the batch file's own metadata, as a zstd DBN file, which
    Nautilus's Databento adapter expects; the raw file is only read."""
    compression = Compression("zstd" if raw.name.endswith(".zst") else "none")
    decoder = DBNDecoder(compression=compression)
    kept = io.BytesIO()
    with raw.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_BYTES), b""):
            decoder.write(chunk)
            for record in decoder.decode():
                if isinstance(record, Metadata):
                    kept.write(record.encode())
                elif record.instrument_id == instrument_id and start <= record.ts_event < end:
                    kept.write(bytes(record))
    compressed = io.BytesIO()
    transcoder = Transcoder(compressed, Encoding("dbn"), Compression("zstd"))
    transcoder.write(kept.getvalue())
    transcoder.finish()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(compressed.getvalue())
    return target


def utc_day(day: date) -> int:
    """The instant a UTC day starts, in nanoseconds since the Unix epoch."""
    return (day - date(1970, 1, 1)).days * NANOSECONDS_PER_DAY


def raw_batch_file(store: Store, comparison: Comparison) -> tuple[Path, RawFile]:
    """The vendor's batch file whose records fed the comparison's root, from the raw manifest."""
    files = [
        file
        for file in store.raw.manifest().files
        if file.provider == comparison.provider and comparison.root in file.roots
    ]
    if len(files) != 1:
        raise ValueError(
            f"Expected one raw {comparison.provider} file feeding {comparison.root} in the raw "
            f"manifest, got {[file.path for file in files]}."
        )
    (raw_file,) = files
    return store.folder / "raw" / Path(*PurePosixPath(raw_file.path).parts), raw_file


def written_cut(folder: Path, raw: Path, raw_file: RawFile, comparison: Comparison) -> Path:
    """The month cut for the comparison, written once per raw file and reused, with `cut.json`
    beside it naming the raw file, the cut, and their SHA-256s for the report."""
    end = comparison.last + timedelta(days=1)
    name = f"{comparison.contract}-{CUT_FROM}-{comparison.last}-{raw_file.sha256[:12]}.dbn.zst"
    cut = folder / name
    if not cut.is_file():
        print(f"Cutting {comparison.contract} from {raw.name} into {cut.name}")
        instrument_id = instrument_id_of(raw, comparison.raw_symbol)
        cut_month(raw, instrument_id, utc_day(CUT_FROM), utc_day(end), cut)
    facts = {
        "raw_file": {
            "name": raw.name,
            "sha256": raw_file.sha256,
            "vendor_sha256": None
            if raw_file.batch_job is None
            else raw_file.batch_job.published_sha256,
            "vendor_version": raw_file.vendor_version,
        },
        "cut": {
            "name": cut.name,
            "sha256": hashed(cut).sha256,
            "raw_symbol": comparison.raw_symbol,
            "from": CUT_FROM.isoformat(),
            "to": end.isoformat(),
        },
    }
    (folder / "cut.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return cut


def external(*arguments: str) -> None:
    """Run a subcommand of `fefat_xcheck` in the external project's own environment."""
    command = ["uv", "run", "--project", str(EXTERNAL_PROJECT), "python", "-m", "fefat_xcheck"]
    environment = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    subprocess.run([*command, *arguments], cwd=REPOSITORY, env=environment, check=True)


def _comparisons_in_the_store(store: Store, reports_dir: Path) -> list[Comparison]:
    """The Nautilus comparison, and the NinjaTrader 8 one where the store holds the provider's
    dataset of its root; a store without the NinjaTrader import skips it and says so."""
    listed = dataset_status(store, reports_dir)
    comparisons = [NAUTILUS]
    held = listed.filter(
        (pl.col("provider") == NINJATRADER.provider) & (pl.col("root") == NINJATRADER.root)
    )
    if held.is_empty():
        print(
            f"No {NINJATRADER.provider} dataset of {NINJATRADER.root} in the store: the "
            "NinjaTrader 8 comparison is skipped."
        )
        return comparisons
    return [*comparisons, NINJATRADER]


def main() -> int:
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    xcheck = paths.workspace_dir / XCHECK_FOLDER
    comparisons = _comparisons_in_the_store(store, paths.reports_dir)
    for comparison in comparisons:
        print(f"FEFAT's {comparison.name} side: {comparison.contract} on {comparison.provider}")
        record = export_fefat_side(comparison, xcheck / comparison.name)
        print(f"  {len(record['runs'])} runs under {xcheck / comparison.name / 'fefat'}")
    if NINJATRADER in comparisons:
        (xcheck / NINJATRADER.name / EXPORT_FOLDER).mkdir(parents=True, exist_ok=True)
    raw, raw_file = raw_batch_file(store, NAUTILUS)
    cut = written_cut(xcheck / NAUTILUS.name, raw, raw_file, NAUTILUS)
    print(f"NautilusTrader's side on {cut.name}")
    external("nautilus", str(xcheck / NAUTILUS.name))
    draft = xcheck / REPORT.name
    external("report", str(xcheck), str(draft))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft, REPORT)
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
