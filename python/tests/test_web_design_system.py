"""`web/DESIGN.md`, the web app's design system (step 4.3, D-28, D-77): unslop's direction in
five lines, then the palette, the type, the layout, the principles, and the review of the plan
against the generic defaults."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
DESIGN = WEB / "DESIGN.md"
STYLESHEET = WEB / "src" / "index.css"
TOKEN_ROW = re.compile(
    r"^\| [^|]+ \| `(--[a-z0-9-]+)` \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \|", re.M
)
HEX_DECLARATION = re.compile(r"^\s*(--[a-z0-9-]+): (#[0-9a-f]{6});", re.MULTILINE)


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


def declared_colours(selector: str) -> dict[str, str]:
    """The hex colours that `STYLESHEET`'s block for `selector` declares."""
    text = STYLESHEET.read_text(encoding="utf-8")
    block = re.search(rf"^{re.escape(selector)} {{(.*?)^}}", text, re.MULTILINE | re.DOTALL)
    assert block is not None, f"Expected a block '{selector} {{' in {STYLESHEET.name}, got none."
    return dict(HEX_DECLARATION.findall(block.group(1)))


def test_the_designs_tokens_are_the_stylesheets_colours_in_both_themes() -> None:
    tokens = TOKEN_ROW.findall(section("Palette"))
    light, dark = declared_colours(":root"), declared_colours(".dark")
    documented = {token for token, _, _ in tokens}

    assert len(tokens) >= 12, tokens
    assert (set(dark), set(light)) == (documented, documented), "a colour without a row"
    for token, dark_hex, light_hex in tokens:
        assert (dark[token], light[token]) == (dark_hex, light_hex), token
