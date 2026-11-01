"""The check notebook of step 2.14 runs top to bottom, as Run All does, on an xcheck folder made
of hand-made tables under the test's FEFAT home: it counts each comparison's pairs by outcome,
shows the differing pairs and NinjaTrader 8's trades beside FEFAT's, and says so when the folder
is missing."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from fefat.config import resolve_paths
from notebook_runs import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "2.14.ipynb"
POINT = 1_000_000_000
MINUTE = 60 * POINT
HEADER = (
    "Trade number;Instrument;Account;Strategy;Market pos.;Qty;Entry price;Exit price;Entry time;"
    "Exit time;Entry name;Exit name;Profit;Cum. net profit;Commission;Clearing Fee;Exchange Fee;"
    "IP Fee;NFA Fee;MAE;MFE;ETD;Bars;"
)
EXPORT_ROWS = (
    "1;MNQ 09-26;Backtest;FefatCrossCheck;Long;1;24.786,00;24.796,00;03/08/2026 09:36:00;"
    "03/08/2026 09:41:00;L;Profit target;$ 18,10;$ 18,10;$ 1,90;$ 0,00;$ 0,00;$ 0,00;$ 0,00;"
    "$ -4,00;$ 20,00;$ 1,90;5;",
    "2;MNQ 09-26;Backtest;FefatCrossCheck;Short;1;24.800,25;24.790,25;03/08/2026 10:06:00;"
    "03/08/2026 10:08:00;S;Profit target;$ 18,10;$ 36,20;$ 1,90;$ 0,00;$ 0,00;$ 0,00;$ 0,00;"
    "$ -4,00;$ 20,00;$ 1,90;2;",
)


def eastern(hour: int, minute: int) -> int:
    return int(datetime(2026, 8, 3, hour + 4, minute, tzinfo=UTC).timestamp()) * POINT


def fefat_trades() -> pl.DataFrame:
    """Two trades of the market strategy as the FEFAT side writes them, the columns the
    notebook reads: the second exits at the stop where NinjaTrader's export took the target."""
    return pl.DataFrame(
        {
            "entry_decision": [eastern(9, 35), eastern(10, 5)],
            "side": ["long", "short"],
            "entry_ts": [eastern(9, 36), eastern(10, 6)],
            "entry_price": [24_786 * POINT, round(24_800.25 * POINT)],
            "exit_ts": [eastern(9, 41), eastern(10, 8)],
            "exit_price": [24_796.0 * POINT, 24_810.25 * POINT],
            "exit_reason": ["target_1", "stop"],
            "gross_pnl": [20_000_000, -20_000_000],
        }
    )


def classified(outcomes: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "entry_decision": [eastern(9, 35), eastern(10, 5)][: len(outcomes)],
            "side": ["long", "short"][: len(outcomes)],
            "entry_kind": ["market"] * len(outcomes),
            "in_fefat": [True] * len(outcomes),
            "in_other": [True] * len(outcomes),
            "entry_outcome": ["match"] * len(outcomes),
            "exit_outcome": outcomes,
            "outcome": outcomes,
            "entry_ticks": [0] * len(outcomes),
            "exit_ticks": [0, -80][: len(outcomes)],
            "note": ["entry match"] * len(outcomes),
        }
    )


def xcheck_folder() -> Path:
    folder = resolve_paths(os.environ).workspace_dir / "xcheck"
    for comparison in ("nautilus", "nt8"):
        (folder / comparison / "classified").mkdir(parents=True)
        (folder / comparison / "fefat").mkdir()
    classified(["match", "bar_path"]).write_parquet(
        folder / "nt8" / "classified" / "market_ninjatrader_8.parquet"
    )
    fefat_trades().write_parquet(folder / "nt8" / "fefat" / "trades_market.parquet")
    (folder / "nt8" / "fefat" / "fefat.json").write_text(
        json.dumps({"instrument": {"point_value": "2"}}), encoding="utf-8"
    )
    (folder / "nt8" / "export").mkdir()
    (folder / "nt8" / "export" / "trades.csv").write_text(
        "\n".join((HEADER, *EXPORT_ROWS)) + "\n", encoding="utf-8"
    )
    for name in (
        "market_nautilustrader_open_high_low_close",
        "limit_nautilustrader_open_high_low_close",
    ):
        classified(["match", "bar_boundary"]).write_parquet(
            folder / "nautilus" / "classified" / f"{name}.parquet"
        )
    return folder


def test_the_check_notebook_shows_each_comparisons_pairs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    xcheck_folder()

    cells = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "xcheck folder ready: True" in printed
    assert "NinjaTrader 8: 2 trades matched with FEFAT's 2; 2 FEFAT trades" in printed
    assert "bar_path" in printed
    assert "gross profit and loss: FEFAT 0.00 USD, NinjaTrader 8 40.00 USD over 2 pairs" in printed
    assert "market_nautilustrader_open_high_low_close: 2 pairs" in printed
    assert "limit_nautilustrader_open_high_low_close: 2 pairs" in printed
    assert cells["side_by_side"].height == 2


def test_the_check_notebook_says_so_without_the_xcheck_folder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out
    assert "xcheck folder ready: False" in printed
    assert "Run `just xcheck` first: nothing to open." in printed
