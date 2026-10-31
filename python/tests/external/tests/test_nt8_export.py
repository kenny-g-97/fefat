"""Reading NinjaTrader 8's Strategy Analyzer export of its trades (D-59): the grid's columns, the
platform clock's local times (US Eastern) as instants, the locale's numbers, and the entry and
exit names as the strategies' roles."""

from pathlib import Path

import pytest

from fefat_xcheck.nt8_export import read_export

HEADER = (
    "Trade number;Instrument;Account;Strategy;Market pos.;Qty;Entry price;Exit price;Entry time;"
    "Exit time;Entry name;Exit name;Profit;Cum. net profit;Commission;Clearing Fee;Exchange Fee;"
    "IP Fee;NFA Fee;MAE;MFE;ETD;Bars;"
)
EUROPEAN = (
    "1;MNQ 09-26;Backtest;FefatCrossCheck;Long;1;24.786,00;24.796,00;03/08/2026 09:36:00;"
    "03/08/2026 09:41:00;L;Profit target;$ 18,10;$ 18,10;$ 1,90;$ 0,00;$ 0,00;$ 0,00;$ 0,00;"
    "$ -4,00;$ 20,00;$ 1,90;5;"
)
AMERICAN = (
    "2;MNQ 09-26;Backtest;FefatCrossCheck;Short;1;24,800.25;24,810.25;8/3/2026 10:06:00 AM;"
    "8/3/2026 10:08:00 AM;S;Stop loss;($21.90);($3.80);$1.90;$0.00;$0.00;$0.00;$0.00;"
    "($22.00);$4.00;$25.90;2;"
)
FLAT_BY = (
    "3;MNQ 09-26;Backtest;FefatCrossCheck;Long;1;24.790,00;24.792,00;03/08/2026 15:56:00;"
    "03/08/2026 16:01:00;L;FlatBy;$ 2,10;$ -1,70;$ 1,90;$ 0,00;$ 0,00;$ 0,00;$ 0,00;"
    "$ -6,00;$ 4,00;$ 1,90;5;"
)
POINT = 1_000_000_000
EASTERN_OFFSET_HOURS = 4


def written(path: Path, *rows: str) -> Path:
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    return path


def utc_ns(year: int, month: int, day: int, hour: int, minute: int) -> int:
    from datetime import UTC, datetime

    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp()) * POINT


def test_the_export_becomes_trades_in_utc_with_prices_in_units(tmp_path: Path) -> None:
    trades = read_export(
        written(tmp_path / "trades.csv", EUROPEAN, AMERICAN, FLAT_BY), point_value=2
    )

    assert trades["side"].to_list() == ["long", "short", "long"]
    assert trades["entry_price"].to_list() == [
        24_786 * POINT,
        round(24_800.25 * POINT),
        24_790 * POINT,
    ]
    assert trades["exit_price"].to_list() == [
        24_796 * POINT,
        round(24_810.25 * POINT),
        24_792 * POINT,
    ]
    assert trades["entry_ts"].to_list() == [
        utc_ns(2026, 8, 3, 9 + EASTERN_OFFSET_HOURS, 36),
        utc_ns(2026, 8, 3, 10 + EASTERN_OFFSET_HOURS, 6),
        utc_ns(2026, 8, 3, 15 + EASTERN_OFFSET_HOURS, 56),
    ]
    assert trades["exit_ts"].to_list() == [
        utc_ns(2026, 8, 3, 9 + EASTERN_OFFSET_HOURS, 41),
        utc_ns(2026, 8, 3, 10 + EASTERN_OFFSET_HOURS, 8),
        utc_ns(2026, 8, 3, 16 + EASTERN_OFFSET_HOURS, 1),
    ]
    assert trades["exit_reason"].to_list() == ["target", "stop", "flat_by"]
    assert trades["entry_kind"].to_list() == ["market", "market", "market"]
    assert trades["gross_pnl"].to_list() == [20.0, -20.0, 4.0]
    assert trades["commission"].to_list() == [1.9, 1.9, 1.9]


def test_a_market_entry_filled_at_the_next_minutes_open_was_decided_a_minute_before(
    tmp_path: Path,
) -> None:
    trades = read_export(written(tmp_path / "trades.csv", EUROPEAN), point_value=2)

    assert trades["entry_decision"].to_list() == [utc_ns(2026, 8, 3, 9 + EASTERN_OFFSET_HOURS, 35)]


def test_an_export_without_the_grids_columns_is_refused(tmp_path: Path) -> None:
    path = written(tmp_path / "trades.csv")
    path.write_text("Trade number;Instrument\n1;MNQ 09-26\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected the Strategy Analyzer's trade columns"):
        read_export(path, point_value=2)
