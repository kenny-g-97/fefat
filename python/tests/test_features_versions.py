"""Feature versions of step 3.1 (D-71, D-11): `save` writes a feature's record to
`<FEFAT_HOME>/workspaces/default/features/<name>/v<n>.json`, `n` from 1 per name, and returns the
version its hash already has; `load` reads it back with the same hash and refuses a record its
content no longer gives."""

import os
import re
import shutil
from pathlib import Path
from typing import IO, Any

import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import FeatureInput, InstrumentInput, OutputKind
from notebook_runs import features_of_cell

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature with one parameter, as a notebook cell defines it."""


def folder(name: str) -> Path:
    return resolve_paths(os.environ).features_dir / name


def written(name: str) -> dict[str, int]:
    """The files in the feature's folder with the times they were last written."""
    return {path.name: path.stat().st_mtime_ns for path in folder(name).iterdir()}


def test_a_saved_feature_loads_back_with_the_same_hash() -> None:
    gap = features_of_cell(GAP)["gap"]

    saved = ff.features.save(gap)
    loaded = ff.features.load("gap", 1)

    assert saved.version == 1
    assert (folder("gap") / "v1.json").is_file()
    assert loaded == saved
    assert loaded.hash == gap.hash == loaded.content_hash()
    assert loaded.code == gap.code
    assert loaded.parameter_schema == gap.parameter_schema
    assert loaded.outputs == {"gap": OutputKind.PRICE_DISTANCE}
    assert loaded.warmup == "lambda n: n"


def test_saving_the_same_feature_again_returns_its_version_and_writes_nothing() -> None:
    first = ff.features.save(features_of_cell(GAP)["gap"])
    before = written("gap")

    again = ff.features.save(features_of_cell(GAP, "another cell")["gap"])

    assert again == first
    assert written("gap") == before


def test_a_changed_default_or_one_changed_character_saves_a_new_version() -> None:
    first = ff.features.save(features_of_cell(GAP)["gap"])
    other_default = ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    other_character = ff.features.save(features_of_cell(GAP.replace(" - ", " + "))["gap"])

    assert [first.version, other_default.version, other_character.version] == [1, 2, 3]
    assert len({first.hash, other_default.hash, other_character.hash}) == 3
    assert sorted(written("gap")) == ["v1.json", "v2.json", "v3.json"]
    assert ff.features.load("gap", 2).parameter_schema["properties"]["n"]["default"] == 4


def test_versions_count_past_nine_in_numeric_order() -> None:
    variants = [GAP.replace('"n": 3', f'"n": {n}') for n in range(1, 13)]
    saved = [ff.features.save(features_of_cell(text)["gap"]) for text in variants[:11]]

    tenth_again = ff.features.save(features_of_cell(variants[9])["gap"])
    twelfth = ff.features.save(features_of_cell(variants[11])["gap"])

    assert [version.version for version in saved] == list(range(1, 12))
    assert tenth_again == saved[9]
    assert twelfth.version == 12
    assert ff.features.load("gap", 10).hash == saved[9].hash


def test_a_record_keeps_the_inputs_and_outputs_it_declares() -> None:
    source = """\
@ff.feature(params={"n": 3})
def base(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(n)


@ff.feature(
    inputs=[base, ff.features.InstrumentInput(root="MNQ")],
    outputs={"upper": "price", "inside": "flag"},
    warmup=20,
)
def reader(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    return {"upper": pl.col("high"), "inside": pl.col("close") > 0}
"""
    defined = features_of_cell(source)

    saved = ff.features.save(defined["reader"])
    loaded = ff.features.load("reader", 1)

    assert loaded == saved
    assert loaded.inputs == (
        FeatureInput(name="base", hash=defined["base"].hash),
        InstrumentInput(root="MNQ"),
    )
    assert loaded.outputs == {"upper": OutputKind.PRICE, "inside": OutputKind.FLAG}
    assert loaded.warmup == 20
    assert loaded.hash == defined["reader"].hash


@pytest.mark.parametrize(
    ("written", "changed"),
    [
        pytest.param(b"rolling_mean", b"rolling_max", id="code"),
        pytest.param(b'"default": 3', b'"default": 4', id="parameter-schema"),
        pytest.param(b'"gap": "price_distance"', b'"gap": "flag"', id="outputs"),
        pytest.param(b'"warmup": "lambda n: n"', b'"warmup": 0', id="warmup"),
    ],
)
def test_a_file_changed_after_it_was_written_is_refused(written: bytes, changed: bytes) -> None:
    ff.features.save(features_of_cell(GAP)["gap"])
    path = folder("gap") / "v1.json"
    content = path.read_bytes()
    assert written in content
    path.write_bytes(content.replace(written, changed))

    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.features.load("gap", 1)
    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.features.save(features_of_cell(GAP)["gap"])


def test_a_file_whose_inputs_were_changed_after_it_was_written_is_refused() -> None:
    source = """\
@ff.feature(inputs=[ff.features.InstrumentInput(root="MNQ")])
def reader(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close")
"""
    ff.features.save(features_of_cell(source)["reader"])
    path = folder("reader") / "v1.json"
    path.write_bytes(path.read_bytes().replace(b'"root": "MNQ"', b'"root": "MCL"'))

    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.features.load("reader", 1)


def test_a_version_not_saved_is_named_when_it_is_missing() -> None:
    expected = (
        f"Expected version 2 of feature gap at {folder('gap') / 'v2.json'}, got no such file."
    )

    with pytest.raises(FileNotFoundError, match=re.escape(expected)):
        ff.features.load("gap", 2)


def test_a_version_whose_write_fails_leaves_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A half-written version would block every later save of its name, which reads it."""
    gap = features_of_cell(GAP)["gap"]
    opened = Path.open

    class FullDisk:
        """A new file that takes no bytes, as on a full disk."""

        def __init__(self, created: IO[Any]) -> None:
            self.created = created

        def __enter__(self) -> "FullDisk":
            return self

        def __exit__(self, *raised: object) -> None:
            self.created.close()

        def write(self, content: bytes) -> int:
            raise OSError(28, "No space left on device")

    def open_on_a_full_disk(path: Path, mode: str = "r", *rest: Any, **options: Any) -> Any:
        file = opened(path, mode, *rest, **options)
        return FullDisk(file) if mode == "xb" else file

    with monkeypatch.context() as full_disk:
        full_disk.setattr(Path, "open", open_on_a_full_disk)
        with pytest.raises(OSError, match="No space left on device"):
            ff.features.save(gap)

    assert folder("gap").is_dir()
    assert not (folder("gap") / "v1.json").exists()
    assert ff.features.save(gap).version == 1


def test_a_version_another_process_saved_first_is_never_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two processes saving under one name at once both take the next number; the second is
    refused rather than replacing the first, as here, where the versions on disk go unseen."""
    first = ff.features.save(features_of_cell(GAP)["gap"])
    before = (folder("gap") / "v1.json").read_bytes()
    monkeypatch.setattr("fefat.features.versions._version_numbers", lambda folder: [])

    with pytest.raises(ValueError, match="saved by another process first: save it again"):
        ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    assert (folder("gap") / "v1.json").read_bytes() == before
    assert ff.features.load("gap", 1) == first


def test_a_record_moved_under_another_name_is_refused() -> None:
    ff.features.save(features_of_cell(GAP)["gap"])
    folder("other").mkdir()
    shutil.copy(folder("gap") / "v1.json", folder("other") / "v1.json")
    expected = f"Expected version 1 of feature other in {folder('other') / 'v1.json'}, got version 1 of feature gap."

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.features.load("other", 1)
