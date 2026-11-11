import hashlib
import os
import shutil
from datetime import date
from pathlib import Path, PurePosixPath

import polars as pl
import pytest

from fefat.market.catalog import Catalog, parse_catalog
from fefat.market.fidelity import fidelity_in_words
from fefat.market.layout import Dataset, Partition
from fefat.market.quality import assess_quality
from fefat.market.quality_report import DAYS_FILE_NAME, write_quality_report
from fefat.market.schema import parse_schema_name
from fefat.market.status import STATUS_COLUMNS, product_status
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "fixtures" / "synthetic"
FIXTURES = Store(ROOT / "fixtures")
MARCH_5, MARCH_7, MARCH_9 = (date(2026, 3, day) for day in (5, 7, 9))
SCHEMAS = (("ohlcv-1m", "1m"), ("ohlcv-1s", "1s"), ("trades", "trades"))
LISTED = ("root", "coverage", "provider", "schema", "fidelity", "first_trade_date")
MINUTE = 60_000_000_000
DAY = 1_440 * MINUTE


def catalog_of_mes_and_es(es_history_from: date) -> Catalog:
    """A catalog of MES, of which the fixtures hold nothing, and ES, whose history it starts on
    `es_history_from`."""
    return parse_catalog(
        f"""\
version: 7
products:
  - root: MES
    calendar: cme-equity-index
    roll_rule: volume
    schemas: [ohlcv-1m]
    history_from: 2019-05-06
    sources: [kibot, databento]
  - root: ES
    calendar: cme-equity-index
    roll_rule: volume
    schemas: [trades, ohlcv-1s, ohlcv-1m]
    history_from: {es_history_from}
    sources: [databento]
"""
    )


def copied_fixtures(folder: Path) -> Store:
    ignored = shutil.ignore_patterns("databento-batch")
    shutil.copytree(SYNTHETIC, folder / "synthetic", ignore=ignored)
    return Store(folder)


def recorded(store: Store, folder: Path, name: str, day: date, roots: tuple[str, ...]) -> None:
    """A raw file of the provider `synthetic`, imported on `day` and feeding `roots`."""
    source = folder / name
    source.write_bytes(name.encode())
    path = PurePosixPath("synthetic", "job", name)
    store.raw.write(path, source, hashlib.sha256(name.encode()).hexdigest())
    store.raw.record(
        path,
        provider="synthetic",
        vendor_version="synthetic",
        downloaded_on=day,
        batch_job=None,
        imported_on=day,
        roots=roots,
    )


def test_a_product_whose_data_starts_with_its_history_is_complete_at_each_fidelity(
    tmp_path: Path,
) -> None:
    status = product_status(FIXTURES, tmp_path / "reports", catalog_of_mes_and_es(MARCH_5))

    assert status.schema == STATUS_COLUMNS
    assert status.select(*LISTED, "last_trade_date", "quality").rows() == [
        ("MES", "missing", None, None, None, None, None, None),
        *(
            ("ES", "complete", "synthetic", schema, fidelity, MARCH_5, MARCH_9, "unchecked")
            for schema, fidelity in SCHEMAS
        ),
        *(
            (
                "BTCUSDT-PERP",
                "unlisted",
                "synthetic",
                schema,
                fidelity,
                MARCH_7,
                MARCH_7,
                "unchecked",
            )
            for schema, fidelity in SCHEMAS
        ),
    ]


def test_a_product_whose_data_starts_after_its_history_is_partial(tmp_path: Path) -> None:
    catalog = catalog_of_mes_and_es(date(2026, 3, 2))

    status = product_status(FIXTURES, tmp_path / "reports", catalog)

    es = status.filter(pl.col("root") == "ES").select("coverage", "history_from").unique()
    assert es.rows() == [("partial", date(2026, 3, 2))]


def test_a_missing_product_names_its_first_recommended_source(tmp_path: Path) -> None:
    status = product_status(FIXTURES, tmp_path / "reports", catalog_of_mes_and_es(MARCH_5))

    recommended = dict(status.select("root", "recommended_source").unique().rows())
    assert recommended == {"MES": "Kibot", "ES": "Databento", "BTCUSDT-PERP": None}


def test_each_dataset_shows_its_origin_and_licence_scope(tmp_path: Path) -> None:
    status = product_status(FIXTURES, tmp_path / "reports", catalog_of_mes_and_es(MARCH_5))

    held = status.filter(pl.col("provider").is_not_null()).select("origin", "licence_scope")
    assert held.unique().rows() == [
        ("import", "Synthetic data of scripts/gen_fixtures.py; no licence applies")
    ]


def test_the_last_import_is_the_newest_file_of_the_provider_that_fed_the_root(
    tmp_path: Path,
) -> None:
    store = copied_fixtures(tmp_path)
    recorded(store, tmp_path, "first.dbn", date(2026, 10, 13), ("ES",))
    recorded(store, tmp_path, "second.dbn", date(2026, 10, 15), ("ES",))
    recorded(store, tmp_path, "condition.json", date(2026, 10, 16), ())

    status = product_status(store, tmp_path / "reports", catalog_of_mes_and_es(MARCH_5))

    imports = dict(status.select("root", "last_import").unique().rows())
    assert imports == {"MES": None, "ES": date(2026, 10, 15), "BTCUSDT-PERP": None}


def test_a_report_older_than_its_dataset_is_stale(tmp_path: Path) -> None:
    store = copied_fixtures(tmp_path / "store")
    reports = tmp_path / "store" / "reports"
    write_quality_report(assess_quality(store, "synthetic", "ES", tmp_path / "cache"), reports)
    trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
    march_9 = Partition(dataset=trades, contract="ESH2026", key=MARCH_9)
    march_10 = Partition(dataset=trades, contract="ESH2026", key=date(2026, 3, 10))
    store.write_partition(march_10, store.scan_partition(march_9).collect())

    status = product_status(store, reports, catalog_of_mes_and_es(MARCH_5))

    es = status.filter(pl.col("root") == "ES").select("schema", "quality", "checked_through")
    assert es.rows() == [
        ("ohlcv-1m", "clean", MARCH_9),
        ("ohlcv-1s", "clean", MARCH_9),
        ("trades", "stale", MARCH_9),
    ]


def written_at(path: Path, nanoseconds: int) -> None:
    """Give `path` the time a write at `nanoseconds` since the Unix epoch would have given it."""
    os.utime(path, ns=(nanoseconds, nanoseconds))


def test_a_report_older_than_a_backfill_of_its_dataset_is_stale_until_written_again(
    tmp_path: Path,
) -> None:
    # Step 5.1 (from `BACKLOG.md`): a session imported before the data's first leaves the last
    # trade date the report checked through as it was, so only the files' times tell that the
    # report never read it. The times are set, since Windows' clock can give two writes one time.
    store = copied_fixtures(tmp_path / "store")
    reports = tmp_path / "store" / "reports"
    cache = tmp_path / "cache"
    folder = write_quality_report(assess_quality(store, "synthetic", "ES", cache), reports)
    days = folder / DAYS_FILE_NAME
    copied = max(path.stat().st_mtime_ns for path in store.folder.rglob("part.parquet"))
    written_at(days, copied + MINUTE)
    trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
    march_4 = Partition(dataset=trades, contract="ESH2026", key=date(2026, 3, 4))
    march_5 = store.scan_partition(Partition(dataset=trades, contract="ESH2026", key=MARCH_5))
    store.write_partition(
        march_4,
        march_5.collect().with_columns(pl.col("ts_recv") - DAY, pl.col("ts_event") - DAY),
    )
    written_at(store.folder / march_4.relative_path(), copied + 2 * MINUTE)

    backfilled = product_status(store, reports, catalog_of_mes_and_es(MARCH_5))
    write_quality_report(assess_quality(store, "synthetic", "ES", cache), reports)
    written_at(days, copied + 3 * MINUTE)
    checked_again = product_status(store, reports, catalog_of_mes_and_es(MARCH_5))

    es = pl.col("root") == "ES"
    shown = ("schema", "first_trade_date", "quality", "checked_through")
    assert backfilled.filter(es).select(shown).rows() == [
        ("ohlcv-1m", MARCH_5, "clean", MARCH_9),
        ("ohlcv-1s", MARCH_5, "clean", MARCH_9),
        ("trades", date(2026, 3, 4), "stale", MARCH_9),
    ]
    assert checked_again.filter(es).get_column("quality").to_list() == ["clean"] * 3


@pytest.mark.parametrize(
    ("fidelity", "words"),
    [
        ("trades", "trades"),
        ("tbbo", "tbbo"),
        ("1s", "1-second"),
        ("1m", "1-minute"),
        ("5m", "5-minute"),
        ("1d", "1-day"),
    ],
)
def test_a_fidelity_reads_as_words(fidelity: str, words: str) -> None:
    assert fidelity_in_words(fidelity) == words


def test_a_flagged_report_older_than_its_dataset_stays_flagged(tmp_path: Path) -> None:
    # The 101st trade of ESH2026 on 2026-03-05 repeated right after itself is a finding.
    store = copied_fixtures(tmp_path / "store")
    reports = tmp_path / "store" / "reports"
    trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
    march_5 = Partition(dataset=trades, contract="ESH2026", key=MARCH_5)
    rows = store.scan_partition(march_5).collect()
    store.write_partition(march_5, pl.concat([rows.head(101), rows.slice(100)]))
    write_quality_report(assess_quality(store, "synthetic", "ES", tmp_path / "cache"), reports)
    march_9 = Partition(dataset=trades, contract="ESH2026", key=MARCH_9)
    march_10 = Partition(dataset=trades, contract="ESH2026", key=date(2026, 3, 10))
    store.write_partition(march_10, store.scan_partition(march_9).collect())

    status = product_status(store, reports, catalog_of_mes_and_es(MARCH_5))

    es = status.filter(pl.col("root") == "ES").select("schema", "quality", "checked_through")
    assert es.rows() == [
        ("ohlcv-1m", "flagged", MARCH_9),
        ("ohlcv-1s", "flagged", MARCH_9),
        ("trades", "flagged", MARCH_9),
    ]
