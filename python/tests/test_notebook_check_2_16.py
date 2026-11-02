"""The check notebook of step 2.16 runs top to bottom, as Run All does, on a tick-check folder
made of hand-made tables under the test's FEFAT home: it prints each session's bar check, the
reference engine's fills against the Rust engine's, the differences of ticks and minutes by
class, and the hashes, and ends on a verdict; without the folder it says so."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from fefat.backtest.fidelity_classes import CLASSIFIED_COLUMNS
from fefat.config import resolve_paths
from fefat.market.engine_units import price_text
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.16.ipynb"
SECOND = 1_000_000_000
POINT = 1_000_000_000
TICK = 250_000_000


def instant(hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(2026, 9, 21, hour, minute, second, tzinfo=UTC).timestamp()) * SECOND


def facts() -> dict[str, Any]:
    """What `just tick-check` saves for the notebook, for one strategy and two sessions."""
    return {
        "check": {"provider": "ibkr", "contract": "MNQZ2026", "reference_provider": "databento"},
        "sessions": [
            {"trade_date": "2026-09-21", "prints": 976_389, "fidelity": "trades", "left_out": None},
            {
                "trade_date": "2026-09-23",
                "prints": 1_069_604,
                "fidelity": "1m",
                "left_out": "its records add up to 464 lots, not the bar's 463",
            },
        ],
        "bars": [
            {
                "trade_date": "2026-09-21",
                "rebuilt": {"compared": 1_379, "differences": 0, "columns": [], "minutes": []},
                "reference": {"both": 1_379, "volume_differs": 13, "price_differs": 9},
            },
            {
                "trade_date": "2026-09-23",
                "rebuilt": {
                    "compared": 1_380,
                    "differences": 3,
                    "columns": ["close", "trade_count", "volume"],
                    "minutes": ["20:59Z"],
                },
                "reference": None,
            },
        ],
        "strategies": [
            {
                "name": "market",
                "differential": {
                    "rust_fills": 242,
                    "reference_fills": 242,
                    "identical": 242,
                    "minute_fills": 242,
                    "minute_identical": 242,
                },
                "fidelity": {
                    "unknown": 0,
                    "trades_by_class": {"bar_boundary": 1},
                    "restamped": {"trades_apart": 0, "trades_by_class": {}, "unknown": 0},
                },
                "determinism": {
                    "run_key": "40adf5c11c28" + "0" * 52,
                    "fills_hash": "1ef0e8fddd02fe3b" + "0" * 48,
                    "second_fills_hash": "1ef0e8fddd02fe3b" + "0" * 48,
                    "prefixes": [{"through": "2026-09-21", "equal": True}],
                },
            }
        ],
    }


def classified() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "entry_decision": [instant(13, 35), instant(13, 40)],
            "side": ["long", "short"],
            "entry_kind": ["market", "market"],
            "in_ticks": [True, True],
            "in_minutes": [True, True],
            "entry_outcome": ["match", "bar_boundary"],
            "exit_outcome": ["match", "match"],
            "outcome": ["match", "bar_boundary"],
            "entry_ticks": [0, 2],
            "exit_ticks": [0, 0],
            "note": ["entry match; exit stop against stop: match", "entry bar_boundary; exit"],
        },
        schema=CLASSIFIED_COLUMNS,
    )


def trades(entry_after: int) -> pl.DataFrame:
    """Two trades of the market strategy as the tick check saves them, entered `entry_after`
    seconds after their decision, the columns the notebook reads."""
    later = entry_after * SECOND
    return pl.DataFrame(
        {
            "entry_decision": [instant(13, 35), instant(13, 40)],
            "side": ["long", "short"],
            "entry_ts": [instant(13, 35) + later, instant(13, 40) + later],
            "entry_price": [24_800 * POINT, 24_810 * POINT + 2 * TICK],
            "exit_ts": [instant(13, 38), instant(13, 44)],
            "exit_price": [24_790 * POINT, 24_820 * POINT],
            "exit_reason": ["stop", "stop"],
        }
    )


def tick_check_folder() -> Path:
    folder = resolve_paths(os.environ).workspace_dir / "tick-check"
    folder.mkdir(parents=True)
    (folder / "facts.json").write_text(json.dumps(facts()), encoding="utf-8")
    classified().write_parquet(folder / "classified_market.parquet")
    trades(5).write_parquet(folder / "trades_market_ticks.parquet")
    trades(60).write_parquet(folder / "trades_market_minutes.parquet")
    return folder


def test_the_check_notebook_shows_the_tick_check_and_ends_on_its_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tick_check_folder()

    cells = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "tick-check folder ready: True" in printed
    assert "2026-09-21: 976,389 prints, filled on trade prints" in printed
    assert "rebuilt bars: 1,379 compared, 0 differences" in printed
    assert "2026-09-23: 1,069,604 prints, filled on 1-minute bars" in printed
    assert "rebuilt bars: 1,380 compared, 3 differences (close, trade_count, volume at 20:59Z)" in (
        printed
    )
    assert "market: 242 of 242 fills identical on prints, 242 of 242 on 1-minute bars" in printed
    assert "market: 2 trades on prints and at one minute, 1 differing" in printed
    assert "bar_boundary" in printed
    assert "market: fills 1ef0e8fddd02fe3b, again 1ef0e8fddd02fe3b, prefixes equal: True" in printed
    assert cells["side_by_side"].height == 2
    assert not {"entry_price", "exit_price"} & set(cells["side_by_side"].columns)
    for price in (*trades(5)["entry_price"], *trades(5)["exit_price"]):
        assert str(price) not in printed
        assert price_text(price) not in printed
    assert printed.rstrip().endswith(
        "Verdict: reference and Rust identical: True; differences without a class: 0; "
        "rebuilt bars equal the provider's on 1 of 2 sessions."
    )


def test_the_check_notebook_says_so_without_the_tick_check_folder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "tick-check folder ready: False" in printed
    assert "Run `just tick-check` first: nothing to open." in printed
