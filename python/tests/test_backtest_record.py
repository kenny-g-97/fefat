"""A run's record, request, and artifacts as the SDK reads them back (step 5.3, from the Phase 2
exit's step review, D-93): their mappings hold what `run.json` says, refusing a change in place at
any depth, and each state an artifact writes as text is one of its `StrEnum`'s words, or the
artifact is refused, as a column of the wrong type is."""

import copy
import os
import pickle
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import fefat as ff
from fefat.backtest import FeaturePin, Run, RunConfig
from fefat.backtest.metrics import Outcome
from fefat.backtest.record import InstrumentRecord
from fefat.backtest.requests import request_of
from fefat.config import resolve_paths
from fefat.market.instruments import InstrumentKind
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")


@pytest.fixture
def saved() -> Run:
    store_with("ohlcv-1m")
    return ff.backtest.run(breakout(), *WINDOW)


CHANGES: list[tuple[str, Callable[[Run], object]]] = [
    (
        "a setting of the engine's config",
        lambda run: run.record.engine_config.pop("fees"),  # pyright: ignore[reportAttributeAccessIssue]
    ),
    ("a config's roll", lambda run: run.record.engine_config["rolls"].append({})),
    ("the instrument", lambda run: run.record.engine_config["instrument"].clear()),
    (
        "the strategy's specification",
        lambda run: run.record.strategy.spec.update(timeframe="1m"),  # pyright: ignore[reportAttributeAccessIssue]
    ),
    (
        "a breakdown of the metrics",
        lambda run: run.record.metrics.breakdowns.year.setdefault(  # pyright: ignore[reportAttributeAccessIssue]
            2027, Outcome(trades=0, wins=0, pnl=Decimal(0))
        ),
    ),
]


@pytest.mark.parametrize(("what", "change"), CHANGES, ids=[what for what, _ in CHANGES])
def test_a_saved_runs_record_refuses_a_change_in_place(
    saved: Run, what: str, change: Callable[[Run], object]
) -> None:
    with pytest.raises(TypeError, match="Expected a record left as it was read"):
        change(saved)

    assert Run.open(saved.folder).record == saved.record


def test_a_runs_request_and_a_features_pin_refuse_a_change_in_place(saved: Run) -> None:
    paths = resolve_paths(os.environ)
    request = request_of(breakout(), *WINDOW, RunConfig(), paths)
    assert request is not None
    pin = FeaturePin(slot="rsi", name="rsi", version=1, hash="0" * 64, parameters={"n": [14]})

    with pytest.raises(TypeError, match="Expected a record left as it was read"):
        request.strategy["features"].append({})
    with pytest.raises(TypeError, match="Expected a record left as it was read"):
        pin.parameters["n"].append(28)  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
    assert pin.parameters == {"n": [14]}


def test_a_record_read_back_writes_its_bytes_and_copies_as_a_value(saved: Run) -> None:
    written = (saved.folder / "run.json").read_bytes()
    record = Run.open(saved.folder).record

    assert record.model_dump_json(indent=2).encode() + b"\n" == written
    assert pickle.loads(pickle.dumps(record)) == record
    assert copy.deepcopy(record) == record


def test_an_instrument_of_an_unknown_currency_is_refused() -> None:
    written = {
        "root": "ES",
        "kind": InstrumentKind.FUTURES,
        "currency": "ESD",
        "tick_size": "0.25",
        "point_value": "50",
        "lot_step": "1",
    }

    with pytest.raises(ValidationError, match="currency"):
        InstrumentRecord.model_validate(written)


def copy_with(run: Run, name: str, column: str, word: str) -> Path:
    """The run saved again beside it, the first row of the artifact `name` holding `word` in
    `column`, its type kept."""
    copied = run.folder.with_name(f"{name}-{column}")
    shutil.copytree(run.folder, copied)
    path = copied / f"{name}.parquet"
    frame = pl.read_parquet(path)
    first = pl.int_range(pl.len()) == 0
    changed = frame.with_columns(
        pl.when(first).then(pl.lit(word)).otherwise(pl.col(column)).alias(column)
    )
    changed.write_parquet(path, compression="zstd")
    return copied


@pytest.mark.parametrize(
    ("name", "column", "word"),
    [
        ("fills", "role", "teleport"),
        ("fills", "side", "up"),
        ("fills", "liquidity", "neither"),
        ("fills", "fidelity", "1x"),
        ("orders", "kind", "iceberg"),
        ("orders", "state", "lost"),
        ("log", "kind", "rumour"),
        ("costs", "reason", "tip"),
        ("trades", "side", "buy"),
        ("trades", "exit_reason", "boredom"),
        ("trades", "path_fidelity", "ticks"),
        ("trade_paths", "kind", "sideways"),
    ],
)
def test_an_artifact_holding_a_state_outside_its_words_is_refused(
    saved: Run, name: str, column: str, word: str
) -> None:
    copied = Run.open(copy_with(saved, name, column, word))

    with pytest.raises(ValueError, match=f"Expected the {name} artifact's {column} among"):
        getattr(copied, name)
