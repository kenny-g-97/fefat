"""Strategy versions, step 5.2 (D-93, D-84): `ff.strategy.save` writes a version's record to
`<FEFAT_HOME>/workspaces/default/strategies/<name>/v<n>.json`, `n` from 1 per name, with the
feature versions its slots read saved and pinned; the same code with the same words returns its
version and writes nothing, while other words are refused, since a version never changes; `load`
refuses a file changed after it was written; and `diff` gives the unified diff of two versions'
code, from a notebook as from the app (Done means 1)."""

import os
import re
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.strategy.source_code import StrategyCodeError
from fefat.strategy.versions import LIBRARY_COLUMNS, PinnedFeature, StrategyKind
from strategy_code import BREAKOUT, HYPOTHESIS, WITH_A_SLOT

WIDER_STOP = BREAKOUT.replace("stop_atr: float = 1.5", "stop_atr: float = 2.0")
"""The breakout with a wider stop by default, its version 2."""


def folder(name: str) -> Path:
    return resolve_paths(os.environ).strategies_dir / name


def written(name: str) -> dict[str, int]:
    """The files in the strategy's folder with the times they were last written."""
    return {path.name: path.stat().st_mtime_ns for path in folder(name).iterdir()}


def test_two_versions_are_saved_and_diffed() -> None:
    # Done means 1, from a notebook: two versions of a strategy, and the diff of their code.
    first = ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS, changelog="The guide's.")
    second = ff.strategy.save("breakout", WIDER_STOP, hypothesis=HYPOTHESIS, changelog="Wider.")

    assert (first.version, second.version) == (1, 2)
    assert sorted(written("breakout")) == ["v1.json", "v2.json"]
    assert ff.strategy.load("breakout", 1) == first
    assert ff.strategy.load("breakout", 2) == second
    assert ff.strategy.diff("breakout", 1, 2) == (
        "--- breakout v1\n"
        "+++ breakout v2\n"
        "@@ -3,7 +3,7 @@\n"
        " import fefat as ff\n"
        " \n"
        " \n"
        "-def strategy(lookback: int = 12, stop_atr: float = 1.5) -> ff.SignalStrategy:\n"
        "+def strategy(lookback: int = 12, stop_atr: float = 2.0) -> ff.SignalStrategy:\n"
        '     close = pl.col("close")\n'
        "     return ff.SignalStrategy(\n"
        '         instrument="MES",\n'
    )


def test_a_version_keeps_what_its_strategy_is() -> None:
    saved = ff.strategy.save("breakout", BREAKOUT, hypothesis=f"  {HYPOTHESIS}  ")

    assert saved.kind is StrategyKind.SIGNAL
    assert (saved.instrument, saved.timeframe) == ("MES", "5m")
    assert (saved.hypothesis, saved.changelog) == (HYPOTHESIS, "")
    assert saved.code == BREAKOUT
    assert saved.parameter_schema["properties"]["stop_atr"]["default"] == 1.5
    assert saved.pinned_features == ()
    assert saved.hash == saved.content_hash()
    assert saved.created_at.tzinfo is not None


def test_the_feature_versions_its_slots_read_are_saved_and_pinned_once_each() -> None:
    # As a run pins them (D-79): by name, number, and content hash, saved in the library first.
    code = WITH_A_SLOT.format(
        feature='ff.indicators.rsi(14), "slow": ff.indicators.rsi(28), "atr": ff.indicators.atr(14)',
        entry='pl.col("read") < 30',
    )

    saved = ff.strategy.save("oversold", code, hypothesis=HYPOTHESIS)

    rsi, atr = ff.features.load("rsi", 1), ff.features.load("atr", 1)
    assert saved.pinned_features == (
        PinnedFeature(name="atr", version=1, hash=atr.hash),
        PinnedFeature(name="rsi", version=1, hash=rsi.hash),
    )
    assert ff.features.library().select("name", "version").rows() == [("atr", 1), ("rsi", 1)]


def test_the_same_code_with_the_same_words_returns_its_version_and_writes_nothing() -> None:
    first = ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS, changelog="First.")
    before = written("breakout")

    again = ff.strategy.save(
        "breakout", BREAKOUT + "\n\n", hypothesis=HYPOTHESIS, changelog="First."
    )

    assert again == first
    assert written("breakout") == before


def test_the_code_of_a_saved_version_with_other_words_is_refused() -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS, changelog="First.")
    before = written("breakout")

    with pytest.raises(ValueError, match="a version never changes, so change the code"):
        ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS, changelog="Another word.")
    assert written("breakout") == before


def test_a_version_whose_file_was_changed_is_refused() -> None:
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    path = folder("breakout") / "v1.json"
    path.write_bytes(path.read_bytes().replace(b"stop_atr: float = 1.5", b"stop_atr: float = 9.5"))

    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.strategy.load("breakout", 1)


def test_a_version_not_saved_is_named_when_it_is_missing() -> None:
    expected = (
        f"Expected version 2 of strategy breakout at {folder('breakout') / 'v2.json'}, got no "
        "such file."
    )

    with pytest.raises(FileNotFoundError, match=re.escape(expected)):
        ff.strategy.load("breakout", 2)


def test_a_version_another_process_saved_first_is_never_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two processes saving one strategy at once both take the next number; the second is refused
    rather than replacing the first, as here, where the versions on disk go unseen."""
    first = ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    before = (folder("breakout") / "v1.json").read_bytes()
    monkeypatch.setattr("fefat.strategy.versions.version_numbers", lambda folder: [])

    with pytest.raises(ValueError, match="saved by another process first: save it again"):
        ff.strategy.save("breakout", WIDER_STOP, hypothesis=HYPOTHESIS)
    assert (folder("breakout") / "v1.json").read_bytes() == before
    assert ff.strategy.load("breakout", 1) == first


@pytest.mark.parametrize("name", ["../breakout", "Breakout", "1st", "nul", "com1", "a" * 65, ""])
def test_a_name_that_is_no_strategy_name_is_refused_before_the_code_runs(
    name: str, tmp_path: Path
) -> None:
    ran = tmp_path / "ran"
    code = f"from pathlib import Path\n\nPath({str(ran)!r}).touch()\n" + BREAKOUT

    with pytest.raises(ValueError, match="Expected a strategy's name, a lower-case"):
        ff.strategy.save(name, code, hypothesis=HYPOTHESIS)
    assert not ran.exists()
    assert not resolve_paths(os.environ).strategies_dir.exists()


@pytest.mark.parametrize("hypothesis", ["", "   ", "One line.\nAnother line."])
def test_a_hypothesis_that_is_not_one_line_is_refused_before_the_code_runs(
    hypothesis: str,
) -> None:
    with pytest.raises(ValueError, match="Expected the hypothesis as one sentence on one line"):
        ff.strategy.save("breakout", "this is not code", hypothesis=hypothesis)


def test_code_that_gives_no_strategy_writes_nothing() -> None:
    broken = BREAKOUT.replace('pl.col("close")', 'pl.col("close") +')

    with pytest.raises(StrategyCodeError) as refused:
        ff.strategy.save("breakout", broken, hypothesis=HYPOTHESIS)

    assert refused.value.line == 7
    assert not folder("breakout").exists()


def test_the_lint_warns_at_a_save_and_saves() -> None:
    ahead = BREAKOUT.replace("rolling_max(lookback).shift(1)", "rolling_max(lookback).shift(-1)")

    with pytest.warns(UserWarning, match="Strategy breakout, line 12: .*a negative shift"):
        saved = ff.strategy.save("breakout", ahead, hypothesis=HYPOTHESIS)

    assert saved.version == 1


def test_the_library_lists_each_saved_version_by_name_then_number() -> None:
    assert ff.strategy.library().is_empty()
    assert ff.strategy.library().schema == LIBRARY_COLUMNS
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    ff.strategy.save("breakout", WIDER_STOP, hypothesis=HYPOTHESIS)
    ff.strategy.save("another", BREAKOUT, hypothesis=HYPOTHESIS)

    listed = ff.strategy.library()

    assert listed.select("name", "version", "instrument", "timeframe").rows() == [
        ("another", 1, "MES", "5m"),
        ("breakout", 1, "MES", "5m"),
        ("breakout", 2, "MES", "5m"),
    ]
    assert listed.get_column("hash").to_list() == [
        ff.strategy.load(name, number).hash
        for name, number in (("another", 1), ("breakout", 1), ("breakout", 2))
    ]
    assert listed.filter(pl.col("name") == "breakout").height == 2
