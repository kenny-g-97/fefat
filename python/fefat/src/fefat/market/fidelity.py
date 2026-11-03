"""The fidelity of market data, one type for the scenarios, the engines, the cache, and `load`
(D-51, `docs/spec/fill-semantics.md` §2 and F-TAG-01): the finest data an order fills on, for
a day, and the data `load` builds bars from. It is spelled as the scenarios spell it: `tbbo`
(trades, each with the best bid and ask just before it), `trades` (trade prints alone), or bars
of a timeframe, `1s`, `1m`, or an import's coarser `5m` or `1d`.

    parse_fidelity("trades") is TickFidelity.TRADES
    parse_fidelity("1m") == Timeframe(count=1, unit=TimeUnit.MINUTE)

A `FidelityEra` is trade dates in a row on one level: those a run filled on (D-58, D-64), or
those whose signal bars `load` built (D-71).
"""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer

from fefat.market.schema import FrozenModel, Timeframe, TimeUnit

ONE_SECOND = Timeframe(count=1, unit=TimeUnit.SECOND)
"""1-second bars, the finest bars a store holds."""
ONE_MINUTE = Timeframe(count=1, unit=TimeUnit.MINUTE)
"""1-minute bars, the bars every product's history holds and its roll calendar reads."""


class TickFidelity(StrEnum):
    """Tick data: trades with the quote just before each, or trades alone."""

    TBBO = "tbbo"
    TRADES = "trades"


_EXPECTED = "Expected a fidelity: tbbo, trades, or a bar timeframe such as 1s, 1m, 5m, or 1d"


def parse_fidelity(value: object) -> TickFidelity | Timeframe:
    """A fidelity from its text, `tbbo`, `trades`, or a bar timeframe such as `1m`; a fidelity
    passes through unchanged."""
    if isinstance(value, TickFidelity | Timeframe):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{_EXPECTED}, got {value!r}.")
    if value in TickFidelity:
        return TickFidelity(value)
    try:
        return Timeframe.parse(value)
    except ValueError:
        raise ValueError(f"{_EXPECTED}, got {value!r}.") from None


Fidelity = Annotated[TickFidelity | Timeframe, BeforeValidator(parse_fidelity)]
"""A fidelity as a model field, read from its text."""

FidelityText = Annotated[
    TickFidelity | Timeframe,
    BeforeValidator(parse_fidelity),
    PlainSerializer(str, return_type=str),
]
"""A fidelity as a field written as its text, `trades` or `1m`, and read back from it."""


class FidelityEra(FrozenModel):
    """Trade dates in a row on one level, from `first` to `last`, `trade_dates` of them: those a
    run filled on, each the finest it held at or coarser than the run's fidelity (`02` §1.6,
    D-58), or those whose signal bars `load` built, each from the finest level it holds that
    builds the bars (D-71)."""

    first: date
    last: date
    trade_dates: int = Field(ge=1)
    fidelity: FidelityText


def fidelity_in_words(fidelity: object) -> str:
    """A fidelity, or its text, as prose writes it before a noun: `tbbo`, `trades`, or the
    timeframe of its bars, such as `1-minute`."""
    parsed = parse_fidelity(fidelity)
    if isinstance(parsed, Timeframe):
        return parsed.in_words()
    return str(parsed)
