"""The previews of both importers (step 5.14, ADR-0021, Done means 3): each reads its file
against the store as the import would and writes nothing, says what the import then does, names
the sessions the file adds, counts the records the store holds and those that differ, and holds
no price in that account. Every file is generated in the test's folder but the fixtures' batch
and NinjaTrader sample."""

from datetime import date
from pathlib import Path

import pytest
from databento_dbn import OHLCVMsg

from dbn_files import utc
from export_samples import (
    PRESETS,
    SAMPLES,
    SYNTHETIC,
    sample_lines,
    sample_request,
    with_a_lot_more_in_the_last_bar,
    written_export,
)
from fefat.market.engine_units import price_text
from fefat.market.importers.databento import import_databento, preview_databento
from fefat.market.importers.file_import import FileImportRequest, import_file, preview_file
from fefat.market.importers.file_report import AlreadyImported, FileImportReport
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import ImportProfile
from fefat.market.importers.report import DatasetMerge, DayRecords
from fefat.market.instruments import STATIC_TABLE
from fefat.market.store import Store
from test_market_importers_merge_properties import (
    IMPORTED_ON,
    MARCH_9,
    ONE_MINUTE,
    TICK,
    es_bars,
    march_file,
    march_store,
    through_a_profile,
    tree,
)

BATCH = SYNTHETIC / "databento-batch" / "GLBX-20260310-SYNTHETIC0"
MARCH_10 = utc(2026, 3, 10, 14, 30)
TAKEN = "the file's taken in place of 1 stored record"


def test_a_databento_preview_names_what_the_import_then_adds_and_writes_nothing(
    tmp_path: Path,
) -> None:
    # The store holds three bars of 2026-03-09. The file holds the last of them again, the bar
    # after it, a bar of the next session, and one of February, a month the store lacks.
    store, cache = march_store(tmp_path), tmp_path / "cache"
    before = tree(store.folder)
    bars = es_bars(utc(2026, 2, 10, 14, 30), MARCH_9[2], utc(2026, 3, 9, 14, 33), MARCH_10)
    source = march_file(tmp_path, "later", bars)

    preview = preview_databento(source, store, cache)
    untouched = tree(store.folder)
    report = import_databento(source, store, cache, imported_on=IMPORTED_ON)

    assert untouched == before
    assert preview.files == report.files
    (merge,) = preview.files[0].merges
    assert (merge.records_added, merge.records_held, merge.records_differing) == (3, 1, 0)
    assert merge.new_sessions == (
        DayRecords(trade_date=date(2026, 2, 10), records=1),
        DayRecords(trade_date=date(2026, 3, 10), records=1),
    )
    assert merge.extended_sessions == (DayRecords(trade_date=date(2026, 3, 9), records=1),)
    assert (merge.partitions_changed, merge.partitions_unchanged) == (2, 0)
    assert not preview.refuses()
    shown = preview.summary().splitlines()
    assert shown[0] == f"Preview of {source}; nothing was written."
    assert shown[-5:] == [
        "    New sessions: 2 records on 2 trade dates: 2026-02-10 (1), 2026-03-10 (1)",
        "    Sessions the store holds that gain records: 1 record on 1 trade date: 2026-03-09 (1)",
        "    Records: 3 new, 1 already held, 0 that differ",
        "    Partitions: 2 that change, 0 unchanged",
        "It would import as it is.",
    ]


def test_a_databento_preview_of_bars_that_differ_would_be_refused_unless_the_files_stand(
    tmp_path: Path,
) -> None:
    store, cache = march_store(tmp_path), tmp_path / "cache"
    before = tree(store.folder)
    source = march_file(tmp_path, "revised", es_bars(MARCH_9[1], close=6_751_250_000_000))

    refused = preview_databento(source, store, cache)
    taken = preview_databento(source, store, cache, differing=DifferingRecords.TAKE_THE_FILE)

    assert tree(store.folder) == before
    assert (refused.refuses(), taken.refuses()) == (True, False)
    shown = refused.summary().splitlines()
    assert "    Records: 0 new, 0 already held, 1 that differ" in shown
    assert "    Records that differ: 1 record on 1 trade date: 2026-03-09 (1)" in shown
    assert shown[-1].startswith("It would be refused: its records differ from the ones the store")
    assert "--differing take-file" in shown[-1]
    assert f"    Records: 0 new, 0 already held, 1 that differ, {TAKEN}" in taken.summary()
    assert taken.summary().splitlines()[-1] == "It would import as it is."


def test_a_preview_of_a_batch_download_writes_no_file_its_sidecars_included(
    tmp_path: Path,
) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"

    preview = preview_databento(BATCH, store, cache)
    written = tree(tmp_path / "data")
    report = import_databento(BATCH, store, cache, imported_on=IMPORTED_ON)

    assert written == {}
    assert preview.batch == report.batch and preview.files == report.files
    assert (
        "    New sessions: 4,141 records on 3 trade dates: 2026-03-05 (1,380), 2026-03-06 (1,381), "
        "2026-03-09 (1,380)"
    ) in preview.summary().splitlines()
    assert len(store.raw.manifest().files) == 4


def test_a_databento_preview_of_an_imported_file_says_that_it_would_import_nothing(
    tmp_path: Path,
) -> None:
    store = march_store(tmp_path)
    before = tree(store.folder)

    preview = preview_databento(
        march_file(tmp_path, "first", es_bars(*MARCH_9)), store, tmp_path / "cache"
    )

    assert tree(store.folder) == before
    assert preview.files == () and len(preview.already_imported) == 1
    assert not preview.refuses()
    assert preview.summary().splitlines()[-2:] == [
        f"Already imported: {preview.already_imported[0]}",
        "It would import nothing.",
    ]


def test_a_file_preview_names_what_the_import_then_adds_and_writes_nothing(
    tmp_path: Path,
) -> None:
    # The store holds the sample but its last bar, of 2026-03-09. The later export holds the
    # sample whole and the first two bars of the next session, stamped at their close.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    ninjatrader, lines = PRESETS["ninjatrader"], sample_lines("ninjatrader")
    earlier = written_export(tmp_path / "earlier", "ES 03-26.Last.txt", lines[:-1])
    through_a_profile(ninjatrader)(earlier, store, cache)
    before = tree(store.folder)
    next_session = [
        "20260309 220100;6851;6851.25;6850.75;6851;12",
        "20260309 220200;6851;6851.5;6851;6851.25;7",
    ]
    later = written_export(tmp_path / "later", "ES 03-26.Last.txt", [*lines, *next_session])
    request = FileImportRequest(path=later, profile=ninjatrader)

    preview = preview_file(request, store, STATIC_TABLE, cache)
    untouched = tree(store.folder)
    report = import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)

    assert untouched == before
    assert isinstance(report, FileImportReport)
    merge = report.merge
    assert preview.against_the_store == merge
    assert (merge.records_added, merge.records_held, merge.records_differing) == (3, 4_140, 0)
    assert merge.new_sessions == (DayRecords(trade_date=date(2026, 3, 10), records=2),)
    assert merge.extended_sessions == (DayRecords(trade_date=date(2026, 3, 9), records=1),)
    assert preview.refusals() == []
    assert preview.summary().splitlines()[-6:] == [*merge.lines(), "It would import as it is."]


def test_a_file_preview_of_bars_that_differ_would_be_refused_unless_the_files_stand(
    tmp_path: Path,
) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    ninjatrader = PRESETS["ninjatrader"]
    through_a_profile(ninjatrader)(SAMPLES["ninjatrader"][0], store, cache)
    before = tree(store.folder)
    lines = with_a_lot_more_in_the_last_bar(sample_lines("ninjatrader"))
    changed = written_export(tmp_path / "exports", "ES 03-26.Last.txt", lines)
    request = FileImportRequest(path=changed, profile=ninjatrader)

    refused = preview_file(request, store, STATIC_TABLE, cache)
    taken = preview_file(
        request, store, STATIC_TABLE, cache, differing=DifferingRecords.TAKE_THE_FILE
    )

    assert tree(store.folder) == before
    assert (len(refused.refusals()), taken.refusals()) == (1, [])
    assert "1 with other values" in refused.refusals()[0]
    shown = refused.summary().splitlines()
    assert "    Records that differ: 1 record on 1 trade date: 2026-03-09 (1)" in shown
    assert shown[-1].startswith("It would be refused: its records differ from the ones the store")
    assert "--differing take-file" in shown[-1]
    assert f"    Records: 0 new, 4,140 already held, 1 that differ, {TAKEN}" in taken.summary()
    assert taken.summary().splitlines()[-1] == "It would import as it is."


def test_a_file_preview_of_an_imported_file_says_so_and_refuses_what_its_import_refuses(
    tmp_path: Path,
) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    request = sample_request("ninjatrader")
    import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    before = tree(store.folder)
    under_another_contract = sample_request("ninjatrader", contract="ESM2026")

    preview = preview_file(request, store, STATIC_TABLE, cache)

    assert tree(store.folder) == before
    assert isinstance(preview.against_the_store, AlreadyImported)
    assert preview.refusals() == []
    raw_path = store.raw.manifest().files[0].path
    assert preview.summary().splitlines()[-1] == (
        f"It is imported already, as raw/{raw_path}: importing it again changes nothing."
    )
    with pytest.raises(ValueError, match="a file is imported once, as its first import read it"):
        preview_file(under_another_contract, store, STATIC_TABLE, cache)


def test_a_preview_of_an_imported_file_refuses_nothing_though_its_profile_now_misreads_it(
    tmp_path: Path,
) -> None:
    # A profile edited under its name is not told apart from the one a file was imported with
    # (`file_import`'s shortcut), so the import of such a file changes nothing, and its preview
    # says so: it shows the problems the profile now finds and refuses nothing.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    request = sample_request("ninjatrader")
    import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    preset = request.profile.model_dump(mode="json")
    misreading = ImportProfile.model_validate(
        {**preset, "price": {"unit": "decimal", "scale": "0.1"}}
    )

    preview = preview_file(
        sample_request("ninjatrader", profile=misreading), store, STATIC_TABLE, cache
    )
    again = import_file(
        sample_request("ninjatrader", profile=misreading),
        store,
        cache,
        imported_on=IMPORTED_ON,
        instruments=STATIC_TABLE,
    )

    assert isinstance(again, AlreadyImported)
    assert preview.against_the_store == again
    assert preview.reading.problems != ()
    assert preview.refusals() == []


def quarter_bar(instant: int, close: int) -> OHLCVMsg:
    """A bar of ESH2026 none of whose prices is a whole number of points, so that each reads
    apart from a count, a date, and a hash."""
    return OHLCVMsg(ONE_MINUTE, 1, 1001, instant, close, close + TICK, close, close, 10)


def priced(texts: list[str], prices: set[int]) -> list[tuple[str, str]]:
    """Each price found in a text, as the store's whole number or as its decimal."""
    written = {form for price in prices for form in (str(price), price_text(price))}
    return [(form, text) for text in texts for form in sorted(written) if form in text]


def test_no_price_reaches_what_a_databento_import_or_its_preview_says(tmp_path: Path) -> None:
    # Done means 3: the bar the two dispute and the bar the file adds carry prices of their
    # own, and neither they nor the stored ones appear in the refusal, the previews, the
    # report, or the account of the merge.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    closes = {"stored": 6_750_250_000_000, "revised": 6_751_250_000_000, "new": 6_752_250_000_000}
    stored = [quarter_bar(instant, closes["stored"]) for instant in MARCH_9]
    import_databento(march_file(tmp_path, "first", stored), store, cache, imported_on=IMPORTED_ON)
    bars = [quarter_bar(MARCH_9[1], closes["revised"]), quarter_bar(MARCH_10, closes["new"])]
    source = march_file(tmp_path, "revised", bars)
    take = DifferingRecords.TAKE_THE_FILE

    with pytest.raises(ValueError, match="got 1 with other values") as refused:
        import_databento(source, store, cache, imported_on=IMPORTED_ON)
    previews = [
        preview_databento(source, store, cache),
        preview_databento(source, store, cache, differing=take),
    ]
    report = import_databento(source, store, cache, imported_on=IMPORTED_ON, differing=take)

    (merge,) = report.files[0].merges
    assert (merge.records_added, merge.records_differing) == (1, 1)
    texts = [
        str(refused.value),
        *(preview.summary() for preview in previews),
        report.summary(),
        merge.model_dump_json(),
    ]
    prices = {price for close in closes.values() for price in (close, close + TICK)}
    assert priced(texts, prices) == []
    assert priced(["6750.25"], prices) == [("6750.25", "6750.25")]


def test_no_price_reaches_what_a_file_import_says_of_its_merge(tmp_path: Path) -> None:
    # A file preview shows its first records as stored, prices and all, on the trader's screen,
    # as it did before this step; the account of the merge, in the preview and the report, and
    # the refusal of the bar that differs hold none of that bar's prices.
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    ninjatrader = PRESETS["ninjatrader"]
    through_a_profile(ninjatrader)(SAMPLES["ninjatrader"][0], store, cache)
    lines = with_a_lot_more_in_the_last_bar(sample_lines("ninjatrader"))
    changed = written_export(tmp_path / "exports", "ES 03-26.Last.txt", lines)
    request = FileImportRequest(path=changed, profile=ninjatrader)
    take = DifferingRecords.TAKE_THE_FILE

    with pytest.raises(ValueError, match="got 1 with other values") as refused:
        import_file(request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE)
    preview = preview_file(request, store, STATIC_TABLE, cache, differing=take)
    report = import_file(
        request, store, cache, imported_on=IMPORTED_ON, instruments=STATIC_TABLE, differing=take
    )

    assert isinstance(report, FileImportReport)
    assert isinstance(preview.against_the_store, DatasetMerge)
    last_bar = store.scan_partition(next(iter(store.list_partitions())).partition).collect().tail(1)
    prices = set(last_bar.select("open", "high", "low", "close").row(0))
    texts = [
        str(refused.value),
        *preview.against_the_store.lines(),
        *report.merge.lines(),
        report.merge.model_dump_json(),
    ]
    assert len(prices) == 3
    assert priced(texts, prices) == []
