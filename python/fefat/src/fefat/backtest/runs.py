"""`ff.backtest.run` (step 2.10, `02` §5): a signal strategy's backtest in one call. It reads
what `fefat.backtest.run_inputs` gathers, keys the run on its specification, its config, its
signal frame, its data's snapshots, and the engine's versions (`02` §4), and returns the run of
that key when its folder holds one; otherwise it runs the engine (`fefat_engine`) and writes the
run's artifacts and record under `FEFAT_HOME/workspaces/default/artifacts/runs/<run key>/`, with
the run's metrics (step 2.11), which a rerun at one more tick of slippage and the engine's
`fefat-metrics` work out, the fidelity era of each trade date, and the fidelity check of its
days finer than a minute (step 2.12), which reruns them coarser; and each trade's path, with the
mix of their fidelities (step 2.13), which the reruns leave out.

    run = ff.backtest.run(strategy, "2026-03-05", "2026-03-09")
    run.trades, run.fills, run.trade_paths, run.equity("1d"), run.config, run.hash, run.metrics
    run.explain(trade_id=4)
    run.report()
"""

import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import fefat_engine
import polars as pl

from fefat.backtest.artifacts import (
    ENGINE_TABLES,
    RECORD_FILE,
    artifacts_of,
    read_artifact,
    read_record,
    write_run,
)
from fefat.backtest.explain import Explanation, explain
from fefat.backtest.fidelity import CheckedRun, PeriodRun, fidelity_check_of
from fefat.backtest.metrics import Metrics
from fefat.backtest.metrics_inputs import friction_tested, metrics_inputs_json, parameters_of
from fefat.backtest.record import (
    EngineVersions,
    FeaturePin,
    InstrumentRecord,
    PathFidelity,
    RunRecord,
    RunSummary,
    StrategyRecord,
)
from fefat.backtest.report import report_text
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.backtest.run_inputs import RunInputs, run_inputs
from fefat.config import resolve_paths
from fefat.features.evaluation import FeatureSpec
from fefat.features.versions import save
from fefat.market.engine_units import micro_units, money_text
from fefat.market.fidelity import FidelityEra
from fefat.strategy.signal_strategy import SignalStrategy

DAILY = "1d"


@dataclass(frozen=True)
class Run:
    """A saved run: its folder and its record, `run.json`, each artifact read when asked for."""

    folder: Path
    record: RunRecord

    @classmethod
    def open(cls, folder: Path) -> "Run":
        """The run saved in `folder`."""
        return cls(folder=folder, record=read_record(folder))

    @property
    def id(self) -> str:
        return self.record.run_id

    @property
    def hash(self) -> str:
        """The run key (`02` §4), the name of the run's folder."""
        return self.record.run_key

    @property
    def config(self) -> AppliedRunConfig:
        """The settings the run ran under, every default applied."""
        return self.record.config

    @property
    def metrics(self) -> Metrics:
        """The run's metrics (`02` §7), as its record holds them."""
        return self.record.metrics

    def explain(self, trade_id: int) -> Explanation:
        """Trade `trade_id`, the id of its entry order, replayed through the reference engine on
        the run's own records (`fefat.backtest.explain`): prints each event with its rule and
        each fill with its rule and slippage, and raises `EnginesDisagreementError` when the
        reference's fills are not the Rust engine's."""
        explanation = explain(self, trade_id)
        print(explanation.text())
        return explanation

    def report(self) -> None:
        """Prints the run's report (`fefat.backtest.report.report_text`): its fidelity eras, its
        metrics with its trades split by the fidelity of their entry, and its fidelity check."""
        print(report_text(self.record))

    @property
    def trades(self) -> pl.DataFrame:
        return read_artifact(self.folder, "trades")

    @property
    def fills(self) -> pl.DataFrame:
        return read_artifact(self.folder, "fills")

    @property
    def trade_paths(self) -> pl.DataFrame:
        """Each point of each trade's path (`fefat.backtest.schemas.TRADE_PATHS`), `trade` its
        row in `trades` from 0."""
        return read_artifact(self.folder, "trade_paths")

    @property
    def orders(self) -> pl.DataFrame:
        return read_artifact(self.folder, "orders")

    @property
    def costs(self) -> pl.DataFrame:
        return read_artifact(self.folder, "costs")

    @property
    def log(self) -> pl.DataFrame:
        return read_artifact(self.folder, "log")

    @property
    def signals(self) -> pl.DataFrame:
        return read_artifact(self.folder, "signals")

    def equity(self, timeframe: str) -> pl.DataFrame:
        """The account at each trade date's last decision for `1d`, or after each decision for
        the strategy's own timeframe."""
        bars = str(self.record.strategy.spec["timeframe"])
        if timeframe == DAILY:
            return read_artifact(self.folder, "equity_daily")
        if timeframe == bars:
            return read_artifact(self.folder, "equity")
        raise ValueError(
            f"Expected the timeframe {DAILY} or the strategy's, {bars}, got {timeframe!r}."
        )


def run(
    strategy: SignalStrategy,
    start: str | date,
    end: str | date,
    config: RunConfig | None = None,
) -> Run:
    """The backtest of `strategy` on the trade dates from `start` to `end` under `config`, the
    defaults where it is left out: read back when a run of its key is saved, else run and
    saved. The warnings its record holds are raised on every call, as `load` raises its own."""
    paths = resolve_paths(os.environ)
    inputs = run_inputs(strategy, start, end, RunConfig() if config is None else config, paths)
    frame_hash = fefat_engine.table_hash(inputs.signals)
    key = run_key(inputs, frame_hash)
    folder = paths.runs_dir / key
    if (folder / RECORD_FILE).is_file():
        saved = Run.open(folder)
    else:
        written = StrategyRecord(
            spec=inputs.spec.document(),
            features=strategy.feature_columns(),
            feature_versions=_pins(strategy),
        )
        saved = _ran(inputs, inputs.cache_paths(paths), written, folder, key, frame_hash)
    for warning in saved.record.warnings:
        warnings.warn(warning, UserWarning, stacklevel=2)
    return saved


def run_key(inputs: RunInputs, frame_hash: str) -> str:
    """The run key of `inputs` (`02` §4), their signal frame hashing to `frame_hash`: the name of
    the run's folder, which a second run of the same inputs reads back."""
    partitions = list(inputs.partition_hashes)
    return fefat_engine.run_key(inputs.spec_json(), frame_hash, partitions, inputs.config_json())


def _pins(strategy: SignalStrategy) -> tuple[FeaturePin, ...]:
    """The version of each feature the strategy's slots read, each saved in the library where it
    is not yet (step 3.7), so that the run's record names it as the library keeps it."""
    return tuple(
        _pin(slot, feature)
        for slot, feature in strategy.features.items()
        if isinstance(feature, FeatureSpec)
    )


def _pin(slot: str, feature: FeatureSpec) -> FeaturePin:
    saved = save(feature.definition)
    parameters = feature.parameters.model_dump(mode="json")
    return FeaturePin(
        slot=slot, name=saved.name, version=saved.version, hash=saved.hash, parameters=parameters
    )


def _ran(
    inputs: RunInputs,
    cache_paths: tuple[Path, ...],
    strategy: StrategyRecord,
    folder: Path,
    key: str,
    frame_hash: str,
) -> Run:
    """The run of `inputs` through the engine over its fronts' caches in `cache_paths`, its
    artifacts and record, which names `strategy`, written to `folder`."""
    caches = [str(path) for path in cache_paths]
    replay = str(inputs.config.replay)
    outputs = fefat_engine.run_signal_backtest(
        inputs.spec_json(), inputs.signals, caches, inputs.config_json(), replay
    )
    engine = {name: pl.DataFrame(outputs[name]) for name in ENGINE_TABLES}
    capital = micro_units(inputs.config.capital)
    artifacts = artifacts_of(engine, inputs.signals, strategy.features, inputs.parameters, capital)
    summary = outputs["summary"]
    eras = tuple(FidelityEra.model_validate(era) for era in summary["eras"])
    itself = PeriodRun(inputs.config.fidelity, engine["trades"], engine["equity"], eras)
    check = fidelity_check_of(_checked(inputs, cache_paths, itself))
    metrics = _metrics(inputs, artifacts, caches).model_copy(update={"fidelity_check": check})
    record = RunRecord(
        run_id=key,
        run_key=key,
        versions=EngineVersions(
            engine=fefat_engine.ENGINE_VERSION,
            fill_model=fefat_engine.FILL_MODEL_VERSION,
            artifact_schema=fefat_engine.ARTIFACT_SCHEMA_VERSION,
        ),
        strategy=strategy,
        window=inputs.window,
        instrument=_instrument_record(inputs),
        datasets=inputs.datasets,
        signal_frame_hash=frame_hash,
        signal_bar_eras=inputs.signal_bar_eras,
        config=inputs.config,
        fee_table=inputs.fee_table,
        rolls=inputs.rolls,
        engine_config=inputs.engine_config,
        fidelity_eras=eras,
        path_fidelities=_path_fidelities(artifacts["trades"]),
        warnings=(*inputs.warnings, *_engine_warnings(engine["log"], inputs)),
        summary=RunSummary(
            fills=engine["fills"].height,
            ambiguous_fills=summary["ambiguous_fills"],
            trades=artifacts["trades"].height,
            position=summary["position"],
            cash=Decimal(money_text(summary["cash"])),
            pnl=Decimal(money_text(int(artifacts["trades"].get_column("pnl").sum()))),
        ),
        metrics=metrics,
    )
    write_run(folder, artifacts, record)
    return Run(folder=folder, record=record)


def _metrics(
    inputs: RunInputs, artifacts: Mapping[str, pl.DataFrame], caches: list[str]
) -> Metrics:
    """The run's metrics, with the profit and loss of its trades rerun at one more tick of
    slippage on market and stop orders (`02` §7, F-SLP-01); a rerun the engine refuses refuses
    the run."""
    replay, config = str(inputs.config.replay), inputs.config_json_at_one_more_tick()
    try:
        slipped = fefat_engine.run_signal_backtest(
            inputs.spec_json(), inputs.signals, caches, config, replay, trade_paths=False
        )
    except ValueError as error:
        raise ValueError(
            f"Expected the rerun at one more tick of slippage to run, got: {error}"
        ) from error
    document = metrics_inputs_json(
        artifacts,
        capital=micro_units(inputs.config.capital),
        instrument=inputs.parameters,
        window=inputs.window,
        time_zone=inputs.time_zone,
        pnl_at_plus_one_tick=int(pl.DataFrame(slipped["trades"]).get_column("pnl").sum()),
        parameters=parameters_of(inputs.spec.execution),
        friction_tested=friction_tested(inputs.config.slippage_ticks, artifacts["fills"]),
    )
    return Metrics.model_validate_json(fefat_engine.metrics(document))


def _path_fidelities(trades: pl.DataFrame) -> tuple[PathFidelity, ...]:
    """How many trades' paths have each fidelity, in the order each first closed."""
    counted = trades.group_by("path_fidelity", maintain_order=True).len("trades")
    return tuple(
        PathFidelity(fidelity=fidelity, trades=count) for fidelity, count in counted.iter_rows()
    )


def _checked(inputs: RunInputs, cache_paths: tuple[Path, ...], itself: PeriodRun) -> CheckedRun:
    """What the fidelity check reads of the run of `inputs`, `itself`, whose fronts' caches lie
    in one folder of the root's contracts."""
    return CheckedRun(
        spec_json=inputs.spec_json(),
        signals=inputs.signals,
        engine_config=inputs.engine_config,
        cache_folder=cache_paths[0].parent,
        replay=inputs.config.replay,
        capital=micro_units(inputs.config.capital),
        window=inputs.window,
        run=itself,
    )


def _instrument_record(inputs: RunInputs) -> InstrumentRecord:
    instrument = inputs.instrument
    return InstrumentRecord(
        root=instrument.root,
        kind=instrument.kind,
        currency=str(instrument.currency),
        tick_size=instrument.tick_size,
        point_value=instrument.point_value,
        lot_step=instrument.lot_step,
    )


def _engine_warnings(log: pl.DataFrame, inputs: RunInputs) -> tuple[str, ...]:
    """The warnings of the engine's log, the fee table's first schedule pricing a fill before
    its date named with the table (F-FEE-01)."""
    warned = log.filter(pl.col("kind") == "warning")
    table = inputs.fee_table
    first = table.schedules[0][0]
    messages = []
    for text, rule in warned.select("text", "rule").iter_rows():
        if rule == "F-FEE-01":
            text = (
                f"the fee table {table.name} has no schedule before {first}, so its first "
                "schedule priced the fills of earlier trade dates"
            )
        messages.append(f"{text} ({rule})")
    return tuple(messages)
