"""The strategies to start from (step 5.2, D-93): the engine guide's breakout, a mean reversion
reading `ff.indicators.rsi` in a slot, which needs no feature of yours, and a breakout in an
entry window with a flat-by time, each a module of this folder whose function `strategy` gives it
on MES's 5-minute bars and whose docstring states its hypothesis. Together their parameters are
of every type a form renders: an integer, a number, a boolean, one of a few words, and a text.
`GET /v1/strategies/templates` serves them, and a strategy created from one starts with its code.

    for template in ff.strategy.templates():
        ff.strategy.save(f"my_{template.name}", template.code, hypothesis=template.hypothesis)
"""

import ast
from pathlib import Path

from fefat.market.schema import FrozenModel

TEMPLATE_NAMES = ("breakout", "mean_reversion", "entry_window")
"""The templates, by the names of their modules, in the order they are listed."""


class StrategyTemplate(FrozenModel):
    """A strategy to start from: its name, its hypothesis, one sentence stating the edge, and its
    code, a strategy version's (`fefat.strategy.source_code`)."""

    name: str
    hypothesis: str
    code: str


def templates() -> tuple[StrategyTemplate, ...]:
    """The templates, in the order of `TEMPLATE_NAMES`, each read from its module's file."""
    return tuple(_template(name) for name in TEMPLATE_NAMES)


def _template(name: str) -> StrategyTemplate:
    code = Path(__file__).with_name(f"{name}.py").read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(code))
    if docstring is None:
        raise ValueError(
            f"Expected the template {name} to state its hypothesis in its docstring, got none."
        )
    return StrategyTemplate(name=name, hypothesis=" ".join(docstring.split()), code=code)
