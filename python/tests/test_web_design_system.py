"""`web/DESIGN.md`, the web app's design system (step 4.3, D-28, D-77): unslop's direction in
five lines, then the palette, the type, the layout, the principles, and the review of the plan
against the generic defaults."""

import re
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[2] / "web" / "DESIGN.md"


def section(title: str) -> str:
    """The text of `DESIGN`'s section `title`, up to the next section."""
    text = DESIGN.read_text(encoding="utf-8")
    found = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert found is not None, f"Expected a section '## {title}' in {DESIGN.name}, got none."
    return found.group(1)


def test_the_design_opens_with_unslops_direction_in_five_lines() -> None:
    headings = re.findall(r"^## (.+)$", DESIGN.read_text(encoding="utf-8"), re.MULTILINE)
    lines = re.findall(r"^- \*\*(\w+)\.\*\* \S", section("Direction"), re.MULTILINE)

    assert headings[0] == "Direction"
    assert lines == ["Product", "Character", "World", "Moments", "Signature"]


def test_the_design_records_tokens_type_layout_principles_and_its_review() -> None:
    headings = re.findall(r"^## (.+)$", DESIGN.read_text(encoding="utf-8"), re.MULTILINE)

    expected = {"Palette", "Type", "Layout", "Motion", "Principles"}
    assert expected | {"Review against the generic defaults"} <= set(headings)


def test_the_palette_names_four_to_six_hex_values() -> None:
    named = re.findall(r"^\| (\w+) \| `(#[0-9a-f]{6})` \|", section("Palette"), re.MULTILINE)

    assert 4 <= len(named) <= 6, named
