"""What `load` reads a symbol's bars from, built for a store the caller names (step 5.1, from
`BACKLOG.md`): the app's services hold the store the container built, while a notebook's `load`
reads the store `FEFAT_DATA_DIR` names."""

import pickle
import shutil
from datetime import date
from pathlib import Path

import pytest

from fefat.market.schema import Timeframe
from fefat.market.series_source import UnknownSymbolError, series_source, series_source_in
from fefat.market.store import ListedStore, Store

SYNTHETIC = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
MARCH_6 = date(2026, 3, 6)


def store_elsewhere(folder: Path) -> Store:
    """A store of the fixtures' 1-minute bars in `folder`, which no variable names."""
    shutil.copytree(SYNTHETIC / "ohlcv-1m", folder / "synthetic" / "ohlcv-1m")
    return Store(folder)


def test_a_source_built_for_a_store_reads_that_store_whatever_the_environment_names(
    tmp_path: Path,
) -> None:
    # The environment's data folder, from the tests' conftest, holds nothing.
    store = store_elsewhere(tmp_path / "elsewhere")

    source = series_source_in(store, tmp_path / "cache", "ES")
    bars = source.signal_bars(Timeframe.parse("5m"), (MARCH_6, MARCH_6))

    assert (bars.height, source.provider) == (276, "synthetic")
    with pytest.raises(ValueError, match="Expected one provider of ES in the store, got none"):
        series_source("ES")


def test_a_source_keeps_its_own_listing_of_the_store(tmp_path: Path) -> None:
    # A request lists each dataset once, however many times its load reads the listing.
    store = store_elsewhere(tmp_path / "elsewhere")

    source = series_source_in(store, tmp_path / "cache", "ESH2026")

    assert isinstance(source.store, ListedStore)
    assert source.store.folder == store.folder
    assert source.contract == "ESH2026"


@pytest.mark.parametrize("symbol", ["ZZ", "ZZH2026", ""])
def test_a_symbol_that_names_no_root_and_no_contract_of_one_is_unknown(
    tmp_path: Path, symbol: str
) -> None:
    store = store_elsewhere(tmp_path / "elsewhere")

    with pytest.raises(UnknownSymbolError, match=f"or a contract such as MESH2024, got '{symbol}'"):
        series_source_in(store, tmp_path / "cache", symbol)


def test_an_unknown_symbol_crosses_a_process_whole(tmp_path: Path) -> None:
    # Step 5.1's review: a notebook's pool of loads sends its workers' errors back pickled, and
    # an error its pickle cannot rebuild breaks the pool instead of saying which symbol.
    store = store_elsewhere(tmp_path / "elsewhere")
    with pytest.raises(UnknownSymbolError) as refused:
        series_source_in(store, tmp_path / "cache", "ESX")

    again = pickle.loads(pickle.dumps(refused.value))

    assert (type(again), str(again)) == (UnknownSymbolError, str(refused.value))
