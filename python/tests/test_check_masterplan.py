from pathlib import Path

import check_masterplan

LOG = (
    "| ID | Decision | Why | Consequences |\n| --- | --- | --- | --- |\n"
    "| D-01 **ADR** (superseded by D-03) | Old | Why | Then |\n"
    "| D-02 | Not a record | Why | Then |\n"
    "| D-03 **ADR** (2026-10-08) | New | Why | Then |\n"
)


def write_record(folder: Path, name: str, decision: str, status: str) -> None:
    sections = "\n\n".join(f"## {section}\n\nText." for section in check_masterplan.ADR_SECTIONS)
    text = f"# {name}\n\nDecision log: [{decision}](../masterplan/DECISIONS.md)\n\n{sections} {status}\n"
    (folder / name).write_text(text, encoding="utf-8")


def decision_log(tmp_path: Path) -> Path:
    log = tmp_path / "DECISIONS.md"
    log.write_text(LOG, encoding="utf-8")
    return log


def test_a_missing_decision_log_is_reported_rather_than_raised(tmp_path: Path) -> None:
    errors = check_masterplan.adr_errors(tmp_path / "DECISIONS.md", tmp_path)

    assert errors == ["DECISIONS.md not found"]


def test_the_decision_records_match_the_log() -> None:
    assert check_masterplan.adr_errors(check_masterplan.DECISIONS, check_masterplan.ADRS) == []


def test_records_in_the_log_order_with_the_successor_linked_pass(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by [ADR-0002](0002-new.md).")
    write_record(tmp_path, "0002-new.md", "D-03", "Accepted.")

    assert check_masterplan.adr_errors(decision_log(tmp_path), tmp_path) == []


def test_a_decision_marked_adr_without_its_record_is_reported(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by [ADR-0002](0002-new.md).")

    errors = check_masterplan.adr_errors(decision_log(tmp_path), tmp_path)

    assert any("expected 2 records" in error for error in errors), errors


def test_a_record_that_names_another_decision_is_reported(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by [ADR-0002](0002-new.md).")
    write_record(tmp_path, "0002-new.md", "D-02", "Accepted.")

    errors = check_masterplan.adr_errors(decision_log(tmp_path), tmp_path)

    assert any("0002-new.md" in error and "D-03" in error for error in errors), errors


def test_a_gap_in_the_record_numbers_is_reported(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by [ADR-0003](0003-new.md).")
    write_record(tmp_path, "0003-new.md", "D-03", "Accepted.")

    errors = check_masterplan.adr_errors(decision_log(tmp_path), tmp_path)

    assert any("0003-new.md" in error and "0002" in error for error in errors), errors


def test_a_record_without_the_five_sections_is_reported(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by [ADR-0002](0002-new.md).")
    (tmp_path / "0002-new.md").write_text(
        "# 0002-new.md\n\nDecision log: [D-03](../masterplan/DECISIONS.md)\n\n## Context\n\nText.\n",
        encoding="utf-8",
    )

    errors = check_masterplan.adr_errors(decision_log(tmp_path), tmp_path)

    assert any("0002-new.md" in error and "sections" in error for error in errors), errors


def test_a_successor_without_a_record_is_named_as_such(tmp_path: Path) -> None:
    log = tmp_path / "DECISIONS.md"
    log.write_text(LOG.replace("superseded by D-03", "superseded by D-02"), encoding="utf-8")
    write_record(tmp_path, "0001-old.md", "D-01", "Superseded by D-02.")
    write_record(tmp_path, "0002-new.md", "D-03", "Accepted.")

    errors = check_masterplan.adr_errors(log, tmp_path)

    assert any("D-02" in error and "no record" in error for error in errors), errors


def test_a_superseded_record_without_a_link_to_its_successor_is_reported(tmp_path: Path) -> None:
    write_record(tmp_path, "0001-old.md", "D-01", "Accepted.")
    write_record(tmp_path, "0002-new.md", "D-03", "Accepted.")

    errors = check_masterplan.adr_errors(decision_log(tmp_path), tmp_path)

    assert any("0001-old.md" in error and "successor" in error for error in errors), errors
