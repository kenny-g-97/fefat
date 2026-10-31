"""A run's artifacts (step 2.10, `02` §7): the engine's tables made into the artifacts of
`fefat.backtest.schemas`, the trades with their entry's trade date and features, their initial
risk, and their R multiples, their paths as the engine records them (step 2.13), the equity at
each signal bar with its trade date, and the equity of each trade date; each written as Parquet,
with `run.json`, into the run's folder, named by its key, which is written whole or not at all,
and read back."""

import math
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import fefat_engine
import polars as pl
from pydantic import BaseModel, ConfigDict

from fefat.backtest.record import EngineVersions, RunRecord
from fefat.backtest.schemas import ARTIFACT_SCHEMAS, ENGINE_EQUITY, ENGINE_TRADES, EQUITY
from fefat.market.engine_units import InstrumentParameters
from fefat.market.store_files import parsed_json
from fefat.strategy.signal_frame import require_column_types

ENGINE_TABLES = ("fills", "orders", "log", "costs", "trades", "trade_paths", "equity")
"""The tables the engine gives for a run (`fefat_engine.run_signal_backtest`)."""
RECORD_FILE = "run.json"
_PARTIAL = ".partial"
_FIRST_SCHEMA_WITH_PATHS = 2
"""The artifact schema from which every run keeps its trades' paths (step 2.13)."""


def artifacts_of(
    engine: Mapping[str, pl.DataFrame],
    signals: pl.DataFrame,
    features: Sequence[str],
    parameters: InstrumentParameters,
    capital: int,
) -> dict[str, pl.DataFrame]:
    """Each artifact of a run from the engine's tables, its signal frame, the names of its
    strategy's features, its instrument in the engines' integers, and its capital in
    micro-units, the equity before its first decision."""
    equity = _equity(engine["equity"], signals)
    return {
        "fills": engine["fills"],
        "orders": engine["orders"],
        "log": engine["log"],
        "costs": engine["costs"],
        "trades": _trades(engine["trades"], engine["fills"], signals, features, parameters),
        "trade_paths": engine["trade_paths"],
        "equity": equity,
        "equity_daily": _equity_daily(equity, capital),
        "signals": signals,
    }


def _trades(
    trades: pl.DataFrame,
    fills: pl.DataFrame,
    signals: pl.DataFrame,
    features: Sequence[str],
    parameters: InstrumentParameters,
) -> pl.DataFrame:
    """The trades with the trade date of their entry's fill, which an entry decided at a
    session's last close takes from the next session's open (F-SES-01), and the value of each
    feature on the entry row, `<feature>_at_entry`; the initial risk of their entry's lots,
    rounded against the trader as an amount is (F-FEE-03); and their profit and loss and
    excursions in R."""
    require_column_types(trades, ENGINE_TRADES, "the engine's trades")
    entry_fills = fills.select(
        pl.col("order").alias("entry_order"), pl.col("trade_date").alias("entry_trade_date")
    ).unique("entry_order", keep="first", maintain_order=True)
    entry_rows = signals.select(
        pl.col("ts_close").alias("entry_decision"),
        *(pl.col(feature).alias(f"{feature}_at_entry") for feature in features),
    )
    dated = trades.join(entry_fills, on="entry_order", how="left", maintain_order="left")
    joined = dated.join(entry_rows, on="entry_decision", how="left", maintain_order="left")
    risks = joined.select("initial_risk_ticks", "lots").iter_rows()
    risk = [_risk(ticks, lots, parameters) for ticks, lots in risks]
    ticks = pl.col("initial_risk_ticks")
    return joined.with_columns(
        initial_risk=pl.Series(risk, dtype=pl.Int64),
    ).with_columns(
        r_multiple=pl.col("pnl") / pl.col("initial_risk"),
        mae_r=pl.col("mae_ticks") / ticks,
        mfe_r=pl.col("mfe_ticks") / ticks,
    )


def _risk(ticks: int | None, lots: int, parameters: InstrumentParameters) -> int | None:
    """What `lots` lose from their entry to a stop `ticks` away, in micro-units, rounded up."""
    if ticks is None:
        return None
    return math.ceil(parameters.value(ticks * parameters.tick, lots))


def _equity(equity: pl.DataFrame, signals: pl.DataFrame) -> pl.DataFrame:
    """The account after each decision with the trade date of its signal bar."""
    require_column_types(equity, ENGINE_EQUITY, "the engine's equity")
    dates = signals.select(pl.col("ts_close").alias("ts"), "trade_date")
    joined = equity.join(dates, on="ts", how="left", maintain_order="left")
    return joined.select(EQUITY.names())


def _equity_daily(equity: pl.DataFrame, capital: int) -> pl.DataFrame:
    """The account at each trade date's last decision, and the day's profit and loss, the first
    day's from the capital."""
    daily = equity.group_by("trade_date", maintain_order=True).agg(
        pl.col("cash", "position", "mark", "equity").last()
    )
    before = pl.col("equity").shift(1, fill_value=capital)
    return daily.sort("trade_date").with_columns(pnl=pl.col("equity") - before)


def write_run(folder: Path, artifacts: Mapping[str, pl.DataFrame], record: RunRecord) -> None:
    """The run's artifacts and record in `folder`, written into a folder of this writer's own
    beside it and renamed into place once whole, so that a folder holds a whole run or none, a
    writer never touches another's folder, and a run another process saved first is kept."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix=f"{folder.name}.", suffix=_PARTIAL, dir=folder.parent))
    try:
        for name, frame in artifacts.items():
            require_column_types(frame, ARTIFACT_SCHEMAS[name], f"the {name} artifact's")
            frame.write_parquet(partial / f"{name}.parquet", compression="zstd")
        content = record.model_dump_json(indent=2).encode() + b"\n"
        (partial / RECORD_FILE).write_bytes(content)
        partial.rename(folder)
    except BaseException as error:
        shutil.rmtree(partial, ignore_errors=True)
        if not isinstance(error, OSError) or not (folder / RECORD_FILE).is_file():
            raise


class _WrittenBy(BaseModel):
    """The versions of the engine that wrote a record, read before the record itself."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    versions: EngineVersions


def read_record(folder: Path) -> RunRecord:
    """The record of the run in `folder`, refused by name when another version of the engine
    or of the artifacts' layout wrote it, since a record holds what its own versions' runs
    produce; a run saved before step 2.13 has no trade paths, and its refusal says so."""
    path = folder / RECORD_FILE
    content = path.read_bytes()
    written = parsed_json(_WrittenBy, content, str(path)).versions
    if written.engine != fefat_engine.ENGINE_VERSION:
        raise ValueError(
            f"Expected a run of engine version {fefat_engine.ENGINE_VERSION}, got one of version "
            f"{written.engine} in {folder}: run it again with this engine."
        )
    if written.artifact_schema != fefat_engine.ARTIFACT_SCHEMA_VERSION:
        without = written.artifact_schema < _FIRST_SCHEMA_WITH_PATHS
        reason = ", which has no trade paths" if without else ""
        raise ValueError(
            f"Expected a run of artifact schema {fefat_engine.ARTIFACT_SCHEMA_VERSION}, got one of "
            f"schema {written.artifact_schema} in {folder}{reason}: run it again with this engine."
        )
    return parsed_json(RunRecord, content, str(path))


def read_artifact(folder: Path, name: str) -> pl.DataFrame:
    """The artifact `name` of the run in `folder`, refused unless it holds its columns."""
    if name not in ARTIFACT_SCHEMAS:
        raise ValueError(f"Expected an artifact ({', '.join(ARTIFACT_SCHEMAS)}), got {name!r}.")
    frame = pl.read_parquet(folder / f"{name}.parquet")
    require_column_types(frame, ARTIFACT_SCHEMAS[name], f"the {name} artifact's of {folder}")
    return frame
