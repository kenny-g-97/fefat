"""The data catalog's routes of step 5.1 (D-93, `01-architecture.md` sections 6 and 7): what the
store in the data folder holds, read through the SDK at each request, and the catalog sync, the
quality reports as a job, behind the login. Done means 1: the datasets list with their trade dates
and fidelity."""

import os
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from fastapi.testclient import TestClient

from fefat.config import resolve_paths
from fefat.market.calendar_definition import CalendarId
from fefat.market.catalog import CATALOG
from fefat.market.instruments import Currency, Instrument, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.layout import Dataset, Partition
from fefat.market.quality import assess_quality
from fefat.market.quality_report import (
    FINDING_COLUMNS,
    stored_coverage_by_month,
    write_quality_report,
)
from fefat.market.saved_instruments import save_instrument
from fefat.market.schema import parse_schema_name
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from generated_minutes import listing, write_minutes
from local_server import logged_in
from notebook_runs import store_with

PROBLEM = "application/problem+json"
DEADLINE_SECONDS = 60
SYNTHETIC_LICENCE = "Synthetic data of scripts/gen_fixtures.py; no licence applies"
ES_TRADES = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
A_NEW_PRODUCT = Instrument(
    root="XES",
    kind=InstrumentKind.FUTURES,
    tick_size=Decimal("0.5"),
    point_value=Decimal(25),
    lot_step=Decimal(1),
    currency=Currency.EUR,
    calendar=CalendarId.CME_EQUITY_INDEX,
    last_trade_rule=ThirdFriday(),
    valid_from=date(2026, 3, 5),
    valid_to=None,
    sources=("profile xes-5m",),
)


def test_the_datasets_list_each_with_its_trade_dates_fidelity_and_quality(
    client: TestClient, container: Container
) -> None:
    # Done means 1, on the synthetic fixtures: each dataset with its range and fidelity.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    logged_in(client, container)

    response = client.get("/v1/datasets")

    listed = response.json()
    assert response.status_code == 200
    assert [
        (each["id"], each["first_trade_date"], each["last_trade_date"], each["fidelity"])
        for each in listed
    ] == [
        ("synthetic:ohlcv-1m:BTCUSDT-PERP", "2026-03-07", "2026-03-07", "1m"),
        ("synthetic:ohlcv-1s:BTCUSDT-PERP", "2026-03-07", "2026-03-07", "1s"),
        ("synthetic:trades:BTCUSDT-PERP", "2026-03-07", "2026-03-07", "trades"),
        ("synthetic:ohlcv-1m:ES", "2026-03-05", "2026-03-09", "1m"),
        ("synthetic:ohlcv-1s:ES", "2026-03-05", "2026-03-09", "1s"),
        ("synthetic:trades:ES", "2026-03-05", "2026-03-09", "trades"),
    ]
    assert listed[3] == {
        "id": "synthetic:ohlcv-1m:ES",
        "provider": "synthetic",
        "root": "ES",
        "schema_name": "ohlcv-1m",
        "fidelity": "1m",
        "contracts": 2,
        "first_trade_date": "2026-03-05",
        "last_trade_date": "2026-03-09",
        "quality": "unchecked",
        "checked_through": None,
        "origin": "import",
        "licence_scope": SYNTHETIC_LICENCE,
        "last_import": None,
    }


def test_a_datasets_quality_flows_from_its_roots_report_with_every_schemas_findings(
    client: TestClient, container: Container
) -> None:
    # The 101st trade of ESH2026 on 2026-03-05 repeated right after itself is a finding of the
    # trades, which flags the root's report, and so its bars too, which show the finding.
    store_with("trades", "ohlcv-1m")
    logged_in(client, container)
    unchecked = client.get("/v1/datasets/synthetic:trades:ES/quality").json()
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    march_5 = Partition(dataset=ES_TRADES, contract="ESH2026", key=date(2026, 3, 5))
    rows = store.scan_partition(march_5).collect()
    store.write_partition(march_5, pl.concat([rows.head(101), rows.slice(100)]))
    write_quality_report(
        assess_quality(store, "synthetic", "ES", paths.cache_dir), paths.reports_dir
    )

    of_trades = client.get("/v1/datasets/synthetic:trades:ES/quality").json()
    of_minutes = client.get("/v1/datasets/synthetic:ohlcv-1m:ES/quality").json()
    listed = {each["id"]: each["quality"] for each in client.get("/v1/datasets").json()}

    duplicate = {
        "trade_date": "2026-03-05",
        "kind": "duplicates",
        "schema_name": "trades",
        "contract": "ESH2026",
        "count": 1,
    }
    # Step 5.4: the report's coverage by month, as the SDK reads it back.
    march = {
        "month": "2026-03",
        "sessions": 3,
        "with_records": 3,
        "tick_days": 3,
        "second_days": 0,
        "minute_days": 3,
        "findings": 1,
        "vendor_flagged": 0,
    }
    assert stored_coverage_by_month(paths.reports_dir, "synthetic", "ES").to_dicts() == [march]
    assert unchecked == {
        "id": "synthetic:trades:ES",
        "quality": "unchecked",
        "checked_through": None,
        "findings": [],
        "findings_total": 0,
        "months": [],
    }
    assert of_trades == {
        "id": "synthetic:trades:ES",
        "quality": "flagged",
        "checked_through": "2026-03-09",
        "findings": [duplicate],
        "findings_total": 1,
        "months": [march],
    }
    assert of_minutes == {**of_trades, "id": "synthetic:ohlcv-1m:ES"}
    assert (listed["synthetic:trades:ES"], listed["synthetic:ohlcv-1m:ES"]) == (
        "flagged",
        "flagged",
    )


def test_a_datasets_quality_lists_the_first_200_findings_with_how_many_there_are(
    client: TestClient, container: Container
) -> None:
    # Step 5.1's review: a report of 250 findings lists its first 200 (`FINDINGS_SHOWN`).
    store_with("trades")
    logged_in(client, container)
    paths = resolve_paths(os.environ)
    assessed = assess_quality(Store(paths.data_dir), "synthetic", "ES", paths.cache_dir)
    many = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 250,
            "kind": ["duplicates"] * 250,
            "schema": ["trades"] * 250,
            "contract": ["ESH2026"] * 250,
            "count": range(1, 251),
        },
        schema=FINDING_COLUMNS,
    )
    write_quality_report(replace(assessed, findings=many), paths.reports_dir)

    quality = client.get("/v1/datasets/synthetic:trades:ES/quality").json()

    assert quality["findings_total"] == 250
    assert [each["count"] for each in quality["findings"]] == list(range(1, 201))


@pytest.mark.parametrize(
    "dataset_id",
    [
        "synthetic:trades:ZZ",
        "databento:trades:ES",
        "synthetic:ohlcv-5m:ES",
        "synthetic:funding:BTCUSDT-PERP",
        "synthetic:nonsense:ES",
        "synthetic:trades",
        "a:b:c:d",
    ],
)
def test_an_id_that_names_no_dataset_the_store_holds_is_a_problem(
    client: TestClient, container: Container, dataset_id: str
) -> None:
    store_with("trades", "funding")
    logged_in(client, container)

    refused = client.get(f"/v1/datasets/{dataset_id}/quality")

    assert (refused.status_code, refused.headers["content-type"]) == (404, PROBLEM)
    assert refused.json()["detail"] == (
        "Expected the id of a dataset the store holds, provider:schema:root such as "
        f"synthetic:trades:ES, got {dataset_id!r}."
    )


def test_the_catalog_gives_each_product_the_datasets_that_cover_it_then_the_unlisted(
    client: TestClient, container: Container
) -> None:
    # MES's minutes start with its history, MNQ's four weeks after; MCL and MGC are missing,
    # and the fixtures' ES and bitcoin are no product of the catalog.
    store_with("ohlcv-1m")
    days = ("2019-05-06", "2019-05-07")
    write_minutes((listing("MESM2019", 4001, days, days),), root="MES")
    later = ("2019-06-03", "2019-06-04")
    write_minutes((listing("MNQM2019", 4101, later, later),), root="MNQ")
    logged_in(client, container)

    catalog = client.get("/v1/catalog").json()

    products = {product["root"]: product for product in catalog["products"]}
    assert catalog["version"] == CATALOG.version
    assert list(products) == ["MES", "MNQ", "MCL", "MGC"]
    assert (products["MES"]["history_from"], products["MES"]["recommended_source"]) == (
        "2019-05-06",
        "Databento",
    )
    assert [
        (each["id"], each["coverage"], each["first_trade_date"], each["quality"])
        for root in ("MES", "MNQ")
        for each in products[root]["datasets"]
    ] == [
        ("synthetic:ohlcv-1m:MES", "complete", "2019-05-06", "unchecked"),
        ("synthetic:ohlcv-1m:MNQ", "partial", "2019-06-03", "unchecked"),
    ]
    assert (products["MCL"]["datasets"], products["MGC"]["datasets"]) == ([], [])
    assert [each["id"] for each in catalog["unlisted"]] == [
        "synthetic:ohlcv-1m:BTCUSDT-PERP",
        "synthetic:ohlcv-1m:ES",
    ]


def test_the_sources_are_the_source_guide_as_it_is(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    response = client.get("/v1/sources")

    assert response.status_code == 200
    assert response.json() == SOURCE_GUIDE.model_dump(mode="json")


def test_the_instruments_are_feats_and_those_an_import_saved(
    client: TestClient, container: Container
) -> None:
    save_instrument(resolve_paths(os.environ).data_dir, A_NEW_PRODUCT)
    logged_in(client, container)

    listed = client.get("/v1/instruments").json()

    by_root = {each["root"]: each for each in listed}
    assert [each["root"] for each in listed] == sorted(by_root)
    assert len(listed) == 13
    assert by_root["ES"] == {
        "root": "ES",
        "kind": "futures",
        "tick_size": 0.25,
        "point_value": 50.0,
        "lot_step": 1.0,
        "currency": "USD",
        "calendar": "cme-equity-index",
        "valid_from": "1997-09-09",
        "valid_to": None,
        "saved": False,
    }
    assert {name: by_root["XES"][name] for name in ("tick_size", "currency", "saved")} == {
        "tick_size": 0.5,
        "currency": "EUR",
        "saved": True,
    }
    assert by_root["BTCUSDT"]["lot_step"] == 0.00001


def test_a_catalog_sync_of_every_product_answers_queued_and_runs_in_the_pool_to_its_end(
    client: TestClient, container: Container
) -> None:
    # The one test of the sync's route that runs a worker of the pool.
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)

    started = client.post("/v1/catalog/sync", json={}, headers=csrf)
    job_id = started.json()["id"]
    deadline = time.monotonic() + DEADLINE_SECONDS
    ended = client.get(f"/v1/jobs/{job_id}").json()
    while ended["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.1)
        ended = client.get(f"/v1/jobs/{job_id}").json()

    clean = {"provider": "synthetic", "status": "clean", "findings": 0}
    assert started.status_code == 202
    assert {name: started.json()[name] for name in ("kind", "payload", "status")} == {
        "kind": "catalog_sync",
        "payload": {"root": None},
        "status": "queued",
    }
    assert (ended["status"], ended["progress"], ended["result"]) == (
        "succeeded",
        100.0,
        {"reports": [{**clean, "root": "BTCUSDT-PERP"}, {**clean, "root": "ES"}]},
    )
    assert client.get("/v1/datasets/synthetic:ohlcv-1m:ES/quality").json()["quality"] == "clean"


def test_a_sync_of_what_the_store_lacks_is_refused_and_queues_no_job(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    csrf = logged_in(client, container)
    of_an_empty_store = client.post("/v1/catalog/sync", json={}, headers=csrf)
    store_with("ohlcv-1m")

    of_an_unknown_root = client.post("/v1/catalog/sync", json={"root": "ZZ"}, headers=csrf)
    without_the_csrf_token = client.post("/v1/catalog/sync", json={"root": "ES"})

    refusals = (of_an_empty_store, of_an_unknown_root)
    assert [(each.status_code, each.headers["content-type"]) for each in refusals] == [
        (404, PROBLEM),
        (404, PROBLEM),
    ]
    assert [each.json()["detail"] for each in refusals] == [
        "Expected trades or bars of any product in the store, got none.",
        "Expected trades or bars of ZZ in the store, got none.",
    ]
    assert without_the_csrf_token.status_code == 403
    assert job_records.recent(10) == ()


def test_the_catalog_needs_a_login_and_an_api_token_is_one(
    client: TestClient, container: Container
) -> None:
    paths = ("/datasets", "/datasets/synthetic:trades:ES/quality", "/catalog")
    anonymous = [client.get(f"/v1{path}") for path in (*paths, "/sources", "/instruments")]
    anonymous_sync = client.post("/v1/catalog/sync", json={})
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    with_a_token = client.get("/v1/datasets", headers=bearer)
    sync_with_a_token = client.post("/v1/catalog/sync", json={}, headers=bearer)

    assert [each.status_code for each in (*anonymous, anonymous_sync)] == [401] * 6
    assert (with_a_token.status_code, with_a_token.json()) == (200, [])
    # An empty store holds nothing to sync: the token was let in, and the sync refused.
    assert sync_with_a_token.status_code == 404
