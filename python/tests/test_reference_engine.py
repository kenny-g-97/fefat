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
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.continuous import volume_rolls
from fefat.market.fidelity import TickFidelity
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.schema import Timeframe, parse_schema_name
from fefat.market.store import Store
from fefat.reference.costs import DatedFees, DatedFuturesFee, RunFees
from fefat.reference.engine import ReferenceEngine
from fefat.reference.event_log import EventKind
from fefat.reference.exit_plan import ExitPlan
from fefat.reference.hours import AlwaysOpen, CalendarHours, TradingHours
from fefat.reference.ledger import Trade, trades_of
from fefat.reference.orders import OrderRole, PositionSide, Side
from fefat.reference.rolls import rolls_within, tape_across_rolls
from fefat.reference.scenario_runner import run_scenario, scenario_hours
from fefat.reference.scenarios import Scenario, load_scenario
from fefat.reference.settings import RunSettings
from fefat.reference.strategy import Decision, DecisionContext
from fefat.reference.tape import (
    BarRecord,
    FundingRate,
    TbboRecord,
    TradeRecord,
    funding_rates_of,
    tape_of_bars,
    tape_of_trades,
)
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_nanoseconds, instrument_parameters, lots_of, price_units

ONE_MINUTE = Timeframe.parse("1m")
MES = instrument_parameters(instruments.get("MES"))
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BTC_FUNDING = Dataset(
    provider="synthetic", schema_name=parse_schema_name("funding"), root="BTCUSDT-PERP"
)
QUIET = ("5000.00", "5000.00", "5000.00", "5000.00")
FRIDAY, MONDAY = "2026-03-06T14:30:00", "2026-03-09T14:30:00"
END = instant_nanoseconds("2026-03-09T21:00:00Z")


def fixture_minutes() -> pl.DataFrame:
    """The fixtures' 1-minute bars of ES, each with its contract (`Store.scan_contracts`)."""
    es_minutes = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    request = PartitionRequest(dataset=es_minutes, start=date(2026, 3, 5), end=date(2026, 3, 9))
    return Store(FIXTURES).scan_contracts(request).collect()


def sessions_of_es(cache: Path) -> SessionTable:
    return sessions_of(instruments.get("ES").session_calendar(), cache)


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
        context.market(Side.BUY, 1, ExitPlan.in_ticks(stop_ticks=12, target_ticks=24))
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
        OrderRole.TARGET_1,
    )
    assert trades_of(result.fills) == (
        Trade(
            side=PositionSide.LONG,
            lots=1,
            entry_ts=instant_nanoseconds("2026-03-06T14:32:00Z"),
            entry_price=price_units("5000.75"),
            exit_ts=instant_nanoseconds("2026-03-06T14:33:00Z"),
            exit_price=price_units("5006.75"),
            exit_reason=OrderRole.TARGET_1,
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


def tbbo_record(clock: str, price: str, bid: str, ask: str) -> TbboRecord:
    """A TBBO record of 2026-03-06: two lots traded under five bid and five offered."""
    return TbboRecord.model_validate(
        {
            "ts": f"2026-03-06T{clock}Z",
            "price": price,
            "size": 2,
            "bid": bid,
            "ask": ask,
            "bid_size": 5,
            "ask_size": 5,
        }
    )


def test_flatten_leaves_a_stop_triggered_on_tbbo_to_fill_on_the_next_record() -> None:
    # F-STP-02: from its trigger a TBBO stop is a market order already sent, which no decision
    # cancels, so the flatten at 14:35 leaves the stop triggered at 14:34:59.950 to fill on the
    # next record (S-template-005, by hand).
    tape = (
        tbbo_record("14:30:00.200", "5000.00", "4999.75", "5000.00"),
        tbbo_record("14:34:59.950", "4997.00", "4996.75", "4997.00"),
        tbbo_record("14:35:00.020", "4996.75", "4996.50", "4996.75"),
        tbbo_record("14:35:00.300", "4995.00", "4994.75", "4995.00"),
    )
    tbbo = TickFidelity.TBBO
    engine = ReferenceEngine(RunSettings.for_fidelity(tbbo), MES, tbbo, AlwaysOpen())
    decisions = [decision_at("14:30:00"), decision_at("14:35:00")]

    result = engine.run(tape, decisions, buy_with_a_bracket_then_flatten)

    assert [(fill.role, fill.price, fill.rule) for fill in result.fills] == [
        (OrderRole.ENTRY, price_units("5000.00"), "F-MKT-01"),
        (OrderRole.STOP, price_units("4996.50"), "F-STP-02"),
    ]


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


def test_the_market_is_closed_inside_a_sessions_halt(tmp_path: Path) -> None:
    # Labor Day 2026: MES halts from 12:00 to 17:00 Chicago, 17:00 to 22:00 UTC, inside the
    # session of 2026-09-08, and nothing trades or fills there (F-SES-02).
    sessions = sessions_of(instruments.get("MES").session_calendar(), tmp_path)
    halts = instant_nanoseconds("2026-09-07T17:00:00Z")
    reopens = instant_nanoseconds("2026-09-07T22:00:00Z")
    hours = CalendarHours.around(sessions, halts, reopens)

    edges = (halts - 1, halts, reopens - 1, reopens)
    assert [hours.is_open(instant) for instant in edges] == [True, False, False, True]


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


def spliced_across_the_roll(**columns: list[Any]) -> pl.DataFrame:
    """A bar of ESH2026 on 2026-03-06 and one of ESM2026 on 2026-03-09, after the fixtures' roll,
    the second the new front's first, as `load` splices them, 20.00 above the first's prices."""
    friday, monday = instant_nanoseconds(f"{FRIDAY}Z"), instant_nanoseconds(f"{MONDAY}Z")
    spliced = {
        "ts_open": [friday, monday],
        "ts_close": [friday + 60 * 10**9, monday + 60 * 10**9],
        "contract": ["ESH2026", "ESM2026"],
        "adj_offset": [0, -20_000_000_000],
        "roll_flag": [False, True],
        "volume": [7, 5],
        "zero_volume": [False, False],
    }
    return signal_bars(**{**spliced, **columns})


def test_a_tape_across_a_roll_gives_each_front_at_its_own_prices_and_the_roll(
    tmp_path: Path,
) -> None:
    # Step 2.9 (F-ROL-01): a series load spliced is replayed at each front's raw prices, its
    # prices less its adj_offset, which the roll's gap separates (D-09), with the roll between
    # them, which a run across it must be given.
    calendar = volume_rolls(fixture_minutes(), sessions_of_es(tmp_path), instruments.get("ES"), END)

    (first, second), (roll,) = tape_across_rolls(spliced_across_the_roll(), calendar)

    assert (first.open, first.close) == (price_units("5010.00"), price_units("5011.00"))
    assert (second.open, second.close) == (price_units("5031.00"), price_units("5031.00"))
    assert (roll.rolled_from, roll.contract) == ("ESH2026", "ESM2026")


def test_a_tape_across_rolls_refuses_bars_its_calendar_did_not_splice(tmp_path: Path) -> None:
    # Step 2.9 (F-ROL-01): the bars of every contract, which a load without splicing returns,
    # change contract without a new front's first bar, and contracts the calendar's rolls do not
    # pass between would be replayed without their roll.
    calendar = volume_rolls(fixture_minutes(), sessions_of_es(tmp_path), instruments.get("ES"), END)

    with pytest.raises(ValueError, match="Expected a series spliced by the roll calendar of ES"):
        tape_across_rolls(spliced_across_the_roll(roll_flag=[False, False]), calendar)
    with pytest.raises(ValueError, match="Expected the bars of ESH2026, ESM2026"):
        tape_across_rolls(spliced_across_the_roll(contract=["ESH2026", "ESU2026"]), calendar)


def test_the_rolls_a_tape_crosses_are_those_of_the_roll_calendar_inside_it(
    tmp_path: Path,
) -> None:
    # Step 2.9 (F-ROL-01): the fixtures' roll at the open of 2026-03-09 lies inside a tape from
    # 2026-03-06 to 03-09, and outside one of 03-09 alone, which starts after it.
    calendar = volume_rolls(fixture_minutes(), sessions_of_es(tmp_path), instruments.get("ES"), END)
    across = (
        bar("14:30:00", "14:31:00", *QUIET),
        bar("14:30:00", "14:31:00", *QUIET, day="2026-03-09"),
    )
    after = (bar("14:30:00", "14:31:00", *QUIET, day="2026-03-09"),)
    up_to_the_open = (
        bar("14:30:00", "14:31:00", *QUIET),
        bar("21:59:00", "22:00:00", *QUIET, day="2026-03-08"),
    )

    (roll,) = rolls_within(calendar, across)

    assert (roll.rolled_from, roll.contract, str(roll.reason)) == ("ESH2026", "ESM2026", "volume")
    assert roll.session_open == instant_nanoseconds("2026-03-08T22:00:00Z")
    assert rolls_within(calendar, after) == ()
    # A bar that closes at the roll's open comes before the roll, so no bar follows it (F-CLK-02).
    assert rolls_within(calendar, up_to_the_open) == ()


def test_the_fixtures_funding_rows_read_as_the_engines_funding_rates() -> None:
    # Step 2.9 (F-FND-01): a rate at each funding time of the BTC day, read from 1e-9 units.
    request = PartitionRequest(dataset=BTC_FUNDING, start=date(2026, 3, 7), end=date(2026, 3, 7))
    rates = funding_rates_of(Store(FIXTURES).scan(request).collect())

    assert [rate.ts for rate in rates] == [
        instant_nanoseconds(f"2026-03-07T{hour}:00:00Z") for hour in ("00", "08", "16")
    ]
    assert [rate.rate for rate in rates] == [
        Decimal("0.000082070"),
        Decimal("0.000146280"),
        Decimal("-0.000005730"),
    ]


def test_a_tape_of_trades_reads_the_receive_clock_in_the_vendors_order() -> None:
    trades = pl.DataFrame(
        {
            "ts_recv": [300, 200, 200],
            "ts_event": [290, 190, 195],
            "instrument_id": [1001, 1001, 1001],
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


def test_a_tape_of_trades_refuses_the_trades_of_two_contracts() -> None:
    trades = pl.DataFrame(
        {
            "ts_recv": [100, 200],
            "ts_event": [90, 190],
            "instrument_id": [1001, 1003],
            "price": [1, 2],
            "size": [1, 1],
            "sequence": [1, 2],
        }
    )

    with pytest.raises(ValueError, match="Expected the trades of one contract, got instruments"):
        tape_of_trades(trades)


def test_an_oco_sibling_cancelled_at_a_bars_open_never_fills() -> None:
    # Both stops are through the market, the last close at 5000.00, when they see their first bar,
    # so both would fill at its open as market orders (F-STP-05): the lower id fills at
    # 5000.50 + 0.25, and the other, cancelled at once (F-OCO-01), must not fill after all.
    placed, oco = "2026-03-06T14:31:00.000Z", "fade"
    scenario = Scenario.model_validate(
        {
            "id": "S-fill-900",
            "title": "Of two stops of one OCO group both through the market at a bar's open, one fills",
            "fidelity": "1m",
            "instrument": "ES",
            "orders": [
                {"id": 1, "placed_at": placed, "side": "buy", "kind": "stop", "price": "4995.00"}
                | {"quantity": 1, "oco": oco},
                {"id": 2, "placed_at": placed, "side": "sell", "kind": "stop", "price": "5005.00"}
                | {"quantity": 1, "oco": oco},
            ],
            "tape": [
                {"ts_open": "2026-03-06T14:30:00Z", "ts_close": "2026-03-06T14:31:00Z"}
                | {"open": "4999.50", "high": "5000.25", "low": "4999.25", "close": "5000.00"}
                | {"volume": 120},
                {"ts_open": "2026-03-06T14:31:00Z", "ts_close": "2026-03-06T14:32:00Z"}
                | {"open": "5000.50", "high": "5001.00", "low": "4999.75", "close": "5000.75"}
                | {"volume": 150},
            ],
            "expected": {
                "fills": [
                    {"order": 1, "ts": "2026-03-06T14:32:00Z", "price": "5000.75"}
                    | {"rule": "F-STP-05"}
                ]
            },
            "rules": ["F-OCO-01", "F-STP-05"],
        }
    )

    assert run_scenario(scenario, AlwaysOpen()).differences == ()


def test_a_strategy_enters_only_flat_and_with_nothing_working() -> None:
    def buys_twice(bar_row: Any, context: DecisionContext) -> None:
        context.market(Side.BUY, 1)
        context.market(Side.BUY, 1)

    def buys_nothing(bar_row: Any, context: DecisionContext) -> None:
        context.market(Side.BUY, 0)

    tape = (bar("14:31:00", "14:32:00", "5000.00", "5000.50", "4999.75", "5000.25"),)
    settings = RunSettings.for_fidelity(ONE_MINUTE)

    with pytest.raises(ValueError, match="Expected an entry while flat with no working orders"):
        ReferenceEngine(settings, MES, ONE_MINUTE, AlwaysOpen()).run(
            tape, [decision_at("14:31:00")], buys_twice
        )
    with pytest.raises(ValueError, match="Expected a whole number of lots above zero, got 0"):
        ReferenceEngine(settings, MES, ONE_MINUTE, AlwaysOpen()).run(
            tape, [decision_at("14:31:00")], buys_nothing
        )


def test_each_run_of_an_engine_starts_from_an_empty_book() -> None:
    tape = (
        bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
    )
    engine = ReferenceEngine(RunSettings.for_fidelity(ONE_MINUTE), MES, ONE_MINUTE, AlwaysOpen())

    first = engine.run(tape, [decision_at("14:31:00")], buy_with_a_bracket_then_flatten)
    second = engine.run(tape, [decision_at("14:31:00")], buy_with_a_bracket_then_flatten)

    assert second.fills == first.fills
    assert second.log is not first.log
    assert len(second.log.entries) == len(first.log.entries)


def test_a_position_is_marked_once_an_instant_at_its_last_trade() -> None:
    # F-MRK-01's mark "once every event at ts is done": two prints at one instant leave one mark.
    trades = TickFidelity.TRADES
    tape = tuple(
        TradeRecord.model_construct(ts=ts, ts_event=None, price=price_units(price), size=1)
        for ts, price in ((100, "5000.00"), (100, "5000.25"), (200, "5000.50"))
    )
    engine = ReferenceEngine(RunSettings.for_fidelity(trades), MES, trades, AlwaysOpen())

    marks = engine.run(tape, position=1).marks

    assert [(mark.ts, mark.price) for mark in marks] == [
        (100, price_units("5000.25")),
        (200, price_units("5000.50")),
    ]


def test_a_run_given_no_trade_dates_prices_fees_by_the_trade_dates_its_hours_give(
    tmp_path: Path,
) -> None:
    # Step 2.9 (F-FEE-01): a buy at 23:30 UTC on Sunday 2026-03-08 trades in the session of
    # 2026-03-09, whose schedule prices it, not the one of its UTC day.
    trades = TickFidelity.TRADES
    sunday = instant_nanoseconds("2026-03-08T23:30:00Z")
    tape = (
        TradeRecord.model_construct(
            ts=sunday + 200_000_000, ts_event=None, price=price_units("5000.00"), size=1
        ),
    )
    schedules = (
        DatedFuturesFee(per_contract_side=Decimal("2.00"), effective_from=date(2026, 3, 6)),
        DatedFuturesFee(per_contract_side=Decimal("2.50"), effective_from=date(2026, 3, 9)),
    )
    fees = RunFees.of(DatedFees(kind="futures", schedules=schedules))
    hours = CalendarHours.around(sessions_of_es(tmp_path), sunday, sunday)
    engine = ReferenceEngine(RunSettings.for_fidelity(trades), MES, trades, hours, fees)

    result = engine.run(
        tape, [Decision(ts=sunday, bar={"ts_close": sunday})], buy_with_a_bracket_then_flatten
    )

    assert [fill.fee for fill in result.fills] == [2_500_000]


def test_a_scenario_roll_off_its_sessions_open_is_refused(tmp_path: Path) -> None:
    # Step 2.9 (F-ROL-01): a roll comes at the open of its trade date's session, 22:00 UTC on
    # 2026-03-08 for ES's session of 03-09, so a scenario that names another instant is refused.
    scenario = load_scenario(FIXTURES / "scenarios" / "S-fill-058.yaml")
    (roll,) = scenario.rolls
    an_hour_late = roll.model_copy(update={"session_open": roll.session_open + 3_600 * 10**9})
    late = scenario.model_copy(update={"rolls": (an_hour_late,)})
    sessions = sessions_of_es(tmp_path)

    with pytest.raises(ValueError, match="Expected the roll on 2026-03-09 at its session's open"):
        run_scenario(late, scenario_hours(late, sessions), sessions)


def test_funding_times_out_of_order_or_repeated_are_refused() -> None:
    # Step 2.9 (F-FND-01): as the Rust engine does, rather than sorting them or paying twice.
    trades = TickFidelity.TRADES
    tape = (
        TradeRecord.model_construct(ts=100, ts_event=None, price=price_units("5000.00"), size=1),
    )
    engine = ReferenceEngine(RunSettings.for_fidelity(trades), MES, trades, AlwaysOpen())
    later, earlier = (
        FundingRate.model_construct(ts=300, rate=Decimal("0.0001")),
        FundingRate.model_construct(ts=200, rate=Decimal("0.0001")),
    )

    for rates in ((later, earlier), (earlier, earlier)):
        with pytest.raises(ValueError, match="Expected the funding times in order, each once"):
            engine.run(tape, funding_rates=rates, position=1)


def test_an_empty_tape_is_refused() -> None:
    every_bucket_empty = signal_bars(zero_volume=[True, True])
    no_trades = pl.DataFrame(
        schema={"ts_recv": pl.Int64, "ts_event": pl.Int64, "instrument_id": pl.UInt32}
        | {"price": pl.Int64, "size": pl.UInt32, "sequence": pl.UInt32}
    )

    with pytest.raises(ValueError, match="Expected stored bars with trades, got none in 2 rows"):
        tape_of_bars(every_bucket_empty)
    with pytest.raises(ValueError, match="Expected trades, got none"):
        tape_of_trades(no_trades)


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
