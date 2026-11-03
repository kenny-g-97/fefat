"""The check notebook of step 3.2 (Your checks) runs top to bottom, as Run All does, on a store of
synthetic 1-minute bars: a 15-minute RSI on ES's 5-minute bars keeps its value between 15-minute
closes and changes only at them, ES's rows read the fixtures' bitcoin with its staleness, the
part on MCL and MES is skipped, and a window of one day has its RSI from its first row."""

from pathlib import Path

import pytest

from notebook_runs import run_notebook, store_with

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "checks" / "3.02.ipynb"


def test_the_check_notebook_shows_a_fifteen_minute_rsi_changing_only_at_its_closes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOK)

    printed = capsys.readouterr().out.splitlines()
    assert "ES on 2026-03-09" in printed
    assert "changes only at 15-minute closes: True" in printed
    rsi_15m = check["around"].get_column("rsi_15m").to_list()
    assert len(rsi_15m) == 6
    assert rsi_15m[0] == rsi_15m[1] != rsi_15m[2] == rsi_15m[3] == rsi_15m[4] != rsi_15m[5]
    bitcoin = "BTCUSDT-PERP: 0 rows read a bar of the same close, 276 an older bar, the oldest"
    assert any(line.startswith(bitcoin) for line in printed)
    assert "The store holds no MCL and MES: this part is skipped." in printed
    assert "first row has its RSI: True" in printed
