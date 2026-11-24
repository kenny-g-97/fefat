"""What a run of a window would read, told before anything runs (step 5.6, D-113): the sessions,
bars, and ticks the engine replays, each session on the finest level at or coarser than the run's
fidelity, of the contract the run reads that day; the same split a saved run's fidelity eras
record; and a window without data, which answers zero rather than refuses."""

import os
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
import gen_fixtures
from fefat.backtest import RunConfig, estimates
from fefat.backtest.estimates import WindowEstimate, estimated, held_instruments
from fefat.backtest.record import Window
from fefat.config import resolve_paths
from fefat.market.fees import CryptoFee, FeeChoice, FuturesFee
from fefat.market.fidelity import ONE_MINUTE, ONE_SECOND, TickFidelity
from fefat.market.instruments import Currency
from fefat.market.layout import Dataset, Partition, PartitionRequest
from fefat.market.schema import Timeframe, parse_schema_name
from fefat.market.series_source import SeriesSource, series_source_in
from fefat.market.store import Store
from notebook_runs import breakout, store_with

FIVE_MINUTES = Timeframe.parse("5m")
FIRST, LAST = date(2026, 3, 5), date(2026, 3, 9)


def estimate_of(
    config: RunConfig | None = None,
    start: date | None = FIRST,
    end: date | None = LAST,
) -> WindowEstimate:
    found = estimated(
        "ES",
        FIVE_MINUTES,
        start,
        end,
        RunConfig() if config is None else config,
        resolve_paths(os.environ),
    )
    assert found is not None
    return found


def counts(estimate: WindowEstimate) -> tuple[int, int, int]:
    return estimate.sessions, estimate.bars, estimate.ticks


def table_names(estimate: WindowEstimate) -> tuple[str, ...]:
    return tuple(choice.name for choice in estimate.fee_tables)


def stored(schema: str, contract: str, first: date, last: date) -> int:
    """How many records the store holds of `contract` in `schema` on the trade dates given."""
    store = Store(resolve_paths(os.environ).data_dir)
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root="ES")
    rows = store.scan_contracts(PartitionRequest(dataset=dataset, start=first, end=last))
    held: int = rows.filter(pl.col("contract") == contract).select(pl.len()).collect().item()
    return held


def test_an_estimate_counts_each_sessions_front_under_the_fidelity() -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    friday, monday = date(2026, 3, 6), date(2026, 3, 9)

    finest = estimate_of()
    seconds = estimate_of(RunConfig(fidelity=ONE_SECOND))
    minutes = estimate_of(RunConfig(fidelity=ONE_MINUTE))

    # The roll calendar decides a front from the session before, so the series starts on 03-06.
    assert finest.held == finest.window == Window(start=friday, end=monday)
    assert counts(finest) == (
        2,
        0,
        stored("trades", "ESH2026", friday, friday) + stored("trades", "ESM2026", monday, monday),
    )
    assert counts(seconds) == (
        2,
        stored("ohlcv-1s", "ESH2026", friday, friday)
        + stored("ohlcv-1s", "ESM2026", monday, monday),
        0,
    )
    assert counts(minutes) == (
        2,
        stored("ohlcv-1m", "ESH2026", friday, friday)
        + stored("ohlcv-1m", "ESM2026", monday, monday),
        0,
    )
    assert (str(finest.settings.fidelity), str(seconds.settings.fidelity)) == ("trades", "1s")
    assert finest.levels == ("trades", "1s", "1m")
    assert finest.contracts == ("ESH2026", "ESM2026")
    assert finest.providers == ("synthetic",)
    assert table_names(finest) == ("retail-default", "prop-topstep")


def test_an_estimate_splits_bars_and_ticks_as_a_saved_runs_fidelity_eras() -> None:
    synthetic = resolve_paths(os.environ).data_dir / "synthetic"
    dates = ["--dates", "2026-03-02..2026-03-13", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(synthetic), *dates, "--ticks-from", "2026-03-10"]) == 0
    run = ff.backtest.run(breakout(), "2026-03-02", "2026-03-13")
    minutes, ticks = run.record.fidelity_eras

    estimate = estimate_of(start=date(2026, 3, 2), end=date(2026, 3, 13))

    assert (str(minutes.fidelity), str(ticks.fidelity)) == ("1m", "trades")
    assert estimate.window == run.record.window
    assert estimate.sessions == minutes.trade_dates + ticks.trade_dates
    assert estimate.bars == stored("ohlcv-1m", "ESH2026", minutes.first, minutes.last)
    assert estimate.ticks == stored("trades", "ESH2026", ticks.first, ticks.last)


def test_a_named_contract_is_counted_unspliced() -> None:
    store_with("trades", "ohlcv-1m")

    estimate = estimate_of(RunConfig(contract="ESH2026"))

    assert estimate.held == Window(start=FIRST, end=LAST)
    assert counts(estimate) == (3, 0, stored("trades", "ESH2026", FIRST, LAST))


def test_a_contract_of_another_root_is_refused() -> None:
    store_with("ohlcv-1m")

    with pytest.raises(ValueError, match="Expected a contract of ES, the root the run trades"):
        estimate_of(RunConfig(contract="NQH2026"))


def test_a_window_without_records_answers_zero() -> None:
    store_with("ohlcv-1m")
    held = estimate_of().held

    outside = estimate_of(start=date(2026, 3, 16), end=date(2026, 3, 18))

    assert (outside.held, outside.window, counts(outside)) == (held, None, (0, 0, 0))

    store = Store(resolve_paths(os.environ).data_dir)
    friday = date(2026, 3, 6)
    for file in store.list_partitions():
        if file.partition.dataset.root == "ES":
            rows = store.scan_partition(file.partition).collect()
            store.write_partition(file.partition, rows.filter(pl.col("trade_date") != friday))

    gap = estimate_of(RunConfig(contract="ESH2026"), start=friday, end=friday)

    assert (gap.window, counts(gap)) == (Window(start=friday, end=friday), (0, 0, 0))


def test_a_root_the_store_does_not_hold_has_no_estimate() -> None:
    store_with("ohlcv-1m")

    found = estimated("MNQ", FIVE_MINUTES, None, None, RunConfig(), resolve_paths(os.environ))

    assert found is None


def test_a_window_left_open_is_what_the_series_holds() -> None:
    store_with("ohlcv-1m")

    estimate = estimate_of(start=None, end=None)

    assert estimate.window == estimate.held == Window(start=date(2026, 3, 6), end=LAST)
    assert estimate.sessions == 2


def with_tbbo_of_friday(provider: str = "synthetic") -> None:
    """A TBBO partition of ESH2026 on 2026-03-06, its one session of quotes, from its trades."""
    store = Store(resolve_paths(os.environ).data_dir)
    trades = Dataset(provider=provider, schema_name=parse_schema_name("trades"), root="ES")
    tbbo = Dataset(provider=provider, schema_name=parse_schema_name("tbbo"), root="ES")
    store.write_dataset_metadata(tbbo, store.dataset_metadata(trades))
    friday = date(2026, 3, 6)
    rows = store.scan_partition(Partition(dataset=trades, contract="ESH2026", key=friday))
    tick = 250_000_000
    store.write_partition(
        Partition(dataset=tbbo, contract="ESH2026", key=friday),
        rows.collect().with_columns(
            bid_px_00=pl.col("price") - tick,
            ask_px_00=pl.col("price") + tick,
            bid_sz_00=pl.lit(3, dtype=pl.UInt32),
            ask_sz_00=pl.lit(4, dtype=pl.UInt32),
        ),
    )


def test_a_session_of_tbbo_fills_on_it_and_a_coarser_cap_passes_it_over() -> None:
    store_with("trades", "ohlcv-1m")
    with_tbbo_of_friday()
    friday, monday = date(2026, 3, 6), date(2026, 3, 9)

    finest = estimate_of()
    trades = estimate_of(RunConfig(fidelity=TickFidelity.TRADES))

    assert finest.settings.fidelity == "tbbo"
    assert finest.levels == ("tbbo", "trades", "1m")
    # TBBO on Friday, the rows of its trades, and trades on Monday, the one level it holds.
    assert counts(finest) == counts(trades)
    assert counts(trades) == (
        2,
        0,
        stored("trades", "ESH2026", friday, friday) + stored("trades", "ESM2026", monday, monday),
    )


def test_a_session_holding_only_finer_levels_is_refused_in_the_engines_words() -> None:
    store_with("trades", "ohlcv-1m")
    store = Store(resolve_paths(os.environ).data_dir)
    friday = date(2026, 3, 6)
    for file in store.list_partitions():
        if file.partition.dataset.schema_name == parse_schema_name("ohlcv-1m"):
            rows = store.scan_partition(file.partition).collect()
            kept = rows.filter(
                (pl.col("trade_date") != friday) | (file.partition.contract != "ESH2026")
            )
            store.write_partition(file.partition, kept)

    with pytest.raises(
        ValueError,
        match=r"Expected a level at or coarser than 1m on 2026-03-06, which holds trades",
    ):
        estimate_of(RunConfig(fidelity=ONE_MINUTE))


def test_a_root_of_two_providers_estimates_the_named_one() -> None:
    store_with("ohlcv-1m")
    paths = resolve_paths(os.environ)
    theirs = paths.data_dir / "aaa" / "ohlcv-1m" / "root=ES"
    theirs.parent.mkdir(parents=True)
    shutil.copytree(paths.data_dir / "synthetic" / "ohlcv-1m" / "root=ES", theirs)

    first = estimate_of()
    named = estimate_of(RunConfig(provider="synthetic"))

    assert first.providers == named.providers == ("aaa", "synthetic")
    assert (first.settings.provider, named.settings.provider) == ("aaa", "synthetic")
    with pytest.raises(ValueError, match="Expected a provider of ES in the store"):
        estimate_of(RunConfig(provider="zzz"))


def test_a_provider_that_cannot_splice_the_root_still_names_the_choices() -> None:
    # Ticks alone give no bars for a roll calendar: the answer holds no dates, and names the
    # providers and the contracts, one of which reads without a calendar.
    store_with("trades", "ohlcv-1m")
    paths = resolve_paths(os.environ)
    theirs = paths.data_dir / "aaa" / "trades" / "root=ES"
    theirs.parent.mkdir(parents=True)
    shutil.copytree(paths.data_dir / "synthetic" / "trades" / "root=ES", theirs)

    spliced = estimate_of(RunConfig(provider="aaa"))

    assert spliced.providers == ("aaa", "synthetic")
    assert spliced.levels == ("trades",)
    assert "ESH2026" in spliced.contracts
    assert (spliced.held, spliced.window, counts(spliced)) == (None, None, (0, 0, 0))
    one_contract = estimate_of(RunConfig(provider="aaa", contract="ESH2026"))
    assert one_contract.held is not None
    assert one_contract.ticks > 0


def test_bars_that_cannot_build_the_timeframe_hold_no_dates() -> None:
    store_with("ohlcv-1m")

    found = estimated(
        "ES", Timeframe.parse("30s"), None, None, RunConfig(), resolve_paths(os.environ)
    )

    assert found is not None
    assert (found.held, found.window, counts(found)) == (None, None, (0, 0, 0))
    assert found.levels == ("1m",)


def test_a_refusal_for_another_reason_stays_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only data that cannot make the series answers with no dates: a damaged store says why.
    store_with("ohlcv-1m")
    real = series_source_in

    def damaged(
        store: Store,
        cache: Path,
        symbol: str,
        continuous: bool | None = None,
        provider: str | None = None,
    ) -> SeriesSource:
        if continuous is None:
            raise ValueError("Expected a readable roll calendar, got a damaged file.")
        return real(store, cache, symbol, continuous, provider)

    monkeypatch.setattr(estimates, "series_source_in", damaged)

    with pytest.raises(ValueError, match="damaged file"):
        estimate_of()


def test_a_fee_table_that_prices_the_root_in_every_schedule_is_offered() -> None:
    store_with("ohlcv-1m")

    estimate = estimate_of()

    assert "binance-default" not in table_names(estimate)
    assert estimate.settings.fee_table in table_names(estimate)


def test_each_fee_table_names_its_charge_on_the_windows_last_day_in_the_currency() -> None:
    # D-117: the dialog shows what each table charges, in force on the run's last day; March
    # 2026 comes before the tables' first schedule, whose fees the engines charge then (F-FEE-01).
    store_with("ohlcv-1m")

    inside = estimate_of()
    outside = estimate_of(start=date(2026, 3, 16), end=date(2026, 3, 18))

    assert inside.currency == Currency.USD
    assert inside.fee_tables == (
        FeeChoice(name="retail-default", fee=FuturesFee(per_contract_side=Decimal("2.87"))),
        FeeChoice(name="prop-topstep", fee=FuturesFee(per_contract_side=Decimal("1.89"))),
    )
    # A window the data does not meet quotes each table's newest schedule, NFA's fee doubled.
    assert outside.window is None
    assert outside.fee_tables[0] == FeeChoice(
        name="retail-default", fee=FuturesFee(per_contract_side=Decimal("2.88"))
    )


def test_an_estimate_reads_the_instrument_its_settings_name() -> None:
    # D-114: a run on another instrument reads that instrument's data, contracts, and fees.
    store_with("ohlcv-1m")

    found = estimate_of(RunConfig(instrument="BTCUSDT-PERP"), start=None, end=None)

    assert found.settings.instrument == "BTCUSDT-PERP"
    assert found.contracts == ()
    assert found.currency == Currency.USDT
    assert (found.fee_tables, found.settings.fee_table) == (
        (
            FeeChoice(
                name="binance-default",
                fee=CryptoFee(maker_bps=Decimal(2), taker_bps=Decimal(5)),
            ),
        ),
        "binance-default",
    )
    assert found.sessions > 0
    assert found.bars > 0


def test_an_instrument_named_that_the_store_does_not_hold_has_no_estimate() -> None:
    store_with("ohlcv-1m")

    found = estimated(
        "ES", FIVE_MINUTES, None, None, RunConfig(instrument="MNQ"), resolve_paths(os.environ)
    )

    assert found is None


def test_the_instruments_held_are_those_with_bars_or_ticks() -> None:
    paths = resolve_paths(os.environ)
    store_with("funding")
    assert held_instruments(paths) == ()

    store_with("ohlcv-1m")

    assert held_instruments(paths) == ("BTCUSDT-PERP", "ES")
