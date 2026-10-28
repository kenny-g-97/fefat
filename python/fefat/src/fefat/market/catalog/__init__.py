"""The product catalog (`02-engine-and-data.md` §1.8, D-37, D-38): the products FEFAT ships the
know-how for, each naming its instrument (`fefat.market.instruments`), its session calendar
(`fefat.market.builtin_calendars`), its roll rule (`fefat.market.continuous`), the schemas its
sources supply, the day its history starts, and the sources of the guide
(`fefat.market.sources`) that can supply it, in order of recommendation. FEFAT ships no data
(D-37): `fefat data status` shows how much of each product the trader's own files cover.

The catalog is `catalog.yaml` beside this module, and its `version` grows with each change:

    from fefat.market.catalog import CATALOG
    CATALOG.roots()

The data API's `catalog()`, `ff.market.catalog()`, lists the datasets in the store; import this
package's names with `from fefat.market.catalog import ...`, since `import fefat.market.catalog
as ...` gives that function.
"""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, model_validator

from fefat.market.calendar_definition import CalendarId
from fefat.market.instruments import STATIC_TABLE, InstrumentTable
from fefat.market.layout import FolderName
from fefat.market.schema import FrozenModel, SchemaName
from fefat.market.sources import SOURCE_GUIDE, SourceGuide

CATALOG_FILE_NAME = "catalog.yaml"


class RollRule(StrEnum):
    """How a product's continuous series picks its front contract (`fefat.market.continuous`):
    by volume, by open interest, or a set number of sessions before the last trade date."""

    VOLUME = "volume"
    OPEN_INTEREST = "open-interest"
    CALENDAR = "calendar"


class CatalogProduct(FrozenModel):
    """A product of the catalog: its root in the instrument table, its calendar, its roll rule,
    the schemas its sources supply, the first trade date of its history, and the ids of the
    sources that can supply it, the recommended one first."""

    root: FolderName
    calendar: CalendarId
    roll_rule: RollRule
    schemas: tuple[SchemaName, ...] = Field(min_length=1)
    history_from: date
    sources: tuple[str, ...] = Field(min_length=1)

    def require_known(self, instruments: InstrumentTable, guide: SourceGuide) -> None:
        """Refuse the product unless its root is an instrument of the table on the calendar
        it names, its history starts on or after the root's first trade date, and the guide
        holds each of its sources."""
        calendar = instruments.get(self.root).calendar
        if self.calendar != calendar:
            raise ValueError(
                f"Expected the calendar of {self.root}, {calendar}, got {self.calendar}."
            )
        first_trade_date = instruments.first_trade_date(self.root)
        if self.history_from < first_trade_date:
            raise ValueError(
                f"Expected the history of {self.root} from {first_trade_date}, when it began "
                f"trading, or later, got {self.history_from}."
            )
        known = {source.id for source in guide.sources}
        unknown = [source for source in self.sources if source not in known]
        if unknown:
            raise ValueError(
                f"Expected the sources of {self.root} in the guide, got {', '.join(unknown)}, "
                "which it lacks."
            )


class Catalog(FrozenModel):
    """The catalog's products in the order `fefat data status` lists them, at a version."""

    version: int = Field(ge=1)
    products: tuple[CatalogProduct, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _lists_each_product_once(self) -> Self:
        roots = [product.root for product in self.products]
        repeated = sorted({root for root in roots if roots.count(root) > 1})
        if repeated:
            raise ValueError(
                f"Expected each product listed once, got {', '.join(repeated)} more than once."
            )
        return self

    def roots(self) -> tuple[str, ...]:
        """The products' roots, in catalog order."""
        return tuple(product.root for product in self.products)

    def roll_rule(self, root: str) -> RollRule:
        """The roll rule of `root`: its product's, and for a root the catalog does not list,
        volume, the default rule of continuous series (D-44)."""
        named = [product.roll_rule for product in self.products if product.root == root]
        return named[0] if named else RollRule.VOLUME


def parse_catalog(
    text: str, instruments: InstrumentTable = STATIC_TABLE, guide: SourceGuide = SOURCE_GUIDE
) -> Catalog:
    """The catalog written as YAML in `text`, validated against the instrument table and the
    source guide."""
    catalog = Catalog.model_validate(yaml.safe_load(text))
    for product in catalog.products:
        product.require_known(instruments, guide)
    return catalog


def load_catalog(
    path: Path, instruments: InstrumentTable = STATIC_TABLE, guide: SourceGuide = SOURCE_GUIDE
) -> Catalog:
    """The catalog in the YAML file at `path`, validated; a file that is no catalog is refused
    with its path."""
    try:
        return parse_catalog(path.read_text(encoding="utf-8"), instruments, guide)
    except (ValueError, yaml.YAMLError) as error:
        raise ValueError(f"Expected {path} to hold the product catalog, got: {error}") from error


CATALOG = load_catalog(Path(__file__).with_name(CATALOG_FILE_NAME))
"""The catalog FEFAT ships, read from `catalog.yaml` beside this module."""
