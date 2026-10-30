"""The FEFAT engine, compiled from Rust: engine/crates/fefat-py/src/lib.rs."""

from collections.abc import Iterable, Sequence
from os import PathLike
from typing import Protocol, TypedDict

class _ArrowArray(Protocol):
    def __arrow_c_array__(
        self, requested_schema: object | None = None
    ) -> tuple[object, object]: ...

class _ArrowStream(Protocol):
    def __arrow_c_stream__(self, requested_schema: object | None = None) -> object: ...

class _BuildDetails(TypedDict):
    version: str
    target_os: str
    target_arch: str
    profile: str

class _RunSummary(TypedDict):
    position: int
    cash: int
    ambiguous_fills: int

class _Run(TypedDict):
    fills: _ArrowStream
    orders: _ArrowStream
    log: _ArrowStream
    costs: _ArrowStream
    trades: _ArrowStream
    equity: _ArrowStream
    summary: _RunSummary

type _Int64Arrow = _ArrowArray | _ArrowStream
type _Path = str | PathLike[str]
type _Backtest = tuple[str, _ArrowStream, Sequence[_Path], str]

ENGINE_VERSION: int
FILL_MODEL_VERSION: int
ARTIFACT_SCHEMA_VERSION: int

def running_drawdown(values: _Int64Arrow) -> list[int]: ...
def metrics(inputs_json: str) -> str: ...
def build_details() -> _BuildDetails: ...
def write_cache_month(
    contract_folder: _Path,
    contract: str,
    month: str,
    sources: list[tuple[str, str]],
    trade_dates: Iterable[tuple[str, Sequence[tuple[str, _ArrowStream]]]],
) -> None: ...
def run_signal_backtest(
    spec_json: str,
    signal_frame: _ArrowStream,
    cache_paths: Sequence[_Path],
    config_json: str,
    replay: str = "skipping",
) -> _Run: ...
def run_batch(cases: Sequence[_Backtest], replay: str = "skipping") -> list[_Run]: ...
def table_hash(table: _ArrowStream) -> str: ...
def run_key(
    spec_json: str, signal_frame_hash: str, partition_hashes: list[str], config_json: str
) -> str: ...
