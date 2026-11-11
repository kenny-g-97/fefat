"""The catalog sync (step 5.1, `01-architecture.md` section 6, D-93): the quality report of a
product, or of every product the store holds, written as `fefat data quality` writes it, one
provider's report of a root after another, each a report of the job's progress, between which
the job reads a request to stop. Until the connectors (D-38), it is a product's Update."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from fefat.market.calendar import counted
from fefat.market.layout import FolderName
from fefat.market.quality import assess_quality, reported_products
from fefat.market.quality_report import write_quality_report
from fefat.market.store import Store
from fefat_app.jobs.progress import JobProgress


class CatalogSyncPayload(BaseModel):
    """The product whose reports a sync writes, such as `MES`; every product the store holds
    where it is None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: FolderName | None = None


def run_catalog_sync(
    store: Store,
    reports_folder: Path,
    cache_folder: Path,
    payload: Mapping[str, Any],
    progress: JobProgress,
) -> dict[str, Any]:
    """Write the quality report of each provider's data of the payload's product, or of every
    product, into `reports_folder`, the session tables cached in `cache_folder`, reporting before
    each and once all are written, since a job's progress stays as its last report set it; each
    report's provider, root, status, and count of findings."""
    root = CatalogSyncPayload.model_validate(payload).root
    products = reported_products(store, root)
    written: list[dict[str, Any]] = []
    for done, (provider, product) in enumerate(products):
        message = f"Checking the quality of {provider} {product}"
        progress.advance(100 * done / len(products), message, provider=provider, root=product)
        report = assess_quality(store, provider, product, cache_folder)
        write_quality_report(report, reports_folder)
        status, findings = str(report.status()), report.findings.height
        written.append(
            {"provider": provider, "root": product, "status": status, "findings": findings}
        )
    progress.advance(100, f"Checked {counted(len(products), 'report')}")
    return {"reports": written}
