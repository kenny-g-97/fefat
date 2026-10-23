"""The parts of step 2.2's reference engine that the fill scenarios do not reach: a strategy's
`on_bar` with a bracket set in ticks and an exit, the trade list, bars in a break, the tapes
built from the store's frames, and the instrument's decimals as the engines' integers."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat.market.calendar import sessions_of
from fefat.market.fidelity import TickFidelity
from fefat.market.schema import Timeframe
from fefat.reference.engine import ReferenceEngine
from fefat.reference.event_log import EventKind
from fefat.reference.hours import AlwaysOpen, CalendarHours, TradingHours
from fefat.reference.ledger import Trade, trades_of
from fefat.reference.orders import OrderRole, PositionSide, Side, TicksBracket
from fefat.reference.settings import RunSettings
from fefat.reference.strategy import Decision, DecisionContext
from fefat.reference.tape import BarRecord, TradeRecord, tape_of_bars, tape_of_trades
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_nanoseconds, instrument_parameters, lots_of, price_units

ONE_MINUTE = Timeframe.parse("1m")
MES = instrument_parameters(instruments.get("MES"))


def bar(ts_open: str, ts_close: str, *prices: str, day: str = "2026-03-06") -> BarRecord:
    """A 1-minute bar of MES with its open, high, low, and close, as a scenario writes it."""
    open_, high, low, close = prices
    return BarRecord.model_validate(
        {
            "ts_open": f"{day}T{ts_open}Z",
            "ts_close": f"{day}T{ts_close}Z",
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10,
        }
    )


def decision_at(clock: str, day: str = "2026-03-06") -> Decision:
    ts = instant_nanoseconds(f"{day}T{clock}Z")
    return Decision(ts=ts, bar={"ts_close": ts})


def buy_with_a_bracket_then_flatten(bar_row: Any, context: DecisionContext) -> None:
    """Buy one lot with a bracket 12 ticks under and 24 over the fill when flat, and close the
    position at the next decision."""
    if context.position == 0 and not context.has_working_orders():
        context.market(Side.BUY, 1, TicksBracket(stop_ticks=12, target_ticks=24))
    elif context.position != 0:
        context.flatten()


def run_on_bars(
    tape: tuple[BarRecord, ...], decisions: list[Decision], hours: TradingHours | None = None
) -> RunResult:
    engine = ReferenceEngine(
        RunSettings.for_fidelity(ONE_MINUTE), MES, ONE_MINUTE, hours or AlwaysOpen()
    )
    return engine.run(tape, decisions, buy_with_a_bracket_then_flatten)


def test_a_bracket_in_ticks_is_set_from_its_entrys_fill_and_closes_the_trade() -> None:
    tape = (
        bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
        bar("14:32:00", "14:33:00", "5001.00", "5007.00", "5000.50", "5006.50"),
    )

    result = run_on_bars(tape, [decision_at("14:31:00")])

    entry, target = result.fills
    assert (entry.price, entry.rule, entry.role) == (
        price_units("5000.75"),
        "F-MKT-03",
        OrderRole.ENTRY,
    )
    assert (target.price, target.rule, target.role) == (
        price_units("5006.75"),
        "F-LMT-03",
        OrderRole.TARGET,
    )
    assert trades_of(result.fills) == (
        Trade(
            side=PositionSide.LONG,
            lots=1,
            entry_ts=instant_nanoseconds("2026-03-06T14:32:00Z"),
            entry_price=price_units("5000.75"),
            exit_ts=instant_nanoseconds("2026-03-06T14:33:00Z"),
            exit_price=price_units("5006.75"),
            exit_reason=OrderRole.TARGET,
            pnl=30_000_000,
            fees=0,
        ),
    )
    assert result.position == 0


def test_flatten_cancels_the_bracket_and_closes_at_the_next_bar() -> None:
    tape = (
        bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
        bar("14:32:00", "14:33:00", "5002.00", "5002.50", "5001.50", "5002.25"),
    )

    result = run_on_bars(tape, [decision_at("14:31:00"), decision_at("14:32:00")])

    assert [(fill.role, fill.price) for fill in result.fills] == [
        (OrderRole.ENTRY, price_units("5000.75")),
        (OrderRole.EXIT, price_units("5001.75")),
    ]
    cancelled = [entry for entry in result.log.entries if entry.kind is EventKind.CANCELLED]
    assert [entry.order for entry in cancelled] == [2, 3]
    (trade,) = trades_of(result.fills)
    assert (trade.exit_reason, trade.pnl) == (OrderRole.EXIT, 5_000_000)


def test_a_bar_that_opens_in_the_break_is_not_replayed(tmp_path: Path) -> None:
    # MES's session of Thursday 2026-03-05 closes at 22:00 UTC, the next opens at 23:00 UTC.
    sessions = sessions_of(instruments.get("MES").session_calendar(), tmp_path)
    thursday = "2026-03-05"
    tape = (
        bar("21:58:00", "21:59:00", "5000.00", "5000.50", "4999.75", "5000.25", day=thursday),
        bar("21:59:00", "22:00:00", "5000.25", "5000.50", "5000.00", "5000.25", day=thursday),
        bar("22:10:00", "22:11:00", "4990.00", "4990.50", "4989.75", "4990.25", day=thursday),
        bar("23:00:00", "23:01:00", "5001.00", "5001.50", "5000.75", "5001.25", day=thursday),
    )
    first, last = tape[0].ts_open, tape[-1].ts_close
    hours = CalendarHours.around(sessions, first, last)

    result = run_on_bars(tape, [decision_at("22:00:00", day=thursday)], hours)

    (entry,) = result.fills
    assert (entry.ts, entry.price) == (
        instant_nanoseconds("2026-03-05T23:01:00Z"),
        price_units("5001.25"),
    )
    assert not hours.is_open(tape[2].ts_open)


def test_a_decision_without_a_strategy_is_refused() -> None:
    engine = ReferenceEngine(RunSettings.for_fidelity(ONE_MINUTE), MES, ONE_MINUTE, AlwaysOpen())
    tape = (bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),)

    with pytest.raises(ValueError, match="Expected an on_bar strategy for the decisions"):
        engine.run(tape, [decision_at("14:31:00")])


def test_a_tape_of_another_fidelitys_records_is_refused() -> None:
    trades = TickFidelity.TRADES
    engine = ReferenceEngine(RunSettings.for_fidelity(trades), MES, trades, AlwaysOpen())
    tape = (bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),)

    with pytest.raises(ValueError, match="Expected a tape of TradeRecord for fidelity trades"):
        engine.run(tape)


def test_a_bar_without_trades_is_refused() -> None:
    empty = bar("14:30:00", "14:31:00", "5000.00", "5000.00", "5000.00", "5000.00").model_copy(
        update={"volume": 0}
    )
    engine = ReferenceEngine(RunSettings.for_fidelity(ONE_MINUTE), MES, ONE_MINUTE, AlwaysOpen())

    with pytest.raises(ValueError, match=r"Expected stored bars with trades \(F-BAR-07\)"):
        engine.run((empty,))


def signal_bars(**columns: list[Any]) -> pl.DataFrame:
    """Two rows of `load`'s frame of MESM2026, the second an empty bucket, with `columns`."""
    rows: dict[str, list[Any]] = {
        "ts_open": [1_000, 61_000],
        "ts_close": [61_000, 121_000],
        "trade_date": [date(2026, 3, 6)] * 2,
        "instrument_id": [1, 1],
        "open": [5_010_000_000_000, 5_011_000_000_000],
        "high": [5_012_000_000_000, 5_011_000_000_000],
        "low": [5_009_000_000_000, 5_011_000_000_000],
        "close": [5_011_000_000_000, 5_011_000_000_000],
        "volume": [7, 0],
        "trade_count": [3, 0],
        "vwap": [None, None],
        "contract": ["MESM2026"] * 2,
        "close_raw": [5_001_000_000_000, 5_001_000_000_000],
        "adj_offset": [10_000_000_000, 10_000_000_000],
        "roll_flag": [False, False],
        "zero_volume": [False, True],
    }
    return pl.DataFrame({**rows, **columns}, schema=SIGNAL_BAR_COLUMNS)


def test_a_tape_of_bars_leaves_out_empty_buckets_and_takes_the_raw_prices() -> None:
    (stored,) = tape_of_bars(signal_bars())

    assert (stored.open, stored.high, stored.low, stored.close) == (
        price_units("5000.00"),
        price_units("5002.00"),
        price_units("4999.00"),
        price_units("5001.00"),
    )
    assert (stored.ts_open, stored.ts_close, stored.volume) == (1_000, 61_000, 7)


def test_a_tape_of_bars_refuses_a_back_adjusted_series_and_a_roll() -> None:
    with pytest.raises(ValueError, match="Expected a series with raw prices"):
        tape_of_bars(signal_bars(close_raw=[None, None], adj_offset=[None, None]))
    with pytest.raises(ValueError, match="Expected the bars of one contract"):
        tape_of_bars(signal_bars(contract=["MESH2026", "MESM2026"]))


def test_a_tape_of_trades_reads_the_receive_clock_in_the_vendors_order() -> None:
    trades = pl.DataFrame(
        {
            "ts_recv": [300, 200, 200],
            "ts_event": [290, 190, 195],
            "price": [3, 2, 1],
            "size": [1, 2, 3],
            "sequence": [9, 8, 7],
        }
    )

    tape = tape_of_trades(trades)

    assert tape == (
        TradeRecord.model_construct(ts=200, ts_event=195, price=1, size=3),
        TradeRecord.model_construct(ts=200, ts_event=190, price=2, size=2),
        TradeRecord.model_construct(ts=300, ts_event=290, price=3, size=1),
    )


def test_the_instrument_tables_decimals_become_the_engines_integers() -> None:
    es = instrument_parameters(instruments.get("ES"))
    perpetual = instrument_parameters(instruments.get("BTCUSDT-PERP"))

    assert (es.tick, es.money_per_point, MES.money_per_point) == (
        250_000_000,
        50_000_000,
        5_000_000,
    )
    assert (perpetual.tick, perpetual.money_per_point) == (100_000_000, 1_000)
    assert lots_of(Decimal("0.013"), Decimal("0.001")) == 13
    with pytest.raises(ValueError, match=r"Expected a quantity in whole lots of 0.001"):
        lots_of(Decimal("0.0135"), Decimal("0.001"))
