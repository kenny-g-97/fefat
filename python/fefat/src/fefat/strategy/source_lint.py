"""A strategy's lint (step 5.2, D-93, `02-engine-and-data.md` §6, D-12): the leak detector's rules
on calls (`fefat.features.reading_ahead`) over every statement of a strategy version's code, so
that a negative shift, a backward fill or an interpolation, a centred window or a peak, an
aggregate over the whole frame or over a partition, an as-of join forward or on `ts_open`, or a
reversed column in its slots, its signals, or a feature it defines is named with its line.

    for finding in ff.strategy.lint(code):
        print(finding)  # line 14: long_entry=close.shift(-1) > close,: a negative shift ...

Its findings warn, as a feature's do: a strategy's own expressions pass through no cut of the leak
detector, and the lint reads text alone, so that a shift by a negative parameter, or a leak in a
module the code imports, passes it."""

import ast

from fefat.features.reading_ahead import (
    EXPLANATIONS,
    LintRule,
    calls_in,
    line_of,
    ways_of_reading_ahead,
)
from fefat.market.schema import FrozenModel


class StrategyLintFinding(FrozenModel):
    """A finding of a strategy's lint: its rule, the line of the code it is on, the line's text,
    and why it reads ahead."""

    rule: LintRule
    line: int
    source: str
    explanation: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.source}: {self.explanation}"


def lint(code: str) -> tuple[StrategyLintFinding, ...]:
    """The findings of the lint in `code`, a strategy version's code that parses, by line
    (module docstring)."""
    lines = code.split("\n")
    found = {
        (line_of(call), rule): StrategyLintFinding(
            rule=rule,
            line=line_of(call),
            source=lines[line_of(call) - 1].strip(),
            explanation=EXPLANATIONS[rule],
        )
        for call, rule in ways_of_reading_ahead(calls_in(ast.parse(code).body))
    }
    return tuple(found[key] for key in sorted(found))
