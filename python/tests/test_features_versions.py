"""Feature versions of step 3.1 (D-71, D-11): `save` writes a feature's record to
`<FEFAT_HOME>/workspaces/default/features/<name>/v<n>.json`, `n` from 1 per name, and returns the
version its hash already has; `load` reads it back with the same hash and refuses a record its
content no longer gives; from step 3.7, `ref` reads a saved version back by name and number as a
feature with its parameters, built again from the library where this process never defined it,
`library` lists the saved versions, and `save` saves first the features a feature reads."""

import os
import re
import shutil
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import FeatureDef, FeatureInput, InstrumentInput, OutputKind, combine, registry
from fefat.features.definition import content_hash
from fefat.features.runtime import FeatureGraph
from fefat.features.versions import (
    LIBRARY_COLUMNS,
    code_diff,
    load_in,
    saved_versions,
    saved_versions_in,
    version_numbers,
)
from fefat.market.schema import Timeframe
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
    """A half-written version would block every later save of its name, which reads it: the
    record is written beside its place, flushed, and only then linked into place."""
    gap = features_of_cell(GAP)["gap"]

    def on_a_full_disk(path: Path, content: bytes) -> int:
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as full_disk:
        full_disk.setattr(Path, "write_bytes", on_a_full_disk)
        with pytest.raises(OSError, match="No space left on device"):
            ff.features.save(gap)

    assert folder("gap").is_dir()
    assert list(folder("gap").iterdir()) == []
    assert ff.features.save(gap).version == 1


@pytest.mark.parametrize("name", ["../gap", "gap/../../other", "C:gap", ""])
def test_a_name_that_is_no_feature_name_reads_nothing(name: str) -> None:
    ff.features.save(features_of_cell(GAP)["gap"])
    expected = f"Expected a feature's name, a Python identifier, got {name!r}."

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.features.load(name, 1)


def test_a_version_another_process_saved_first_is_never_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two processes saving under one name at once both take the next number; the second is
    refused rather than replacing the first, as here, where the versions on disk go unseen."""
    first = ff.features.save(features_of_cell(GAP)["gap"])
    before = (folder("gap") / "v1.json").read_bytes()
    monkeypatch.setattr("fefat.features.versions.version_numbers", lambda folder: [])

    with pytest.raises(ValueError, match="saved by another process first: save it again"):
        ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    assert (folder("gap") / "v1.json").read_bytes() == before
    assert ff.features.load("gap", 1) == first


def listing_another_process_missed(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The first listing of the versions a save reads misses the ones saved, as a process that
    listed them before another process saved its version does; the calls are counted."""
    listings: list[int] = []

    def listed(found: Path) -> list[int]:
        listings.append(len(listings))
        return [] if len(listings) == 1 else version_numbers(found)

    monkeypatch.setattr("fefat.features.versions.version_numbers", listed)
    return listings


def test_a_save_another_process_saved_first_returns_that_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 5.3 (from the Phase 3 exit's ponytail review): two backtest jobs running one new
    # feature save it at once; the second takes the first's number, finds its file there, and
    # returns the version of the same hash the first saved.
    first = ff.features.save(features_of_cell(GAP)["gap"])
    listings = listing_another_process_missed(monkeypatch)

    again = ff.features.save(features_of_cell(GAP)["gap"])

    assert again == first
    assert listings == [0, 1]
    assert sorted(path.name for path in folder("gap").iterdir()) == ["v1.json"]


def test_a_save_whose_number_another_version_took_first_takes_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ff.features.save(features_of_cell(GAP)["gap"])
    listing_another_process_missed(monkeypatch)

    wider = ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])

    assert (wider.version, first.version) == (2, 1)
    assert ff.features.load("gap", 2) == wider


def test_a_record_renamed_and_moved_under_another_name_is_refused() -> None:
    """The name a record states is the name of the function its code defines."""
    ff.features.save(features_of_cell(GAP)["gap"])
    folder("other").mkdir()
    record = (folder("gap") / "v1.json").read_bytes()
    (folder("other") / "v1.json").write_bytes(record.replace(b'"name": "gap"', b'"name": "other"'))

    with pytest.raises(ValueError, match="the file was changed after it was written"):
        ff.features.load("other", 1)


def test_a_record_moved_under_another_name_is_refused() -> None:
    ff.features.save(features_of_cell(GAP)["gap"])
    folder("other").mkdir()
    shutil.copy(folder("gap") / "v1.json", folder("other") / "v1.json")
    path = folder("other") / "v1.json"
    expected = f"Expected version 1 of feature other in {path}, got version 1 of feature gap."

    with pytest.raises(ValueError, match=re.escape(expected)):
        ff.features.load("other", 1)


READER = """\
@ff.feature(params={"n": 2})
def base(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(n)


@ff.feature(inputs=[base], outputs={"lifted": "price"})
def lifted(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("base") + 1
"""
"""A feature reading another by its name, as a notebook cell defines them."""
INDICATORS = {
    definition.hash: definition
    for name in ff.indicators.__all__
    if isinstance(definition := getattr(ff.indicators, name), FeatureDef)
}
"""The definitions a session holds once it imports fefat: the indicators'."""
BARS = pl.DataFrame(
    {"ts_close": [1, 2, 3, 4, 5], "close": [10, 13, 11, 16, 12], "close_raw": [10, 13, 11, 16, 12]}
)


def test_a_saved_feature_is_read_back_by_name_and_version_with_its_parameters() -> None:
    # Step 3.7: the feature a strategy names as ff.features.ref("rsi", version=..., n=14).
    saved = ff.features.save(ff.indicators.rsi)

    read = ff.features.ref("rsi", version=saved.version, n=7)

    assert read.definition == ff.indicators.rsi
    assert read.parameters.model_dump() == {"n": 7}
    assert ff.features.ref("rsi", version=saved.version).parameters.model_dump() == {"n": 14}
    with pytest.raises(FileNotFoundError, match="Expected version 2 of feature rsi"):
        ff.features.ref("rsi", version=2)


def test_saving_a_feature_saves_first_the_features_it_reads() -> None:
    defined = features_of_cell(READER)

    ff.features.save(defined["lifted"])

    assert ff.features.library().select("name", "version").rows() == [("base", 1), ("lifted", 1)]


def test_a_feature_another_session_saved_is_built_again_from_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A session that never ran the cell reads the feature and the one it reads from their code.
    defined = features_of_cell(READER)
    ff.features.save(defined["lifted"])
    monkeypatch.setattr(registry, "_DEFINED", dict(INDICATORS))

    read = ff.features.ref("lifted", version=1)

    assert read.definition.hash == defined["lifted"].hash
    assert read.definition is not defined["lifted"]
    assert registry.registered(defined["base"].hash) is not None
    graph = FeatureGraph.of({"lifted": read}, "ES", Timeframe.parse("5m"))
    assert graph.evaluate({graph.signal_grid: BARS})["lifted"].to_list() == [
        None,
        12.5,
        13.0,
        14.5,
        15.0,
    ]


def test_a_saved_combination_is_built_again_with_its_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rsi = ff.indicators.rsi
    stretch = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 10))
    saved = ff.features.save(stretch)
    monkeypatch.setattr(registry, "_DEFINED", dict(INDICATORS))

    read = ff.features.ref("rsi_stretch", version=saved.version)

    assert read.definition.hash == stretch.hash
    assert read.definition.combination == stretch.combination
    assert ff.features.library().filter(pl.col("combined")).get_column("name").to_list() == [
        "rsi_stretch"
    ]


def test_a_feature_read_that_is_neither_defined_nor_saved_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defined = features_of_cell(READER)
    ff.features.save(defined["lifted"])
    shutil.rmtree(folder("base"))
    monkeypatch.setattr(registry, "_DEFINED", {})
    refusal = (
        f"Expected the feature base {defined['base'].hash[:12]} that lifted reads defined in this "
        "process or saved in the library, got neither: define it, or save it with "
        "ff.features.save."
    )

    with pytest.raises(ValueError, match=re.escape(refusal)):
        ff.features.ref("lifted", version=1)


def a_version_of_another_releases_schema() -> ff.features.FeatureVersion:
    """Version 1 of `gap` as a release that writes the parameters' schema otherwise saved it:
    its file loads under its hash, while its code builds another hash today."""
    saved = ff.features.save(features_of_cell(GAP)["gap"])
    schema = {**saved.parameter_schema, "description": "written by another release"}
    drifted = saved.model_copy(
        update={"parameter_schema": schema, "hash": content_hash(saved.code, saved.inputs, schema)}
    )
    (folder("gap") / "v1.json").write_text(drifted.model_dump_json(indent=2), encoding="utf-8")
    return drifted


def test_a_version_whose_schema_a_release_writes_otherwise_is_read_under_its_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 4.1 (from `BACKLOG.md`): the version keeps the schema its hash covers, so `ref` reads
    # it under that hash, which the runs that pin it name. Building it again also keeps the new
    # schema's definition, which `save` would save as a new version, as it does any new one.
    drifted = a_version_of_another_releases_schema()
    monkeypatch.setattr(registry, "_DEFINED", {})

    spec = ff.features.ref("gap", version=1, n=5)

    assert ff.features.load("gap", 1).hash == drifted.hash
    assert spec.definition.hash == drifted.hash
    assert registry.registered(drifted.hash) is spec.definition
    assert spec.parameters.model_dump() == {"n": 5}
    assert spec.warmup == 5


def test_a_version_whose_code_no_longer_gives_its_hash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A version file whose code was written by hand with Windows line ends keeps a hash that its
    # code, normalised when it is built again, no longer gives.
    saved = ff.features.save(features_of_cell(GAP)["gap"])
    code = saved.code.replace("\n", "\r\n")
    edited = saved.model_copy(
        update={"code": code, "hash": content_hash(code, saved.inputs, saved.parameter_schema)}
    )
    (folder("gap") / "v1.json").write_text(edited.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(registry, "_DEFINED", {})

    with pytest.raises(ValueError, match="its code no longer gives its hash"):
        ff.features.ref("gap", version=1)


def test_a_version_read_under_another_releases_schema_is_not_saved_into_another_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Its definition carries the version's hash, which this release's schema does not give, so
    # a library without that version would keep a file that `load` refuses.
    a_version_of_another_releases_schema()
    monkeypatch.setattr(registry, "_DEFINED", {})
    definition = ff.features.ref("gap", version=1).definition
    monkeypatch.setenv("FEFAT_HOME", str(tmp_path / "another-home"))

    with pytest.raises(ValueError, match="define it again from its code"):
        ff.features.save(definition)

    assert not folder("gap").exists()


def test_the_library_lists_each_saved_version_by_name_then_number() -> None:
    assert ff.features.library().is_empty()
    assert ff.features.library().schema == LIBRARY_COLUMNS
    ff.features.save(features_of_cell(GAP)["gap"])
    ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    report_only = folder("validated") / "validations"
    report_only.mkdir(parents=True)

    listed = ff.features.library()

    assert listed.select("name", "version", "combined").rows() == [
        ("gap", 1, False),
        ("gap", 2, False),
    ]
    assert listed.get_column("hash").to_list() == [
        ff.features.load("gap", number).hash for number in (1, 2)
    ]
    assert saved_versions() == [ff.features.load("gap", number) for number in (1, 2)]


def test_a_library_is_read_from_the_folder_it_is_given(tmp_path: Path) -> None:
    # Step 5.2 (D-93): the app reads and indexes the library of the folders its container holds,
    # whatever folder the environment names.
    first = ff.features.save(features_of_cell(GAP)["gap"])
    second = ff.features.save(features_of_cell(GAP.replace('"n": 3', '"n": 4'))["gap"])
    moved = tmp_path / "moved-features"
    shutil.copytree(folder("gap").parent, moved)
    shutil.rmtree(folder("gap"))

    assert load_in(moved, "gap", 2) == second
    assert saved_versions_in(moved) == [first, second]
    assert saved_versions() == []


def test_the_diff_of_two_versions_is_the_unified_diff_of_their_code() -> None:
    # Step 5.2: the diff the API serves for the versions of a feature or a strategy.
    first = ff.features.save(features_of_cell(GAP)["gap"])
    second = ff.features.save(features_of_cell(GAP.replace(" - ", " + "))["gap"])

    changed = code_diff(first.code, second.code, ("gap v1", "gap v2"))

    assert changed == (
        "--- gap v1\n"
        "+++ gap v2\n"
        "@@ -1,3 +1,3 @@\n"
        ' @ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})\n'
        " def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:\n"
        '-    return pl.col("close") - pl.col("close").rolling_mean(n)\n'
        '+    return pl.col("close") + pl.col("close").rolling_mean(n)\n'
    )
    assert code_diff(first.code, first.code, ("gap v1", "gap v1")) == ""


def test_a_combination_named_as_the_feature_it_reads_is_built_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A smoothed RSI saved as a version of rsi: its code names the feature it reads in a
    # literal input, so building it again binds no name its own would shadow.
    smoothed = combine.define("rsi", combine.rolling_mean(ff.indicators.rsi(14), 3))
    saved = ff.features.save(smoothed)
    monkeypatch.setattr(registry, "_DEFINED", dict(INDICATORS))

    read = ff.features.ref("rsi", version=saved.version)

    assert saved.version == 2
    assert read.definition.hash == smoothed.hash


RENAMED = """\
@ff.feature(params={"n": 2})
def base(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close").rolling_mean(n)


smoothed = base


@ff.feature(inputs=[smoothed], outputs={"lifted": "price"})
def lifted(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("base") + 1
"""
"""A feature whose decorator names the feature it reads by another name."""


def test_a_feature_reading_another_under_another_name_is_built_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The code review: the features a decorator names are bound under the names it writes.
    defined = features_of_cell(RENAMED)
    ff.features.save(defined["lifted"])
    monkeypatch.setattr(registry, "_DEFINED", dict(INDICATORS))

    read = ff.features.ref("lifted", version=1)

    assert read.definition.hash == defined["lifted"].hash


def test_a_feature_whose_code_now_reads_another_version_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The code review: a decorator naming an SDK's feature, `ff.indicators.sma`, reads today's
    # SDK, so where its SMA changed, building the version again reads another SMA, which the
    # refusal names rather than blaming the parameter schema.
    reader = features_of_cell(
        '@ff.feature(inputs=[ff.indicators.sma], outputs={"above": "price"})\n'
        "def above(bars: pl.LazyFrame) -> pl.Expr:\n"
        '    return pl.col("sma") + 1\n'
    )["above"]
    ff.features.save(reader)
    other = features_of_cell(GAP.replace("def gap", "def sma").replace('"gap"', '"sma"'))["sma"]
    monkeypatch.setattr(registry, "_DEFINED", dict(INDICATORS))
    monkeypatch.setattr(ff.indicators, "sma", other)

    with pytest.raises(ValueError, match="to read the features its version read, got another sma"):
        ff.features.ref("above", version=1)


TAGGED = """\
@ff.feature(params={"name": "close"}, outputs={"tagged": "price"})
def tagged(bars: pl.LazyFrame, name: str) -> pl.Expr:
    return pl.col(name)
"""
"""A feature whose parameter is called `name`."""


def test_a_feature_with_a_parameter_called_name_is_read_with_it() -> None:
    # The ponytail review: ref's own name takes no keyword, so a parameter may be called so.
    ff.features.save(features_of_cell(TAGGED)["tagged"])

    read = ff.features.ref("tagged", version=1, name="open")

    assert read.parameters.model_dump() == {"name": "open"}
