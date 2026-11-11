"""A run's request and the saved run it made (step 3.7, D-71): a lookup kept beside the saved runs,
`<runs>/requests/<request key>.json`, each file naming the run key of the run its request made,
so that a repeated run opens its saved run without loading bars or evaluating signals, which its
run key needs (D-62), where an identical run evaluated them again before it found the saved one,
1.5 s against the first's 2.2 s on 23 sessions of MES (step 2.10).

The request key is the SHA-256 of everything the signal frame, the engine's config, and the run
key come from that a run knows without loading a bar: the strategy's document, its slots, each
feature by its name, content hash, and parameters, and its expressions as Polars writes them
(`SignalStrategy.signal_document`); the window asked for; the settings, every default applied;
the instrument; for each instrument the features read, the provider, the symbol, the session
table, the roll calendar, and each dataset's snapshot with where its data ends, over the trade
dates from the first the run reads, the lead-in of the feature cache's first partition
(`first_date_read`), as the cache's keys pin them (`PartitionKeys.pins`), with the snapshots the
run key reads over those dates, a perpetual's funding among them;
the SDK's code with the Polars version (`runtime_key`); and the engine's versions. A request is
kept after every run that did not find it, also one whose run key found a saved run, so that a
version of a feature whose values are the same maps to the run its first version made. A
strategy with an expression that calls a Python function, as `map_elements` does, keys no
request and runs as before, since Polars writes such a function by its name alone where it writes
it at all; a request file that cannot be read, or names a run no longer saved, is no lookup, and
the run keeps it again. From step 5.3 `looked_up` gives what the app's lookup answers before it
queues a backtest: the settings applied, the request, and the saved run."""

import hashlib
import json
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from fefat.backtest.artifacts import RECORD_FILE
from fefat.backtest.record import EngineVersions, Hash, InstrumentRecord, Window
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.backtest.run_signals import contract_of
from fefat.backtest.snapshots import Market, finest_level, market_of, snapshots_of
from fefat.config import FefatPaths
from fefat.features.cache import first_date_read
from fefat.features.cache_keys import PartitionKeys, runtime_key
from fefat.features.grids import input_sources
from fefat.market.api import parse_trade_date, series_source
from fefat.market.schema import FrozenDocument, FrozenModel
from fefat.market.snapshot import Sha256
from fefat.market.store_files import json_writer, write_atomically
from fefat.strategy.signal_strategy import SignalStrategy

REQUESTS_FOLDER_NAME = "requests"
"""The folder beside the saved runs that holds their requests."""


class RunRequest(FrozenModel):
    """What a run is made from, as it is known before a bar is loaded (module docstring), its
    strategy's document held read-only."""

    strategy: FrozenDocument
    window: Window
    config: AppliedRunConfig
    instrument: InstrumentRecord
    pins: tuple[str, ...]
    sdk_key: Sha256
    versions: EngineVersions

    def key(self) -> str:
        """The SHA-256 of the request's JSON, its keys sorted."""
        text = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(text.encode()).hexdigest()


class RunRequestRecord(FrozenModel):
    """A request kept beside the saved runs, with the run key of the run it made."""

    request_key: Sha256
    run_key: Hash
    request: RunRequest
    created_at: datetime


@dataclass(frozen=True)
class RunLookup:
    """What `looked_up` knows of a run before a bar is loaded: its settings, every default
    applied; what it reads of the store, as a request pins it, which a run works out again once
    it is done, so that data changed meanwhile refuses it; its request, None for a strategy that
    keys none; and the folder of the saved run that request made, None where none is saved."""

    config: AppliedRunConfig
    pins: tuple[str, ...]
    request: RunRequest | None
    saved: Path | None


def looked_up(
    strategy: SignalStrategy,
    start: str | date,
    end: str | date,
    config: RunConfig,
    paths: FefatPaths,
) -> RunLookup:
    """A run of `strategy` on the trade dates from `start` to `end` under `config`, as it is
    known before a bar is loaded (`RunLookup`). Its market is built for every strategy, so that
    an unknown instrument, provider, or contract is refused here, before the app queues a job
    (step 5.3)."""
    market = market_of(strategy.instrument, config.provider, paths)
    applied = config.applied(finest_level(market.datasets), market.instrument.kind, market.provider)
    window = Window(start=parse_trade_date(start, "start"), end=parse_trade_date(end, "end"))
    root, contract = strategy.instrument, applied.contract
    symbol = root if contract is None else contract_of(root, contract)
    pins = _pins_of(strategy, market, window, symbol)
    document = strategy.signal_document()
    if document is None:
        return RunLookup(config=applied, pins=pins, request=None, saved=None)
    request = RunRequest(
        strategy=document,
        window=window,
        config=applied,
        instrument=InstrumentRecord.of(market.instrument),
        pins=pins,
        sdk_key=runtime_key(),
        versions=EngineVersions.running(),
    )
    return RunLookup(config=applied, pins=pins, request=request, saved=saved_run_of(request, paths))


def request_of(
    strategy: SignalStrategy,
    start: str | date,
    end: str | date,
    config: RunConfig,
    paths: FefatPaths,
) -> RunRequest | None:
    """The request of a run of `strategy` on the trade dates from `start` to `end` under
    `config` (module docstring); None where an expression of it calls a Python function, whose
    code no request could hold (`SignalStrategy.signal_document`)."""
    return looked_up(strategy, start, end, config, paths).request


def _pins_of(
    strategy: SignalStrategy, market: Market, window: Window, symbol: str
) -> tuple[str, ...]:
    """What a run of `strategy` on its market's `symbol` over `window` reads of the store, from
    the first trade date it reads (module docstring): each instrument's pins as the feature
    cache's keys name them, and the snapshots the run key reads."""
    graph = strategy.feature_graph()
    signal = series_source(symbol, provider=market.provider)
    keys = PartitionKeys({graph.root: signal, **input_sources(graph, signal)})
    lead_in = graph.lead_in(market.sessions, window.start)
    first = min(lead_in, first_date_read(graph, signal, (lead_in, window.end)))
    read = snapshots_of(market, first, window)
    return (*keys.pins(graph, (first, window.end)), *(each.sha256 for each in read))


def saved_run_of(request: RunRequest, paths: FefatPaths) -> Path | None:
    """The folder of the saved run `request` made, None where no request file names a run that
    is still saved, or where its file cannot be read."""
    try:
        record = RunRequestRecord.model_validate_json(
            _request_file(paths, request.key()).read_bytes()
        )
    except (OSError, ValidationError):
        return None
    folder = paths.runs_dir / record.run_key
    if record.request != request or not (folder / RECORD_FILE).is_file():
        return None
    return folder


def remember(request: RunRequest, run_key: str, paths: FefatPaths) -> None:
    """Keep `run_key` as the key of the run `request` made, beside the saved runs."""
    record = RunRequestRecord(
        request_key=request.key(), run_key=run_key, request=request, created_at=datetime.now(UTC)
    )
    path = _request_file(paths, record.request_key)
    # shortcut: Windows refuses to replace a file another process is reading, and a request not
    # kept evaluates its signals once more next time; serialize writers with Phase 4's jobs.
    try:
        write_atomically(path, json_writer(record))
    except PermissionError as error:
        warnings.warn(
            f"Expected to keep the run's request in {path}, got {error}; the next identical run "
            "evaluates its signals again before it finds the saved run.",
            UserWarning,
            stacklevel=3,
        )


def _request_file(paths: FefatPaths, request_key: str) -> Path:
    return paths.runs_dir / REQUESTS_FOLDER_NAME / f"{request_key}.json"
