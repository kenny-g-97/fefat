"""Orders decided inside a coarser bar (step 3.7, D-71, `BACKLOG.md`): F-ACT-02 counts a bar whole,
so an order decided at a signal close strictly inside the bar a trade date fills on fills at that
bar's open, a price from before the decision, as an order of a strategy of 30-second bars filling
on 1-minute bars does, or of one of 90-second bars, half of whose closes fall inside a minute.
Until the first step that changes the engine's fill rules has such an order wait for the next
bar, a run warns where its trade dates, or those its fidelity check reran at 1 minute, filled on
bars inside which its decisions fall: bars whose timeframe the strategy's own is not a whole
number of. Both grids start at each session's open and keep their width through its halts
(`fefat.market.bars`), so the rule is exact for the store's bars on the built-in calendars, whose
sessions open on whole hours (`BACKLOG.md`)."""

from collections.abc import Sequence

from fefat.backtest.metrics import FidelityCheck, RefusedCheck
from fefat.market.calendar import counted
from fefat.market.fidelity import FidelityEra
from fefat.market.schema import Timeframe

_WHY = (
    "an order decided inside a bar fills at that bar's open, a price from before the decision "
    "(F-ACT-02, D-71), until a fill model has it wait for the next bar"
)


def inside_bar_warnings(
    timeframe: Timeframe,
    eras: Sequence[FidelityEra],
    check: FidelityCheck | RefusedCheck | None,
) -> tuple[str, ...]:
    """A warning for each level of bars inside which the closes of `timeframe`, the strategy's,
    fall, on the trade dates of the run's `eras` and on those its fidelity check reran at 1
    minute (module docstring)."""
    inside = f"inside which the strategy's {timeframe} closes fall: {_WHY}"
    warned = [
        f"{_dates(group)} filled on {level} bars, {inside}"
        for level, group in _levels_inside(timeframe, eras)
    ]
    if isinstance(check, FidelityCheck):
        reran = check.at_one_minute.outcome.eras
        warned += [
            f"the fidelity check's rerun at 1m filled {_dates(group)} on {level} bars, {inside}"
            for level, group in _levels_inside(timeframe, reran)
        ]
    return tuple(warned)


def _levels_inside(
    timeframe: Timeframe, eras: Sequence[FidelityEra]
) -> list[tuple[Timeframe, list[FidelityEra]]]:
    """Each level of bars among `eras` inside which closes of `timeframe` fall, with its eras."""
    found: dict[str, tuple[Timeframe, list[FidelityEra]]] = {}
    for era in eras:
        level = era.fidelity
        if isinstance(level, Timeframe) and timeframe.nominal_seconds() % level.nominal_seconds():
            found.setdefault(str(level), (level, []))[1].append(era)
    return list(found.values())


def _dates(eras: Sequence[FidelityEra]) -> str:
    """The trade dates `eras` hold, in words."""
    days = sum(era.trade_dates for era in eras)
    first, last = min(era.first for era in eras), max(era.last for era in eras)
    return f"{counted(days, 'trade date')} from {first} to {last}"
