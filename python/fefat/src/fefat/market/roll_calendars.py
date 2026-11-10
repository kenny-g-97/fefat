"""The roll calendar a spliced load follows (`fefat.market.api`, step 2.9, D-44), kept in memory
per dataset of a store's folder while what it is built from keeps its stamp (step 3.3, D-71), so
that the loads of a run and the partitions of the feature cache build it once."""

from datetime import date

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.catalog import CATALOG, RollRule
from fefat.market.continuous import RollCalendar, volume_rolls
from fefat.market.dataset_choice import roll_dataset
from fefat.market.instruments import Instrument
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.store import Store

_KEPT_ROLL_CALENDARS: dict[tuple[str, Dataset], tuple[object, RollCalendar]] = {}
"""The roll calendar last built in this process from each dataset of a store's folder, with the
stamp of what it was built from (`kept_roll_calendar`)."""


def kept_roll_calendar(
    store: Store, datasets: dict[str, Dataset], instrument: Instrument, sessions: SessionTable
) -> RollCalendar:
    """The root's roll calendar, from the 1-minute bars of its whole dataset, or else its
    finest bars (an import's 5-minute bars), whatever the window, and from its first whole
    session: the bars of a first session the data starts inside are left out, since their
    volumes are partial. It rolls by volume, the only rule load applies, and a product the
    catalog gives another rule is refused rather than rolled by volume (step 2.9). It is built once in a process while what it reads keeps its stamp: the
    dataset's partitions by path, size, and modification time, the instrument, and the session
    table's key (D-71)."""
    rule = CATALOG.roll_rule(instrument.root)
    if rule is not RollRule.VOLUME:
        raise ValueError(
            f"Expected the roll rule volume for {instrument.root}, the only rule load applies, "
            f"got {rule} in the product catalog (fefat.market.catalog)."
        )
    dataset = roll_dataset(datasets, instrument.root)
    place = (str(store.folder), dataset)
    stamp = (_listing_stamp(store, dataset), instrument.model_dump_json(), sessions.key)
    kept = _KEPT_ROLL_CALENDARS.get(place)
    if kept is not None and kept[0] == stamp:
        return kept[1]
    calendar = _built_roll_calendar(store, dataset, instrument, sessions)
    _KEPT_ROLL_CALENDARS[place] = (stamp, calendar)
    return calendar


def _listing_stamp(store: Store, dataset: Dataset) -> tuple[tuple[str, int, int], ...]:
    """Each partition of the dataset by path, size, and modification time, as the store lists
    it, which a write changes."""
    return tuple(
        (file.partition.relative_path().as_posix(), file.size_bytes, file.modified_ns)
        for file in store.list_partitions(dataset)
    )


def _built_roll_calendar(
    store: Store, dataset: Dataset, instrument: Instrument, sessions: SessionTable
) -> RollCalendar:
    """The roll calendar of `kept_roll_calendar`, built from `dataset`'s bars."""
    request = PartitionRequest(dataset=dataset, start=date.min, end=date.max)
    bars = store.scan_contracts(request).collect()
    first_day, first_open, received_until = bars.select(
        pl.col("trade_date").min(), pl.col("ts_open").min(), pl.col("ts_close").max()
    ).row(0)
    if first_open > sessions.session(first_day).open:
        bars = bars.filter(pl.col("trade_date") > first_day)
    return volume_rolls(bars, sessions, instrument, received_until)
