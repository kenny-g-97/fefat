"""The index of the workspace's files, step 4.1 (D-84, ADR-0020): the feature versions, the leak
detector's reports, and the saved import profiles the SDK wrote get a row each in the app's
database, the files they index staying the record; indexing again adds only the files it has
not seen, and moves or changes none. From step 5.2 (D-93), the strategy versions with the feature
versions they pin, under the folders the index is given."""

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import fefat as ff
from fefat.config import FefatPaths, resolve_paths
from fefat.features import combine
from fefat.features.validation_report import StartCheck, ValidationReport
from fefat.features.versions import saved_versions_in, validation_file
from fefat.market.importers.profiles import ProfileKind, preset_profiles
from fefat.market.store_files import json_writer, write_atomically
from fefat.strategy import StrategyKind
from fefat.strategy.versions import saved_versions_in as saved_strategy_versions_in
from fefat_app.database import version_index
from fefat_app.database.models import (
    ApiTokenRow,
    Base,
    FeatureRow,
    FeatureValidationRow,
    FeatureVersionRow,
    ImportProfileRow,
    RunRow,
    StrategyRow,
    StrategyVersionFeatureRow,
    StrategyVersionRow,
    WorkspaceRow,
)
from fefat_app.database.run_records import RunTables
from fefat_app.database.schema import not_waiting, opened_database, upgrade_schema
from fefat_app.database.version_index import index_library
from fefat_app.database.workspace_index import IndexSummary, index_workspace
from notebook_runs import breakout, features_of_cell, store_with
from strategy_code import BREAKOUT, ES_BREAKOUT, HYPOTHESIS, WITH_A_SLOT

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


def paths() -> FefatPaths:
    """The folders of the test's `FEFAT_HOME`, which the SDK saved into."""
    return resolve_paths(os.environ)


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

    indexed = index_workspace(engine, paths())

    assert indexed == IndexSummary(
        feature_versions=2, strategy_versions=0, validations=1, profiles=1, runs=0
    )
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
    index_workspace(engine, paths())

    unchanged = index_workspace(engine, paths())
    gap_with(5)
    kept(a_report(second, later_from=date(2026, 2, 3)))
    added = index_workspace(engine, paths())

    assert unchanged == IndexSummary(
        feature_versions=0, strategy_versions=0, validations=0, profiles=0, runs=0
    )
    assert added == IndexSummary(
        feature_versions=1, strategy_versions=0, validations=1, profiles=0, runs=0
    )
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
        "strategies": 0,
        "strategy_versions": 0,
        "strategy_version_features": 0,
        "runs": 0,
    }


def test_indexing_moves_and_changes_no_file(engine: Engine) -> None:
    kept(a_report(gap_with(3), later_from=date(2026, 2, 3)))
    a_saved_profile("es-tradingview-5m")
    before = file_digests()

    index_workspace(engine, paths())

    assert len(before) == 3
    assert file_digests() == before


def test_a_profile_copied_by_hand_under_another_name_is_indexed_once(engine: Engine) -> None:
    # Its copy holds the same bytes, which the index keeps by their SHA-256.
    saved = a_saved_profile("es-tradingview-5m")
    shutil.copyfile(saved, saved.with_name("es-tradingview-5m - Copy.yaml"))

    indexed = index_workspace(engine, paths())

    assert indexed.profiles == 1
    assert row_counts(engine)["import_profiles"] == 1


def test_a_report_of_a_hash_no_version_has_is_indexed_without_a_link(engine: Engine) -> None:
    # A feature validated before it was saved (`test_features_validation.py`).
    unsaved = gap_with(3).model_copy(update={"name": "unsaved", "hash": "d" * 64})
    kept(a_report(unsaved, later_from=date(2026, 2, 3)))

    index_workspace(engine, paths())

    with Session(engine) as session:
        validation = session.scalars(select(FeatureValidationRow)).one()
    assert (validation.feature_name, validation.feature_version_id) == ("unsaved", None)


def a_report_the_sdk_no_longer_reads() -> Path:
    """A report written while step 3.4 was being built, its lint's findings without the feature
    they read, as one on the builder's PC is."""
    report = a_report(gap_with(3), later_from=date(2026, 2, 3)).model_dump(mode="json")
    finding = {"rule": "negative_shift", "line": 3, "source": "shift(-1)", "explanation": "ahead"}
    path = validation_file(report["feature"], report["hash"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**report, "lint": [finding]}), encoding="utf-8")
    return path


def test_a_report_in_a_form_the_sdk_no_longer_reads_stops_the_indexing_with_the_way_out(
    engine: Engine,
) -> None:
    path = a_report_the_sdk_no_longer_reads()

    with pytest.raises(ValueError, match="Validate the feature again") as refused:
        index_workspace(engine, paths())

    assert str(path) in str(refused.value)
    assert set(row_counts(engine).values()) == {0}


def test_a_version_file_changed_after_it_was_written_stops_the_indexing(engine: Engine) -> None:
    gap_with(3)
    a_saved_profile("es-tradingview-5m")
    path = resolve_paths(os.environ).features_dir / "gap" / "v1.json"
    changed = path.read_text(encoding="utf-8").replace("rolling_mean", "rolling_sum")
    path.write_text(changed, encoding="utf-8", newline="\n")

    with pytest.raises(ValueError, match=r"the file was changed after it was written"):
        index_workspace(engine, paths())

    assert set(row_counts(engine).values()) == {0}


def test_a_version_saved_again_under_an_indexed_number_is_refused(engine: Engine) -> None:
    # A version file deleted by hand and its number saved again holds another hash.
    first = gap_with(3)
    index_workspace(engine, paths())
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    other = gap_with(4)
    expected = (
        f"Expected version 1 of feature gap with the hash {first.hash[:12]} as indexed, got "
        f"{other.hash[:12]}"
    )

    with pytest.raises(ValueError, match=expected):
        index_workspace(engine, paths())


def test_a_version_saved_again_under_another_number_is_refused(engine: Engine) -> None:
    # A version file deleted by hand and its code saved again takes the next number.
    first = gap_with(3)
    gap_with(4)
    index_workspace(engine, paths())
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    again = gap_with(3)
    expected = (
        f"Expected the hash {first.hash[:12]} of feature gap as version 1, as indexed, got "
        "version 3"
    )

    with pytest.raises(ValueError, match=expected):
        index_workspace(engine, paths())
    assert (again.hash, again.version) == (first.hash, 3)


def test_a_rebuild_indexes_the_files_as_they_are_and_keeps_the_apps_own_state(
    engine: Engine,
) -> None:
    # The Phase 4 exit (`BACKLOG.md`, rebuild the index tables alone): a version file deleted
    # by hand stopped every indexing, and deleting the database to index anew would lose the
    # password, the sessions, and the API tokens; a rebuild indexes the files as they are now.
    gap_with(3)
    a_saved_profile("es-tradingview-5m")
    index_workspace(engine, paths())
    with Session(engine) as session, session.begin():
        session.add(ApiTokenRow(name="notebook", token_hash="e" * 64, created_at=VALIDATED_AT))
    (resolve_paths(os.environ).features_dir / "gap" / "v1.json").unlink()
    again = gap_with(4)

    with pytest.raises(ValueError, match="fefat db import-workspace --rebuild"):
        index_workspace(engine, paths())
    rebuilt = index_workspace(engine, paths(), rebuild=True)

    assert rebuilt == IndexSummary(
        feature_versions=1, strategy_versions=0, validations=0, profiles=1, runs=0, rebuilt=True
    )
    with Session(engine) as session:
        assert session.scalars(select(FeatureVersionRow.content_hash)).all() == [again.hash]
        assert session.scalars(select(ApiTokenRow.name)).all() == ["notebook"]
    with (
        pytest.raises(IntegrityError, match="feature_versions rows are never deleted"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql("DELETE FROM feature_versions")


def test_a_combination_is_indexed_with_its_description_and_the_features_it_reads(
    engine: Engine,
) -> None:
    # Step 6.6's dialog reopens a combination from its description (from `BACKLOG.md`).
    rsi = ff.indicators.rsi
    stretch = combine.define("rsi_stretch", rsi(14) - combine.rolling_mean(rsi(14), 10))
    saved = ff.features.save(stretch)
    written = saved.model_dump(mode="json")

    indexed = index_workspace(engine, paths())

    with Session(engine) as session:
        row = session.scalars(
            select(FeatureVersionRow).where(FeatureVersionRow.content_hash == saved.hash)
        ).one()
    assert indexed.feature_versions == 2
    assert row.combination_json == written["combination"]
    assert row.inputs_json == written["inputs"]
    assert [each["name"] for each in row.inputs_json] == ["rsi"]


OVERSOLD = WITH_A_SLOT.format(feature="ff.indicators.rsi(14)", entry='pl.col("read") < 30')
"""A strategy reading the SDK's RSI in a slot, which its version pins."""


def test_strategy_versions_are_indexed_with_the_feature_versions_they_pin(
    engine: Engine,
) -> None:
    # Step 5.2 (D-93): a strategy's versions are files the index reads as it reads a feature's.
    oversold = ff.strategy.save("oversold", OVERSOLD, hypothesis=HYPOTHESIS, changelog="First.")
    breakout = ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)

    indexed = index_workspace(engine, paths())
    again = index_workspace(engine, paths())

    assert indexed == IndexSummary(
        feature_versions=1, strategy_versions=2, validations=0, profiles=0, runs=0
    )
    assert again == IndexSummary(
        feature_versions=0, strategy_versions=0, validations=0, profiles=0, runs=0
    )
    with Session(engine) as session:
        strategies = session.scalars(select(StrategyRow).order_by(StrategyRow.name)).all()
        versions = {row.content_hash: row for row in session.scalars(select(StrategyVersionRow))}
        pin = session.scalars(select(StrategyVersionFeatureRow)).one()
        rsi = session.scalars(select(FeatureVersionRow)).one()
    row = versions[oversold.hash]
    assert [(each.name, each.kind) for each in strategies] == [
        ("breakout", StrategyKind.SIGNAL),
        ("oversold", StrategyKind.SIGNAL),
    ]
    assert (row.version_no, row.hypothesis, row.changelog) == (1, HYPOTHESIS, "First.")
    assert (row.instrument, row.timeframe, row.code) == ("MES", "5m", oversold.code)
    assert (row.params_schema_json, row.created_at) == (
        oversold.parameter_schema,
        oversold.created_at,
    )
    assert (pin.strategy_version_id, pin.feature_version_id) == (row.id, rsi.id)
    assert versions[breakout.hash].version_no == 1


def test_a_strategy_version_pinning_a_feature_version_the_library_lacks_stops_the_indexing(
    engine: Engine,
) -> None:
    ff.strategy.save("oversold", OVERSOLD, hypothesis=HYPOTHESIS)
    (paths().features_dir / "rsi" / "v1.json").unlink()

    with pytest.raises(ValueError, match="which version 1 of strategy oversold pins"):
        index_workspace(engine, paths())

    assert set(row_counts(engine).values()) == {0}


def test_a_rebuild_empties_the_strategies_before_the_feature_versions_they_pin(
    engine: Engine,
) -> None:
    # The foreign keys hold during a rebuild, so a pin leaves before the versions it names.
    ff.strategy.save("oversold", OVERSOLD, hypothesis=HYPOTHESIS)
    index_workspace(engine, paths())

    rebuilt = index_workspace(engine, paths(), rebuild=True)

    assert rebuilt == IndexSummary(
        feature_versions=1, strategy_versions=1, validations=0, profiles=0, runs=0, rebuilt=True
    )
    assert row_counts(engine)["strategy_version_features"] == 1
    with (
        pytest.raises(IntegrityError, match="strategy_versions rows are never deleted"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql("DELETE FROM strategy_versions")


def test_the_library_is_read_before_the_index_takes_the_write_lock(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The step review: a save indexes the library twice, and every other writer, a job renewing
    # its lease among them, would wait while the version files are read under the lock.
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    read: list[Path] = []

    def while_another_writes[Record](
        reader: Callable[[Path], list[Record]],
    ) -> Callable[[Path], list[Record]]:
        def reading(folder: Path) -> list[Record]:
            with not_waiting(engine).begin() as connection:
                connection.exec_driver_sql("SELECT 1")
            read.append(folder)
            return reader(folder)

        return reading

    with monkeypatch.context() as patch:
        patch.setattr(version_index, "saved_versions_in", while_another_writes(saved_versions_in))
        patch.setattr(
            version_index,
            "saved_strategy_versions_in",
            while_another_writes(saved_strategy_versions_in),
        )
        index_library(engine, paths())

    assert read == [paths().features_dir, paths().strategies_dir]
    assert row_counts(engine)["strategy_versions"] == 1


def test_a_version_file_copied_by_hand_under_another_number_is_refused(engine: Engine) -> None:
    # The step review: the copy gives its original's hash, which one strategy holds once.
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)
    folder = paths().strategies_dir / "breakout"
    record = json.loads((folder / "v1.json").read_text(encoding="utf-8"))
    (folder / "v2.json").write_text(json.dumps({**record, "version": 2}), encoding="utf-8")

    with pytest.raises(ValueError, match="of strategy breakout as version 1, as indexed, got"):
        index_library(engine, paths())

    assert set(row_counts(engine).values()) == {0}


@pytest.mark.parametrize(
    ("deleted", "named"),
    [("strategies/oversold/v1.json", "strategy oversold"), ("features/rsi/v1.json", "feature rsi")],
)
def test_a_version_file_deleted_by_hand_after_it_was_indexed_is_refused(
    engine: Engine, deleted: str, named: str
) -> None:
    # The step review: a save would otherwise write the next version under the deleted number.
    ff.strategy.save("oversold", OVERSOLD, hypothesis=HYPOTHESIS)
    index_library(engine, paths())
    (paths().workspace_dir / deleted).unlink()

    with pytest.raises(ValueError, match=f"version 1 of {named}, as indexed, got no file"):
        index_library(engine, paths())


def test_the_library_is_indexed_beside_a_report_the_sdk_refuses(engine: Engine) -> None:
    # A save of the app indexes the versions alone (step 5.2), so that a report left from step
    # 3.4's development, as one on the builder's PC is, holds up no save.
    a_report_the_sdk_no_longer_reads()
    ff.strategy.save("breakout", BREAKOUT, hypothesis=HYPOTHESIS)

    index_library(engine, paths())

    counts = row_counts(engine)
    assert (counts["feature_versions"], counts["strategy_versions"]) == (1, 1)
    assert counts["feature_validations"] == 0
    with pytest.raises(ValueError, match="Validate the feature again"):
        index_workspace(engine, paths())


def test_a_saved_run_is_indexed_with_its_strategy_version_and_again_at_a_rebuild(
    engine: Engine,
) -> None:
    # Step 5.3 (D-84): the run folders are the record, which the index reads as it reads the
    # versions; a run of a saved version names it.
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)
    run = ff.backtest.run(version.strategy(), "2026-03-05", "2026-03-09")

    indexed = index_workspace(engine, paths())
    again = index_workspace(engine, paths())
    rebuilt = index_workspace(engine, paths(), rebuild=True)

    assert (indexed.runs, again.runs, rebuilt.runs) == (1, 0, 1)
    with Session(engine) as session:
        row = session.scalars(select(RunRow)).one()
        pinned = session.get_one(StrategyVersionRow, row.strategy_version_id)
    assert (row.run_key, row.job_id, row.created_at) == (run.hash, None, run.saved_at)
    assert (pinned.content_hash, row.parameters_json) == (
        version.hash,
        {"lookback": 12, "stop_atr": 1.5},
    )
    assert row.settings_json == run.config.model_dump(mode="json")
    with (
        pytest.raises(IntegrityError, match="runs rows are never deleted once saved"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql("DELETE FROM runs")


def test_a_run_a_notebook_made_is_indexed_without_a_strategy_version(engine: Engine) -> None:
    # Step 5.3 (its ponytail review): a strategy written in a notebook names no saved version, the
    # SDK's own way of making a run; its row names no version and no parameters.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    assert index_workspace(engine, paths()).runs == 1
    (indexed,) = RunTables(engine, paths()).newest(10)
    assert (indexed.run_key, indexed.strategy, indexed.parameters) == (run.hash, None, {})
