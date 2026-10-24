"""Step 2.3's template in the reference engine: a `StrategySpec`'s basic subset runs from a signal
frame through `TemplateStrategy`, the flat-by time becomes one instant per trade date across the
clock change, the rest of the template is refused until step 2.8, and the template fills as the
hand-written strategy of step 2.2 does on the same bars."""

import re
from datetime import date
from typing import Any

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.schema import Timeframe
from fefat.reference.engine import ReferenceEngine
from fefat.reference.event_log import EventKind
from fefat.reference.hours import AlwaysOpen
from fefat.reference.orders import OrderRole
from fefat.reference.settings import RunSettings
from fefat.reference.signal_rows import SignalRow, signal_frame
from fefat.reference.strategy import decisions_of
from fefat.reference.tape import BarRecord
from fefat.reference.template import TemplateStrategy
from fefat.reference.time_rules import flat_by_instants
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_nanoseconds, instrument_parameters, price_units
from fefat.strategy import (
    BarsCooldown,
    Breakeven,
    EntryWindow,
    Execution,
    Fixed,
    Limit,
    Limits,
    Market,
    Notional,
    OppositeSignal,
    Stop,
    StrategySpec,
    Target,
    TimeRules,
    Trailing,
)
from test_reference_engine import ONE_MINUTE, bar, decision_at, run_on_bars

ES = instruments.get("ES")
MES = instrument_parameters(instruments.get("MES"))
FIVE_MINUTES = Timeframe.parse("5m")


@pytest.fixture(scope="module")
def es_sessions(tmp_path_factory: pytest.TempPathFactory) -> SessionTable:
    return sessions_of(ES.session_calendar(), tmp_path_factory.mktemp("cache"))


def spec_of(**rules: Any) -> StrategySpec:
    """MES on 5-minute signal bars: a market entry with a stop 12 ticks and a target 24 ticks
    from its fill, one lot, with `rules` in place of its own."""
    own = {
        "entry": Market(),
        "stop": Stop(ticks=12),
        "targets": [Target(ticks=24)],
        "sizing": Fixed(1),
    }
    execution = Execution.model_validate({**own, **rules})
    return StrategySpec(spec_version=1, instrument="MES", timeframe="5m", execution=execution)


def signals(*rows: dict[str, Any]) -> pl.DataFrame:
    """The signal frame of `rows`, signal closes of MESM2026 on 2026-03-06 at their UTC clocks."""
    on_the_day = [
        {"trade_date": "2026-03-06", "contract": "MESM2026", **row}
        | {"ts_close": f"2026-03-06T{row['ts_close']}Z"}
        for row in rows
    ]
    return signal_frame([SignalRow.model_validate(row) for row in on_the_day])


def run_template(spec: StrategySpec, frame: pl.DataFrame, tape: tuple[BarRecord, ...]) -> RunResult:
    template = TemplateStrategy(spec, frame, MES, None)
    engine = ReferenceEngine(RunSettings.for_fidelity(ONE_MINUTE), MES, ONE_MINUTE, AlwaysOpen())
    return engine.run(tape, decisions_of(frame), template.on_bar)


def test_the_flat_by_time_is_one_instant_per_trade_date_across_the_clock_change(
    es_sessions: SessionTable,
) -> None:
    # Chicago moves to summer time on 2026-03-08: 15:05 there is 21:05 UTC on Friday 03-06 and
    # 20:05 UTC on Monday 03-09.
    days = [date(2026, 3, 9), date(2026, 3, 6), date(2026, 3, 6)]

    instants = flat_by_instants(days, "15:05", "America/Chicago", es_sessions, FIVE_MINUTES)

    assert instants == {
        date(2026, 3, 6): instant_nanoseconds("2026-03-06T21:05:00Z"),
        date(2026, 3, 9): instant_nanoseconds("2026-03-09T20:05:00Z"),
    }


@pytest.mark.parametrize(
    ("day", "flat_by", "refusal"),
    [
        (date(2026, 3, 6), "16:30", "inside the session of 2026-03-06"),
        (date(2021, 6, 24), "15:20", "outside the halts of the session of 2021-06-24"),
        (date(2026, 3, 6), "15:03", "on a close of the 5m signal bars of 2026-03-06"),
    ],
)
def test_a_flat_by_time_outside_its_session_inside_a_halt_or_off_the_grid_is_refused(
    es_sessions: SessionTable, day: date, flat_by: str, refusal: str
) -> None:
    # Equity index halted daily from 15:15 to 15:30 Chicago until trade date 2021-06-28.
    with pytest.raises(ValueError, match=refusal):
        flat_by_instants([day], flat_by, "America/Chicago", es_sessions, FIVE_MINUTES)


@pytest.mark.parametrize(
    ("rules", "refused"),
    [
        ({"entry": Limit(offset_ticks=2)}, "an entry of kind limit_offset"),
        ({"on_opposite_signal": OppositeSignal.REVERSE}, "on_opposite_signal reverse"),
        ({"stop": Stop(percent=0.5)}, "a stop of kind percent"),
        ({"stop": Stop(atr=1.5)}, "a stop of kind atr"),
        ({"stop": None}, "no stop"),
        ({"targets": [Target(ticks=8, fraction=0.5), Target(ticks=24)]}, "2 targets"),
        ({"targets": [Target(ticks=8, fraction=0.5)]}, "a target closing part of the position"),
        ({"targets": [Target(atr=2)]}, "a target of kind atr"),
        ({"targets": [Target(r=1.3)]}, "an R multiple of 1.3 times 12 ticks, off the tick"),
        (
            {"stop": Stop(column=True), "targets": [Target(r=2)]},
            "an R multiple without a stop in ticks",
        ),
        ({"breakeven": Breakeven(after_target=1)}, "breakeven"),
        ({"trailing": Trailing(ticks=8)}, "a trailing stop"),
        (
            {"time": TimeRules(tz="UTC", windows=[EntryWindow(start="08:30", end="14:30")])},
            "entry windows",
        ),
        ({"time": TimeRules(tz="UTC", max_bars=12)}, "max_bars"),
        ({"time": TimeRules(tz="UTC", no_overnight=True)}, "no_overnight"),
        ({"limits": Limits(cooldown_after_loss=BarsCooldown(bars=3))}, "entry limits"),
        ({"sizing": Notional(25_000)}, "sizing of kind notional"),
    ],
)
def test_a_spec_beyond_the_basic_subset_is_refused_until_step_2_8(
    rules: dict[str, Any], refused: str
) -> None:
    frame = signals({"ts_close": "14:31:00", "long_entry": True})

    with pytest.raises(ValueError, match=rf"basic subset .*{re.escape(refused)}.*step 2\.8"):
        TemplateStrategy(spec_of(**rules), frame, MES, None)


def test_the_template_fills_as_the_hand_written_strategy_on_the_same_bars() -> None:
    tape = (
        bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
        bar("14:32:00", "14:33:00", "5001.00", "5007.00", "5000.50", "5006.50"),
    )
    by_hand = run_on_bars(tape, [decision_at("14:31:00")])

    entry_signal = signals({"ts_close": "14:31:00", "long_entry": True})
    by_template = run_template(spec_of(), entry_signal, tape)

    assert by_template.fills == by_hand.fills


def test_an_exit_still_working_is_not_placed_again_at_the_next_decision() -> None:
    # No bar trades between the exit signal at 14:32 and the decision at 14:33, so the exit placed
    # at 14:32 still works then; it fills on the bar from 14:34 to 14:35.
    tape = (
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
        bar("14:34:00", "14:35:00", "5002.00", "5002.50", "5001.50", "5002.25"),
    )
    frame = signals(
        {"ts_close": "14:31:00", "long_entry": True},
        {"ts_close": "14:32:00", "long_exit": True},
        {"ts_close": "14:33:00", "long_exit": True},
    )

    result = run_template(spec_of(), frame, tape)

    assert [(fill.order, fill.role) for fill in result.fills] == [
        (1, OrderRole.ENTRY),
        (4, OrderRole.EXIT),
    ]
    cancelled = [entry.order for entry in result.log.entries if entry.kind is EventKind.CANCELLED]
    assert cancelled == [2, 3]


def test_a_size_mult_that_makes_part_of_a_lot_is_refused() -> None:
    frame = signals({"ts_close": "14:31:00", "long_entry": True, "size_mult": 1.5})
    tape = (bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),)

    with pytest.raises(ValueError, match="Expected size_mult to make whole lots"):
        run_template(spec_of(), frame, tape)


@pytest.mark.parametrize(
    ("rows", "refusal"),
    [
        (
            ({"ts_close": "14:31:00", "long_entry": True},),
            "Expected the signal frame's stop_price for a stop at the column, got no such column",
        ),
        (
            (
                {"ts_close": "14:31:00", "long_entry": True},
                {"ts_close": "14:36:00", "stop_price": "4990.00"},
            ),
            "Expected the signal frame's stop_price on the entry's bar closing at "
            "2026-03-06T14:31:00Z, got null",
        ),
        (
            ({"ts_close": "14:31:00", "long_entry": True, "stop_price": "4997.10"},),
            "Expected stop_price on the instrument's tick of 0.25, got 4997.1",
        ),
    ],
)
def test_a_stop_at_the_column_needs_its_price_on_the_tick(
    rows: tuple[dict[str, Any], ...], refusal: str
) -> None:
    tape = (bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),)

    with pytest.raises(ValueError, match=re.escape(refusal)):
        run_template(spec_of(stop=Stop(column=True)), signals(*rows), tape)


def test_a_flat_by_time_needs_a_session_calendar() -> None:
    spec = spec_of(time=TimeRules(tz="America/Chicago", flat_by="15:05"))

    with pytest.raises(ValueError, match="Expected a session calendar for the flat-by time"):
        TemplateStrategy(spec, signals({"ts_close": "14:31:00"}), MES, None)


def test_a_signal_frame_with_both_entries_on_a_bar_is_refused() -> None:
    frame = signals({"ts_close": "14:31:00", "long_entry": True, "short_entry": True})

    with pytest.raises(ValueError, match="Expected one of long_entry and short_entry per bar"):
        TemplateStrategy(spec_of(), frame, MES, None)


def test_signal_rows_give_a_frame_of_raw_prices_with_only_the_columns_they_set() -> None:
    frame = signals({"ts_close": "14:31:00", "stop_price": "4997.25"}, {"ts_close": "14:36:00"})

    assert frame.columns == [
        "ts_close",
        "trade_date",
        "contract",
        "adj_offset",
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "stop_price",
    ]
    assert frame.get_column("stop_price").to_list() == [price_units("4997.25"), None]
    assert frame.get_column("adj_offset").to_list() == [0, 0]
