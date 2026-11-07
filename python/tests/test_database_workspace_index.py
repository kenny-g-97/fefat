"""The index of the workspace's files, step 4.1 (D-84, ADR-0020): the feature versions, the leak
detector's reports, and the saved import profiles the SDK wrote get a row each in the app's
database, the files they index staying the record; indexing again adds only the files it has
not seen, and moves or changes none."""

import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import fefat as ff
from fefat.config import resolve_paths
from fefat.features import combine
from fefat.features.validation_report import StartCheck, ValidationReport
from fefat.features.versions import validation_file
from fefat.market.importers.profiles import ProfileKind, preset_profiles
from fefat.market.store_files import json_writer, write_atomically
from fefat_app.database.models import (
    Base,
    FeatureRow,
    FeatureValidationRow,
    FeatureVersionRow,
    ImportProfileRow,
    WorkspaceRow,
)
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.database.workspace_index import IndexSummary, index_workspace
from notebook_runs import features_of_cell

GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature with one parameter, as a notebook cell defines it; another default of `n` gives
another version."""
VALIDATED_AT = datetime(2026, 11, 6, 9, 30, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """The app's database under the test's `FEFAT_HOME`, at the latest schema."""
    with opened_database(resolve_paths(os.environ).database_file) as opened:
        upgrade_schema(opened)
        yield opened


def gap_with(n: int) -> ff.features.FeatureVersion:
    """`gap` with its default `n` saved as a version."""
    return ff.features.save(features_of_cell(GAP.replace('"n": 3', f'"n": {n}'))["gap"])


def a_report(version: ff.features.FeatureVersion, *, later_from: date) -> ValidationReport:
    """A report of the version's hash, which passes where `later_from` lies after the data's
    first trade date, the 2nd of February."""
    return ValidationReport(
        feature=version.name,
        hash=version.hash,
        parameters={"n": 4},
        reads=(),
        instrument="ES",
        timeframe="1m",
        provider="synthetic",
        start=date(2026, 2, 11),
        end=date(2026, 2, 19),
        seed=3,
        stops=2,
        random_cuts=4,
        cuts=(),
        start_check=StartCheck(
            whole_from=date(2026, 2, 2),
            later_from=later_from,
            compared_from=later_from,
            compared={},
            difference=None,
        ),
        lint=(),
        created_at=VALIDATED_AT,
    )


def kept(report: ValidationReport) -> Path:
    """`report` written where the leak detector keeps its feature's latest of its hash."""
    path = validation_file(report.feature, report.hash)
    write_atomically(path, json_writer(report))
    return path


def a_saved_profile(name: str) -> Path:
    """TradingView's preset for 5-minute charts saved as a profile of one's own."""
    profiles_dir = resolve_paths(os.environ).profiles_dir
    profiles_dir.mkdir(parents=True, exist_ok=True)
    fields = preset_profiles()["tradingview"].model_dump(mode="json")
    path = profiles_dir / f"{name}.yaml"
    path.write_text(yaml.safe_dump({**fields, "name": name, "timeframe": "5m"}), encoding="utf-8")
    return path


def row_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            table.name: session.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def file_digests() -> dict[Path, str]:
    """Each file under `FEFAT_HOME` but the database's own, with its SHA-256."""
    home = resolve_paths(os.environ).home
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in home.rglob("*")
        if path.is_file() and not path.name.startswith("fefat.sqlite")
    }


def test_the_first_indexing_adds_a_row_for_each_file(engine: Engine) -> None:
    first, second = gap_with(3), gap_with(4)
    report_file = kept(a_report(second, later_from=date(2026, 2, 3)))
    profile_file = a_saved_profile("es-tradingview-5m")

    indexed = index_workspace(engine)

    assert indexed == IndexSummary(versions=2, validations=1, profiles=1)
    with Session(engine) as session:
        workspace = session.scalars(select(WorkspaceRow)).one()
        feature = session.scalars(select(FeatureRow)).one()
        versions = session.scalars(select(FeatureVersionRow).order_by("version_no")).all()
        validation = session.scalars(select(FeatureValidationRow)).one()
        profile = session.scalars(select(ImportProfileRow)).one()
    assert (workspace.name, workspace.path) == ("default", "workspaces/default")
    assert (feature.name, feature.workspace_id) == ("gap", workspace.id)
    assert [(each.version_no, each.content_hash) for each in versions] == [
        (1, first.hash),
        (2, second.hash),
    ]
    assert versions[1].code == second.code
    assert versions[1].params_schema_json == second.parameter_schema
    assert versions[1].outputs_json == {"gap": "price_distance"}
    assert (versions[1].warmup, versions[1].warmup_sessions) == ("lambda n: n", 0)
    assert versions[1].combination_json is None
    assert versions[1].created_at == second.created_at
    assert validation.feature_version_id == versions[1].id
    assert validation.report_sha256 == hashlib.sha256(report_file.read_bytes()).hexdigest()
    assert (validation.feature_name, validation.feature_hash) == ("gap", second.hash)
    assert (validation.instrument, validation.timeframe, validation.provider) == (
        "ES",
        "1m",
        "synthetic",
    )
    assert (validation.window_start, validation.window_end) == (
        date(2026, 2, 11),
        date(2026, 2, 19),
    )
    assert (validation.parameters_json, validation.passed) == ({"n": 4}, True)
    assert validation.created_at == VALIDATED_AT
    assert (profile.kind, profile.name) == (ProfileKind.MARKET_DATA, "es-tradingview-5m")
    assert profile.sha256 == hashlib.sha256(profile_file.read_bytes()).hexdigest()


def test_indexing_again_adds_only_the_files_it_has_not_seen_and_keeps_a_replaced_report(
    engine: Engine,
) -> None:
    # D-84: the file keeps the latest report of its hash, the index every report it saw.
    second = (gap_with(3), gap_with(4))[1]
    kept(a_report(second, later_from=date(2026, 2, 2)))
    a_saved_profile("es-tradingview-5m")
    index_workspace(engine)

    unchanged = index_workspace(engine)
    gap_with(5)
    kept(a_report(second, later_from=date(2026, 2, 3)))
    added = index_workspace(engine)

    assert unchanged == IndexSummary(versions=0, validations=0, profiles=0)
    assert added == IndexSummary(versions=1, validations=1, profiles=0)
    with Session(engine) as session:
        verdicts = session.scalars(select(FeatureValidationRow.passed)).all()
    assert sorted(verdicts) == [False, True]
    assert row_counts(engine) == {
        "settings": 0,
        "workspaces": 1,
        "features": 1,
        "feature_versions": 3,
        "feature_validations": 2,
        "import_profiles": 1,
        "jobs": 0,
        "events": 0,
        "sessions": 0,
        "api_tokens": 0,
    }


def test_indexing_moves_and_changes_no_file(engine: Engine) -> None:
    kept(a_report(gap_with(3), later_from=date(2026, 2, 3)))
    a_saved_profile("es-tradingview-5m")
    before = file_digests()

    index_workspace(engine)

    assert len(before) == 3
    assert file_digests() == before


def test_a_profile_copied_by_hand_under_another_name_is_indexed_once(engine: Engine) -> None:
    # Its copy holds the same bytes, which the index keeps by their SHA-256.
    saved = a_saved_profile("es-tradingview-5m")
    shutil.copyfile(saved, saved.with_name("es-tradingview-5m - Copy.yaml"))

    indexed = index_workspace(engine)

    assert indexed.profiles == 1
    assert row_counts(engine)["import_profiles"] == 1


def test_a_report_of_a_hash_no_version_has_is_indexed_without_a_link(engine: Engine) -> None:
    # A feature validated before it was saved (`test_features_validation.py`).
    unsaved = gap_with(3).model_copy(update={"name": "unsaved", "hash": "d" * 64})
    kept(a_report(unsaved, later_from=date(2026, 2, 3)))

    index_workspace(engine)

    with Session(engine) as session:
        validation = session.scalars(select(FeatureValidationRow)).one()
    assert (validation.feature_name, validation.feature_version_id) == ("unsaved", None)


def test_a_report_in_a_form_the_sdk_no_longer_reads_stops_the_indexing_with_the_way_out(
    engine: Engine,
) -> None:
    # A report written while step 3.4 was being built, its lint's findings without the feature
    # they read, as one on the builder's PC is.
    report = a_report(gap_with(3), later_from=date(2026, 2, 3)).model_dump(mode="json")
    finding = {"rule": "negative_shift", "line": 3, "source": "shift(-1)", "explanation": "ahead"}
    path = validation_file(report["feature"], report["hash"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**report, "lint": [finding]}), encoding="utf-8")

    with pytest.raises(ValueError, match="Validate the feature again") as refused:
        index_workspace(engine)

    assert str(path) in str(refused.value)
    assert set(row_counts(engine).values()) == {0}


def test_a_version_file_changed_after_it_was_written_stops_the_indexing(engine: Engine) -> None:
    gap_with(3)
    a_saved_profile("es-tradingview-5m")
    path = resolve_paths(os.environ).features_dir / "gap" / "v1.json"
    changed = path.read_text(encoding="utf-8").replace("rolling_mean", "rolling_sum")
    path.write_text(changed, encoding="utf-8", newline="\n")

    with pytest.raises(ValueError, match=r"the file was changed after it was written"):
        index_workspace(engine)

    assert set(row_counts(engine).values()) == {0}


def test_a_version_saved_again_under_an_indexed_number_is_refused(engine: Engine) -> None:
    # A version file deleted by hand and its number saved again holds another hash.
    first = gap_with(3)
    index_workspace(engine)
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    other = gap_with(4)
    expected = (
        f"Expected version 1 of feature gap with the hash {first.hash[:12]} as indexed, got "
        f"{other.hash[:12]}"
    )

    with pytest.raises(ValueError, match=expected):
        index_workspace(engine)


def test_a_version_saved_again_under_another_number_is_refused(engine: Engine) -> None:
    # A version file deleted by hand and its code saved again takes the next number.
    first = gap_with(3)
    gap_with(4)
    index_workspace(engine)
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    again = gap_with(3)
    expected = (
        f"Expected the hash {first.hash[:12]} of feature gap as version 1, as indexed, got "
        "version 3"
    )

    with pytest.raises(ValueError, match=expected):
        index_workspace(engine)
    assert (again.hash, again.version) == (first.hash, 3)


def test_a_combination_is_indexed_with_its_description_and_the_features_it_reads(
    engine: Engine,
) -> None:
    # Step 6.6's dialog reopens a combination from its description (from `BACKLOG.md`).
    rsi = ff.indicators.rsi
    stretch = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 10))
    saved = ff.features.save(stretch)
    written = saved.model_dump(mode="json")

    indexed = index_workspace(engine)

    with Session(engine) as session:
        row = session.scalars(
            select(FeatureVersionRow).where(FeatureVersionRow.content_hash == saved.hash)
        ).one()
    assert indexed.versions == 2
    assert row.combination_json == written["combination"]
    assert row.inputs_json == written["inputs"]
    assert [each["name"] for each in row.inputs_json] == ["rsi"]
