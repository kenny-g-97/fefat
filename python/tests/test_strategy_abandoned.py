"""A strategy's abandoned mark, step 5.5 (D-29, D-109): the record of an idea that broke, where it
broke and the lesson, kept as `strategies/<name>/abandoned.json` beside the strategy's versions,
which it leaves as they are; written once, read back by its strategy's name, and removed when the
strategy is reopened."""

import os
from pathlib import Path

import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.strategy.abandoned_marks import (
    AlreadyAbandonedError,
    NotAbandonedError,
    abandon_in,
    abandoned_marks_in,
    reopen_in,
)
from strategy_code import BREAKOUT, HYPOTHESIS

BROKE = "Past 2024 the breakouts stopped running on."
LESSON = "An hour's range on MES is too short a base for a breakout."


def strategies_dir() -> Path:
    return resolve_paths(os.environ).strategies_dir


def test_a_mark_is_written_beside_the_versions_and_read_back_by_name() -> None:
    saved = ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    version_file = strategies_dir() / "breakout" / "v1.json"
    before = version_file.read_bytes()

    mark = abandon_in(strategies_dir(), "breakout", breaking_point=f" {BROKE}\n", lesson=LESSON)

    assert (mark.breaking_point, mark.lesson) == (BROKE, LESSON)
    assert mark.abandoned_at.tzinfo is not None
    assert sorted(path.name for path in (strategies_dir() / "breakout").iterdir()) == [
        "abandoned.json",
        "v1.json",
    ]
    assert abandoned_marks_in(strategies_dir()) == {"breakout": mark}
    assert version_file.read_bytes() == before
    assert ff.strategy.load("breakout", 1) == saved
    assert len(ff.strategy.library()) == 1


def test_a_strategy_abandoned_already_is_refused_and_keeps_its_mark() -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    first = abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)

    with pytest.raises(AlreadyAbandonedError, match="abandoned already"):
        abandon_in(strategies_dir(), "breakout", breaking_point="Another.", lesson="Another.")

    assert abandoned_marks_in(strategies_dir()) == {"breakout": first}


def test_a_strategy_without_a_saved_version_is_refused_and_no_folder_is_made() -> None:
    with pytest.raises(ValueError, match="no saved version"):
        abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)

    assert not strategies_dir().exists()
    assert abandoned_marks_in(strategies_dir()) == {}


@pytest.mark.parametrize(("breaking_point", "lesson"), [("", LESSON), (BROKE, "  \n ")])
def test_a_mark_without_its_breaking_point_or_its_lesson_is_refused(
    breaking_point: str, lesson: str
) -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)

    with pytest.raises(ValueError, match="Expected where the strategy broke and its lesson"):
        abandon_in(strategies_dir(), "breakout", breaking_point=breaking_point, lesson=lesson)

    assert abandoned_marks_in(strategies_dir()) == {}


def test_reopening_removes_the_mark_and_a_strategy_not_abandoned_is_refused() -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)

    reopen_in(strategies_dir(), "breakout")

    assert abandoned_marks_in(strategies_dir()) == {}
    with pytest.raises(NotAbandonedError, match="not abandoned"):
        reopen_in(strategies_dir(), "breakout")
    again = abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)
    assert abandoned_marks_in(strategies_dir()) == {"breakout": again}


@pytest.mark.parametrize("name", ["../outside", "Breakout", "con"])
def test_a_name_that_is_no_strategys_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="Expected a strategy's name"):
        abandon_in(strategies_dir(), name, breaking_point=BROKE, lesson=LESSON)


def test_a_mark_a_reopening_removes_after_the_listing_is_passed_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)
    reading = Path.read_bytes

    def reopened_first(path: Path) -> bytes:
        if path.name == "abandoned.json":
            reopen_in(strategies_dir(), "breakout")
        return reading(path)

    monkeypatch.setattr(Path, "read_bytes", reopened_first)

    assert abandoned_marks_in(strategies_dir()) == {}


def test_a_reopening_tries_again_while_a_read_holds_the_mark_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Windows refuses to remove a file another handle holds open, as an indexing's read does.
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    abandon_in(strategies_dir(), "breakout", breaking_point=BROKE, lesson=LESSON)
    removing = Path.unlink
    held = [PermissionError(32, "The file is being used by another process")]

    def held_once(path: Path, missing_ok: bool = False) -> None:
        if path.name == "abandoned.json" and held:
            raise held.pop()
        removing(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held_once)

    reopen_in(strategies_dir(), "breakout")

    assert (held, abandoned_marks_in(strategies_dir())) == ([], {})


def test_a_mark_changed_by_hand_into_no_mark_is_refused_with_its_file() -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    mark_file = strategies_dir() / "breakout" / "abandoned.json"
    mark_file.write_text('{"lesson": ""}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"abandoned\.json"):
        abandoned_marks_in(strategies_dir())
