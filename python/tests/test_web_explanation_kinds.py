"""The web's copies of the kinds an explanation carries (step 5.9's ponytail review): the trade
review parses an `explain` job's result with zod, where an event or a fill of a kind it does not
know fails the whole explanation, so each copy is held equal to the engine's enum."""

import re
from pathlib import Path

from fefat.reference.event_log import EventKind
from fefat.reference.ledger import FillFlag, Liquidity

EXPLANATIONS = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "explanations.ts"


def listed(pattern: str) -> list[str]:
    """The quoted words of the list `pattern` finds in the web's explanation module."""
    found = re.search(pattern, EXPLANATIONS.read_text(encoding="utf-8"), re.DOTALL)
    assert found is not None, f"Expected {pattern} in {EXPLANATIONS.name}, got none."
    return re.findall(r'"([a-z_]+)"', found.group(1))


def test_the_webs_event_kinds_are_the_reference_engines() -> None:
    assert listed(r"const EVENT_KINDS = \[(.*?)\]") == [kind.value for kind in EventKind]


def test_the_webs_fill_kinds_are_the_ledgers() -> None:
    assert listed(r"liquidity: z\.enum\(\[(.*?)\]\)") == [each.value for each in Liquidity]
    assert listed(r"flags: z\.array\(z\.enum\(\[(.*?)\]\)\)") == [each.value for each in FillFlag]
