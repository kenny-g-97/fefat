import re
from datetime import date
from decimal import Decimal

import pytest

import fefat as ff
from fefat.market.fees import TABLES, CryptoFee, FeeSchedule, FeeTable, FuturesFee, lookup
from fefat.market.instruments import STATIC_TABLE

RATE_CARD = "https://www.example.com/rate-card"


def es_schedule(effective_from: date, per_contract_side: str) -> FeeSchedule:
    return FeeSchedule(
        effective_from=effective_from,
        sources=(RATE_CARD,),
        fees={"ES": FuturesFee(per_contract_side=Decimal(per_contract_side))},
    )


TWO_SCHEDULES = FeeTable(
    name="a-broker",
    schedules=(es_schedule(date(2026, 1, 5), "2.00"), es_schedule(date(2026, 7, 20), "2.25")),
)


@pytest.mark.parametrize(
    ("on", "per_contract_side"),
    [
        (date(2026, 1, 5), "2.00"),
        (date(2026, 7, 19), "2.00"),
        (date(2026, 7, 20), "2.25"),
        (date(2030, 1, 2), "2.25"),
    ],
)
def test_lookup_picks_the_schedule_in_force_on_the_date(on: date, per_contract_side: str) -> None:
    assert TWO_SCHEDULES.lookup("ES", on) == FuturesFee(
        per_contract_side=Decimal(per_contract_side)
    )


@pytest.mark.parametrize(
    ("on", "per_contract_side"),
    [
        (date(2026, 9, 30), "1.09"),
        (date(2026, 10, 1), "1.19"),
        (date(2027, 6, 30), "1.19"),
        (date(2027, 7, 1), "1.20"),
    ],
)
def test_retail_default_follows_the_cme_change_of_mcl_and_the_nfa_change_by_date(
    on: date, per_contract_side: str
) -> None:
    assert lookup("retail-default", "MCL", on) == FuturesFee(
        per_contract_side=Decimal(per_contract_side)
    )


def test_ff_fees_lookup_gives_a_per_side_fee() -> None:
    fee = ff.fees.lookup("retail-default", "ES", date(2026, 10, 13))

    assert fee == FuturesFee(per_contract_side=Decimal("2.87"))


@pytest.mark.parametrize(("root", "per_contract_side"), [("ES", "2.87"), ("MES", "0.94")])
def test_retail_default_matches_ninjatraders_all_in_examples(
    root: str, per_contract_side: str
) -> None:
    assert lookup("retail-default", root, date(2026, 8, 14)) == FuturesFee(
        per_contract_side=Decimal(per_contract_side)
    )


@pytest.mark.parametrize(
    ("root", "round_turn"),
    [
        ("ES", "3.78"),
        ("NQ", "3.78"),
        ("MES", "1.22"),
        ("MNQ", "1.22"),
        ("CL", "4.02"),
        ("MCL", "1.72"),
        ("GC", "4.32"),
        ("MGC", "1.92"),
    ],
)
def test_prop_topstep_matches_the_round_turns_topstep_publishes(root: str, round_turn: str) -> None:
    assert lookup("prop-topstep", root, date(2026, 10, 13)) == FuturesFee(
        per_contract_side=Decimal(round_turn) / 2
    )


@pytest.mark.parametrize(
    ("root", "maker_bps", "taker_bps"),
    [("BTCUSDT-PERP", 2, 5), ("ETHUSDT-PERP", 2, 5), ("BTCUSDT", 10, 10), ("ETHUSDT", 10, 10)],
)
def test_crypto_fees_are_maker_and_taker_basis_points(
    root: str, maker_bps: int, taker_bps: int
) -> None:
    assert lookup("binance-default", root, date(2026, 10, 13)) == CryptoFee(
        maker_bps=Decimal(maker_bps), taker_bps=Decimal(taker_bps)
    )


def test_a_date_before_a_tables_first_schedule_is_refused() -> None:
    expected = "Expected a schedule of retail-default in force on 2026-07-19, got the first from "

    with pytest.raises(ValueError, match=re.escape(f"{expected}2026-07-20.")):
        lookup("retail-default", "ES", date(2026, 7, 19))


def test_an_unknown_table_is_refused_with_the_names_of_the_tables() -> None:
    expected = "Expected a fee table (binance-default, prop-topstep, retail-default), got 'x'."

    with pytest.raises(ValueError, match=re.escape(expected)):
        lookup("x", "ES", date(2026, 10, 13))


def test_a_root_the_schedule_does_not_price_is_refused_with_the_roots_it_prices() -> None:
    expected = (
        "Expected a root priced by retail-default from 2026-10-01 "
        "(CL, ES, GC, MCL, MES, MGC, MNQ, NQ), got 'ZN'."
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        lookup("retail-default", "ZN", date(2026, 10, 13))


@pytest.mark.parametrize(
    "dates", [(date(2026, 7, 20), date(2026, 1, 5)), (date(2026, 7, 20), date(2026, 7, 20))]
)
def test_schedules_out_of_order_or_on_one_date_are_refused(dates: tuple[date, date]) -> None:
    with pytest.raises(ValueError, match="Expected the schedules of a-broker in order"):
        FeeTable(name="a-broker", schedules=tuple(es_schedule(day, "2.00") for day in dates))


def test_fee_tables_cannot_be_changed_once_built() -> None:
    zero = FuturesFee(per_contract_side=Decimal(0))

    with pytest.raises(TypeError):
        TABLES["retail-default"] = TWO_SCHEDULES  # pyright: ignore[reportIndexIssue]
    with pytest.raises(TypeError):
        TABLES["retail-default"].schedules[0].fees["ES"] = zero  # pyright: ignore[reportIndexIssue]


def test_every_seeded_schedule_names_https_sources_and_prices_roots_of_the_instruments() -> None:
    roots = set(STATIC_TABLE.roots())

    for table in TABLES.values():
        for schedule in table.schedules:
            assert all(source.startswith("https://") for source in schedule.sources), table.name
            assert set(schedule.fees) <= roots, table.name
