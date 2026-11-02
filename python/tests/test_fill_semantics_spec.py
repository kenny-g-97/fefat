"""Step 2.1's fill specification, Done means 1: `docs/spec/fill-semantics.md` names a defined
rule in every cell of order type by fidelity, defines each rule once with its source, and lists
every proposed rule, and the kickoff's answers (D-51), in its sign-off table."""

import re
from pathlib import Path

from fefat.reference.scenarios import specified_rules

ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION = ROOT / "docs" / "spec" / "fill-semantics.md"
RULE = re.compile(r"F-[A-Z]{3}-\d{2}")
DEFINITION = re.compile(r"^\*\*(F-[A-Z]{3}-\d{2})\*\* \(([^)]*)\)", re.MULTILINE)


def specification() -> str:
    return SPECIFICATION.read_text(encoding="utf-8")


def section(title: str) -> str:
    """The body of the section whose heading holds `title`, up to the next section."""
    for part in re.split(r"^## ", specification(), flags=re.MULTILINE):
        heading, _, body = part.partition("\n")
        if title in heading:
            return body
    raise AssertionError(f"Expected a section titled {title!r} in {SPECIFICATION.name}.")


def first_table(body: str) -> list[list[str]]:
    """The cells of the first Markdown table in `body`: its header row, then its body rows."""
    lines = body.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("|"))
    end = next(
        (index for index in range(start, len(lines)) if not lines[index].startswith("|")),
        len(lines),
    )
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[start:end]
    ]
    return [rows[0], *rows[2:]]


def test_every_order_type_on_every_fidelity_names_a_rule_the_specification_defines() -> None:
    header, *rows = first_table(section("Order type by fidelity"))
    defined = set(specified_rules(specification()))

    assert header == ["Order", "`tbbo`", "`trades`", "`1s`", "`1m`", "coarser (`5m`, `1d`)"]
    assert [row[0] for row in rows] == ["Market", "Stop-market", "Limit"]
    for row in rows:
        named = [RULE.findall(cell) for cell in row[1:]]
        assert all(named), f"Expected a rule in every cell of {row[0]}, got {row[1:]}."
        assert {rule for cell in named for rule in cell} <= defined


def test_every_rule_is_defined_once_with_its_source_and_every_mention_is_defined() -> None:
    defined = specified_rules(specification())

    assert len(defined) == len(set(defined))
    assert [rule for rule, _ in DEFINITION.findall(specification())] == list(defined)
    assert set(RULE.findall(specification())) <= set(defined)


def test_the_sign_off_table_lists_every_proposed_rule() -> None:
    proposed = {
        rule for rule, source in DEFINITION.findall(specification()) if "proposed" in source
    }
    header, *rows = first_table(section("Sign-off"))
    listed = {rule for row in rows for rule in RULE.findall(row[header.index("Rules")])}

    assert "Signed off" in header
    assert proposed
    assert proposed - listed == set()


def test_every_default_of_the_sign_off_table_carries_its_date() -> None:
    # The Phase 2 exit's step review: 30 rows waited undated until you signed them off on
    # 2026-11-02; a row added later must carry its date too.
    header, *rows = first_table(section("Sign-off"))
    rules, signed = header.index("Rules"), header.index("Signed off")

    unsigned = [row[rules] for row in rows if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[signed])]

    assert unsigned == []


def test_the_sign_off_table_starts_from_the_kickoff_answers() -> None:
    header, *rows = first_table(section("Sign-off"))
    rules, source = header.index("Rules"), header.index("Source")
    from_the_kickoff = {
        rule for row in rows if "D-51" in row[source] for rule in RULE.findall(row[rules])
    }

    assert {"F-ACT-01", "F-SLP-01", "F-LMT-01"} <= from_the_kickoff
