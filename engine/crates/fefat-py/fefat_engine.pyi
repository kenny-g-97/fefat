"""The FEFAT engine, compiled from Rust: engine/crates/fefat-py/src/lib.rs."""

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

type _Int64Arrow = _ArrowArray | _ArrowStream

def max_drawdown(values: list[int]) -> int: ...
def max_drawdown_arrow(values: _Int64Arrow) -> int: ...
def arrow_values_addresses(values: _Int64Arrow) -> list[int]: ...
def build_details() -> _BuildDetails: ...
