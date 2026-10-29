"""Full execution templates for the differential test of step 2.8, drawn by Hypothesis, a
development tool of the repository: every rule of the template but flat-by, no overnight, and no
weekend, which need an instrument's session calendar and which the scenarios pin; over three to
twelve drawn signal rows with the columns their rules read. A template draws its entry (market, a
limit or a stop at the column or an offset from the mark, with a time to live), its opposite
signals, its stop (ticks, percent, a feature, the column, or none), up to three targets with
their fractions, a breakeven, a trailing stop, entry windows and max bars and minutes in UTC, at
most one entry limit, so that a test can tell what it blocked, and its size (fixed, notional, or
risk). Each case is an `EngineCase` both engines run, on the tapes of `generated_cases`:

    @given(cases=st.lists(full_template_cases(DrawnTapes.TICKS), min_size=10, max_size=10))
    def test_the_engines_agree(cases): ...
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fefat.reference.generated_cases import (
    INSTRUMENTS,
    MILLISECOND,
    OFFSETS_MS,
    DrawnInstrument,
    DrawnTapes,
    drawn_costs_and_rolls,
    drawn_hours,
    drawn_settings,
    fidelity_and_tape,
)
from fefat.reference.orders import Side
from fefat.reference.rust_batch import EngineCase, Replay
from fefat.reference.scenarios import Expected, TemplateScenario
from fefat.reference.signal_rows import SignalRow
from fefat.reference.tape import Tape
from fefat.reference.units import utc_date
from fefat.strategy.spec import StrategySpec

if TYPE_CHECKING:
    from hypothesis.strategies import DrawFn, SearchStrategy

LIMITS = (
    {"blackout": "news"},
    {"max_trades_per_day": 1},
    {"max_trades_per_day": 2},
    {"max_losses_per_day": 1},
    {"max_losses_per_day": 1},
    {"max_losses_per_day": 1},
    {"daily_loss_stop": 25.0},
    {"daily_loss_stop": 25.0},
    {"daily_loss_stop": 25.0},
    {"profit_lock": 0.0001},
    {"profit_lock": 0.0001},
    {"profit_lock": 0.0001},
    {"cooldown_after_loss": {"kind": "bars", "bars": 2}},
    {"cooldown_after_loss": {"kind": "minutes", "minutes": 1}},
    {"fresh_signal": True},
)
"""The entry limits a template draws, one at most, those that need a loss first more often, and
the profit lock, which needs a win net of the drawn fees (step 2.9), as often."""
BARS_WALK = (20, 60)
"""The fewest and the most trades a template's bars are made of, more than an order case's 1 to
25, so that on bars a template trades more than once a day, as its entry limits need."""
CLOCKS = ("00:00", "14:00", "14:30", "14:31", "15:00", "23:00")
"""Local times, in UTC, that the drawn tapes' records fall around (from 14:30 on 2026-03-06)."""


@dataclass(frozen=True, slots=True)
class RowNeeds:
    """What a drawn template's rows must give: `entry_price`, `stop_price`, `target_price`, and
    `trail_ref` for its rules at the column, a feature for its rules by a feature, the blackout
    flag, and whether a row may give both entry signals, the pair; and how size_mult is drawn."""

    entry_price: bool
    stop_price: bool
    target_price: bool
    trail_ref: bool
    pair: bool
    fixed_size: bool


def full_template_cases(tapes: DrawnTapes) -> "SearchStrategy[EngineCase]":
    """The strategy of one drawn case of a full template on `tapes`."""
    from hypothesis import strategies as st

    @st.composite
    def drawn_template(draw: "DrawFn") -> EngineCase:
        drawn = draw(st.sampled_from(INSTRUMENTS))
        fidelity, tape = fidelity_and_tape(draw, drawn, tapes, bars_walk=BARS_WALK)
        hours = drawn_hours(draw, tape)
        spec, needs = _spec(draw, drawn)
        scenario = TemplateScenario.model_construct(
            id="a drawn full template",
            title="a drawn full template",
            fidelity=fidelity,
            instrument=drawn.instrument,
            settings=drawn_settings(draw),
            position=None,
            tape=tape,
            expected=Expected.model_construct(fills=(), marks=(), funding=()),
            rules=("F-CLK-01",),
            strategy=spec,
            signals=_rows(draw, drawn, tape, needs),
            **drawn_costs_and_rolls(draw, drawn, tape, hours),
        )
        replay = draw(st.sampled_from(tuple(Replay)))
        return EngineCase(scenario, hours, replay=replay)

    return drawn_template()


def _spec(draw: "DrawFn", drawn: DrawnInstrument) -> tuple[StrategySpec, RowNeeds]:
    from hypothesis import strategies as st

    entry = _entry(draw)
    stop = draw(st.sampled_from(("ticks", "percent", "atr", "column", None)))
    count = draw(st.sampled_from((0, 1, 2, 3, 3)))
    drawn_targets = [_target(draw, stop is not None) for _ in range(count)]
    targets = [target for _, target in drawn_targets]
    execution: dict[str, object] = {
        "entry": entry,
        "targets": targets,
        "on_opposite_signal": draw(st.sampled_from(("ignore", "close", "reverse"))),
        "signal_exit": draw(st.booleans()),
        "sizing": _sizing(draw, drawn, stop is not None),
    }
    if stop is not None:
        execution["stop"] = _stop(draw, stop)
        _protection(draw, execution, len(targets))
    time = _time(draw)
    if time is not None:
        execution["time"] = time
    if draw(st.sampled_from((True, True, True, False))):
        execution["limits"] = draw(st.sampled_from(LIMITS))
    document = {"spec_version": 1, "instrument": "ES", "timeframe": "1m", "execution": execution}
    spec = StrategySpec.model_validate(document)
    column_target = any(kind == "column" for kind, _ in drawn_targets)
    trailing = execution.get("trailing")
    needs = RowNeeds(
        entry_price=entry["kind"] in ("limit_at_column", "stop_at_column"),
        stop_price=stop == "column",
        target_price=column_target,
        trail_ref=isinstance(trailing, dict) and trailing["by"]["kind"] == "column",
        pair=entry["kind"] != "market" and not (stop == "column" and column_target),
        fixed_size=spec.execution.sizing.kind == "fixed",
    )
    return spec, needs


def _entry(draw: "DrawFn") -> dict[str, object]:
    from hypothesis import strategies as st

    kind = draw(
        st.sampled_from(
            ("market", "market", "limit_at_column", "stop_at_column", "limit_offset", "stop_offset")
        )
    )
    entry: dict[str, object] = {"kind": kind}
    if kind.endswith("offset"):
        entry["ticks"] = draw(st.integers(1, 12))
    if kind != "market" and draw(st.booleans()):
        entry["time_to_live_bars"] = draw(st.integers(1, 3))
    return entry


def _stop(draw: "DrawFn", kind: str) -> dict[str, object]:
    from hypothesis import strategies as st

    if kind == "ticks":
        return {"kind": "ticks", "ticks": draw(st.integers(1, 12))}
    if kind == "percent":
        return {"kind": "percent", "percent": draw(st.sampled_from((0.01, 0.05, 0.1, 0.5)))}
    if kind == "atr":
        return {"kind": "atr", "multiple": draw(st.sampled_from((0.5, 1.0, 2.0))), "feature": "atr"}
    return {"kind": "column"}


def _target(draw: "DrawFn", stopped: bool) -> tuple[str, dict[str, object]]:
    from hypothesis import strategies as st

    kinds = ("ticks", "atr", "column", "r_multiple") if stopped else ("ticks", "atr", "column")
    kind = draw(st.sampled_from(kinds))
    price: dict[str, object] = {"kind": kind}
    if kind == "ticks":
        price["ticks"] = draw(st.integers(1, 6))
    elif kind == "atr":
        price |= {"multiple": draw(st.sampled_from((0.5, 1.0, 1.5))), "feature": "atr"}
    elif kind == "r_multiple":
        price["multiple"] = draw(st.sampled_from((0.5, 1.0, 1.5, 3.0)))
    return kind, {"price": price, "fraction": draw(st.sampled_from((0.25, 0.5, 1.0)))}


def _trigger(draw: "DrawFn", targets: int) -> dict[str, object]:
    from hypothesis import strategies as st

    kinds = ("ticks", "r_multiple", "after_target") if targets else ("ticks", "r_multiple")
    kind = draw(st.sampled_from(kinds))
    if kind == "ticks":
        return {"kind": "ticks", "ticks": draw(st.integers(1, 12))}
    if kind == "r_multiple":
        return {"kind": "r_multiple", "multiple": draw(st.sampled_from((0.5, 1.0, 1.5)))}
    return {"kind": "after_target", "target": draw(st.integers(1, targets))}


def _protection(draw: "DrawFn", execution: dict[str, object], targets: int) -> None:
    """A breakeven and a trailing stop beside a stop, each drawn or not."""
    from hypothesis import strategies as st

    if draw(st.booleans()):
        trigger = _trigger(draw, targets)
        execution["breakeven"] = {"trigger": trigger, "offset_ticks": draw(st.integers(-2, 2))}
    if not draw(st.booleans()):
        return
    by = draw(st.sampled_from(("ticks", "atr", "column")))
    trailing: dict[str, object] = {"by": {"kind": by}}
    if by == "ticks":
        trailing["by"] = {"kind": "ticks", "ticks": draw(st.integers(1, 12))}
    elif by == "atr":
        trailing["by"] = {
            "kind": "atr",
            "multiple": draw(st.sampled_from((0.5, 1.0))),
            "feature": "atr",
        }
    trailing["update"] = (
        "bar_close" if by == "column" else draw(st.sampled_from(("intrabar", "bar_close")))
    )
    if draw(st.booleans()):
        trailing["step_ticks"] = draw(st.integers(1, 3))
    if draw(st.booleans()):
        trailing["activation"] = _trigger(draw, targets)
    execution["trailing"] = trailing


def _time(draw: "DrawFn") -> dict[str, object] | None:
    """Entry windows, max bars, and max minutes in UTC, each drawn or not; none of them, none."""
    from hypothesis import strategies as st

    time: dict[str, object] = {"tz": "UTC"}
    if draw(st.booleans()):
        window: dict[str, object] = {
            "start": draw(st.sampled_from(CLOCKS)),
            "end": draw(st.sampled_from(CLOCKS)),
        }
        if draw(st.booleans()):
            window["weekdays"] = [draw(st.sampled_from(("friday", "saturday")))]
        time["windows"] = [window]
    if draw(st.booleans()):
        time["max_bars"] = draw(st.integers(1, 4))
    if draw(st.booleans()):
        time["max_minutes"] = draw(st.integers(1, 60))
    return time if len(time) > 1 else None


def _sizing(draw: "DrawFn", drawn: DrawnInstrument, stopped: bool) -> dict[str, object]:
    from hypothesis import strategies as st

    kinds = (
        ("fixed", "fixed", "notional", "risk_amount", "risk_percent")
        if stopped
        else ("fixed", "notional")
    )
    kind = draw(st.sampled_from(kinds))
    if kind == "fixed":
        return {"kind": "fixed", "units": float(drawn.quantity(draw(st.integers(1, 4))))}
    if kind == "notional":
        one_lot = (
            abs(drawn.opening) * drawn.instrument.point_value * drawn.instrument.lot_step / 10**9
        )
        return {"kind": "notional", "amount": float(one_lot * draw(st.sampled_from((1, 2, 3))))}
    if kind == "risk_amount":
        return {"kind": "risk_amount", "amount": draw(st.sampled_from((5.0, 50.0, 500.0, 5000.0)))}
    return {"kind": "risk_percent", "percent": draw(st.sampled_from((0.01, 0.5, 1.0, 5.0)))}


def _rows(
    draw: "DrawFn", drawn: DrawnInstrument, tape: Tape, needs: RowNeeds
) -> tuple[SignalRow, ...]:
    """Three to twelve signal closes beside the tape's records, each with its signals, its wake,
    a size multiple on every row or none,
    the columns its rules read, a feature above zero, and the blackout flag."""
    from hypothesis import strategies as st

    beside = st.tuples(st.integers(0, len(tape) - 1), st.sampled_from(OFFSETS_MS))
    closes = sorted(
        {
            tape[record].available_at() + offset * MILLISECOND
            for record, offset in draw(st.lists(beside, min_size=3, max_size=12))
        }
    )
    entries = ("long", "none", "short", "both") if needs.pair else ("long", "none", "short")
    multiples = (1.0, 2.0) if needs.fixed_size else (0.5, 1.0, 1.5, 2.0)
    sized = draw(st.booleans())
    rows = []
    for ts_close in closes:
        entry = draw(st.sampled_from(entries))
        side = Side.SELL if entry == "short" else Side.BUY
        prices = _column_prices(draw, drawn, needs, side)
        rows.append(
            SignalRow.model_construct(
                ts_close=ts_close,
                trade_date=utc_date(ts_close),
                contract="DRAWN",
                long_entry=entry in ("long", "both"),
                short_entry=entry in ("short", "both"),
                long_exit=draw(st.booleans()),
                short_exit=draw(st.booleans()),
                size_mult=draw(st.sampled_from(multiples)) if sized else None,
                wake=draw(st.sampled_from((True, True, False))),
                features={"atr": draw(st.integers(1, 40)) * 250_000_000.0},
                flags={"news": draw(st.booleans())},
                entry_price=prices["entry_price"],
                stop_price=prices["stop_price"],
                target_price=prices["target_price"],
                trail_ref=prices["trail_ref"],
            )
        )
    return tuple(rows)


def _column_prices(
    draw: "DrawFn", drawn: DrawnInstrument, needs: RowNeeds, side: Side
) -> dict[str, int | None]:
    """The row's prices on the tick around the opening: a stop on the losing side of its target
    for the row's entry side."""
    from hypothesis import strategies as st

    away = side.sign() * drawn.tick
    near = st.integers(-12, 12)
    return {
        "entry_price": drawn.opening + draw(near) * drawn.tick if needs.entry_price else None,
        "stop_price": drawn.opening - draw(st.integers(1, 12)) * away if needs.stop_price else None,
        "target_price": drawn.opening + draw(st.integers(1, 12)) * away
        if needs.target_price
        else None,
        "trail_ref": drawn.opening + draw(near) * drawn.tick if needs.trail_ref else None,
    }
