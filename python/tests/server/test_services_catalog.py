"""The catalog sync of step 5.1 over the jobs' records and a dispatcher that runs nothing: a sync
that a queued or running sync of the same product, or of every product, covers gives that job
rather than queueing a second, which would write the same reports at once; a sync of one product
covers no other, and one asked to stop, or cancelled, covers nothing."""

import os
from datetime import timedelta

import pytest

from fefat.config import resolve_paths
from fefat.market.store import Store
from fefat_app.database.job_records import JobTables
from fefat_app.services.catalog import MarketCatalog
from fefat_app.services.jobs import Jobs
from local_server import STARTED_AT, RecordingDispatcher, SettableClock
from notebook_runs import store_with

WORKER = 4242


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def jobs(job_records: JobTables, dispatcher: RecordingDispatcher, clock: SettableClock) -> Jobs:
    return Jobs(job_records, dispatcher, clock)


@pytest.fixture
def catalog(jobs: Jobs) -> MarketCatalog:
    """The catalog over a store of the synthetic trades and minutes of ES and bitcoin."""
    store_with("trades", "ohlcv-1m")
    paths = resolve_paths(os.environ)
    return MarketCatalog(Store(paths.data_dir), paths.reports_dir, paths.cache_dir, jobs)


def test_a_sync_that_a_queued_one_covers_gives_that_job(
    catalog: MarketCatalog, dispatcher: RecordingDispatcher
) -> None:
    of_every_product = catalog.start_sync(None)

    again = catalog.start_sync(None)
    of_es = catalog.start_sync("ES")

    assert again == of_every_product
    assert of_es == of_every_product
    assert dispatcher.calls == [f"submit {of_every_product.id}"]


def test_a_sync_of_one_product_covers_no_other(
    catalog: MarketCatalog, dispatcher: RecordingDispatcher
) -> None:
    of_es = catalog.start_sync("ES")

    of_bitcoin = catalog.start_sync("BTCUSDT-PERP")
    of_every_product = catalog.start_sync(None)

    queued = (of_es, of_bitcoin, of_every_product)
    assert len({job.id for job in queued}) == 3
    assert dispatcher.calls == [f"submit {job.id}" for job in queued]


def test_a_running_sync_covers_and_one_asked_to_stop_or_cancelled_does_not(
    catalog: MarketCatalog, jobs: Jobs, job_records: JobTables
) -> None:
    first = catalog.start_sync("ES")
    job_records.start(first.id, WORKER, STARTED_AT + timedelta(seconds=15), STARTED_AT)

    while_it_runs = catalog.start_sync("ES")
    jobs.cancel(first.id)
    once_it_is_asked_to_stop = catalog.start_sync("ES")
    jobs.cancel(once_it_is_asked_to_stop.id)
    once_that_is_cancelled = catalog.start_sync("ES")

    assert while_it_runs.id == first.id
    assert len({first.id, once_it_is_asked_to_stop.id, once_that_is_cancelled.id}) == 3
