"""What the engine cache holds (`02` §1.6, D-56): each cached contract-month's `index.json`, as
`fefat-data` writes it, and the status of the whole cache, which `fefat cache status` prints:

    for month in engine_cache_status(resolve_paths(os.environ).cache_dir):
        print(month.summary())

`fefat.market.engine_cache` builds the months.
"""

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field

from fefat.market.fidelity import Fidelity, TickFidelity
from fefat.market.layout import YearMonth
from fefat.market.schema import FrozenModel, Timeframe
from fefat.market.snapshot import Sha256
from fefat.market.store_files import parsed_json

ENGINE_CACHE_FOLDER_NAME = "engine"
"""The engine cache's folder in `FEFAT_HOME/cache` (`fefat.config.FefatPaths.cache_dir`)."""
INDEX_FILE_NAME = "index.json"
LAYOUT_VERSION = 2
"""The layout `fefat-data` writes, and its rules for what a month keeps; a month of another layout
is rebuilt. 2 since step 2.7, which leaves out a finer level with a record outside the range of
the bar holding it."""
PARTIAL_SUFFIX = ".partial"
"""The suffix of a month folder being built, which readers pass over."""


def _month_of(value: object) -> object:
    return YearMonth.parse(value) if isinstance(value, str) else value


Month = Annotated[YearMonth, BeforeValidator(_month_of)]
"""A month as the index writes it, `2026-03`."""


class CachedSource(FrozenModel):
    """A store partition a month was built from: its path in the store and its SHA-256."""

    path: str
    sha256: Sha256


class CachedTradeDate(FrozenModel):
    """A trade date of a month: its levels, finest first, the records cut at and after the
    close of the last bar that holds them, and the levels left out, each with its reason."""

    trade_date: date
    levels: tuple[Fidelity, ...]
    cut: dict[Fidelity, int]
    left_out: dict[Fidelity, str]


class CachedFile(FrozenModel):
    """A file of a month: the rows of its batches and its size."""

    rows: int = Field(ge=0)
    bytes: int = Field(ge=0)


class CacheMonthIndex(FrozenModel):
    """A cached contract-month's `index.json`, as `fefat-data` writes it."""

    layout_version: int
    contract: str
    month: Month
    sources: tuple[CachedSource, ...]
    trade_dates: tuple[CachedTradeDate, ...]
    files: dict[str, CachedFile]

    def size_bytes(self) -> int:
        return sum(file.bytes for file in self.files.values())

    def levels_summary(self) -> str:
        """Each level with the trade dates that hold it, coarsest first: `1m 21 days, ...`."""
        days = Counter(level for trade_date in self.trade_dates for level in trade_date.levels)
        ordered = sorted(days.items(), key=lambda level_days: _coarsest_first(level_days[0]))
        return ", ".join(f"{level} {counted(count, 'day')}" for level, count in ordered)

    def notes(self) -> list[str]:
        """The records cut from each trade date and the levels left out of it."""
        notes: list[str] = []
        for day in self.trade_dates:
            if day.cut:
                cut = ", ".join(
                    f"{counted(count, 'record')} of {level}" for level, count in day.cut.items()
                )
                notes.append(f"{day.trade_date}: cut {cut} after the last bar that holds them")
            notes += [
                f"{day.trade_date}: left out {level}, since {reason}"
                for level, reason in day.left_out.items()
            ]
        return notes


def _coarsest_first(level: TickFidelity | Timeframe) -> tuple[int, int]:
    if isinstance(level, Timeframe):
        return (0, -level.nominal_seconds())
    return (1, 0 if level is TickFidelity.TRADES else 1)


def counted(count: int, noun: str) -> str:
    """`1 day`, `2 days`: a count with its noun."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def size_text(size_bytes: int) -> str:
    """A size in kB below a megabyte, else in MB with one decimal."""
    if size_bytes < 1_000_000:
        return f"{size_bytes / 1_000:.0f} kB"
    return f"{size_bytes / 1_000_000:.1f} MB"


def read_cache_month_index(month_folder: Path) -> CacheMonthIndex | None:
    """The index of a cached month, or None while the folder holds none."""
    path = month_folder / INDEX_FILE_NAME
    if not path.is_file():
        return None
    return parsed_json(CacheMonthIndex, path.read_bytes(), str(path))


class CachedMonth(FrozenModel):
    """A contract-month in the engine cache, with its provider and root."""

    provider: str
    root: str
    index: CacheMonthIndex

    def summary(self) -> str:
        """`<provider> <root> <contract> <month>: <level> <days>, ..., <size>`."""
        index = self.index
        place = f"{self.provider} {self.root} {index.contract} {index.month}"
        return f"{place}: {index.levels_summary()}, {size_text(index.size_bytes())}"


def engine_cache_status(cache_folder: Path, root: str | None = None) -> tuple[CachedMonth, ...]:
    """Each contract-month in the engine cache of `cache_folder`, or only `root`'s, with the
    levels of its trade dates, sorted by provider, root, contract, and month."""
    engine_folder = cache_folder / ENGINE_CACHE_FOLDER_NAME
    cached: list[CachedMonth] = []
    for path in sorted(engine_folder.glob(f"*/*/*/*/{INDEX_FILE_NAME}")):
        month_folder = path.parent
        root_folder = month_folder.parent.parent
        if month_folder.name.endswith(PARTIAL_SUFFIX) or root not in (None, root_folder.name):
            continue
        index = parsed_json(CacheMonthIndex, path.read_bytes(), str(path))
        provider = root_folder.parent.name
        cached.append(CachedMonth(provider=provider, root=root_folder.name, index=index))
    return tuple(cached)
