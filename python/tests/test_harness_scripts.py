"""The scripts of step 4.3's harness: `scripts/e2e_server.py`, the seeded server of `just e2e`,
and `scripts/dev.py`, which `just dev` runs, on a home seeded alike unless one is named, and
which starts its server again when the source changes (step 5.1)."""

import http.server
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import keyring
import polars as pl
import pytest
from keyring.backends import null

import dev
import e2e_server
from export_samples import HOUR, PRESETS
from fefat.backtest import saved_runs_in
from fefat.config import load_settings, resolve_paths
from fefat.market.calendar_breaks import BarsInBreaks
from fefat.market.calendar_definition import CalendarId
from fefat.market.calendar_offset import OffsetCause
from fefat.market.importers.file_import import FileImportRequest, preview_file
from fefat.market.importers.file_report import FilePreview
from fefat.market.importers.profiles import NewInstrument
from fefat.market.instruments import Currency, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.saved_instruments import instrument_table
from fefat.market.status import product_status
from fefat.market.store import Store
from fefat_app import database_commands
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.database.schema import opened_database


def test_the_seeded_home_is_made_afresh_with_its_port_and_the_fixtures(tmp_path: Path) -> None:
    home = tmp_path / "fefat-e2e"
    (home / "left-over").mkdir(parents=True)

    e2e_server.seeded_home(home, 8766)

    assert (home / "config.toml").read_text(encoding="utf-8") == "port = 8766\n"
    assert (home / "data" / "synthetic" / "MANIFEST.json").is_file()
    assert not (home / "left-over").exists()


def test_the_seeded_server_stops_before_it_starts_without_its_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as environment:
        environment.delenv("FEFAT_E2E_PORT", raising=False)

        with pytest.raises(SystemExit, match="Expected FEFAT_E2E_PORT in the environment"):
            e2e_server.main()


def test_dev_gives_up_on_a_server_that_ends_before_it_answers() -> None:
    server = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])

    assert dev.answered(server, "http://127.0.0.1:9/v1/healthz") is False
    assert server.returncode == 3


def test_a_home_that_cannot_be_wiped_stops_the_seeded_server_with_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "fefat-e2e"
    home.mkdir()

    def held(path: Path) -> None:
        raise PermissionError(f"[WinError 32] The process cannot access the file: {path}")

    with monkeypatch.context() as patched:
        patched.setattr(e2e_server.shutil, "rmtree", held)

        with pytest.raises(SystemExit, match="is the server of an earlier `just e2e`"):
            e2e_server.seeded_home(home, 8766)


def test_dev_seeds_a_throwaway_home_unless_a_home_is_named(tmp_path: Path) -> None:
    # Step 5.1, `01-architecture.md` section 9: the synthetic fixtures by default, a data folder
    # you name when you choose, and a home you name as it is.
    throwaway = Path(tempfile.gettempdir()) / "fefat-dev"

    assert dev.dev_home({}) == dev.DevHome(home=throwaway, data_dir=None)
    assert dev.dev_home({"FEFAT_DATA_DIR": str(tmp_path)}) == dev.DevHome(
        home=throwaway, data_dir=tmp_path
    )
    assert dev.dev_home({"FEFAT_HOME": str(tmp_path)}) is None


def test_the_source_stamp_changes_with_a_saved_added_or_renamed_file_and_not_a_cached_one(
    tmp_path: Path,
) -> None:
    # Step 5.1: `just dev` starts its server again when the stamp of the source changes.
    package = tmp_path / "src" / "fefat"
    (package / "__pycache__").mkdir(parents=True)
    module = package / "api.py"
    module.write_text("load = 1\n", encoding="utf-8")
    sources = (tmp_path / "src",)
    first = dev.source_stamp(sources)

    (package / "__pycache__" / "api.cpython-312.pyc").write_bytes(b"compiled")
    cached = dev.source_stamp(sources)
    later = module.stat().st_mtime_ns + 1_000_000_000
    os.utime(module, ns=(later, later))
    saved = dev.source_stamp(sources)
    (package / "status.py").write_text("datasets = 1\n", encoding="utf-8")
    added = dev.source_stamp(sources)
    module.rename(package / "loads.py")
    renamed = dev.source_stamp(sources)

    assert cached == first
    assert len({first, saved, added, renamed}) == 4


def test_the_source_stamp_of_a_folder_gone_mid_scan_is_empty(tmp_path: Path) -> None:
    # Step 5.1's review: a checkout that removes a package's folder must not end `just dev`.
    assert dev.source_stamp((tmp_path / "gone",)) == frozenset()


def test_dev_names_a_home_with_a_port_of_its_own_where_the_throwaway_ones_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 5.1's review: the throwaway home has no `config.toml` to set another port in.
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as other:
        port = other.server_address[1]
        threading.Thread(target=other.serve_forever, daemon=True).start()
        monkeypatch.delenv("FEFAT_HOME")
        monkeypatch.setattr(dev, "DEV_PORT", port)

        with pytest.raises(SystemExit, match="or name a FEFAT_HOME whose config"):
            dev.main()
        other.shutdown()


def test_dev_refuses_a_port_another_server_answers_on_before_starting_anything(
    tmp_path: Path,
) -> None:
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as other:
        port = other.server_address[1]
        threading.Thread(target=other.serve_forever, daemon=True).start()
        paths = resolve_paths(os.environ)
        paths.home.mkdir(parents=True, exist_ok=True)
        paths.config_file.write_text(f"port = {port}\n", encoding="utf-8")

        with pytest.raises(SystemExit, match=f"Expected port {port} free for fefat up"):
            dev.main()
        other.shutdown()


@pytest.fixture
def seeding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The variables the seed sets, given back after the test, and a keyring of its own for the
    container the seed builds: keyring keeps the backend of its first use in the process, which
    would be the seed's null one for every test after (the step's ponytail review)."""
    for name in ("FEFAT_HOME", "FEFAT_DATA_DIR", "PYTHON_KEYRING_BACKEND"):
        monkeypatch.setenv(name, os.environ[name])
    monkeypatch.setattr(keyring, "get_keyring", null.Keyring)


@pytest.mark.usefixtures("seeding")
def test_the_seed_saves_the_demo_strategy_and_its_first_run_indexed(tmp_path: Path) -> None:
    # Step 5.3 (D-93): the specs' `demo-run-01` is the first run of the strategy `demo` that
    # `GET /v1/runs` lists; the seed makes it through the SDK on the fixtures and indexes both as
    # `fefat db import-workspace` does, leaving no job.
    e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")

    paths = resolve_paths(os.environ)
    with opened_database(paths.database_file) as engine:
        strategies = LibraryTables(engine, paths).strategies()
        runs = RunTables(engine, paths).newest(10)
        jobs = JobTables(engine).recent(10)
    (run,) = runs
    (saved,) = saved_runs_in(paths.runs_dir)
    assert [strategy.name for strategy in strategies] == ["demo"]
    assert run.strategy is not None
    assert (run.strategy.name, run.status, run.run_key) == ("demo", "succeeded", saved.hash)
    assert saved.record.summary.trades >= 3
    assert jobs == ()


@pytest.mark.usefixtures("seeding")
def test_the_seed_writes_a_year_of_mes_a_product_of_the_catalog_unchecked(tmp_path: Path) -> None:
    # Step 5.4: a dataset page's Check quality needs a product of the catalog, and the chart a
    # year of 5-minute bars to scroll back through, which the fixtures' ES and bitcoin are not.
    e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")

    paths = resolve_paths(os.environ)
    status = product_status(Store(paths.data_dir), paths.reports_dir)
    (mes,) = status.filter(pl.col("root") == "MES").iter_rows(named=True)
    assert {name: mes[name] for name in ("provider", "schema", "coverage", "quality")} == {
        "provider": "synthetic",
        "schema": "ohlcv-1m",
        "coverage": "partial",
        "quality": "unchecked",
    }
    assert (mes["first_trade_date"], mes["last_trade_date"]) == (
        date(2025, 4, 1),
        date(2026, 3, 31),
    )
    assert mes["contracts"] == 5


@pytest.mark.usefixtures("seeding")
def test_a_seed_on_a_named_data_folder_writes_no_market_data_into_it(tmp_path: Path) -> None:
    # A guard: `just dev` with FEFAT_DATA_DIR serves the trader's own data, where nothing
    # synthetic may land.
    named = tmp_path / "their-data"
    named.mkdir()

    e2e_server.seed(tmp_path / "fefat-dev", 8765, "horse battery", data_dir=named)

    assert list(named.iterdir()) == []


@pytest.mark.usefixtures("seeding")
def test_the_seed_stops_where_the_index_refuses_what_it_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.3 (its code review): a seed whose index refused would start a server without the
    # run the specs call demo-run-01, failing them far from the cause.
    def refused(*arguments: object, **named: object) -> object:
        raise ValueError("Expected the files as indexed, got one changed by hand.")

    monkeypatch.setattr(database_commands, "index_workspace", refused)

    with pytest.raises(SystemExit, match="Expected `fefat db import-workspace` to index"):
        e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")


XES = NewInstrument(
    root="XES",
    kind=InstrumentKind.FUTURES,
    tick_size=Decimal("0.25"),
    point_value=Decimal(50),
    currency=Currency.USD,
    calendar=CalendarId.CME_EQUITY_INDEX,
    last_trade_rule=ThirdFriday(),
    first_trade_date=date(2010, 1, 4),
)
"""The new product the import spec's wizard specifies (step 5.12)."""


@pytest.mark.usefixtures("seeding")
def test_the_seed_writes_two_overlapping_exports_of_a_new_product_under_its_import_root(
    tmp_path: Path,
) -> None:
    # Step 5.12: the import spec's files, beside the home, under the root config.toml names; the
    # first, read in Chicago's time zone, runs six hours late, the review the spec corrects; the
    # first revised, its last bar one lot more, whose records differ from the first's; and two
    # more contracts of the first's dates, ten lots a bar, for a round of several files (D-102).
    e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")

    paths = resolve_paths(os.environ)
    exports = tmp_path / "fefat-e2e-exports"
    first, second = (exports / folder / "XES 03-26.Last.txt" for folder in ("first", "second"))
    assert load_settings(paths.config_file).import_roots == (exports,)
    store = Store(paths.data_dir)
    profile = PRESETS["ninjatrader"].model_copy(update={"instrument": XES})
    previews = [
        preview_file(
            FileImportRequest(path=path, profile=profile, time_zone=zone),
            store,
            instrument_table(store.folder),
            paths.cache_dir,
        )
        for path, zone in (
            (first, None),
            (second, None),
            (first, "America/Chicago"),
            (exports / "more" / "XES 06-26.Last.txt", None),
            (exports / "more" / "XES 09-26.Last.txt", None),
        )
    ]
    dates = [(each.reading.first_trade_date, each.reading.last_trade_date) for each in previews]
    assert dates[:2] == [
        (date(2026, 2, 2), date(2026, 2, 6)),
        (date(2026, 2, 5), date(2026, 2, 11)),
    ]
    assert [each.reading.refusals() for each in previews[:2]] == [[], []]
    (offset,) = previews[2].reading.calendar.offsets
    assert (offset.nanoseconds, offset.cause) == (6 * HOUR, OffsetCause.TIME_ZONE)
    *same, revised = (exports / "revised" / "XES 03-26.Last.txt").read_text().splitlines()
    *bars, last = first.read_text().splitlines()
    assert same == bars
    assert revised.rsplit(";", 1)[0] == last.rsplit(";", 1)[0]
    assert int(revised.rsplit(";", 1)[1]) == int(last.rsplit(";", 1)[1]) + 1
    more = previews[3:]
    assert [each.reading.contracts for each in more] == [("XESM2026",), ("XESU2026",)]
    assert [(each.reading.first_trade_date, each.reading.last_trade_date) for each in more] == [
        dates[0],
        dates[0],
    ]
    assert [each.reading.refusals() for each in more] == [[], []]
    tens = (exports / "more" / "XES 06-26.Last.txt").read_text().splitlines()
    assert [line.rsplit(";", 1) for line in tens] == [
        [line.rsplit(";", 1)[0], "10"] for line in [*bars, last]
    ]


@pytest.mark.usefixtures("seeding")
def test_the_seed_writes_exports_with_bars_in_a_break_for_the_correction(tmp_path: Path) -> None:
    # Step 5.15: the folder `breaks` holds three contracts of the first export's dates whose
    # break after 02-03 holds nine bars, the last closing at the next open, which the review
    # refuses for their bars in a break alone and the correction takes without 02-03 and 02-04;
    # and a fourth without them, which imports as it is.
    e2e_server.seed(tmp_path / "fefat-e2e", 8766, "horse battery")

    paths = resolve_paths(os.environ)
    breaks = tmp_path / "fefat-e2e-exports" / "breaks"
    store = Store(paths.data_dir)
    profile = PRESETS["ninjatrader"].model_copy(update={"instrument": XES})

    def previewed(name: str, choice: BarsInBreaks) -> FilePreview:
        request = FileImportRequest(path=breaks / name, profile=profile, bars_in_breaks=choice)
        return preview_file(request, store, instrument_table(store.folder), paths.cache_dir)

    for name in e2e_server.XES_WITH_A_BREAK:
        refused = previewed(name, BarsInBreaks.REFUSE).reading
        left_out = previewed(name, BarsInBreaks.LEAVE_OUT).reading
        (found,) = refused.calendar.breaks_with_bars
        assert refused.only_bars_in_breaks_refuse()
        assert [(each.after, each.bars) for each in found.breaks] == [(date(2026, 2, 3), 9)]
        assert found.trade_dates_beside() == [date(2026, 2, 3), date(2026, 2, 4)]
        assert found.records_beside() == 2 * 1_380 + 9
        assert (left_out.refusals(), left_out.records) == ([], 3 * 1_380)
    clean = previewed(e2e_server.XES_WITHOUT_A_BREAK, BarsInBreaks.REFUSE).reading
    assert (clean.refusals(), clean.records) == ([], 5 * 1_380)
