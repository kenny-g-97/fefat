"""A strategy's abandoned mark (step 5.5, D-29, D-109): the record of an idea that broke, so that
the library keeps its failures beside its successes, as the `backtest-expert` skill's case studies
keep the breaking point and the lesson of each. A mark is one file beside the strategy's versions,
`strategies/<name>/abandoned.json`, holding where the strategy broke, the lesson, and when it was
marked; it labels the strategy and blocks nothing, its versions staying as they are, and the app's
database indexes it in the strategy's row (ADR-0020).

    abandon_in(strategies_dir, "breakout", breaking_point="Past 2024 ...", lesson="An hour ...")
    abandoned_marks_in(strategies_dir)  # {"breakout": AbandonedMark(...)}
    reopen_in(strategies_dir, "breakout")  # the mark removed

The app writes the marks, which a notebook reads as files. A mark is only ever created whole
(`create_atomically`), so that a reader never sees half of one, and a second mark of the same
strategy is refused rather than written over the first; reopening removes the file, and the
strategy can be marked again."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, Field

from fefat.features.versions import version_numbers
from fefat.market.schema import FrozenModel
from fefat.market.store_files import create_atomically, json_writer, parsed_json
from fefat.strategy.versions import strategy_folder

MARK_FILE = "abandoned.json"
"""The file of a strategy's mark, in the folder of its versions, which no version's name takes."""


class AbandonedMark(FrozenModel):
    """Where a strategy broke, the lesson it taught, and when it was marked abandoned; the folder
    its file stands in names the strategy."""

    breaking_point: str = Field(min_length=1)
    lesson: str = Field(min_length=1)
    abandoned_at: AwareDatetime


class AlreadyAbandonedError(ValueError):
    """A mark asked of a strategy marked abandoned already, whose mark stays as it was."""


class NotAbandonedError(ValueError):
    """A strategy reopened that holds no mark."""


def abandon_in(
    strategies_dir: Path, name: str, *, breaking_point: str, lesson: str
) -> AbandonedMark:
    """Mark the strategy `name` in `strategies_dir` abandoned, with where it broke and its lesson,
    each without the spaces around it; refused where the strategy has no saved version, where
    either text is empty, and with `AlreadyAbandonedError` where a mark stands."""
    folder = strategy_folder(strategies_dir, name)
    if not version_numbers(folder):
        raise ValueError(
            f"Expected a saved strategy to mark abandoned, got {name}, which has no saved version "
            f"in {strategies_dir}."
        )
    texts = (breaking_point.strip(), lesson.strip())
    if not all(texts):
        raise ValueError(
            "Expected where the strategy broke and its lesson, each a sentence or more, got "
            f"{breaking_point!r} and {lesson!r}."
        )
    mark = AbandonedMark(breaking_point=texts[0], lesson=texts[1], abandoned_at=datetime.now(UTC))
    try:
        create_atomically(folder / MARK_FILE, json_writer(mark))
    except FileExistsError as error:
        raise AlreadyAbandonedError(
            f"Expected strategy {name} not abandoned yet, got it abandoned already: reopen it "
            "first to mark it again."
        ) from error
    return mark


def reopen_in(strategies_dir: Path, name: str) -> None:
    """Remove the mark of the strategy `name` in `strategies_dir`, refused with
    `NotAbandonedError` where it holds none."""
    try:
        (strategy_folder(strategies_dir, name) / MARK_FILE).unlink()
    except FileNotFoundError as error:
        raise NotAbandonedError(
            f"Expected strategy {name} abandoned, to reopen it, got it not abandoned."
        ) from error


def abandoned_marks_in(strategies_dir: Path) -> dict[str, AbandonedMark]:
    """The mark of each strategy in `strategies_dir` that holds one, by its name, each refused
    where its folder's name is no strategy's or its file holds no mark; a folder without a mark is
    passed over, as `saved_versions_in` passes over one without a version. None while nothing is
    saved, and no folder is made."""
    marked = (
        sorted(each.name for each in strategies_dir.iterdir() if (each / MARK_FILE).is_file())
        if strategies_dir.is_dir()
        else []
    )
    read = {name: _read_mark(strategies_dir, name) for name in marked}
    return {name: mark for name, mark in read.items() if mark is not None}


def _read_mark(strategies_dir: Path, name: str) -> AbandonedMark | None:
    """The mark of the strategy `name`; None where a reopening removed it since the folders were
    listed, which that reopening's own indexing then reads."""
    path = strategy_folder(strategies_dir, name) / MARK_FILE
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    return parsed_json(AbandonedMark, content, str(path))
