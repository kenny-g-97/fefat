"""The data guide (step 1.11) answers where your data is, which sources to get files from, how
to import them, and how to check them, and names only commands, presets, and files that
exist."""

import re
from pathlib import Path

import pytest

from fefat.market.importers.profiles import preset_profiles
from fefat_app.cli import main

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "data-guide.md"
QUESTIONS = (
    "## Where your data is",
    "## Which sources, and where to get their files",
    "## Importing Databento files",
    "## Importing your own exports",
    "## Checking coverage and quality",
)


def guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_the_guide_has_a_section_for_each_question_it_answers() -> None:
    headings = [line for line in guide_text().splitlines() if line.startswith("## ")]

    assert [question for question in QUESTIONS if question not in headings] == []


def test_every_command_the_guide_names_is_one_the_cli_has(
    capsys: pytest.CaptureFixture[str],
) -> None:
    named = sorted(set(re.findall(r"fefat data [a-z-]+(?: databento| file)?", guide_text())))
    refused = []
    for command in named:
        with pytest.raises(SystemExit) as exit_info:
            main([*command.split()[1:], "--help"])
        if exit_info.value.code != 0:
            refused.append(command)

    capsys.readouterr()
    assert "fefat data import file" in named
    assert refused == []


def test_the_guide_names_every_preset() -> None:
    text = guide_text()

    assert [name for name in preset_profiles() if f"`{name}`" not in text] == []


def test_every_repository_file_the_guide_names_exists() -> None:
    named = re.findall(r"`((?:docs|notebooks|python|fixtures)/[^`<>*]+)`", guide_text())

    assert named
    assert [path for path in named if not (ROOT / path).exists()] == []
