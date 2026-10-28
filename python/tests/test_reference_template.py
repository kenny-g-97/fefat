"""Steps 2.3 and 2.8's template in the reference engine: a `StrategySpec` runs from a signal frame
through `TemplateStrategy`, every rule of the specification runs, the flat-by time becomes one
instant per trade date across the clock change, and on an early close the last signal close
before the close, and the template fills as the hand-written strategy of step 2.2 does on the
same bars."""

import re
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml
from pydantic import ValidationError

from fefat.market import instruments
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.schema import Timeframe
from fefat.reference.engine import ReferenceEngine
from fefat.reference.event_log import EventKind
from fefat.reference.hours import AlwaysOpen
from fefat.reference.orders import OrderRole
from fefat.reference.scenarios import TemplateScenario
from fefat.reference.settings import RunSettings
from fefat.reference.signal_rows import SignalRow, signal_frame
from fefat.reference.strategy import decisions_of
from fefat.reference.tape import BarRecord
from fefat.reference.template import TemplateStrategy
from fefat.reference.time_rules import flat_by_instants, with_time_rules
from fefat.reference.timeline import RunResult
from fefat.reference.units import instant_nanoseconds, instrument_parameters, price_units
from fefat.strategy import (
    BarsCooldown,
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
)
from test_reference_engine import ONE_MINUTE, bar, decision_at, run_on_bars

SCENARIOS = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
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
        (date(2021, 6, 24), "15:20", "outside the halts of the session of 2021-06-24"),
        (date(2021, 6, 24), "15:15", "at or inside the halt from 2021-06-24T20:15:00Z"),
        (date(2026, 3, 6), "15:03", "on a close of the 5m signal bars of 2026-03-06"),
    ],
)
def test_a_flat_by_time_inside_a_halt_or_off_the_grid_is_refused(
    es_sessions: SessionTable, day: date, flat_by: str, refusal: str
) -> None:
    # Equity index halted daily from 15:15 to 15:30 Chicago until trade date 2021-06-28.
    with pytest.raises(ValueError, match=refusal):
        flat_by_instants([day], flat_by, "America/Chicago", es_sessions, FIVE_MINUTES)


@pytest.mark.parametrize(
    "rules",
    [
        {"entry": Limit(offset_ticks=2, time_to_live_bars=3)},
        {"on_opposite_signal": OppositeSignal.REVERSE},
        {"time": TimeRules(tz="UTC", windows=[EntryWindow(start="08:30", end="14:30")])},
        {"time": TimeRules(tz="UTC", max_bars=12, max_minutes=60)},
        {"limits": Limits(cooldown_after_loss=BarsCooldown(bars=3), fresh_signal=True)},
        {"sizing": Notional(25_000)},
    ],
    ids=["limit entry", "reverse", "windows", "max bars and minutes", "limits", "notional"],
)
def test_every_rule_of_the_template_runs(rules: dict[str, Any]) -> None:
    # Step 2.3 refused these until step 2.8; S-template-035 to S-template-071 pin their fills.
    frame = signals({"ts_close": "14:31:00", "long_entry": True})

    TemplateStrategy(spec_of(**rules), frame, MES, None)


@pytest.mark.parametrize(
    "target", [Target(ticks=24), Target(r=2)], ids=["24 ticks", "twice the stop's 12 ticks"]
)
def test_the_template_fills_as_the_hand_written_strategy_on_the_same_bars(target: Any) -> None:
    tape = (
        bar("14:30:00", "14:31:00", "5000.00", "5000.50", "4999.75", "5000.25"),
        bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),
        bar("14:32:00", "14:33:00", "5001.00", "5007.00", "5000.50", "5006.50"),
    )
    by_hand = run_on_bars(tape, [decision_at("14:31:00")])

    entry_signal = signals({"ts_close": "14:31:00", "long_entry": True})
    by_template = run_template(spec_of(targets=[target]), entry_signal, tape)

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
        (4, OrderRole.SIGNAL_EXIT),
    ]
    cancelled = [entry.order for entry in result.log.entries if entry.kind is EventKind.CANCELLED]
    assert cancelled == [2, 3]


def test_size_mult_multiplies_the_fixed_size_of_an_entry() -> None:
    frame = signals({"ts_close": "14:31:00", "long_entry": True, "size_mult": 2.0})
    tape = (bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),)

    result = run_template(spec_of(), frame, tape)

    assert [(fill.order, fill.lots) for fill in result.fills] == [(1, 2)]


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


def test_a_stop_and_a_target_at_the_columns_on_the_wrong_sides_are_refused() -> None:
    # A short's stop belongs above its target: here the columns are swapped.
    row = {"ts_close": "14:31:00", "short_entry": True}
    swapped = signals(row | {"stop_price": "4990.00", "target_price": "5003.00"})
    columns = spec_of(stop=Stop(column=True), targets=[Target(column=True)])
    tape = (bar("14:31:00", "14:32:00", "5000.50", "5001.00", "5000.25", "5000.75"),)

    with pytest.raises(
        ValueError, match="Expected the stop_price above the target_price of a sell"
    ):
        run_template(columns, swapped, tape)


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


@pytest.mark.parametrize("flat_by", ["16:00", "16:30"])
def test_a_flat_by_time_at_or_after_the_close_acts_at_the_last_signal_close_before_it(
    es_sessions: SessionTable, flat_by: str
) -> None:
    # F-TIM-01: the session of Friday 2026-03-06 closes at 16:00 Chicago, 22:00 UTC, at or before
    # the flat-by time, as an early close does; an exit decided at the close would wait for
    # Sunday's open, so the template closes at the last signal close before it, 21:55.
    spec = spec_of(time=TimeRules(tz="America/Chicago", flat_by=flat_by))
    frame = signals({"ts_close": "21:50:00"}, {"ts_close": "21:55:00"}, {"ts_close": "22:00:00"})

    timed = with_time_rules(spec, frame, es_sessions)

    last_before_the_close = instant_nanoseconds("2026-03-06T21:55:00Z")
    assert timed.get_column("flat_by").to_list() == [last_before_the_close] * 3


def test_a_flat_by_time_at_the_sessions_open_is_refused(tmp_path: Path) -> None:
    # A crypto trade date is its UTC day, so 00:00 UTC is the open of its session, where no bar
    # closes.
    day = instruments.get("BTCUSDT-PERP").session_calendar()
    sessions = sessions_of(day, tmp_path)

    with pytest.raises(ValueError, match="inside the session of 2026-03-07"):
        flat_by_instants([date(2026, 3, 7)], "00:00", "UTC", sessions, FIVE_MINUTES)


def test_a_template_scenario_whose_size_is_off_the_lot_step_is_refused_when_it_loads() -> None:
    written = yaml.safe_load((SCENARIOS / "S-template-001.yaml").read_text(encoding="utf-8"))
    written["strategy"]["execution"]["sizing"]["units"] = 0.5

    with pytest.raises(ValidationError, match=re.escape("on the lot step of 1, got 0.5")):
        TemplateScenario.model_validate(written)
