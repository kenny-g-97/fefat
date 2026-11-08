from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from fefat.market.calendar_definition import Calendar, SessionHours, Weekday
from fefat.market.instruments import STATIC_TABLE, Currency, Instrument, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.saved_instruments import instrument_table, save_instrument

MONDAY_TO_FRIDAY = frozenset(
    {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
)
XES_SESSIONS = Calendar(
    name="XES-sessions",
    hours=SessionHours(
        time_zone="America/Chicago",
        opens_at=time(17, 0),
        closes_at=time(16, 0),
        opens_on_previous_day=True,
        weekdays=MONDAY_TO_FRIDAY,
    ),
    holidays=(),
)


def a_new_product(tick_size: str = "0.25") -> Instrument:
    return Instrument(
        root="XES",
        kind=InstrumentKind.FUTURES,
        tick_size=Decimal(tick_size),
        point_value=Decimal(50),
        lot_step=Decimal(1),
        currency=Currency.EUR,
        calendar=XES_SESSIONS,
        last_trade_rule=ThirdFriday(),
        valid_from=date(2026, 3, 5),
        valid_to=None,
        sources=("profile xes-5m",),
    )


def test_a_saved_instrument_joins_the_static_table_with_its_own_calendar(tmp_path: Path) -> None:
    assert save_instrument(tmp_path, a_new_product())

    table = instrument_table(tmp_path)

    assert table.get("XES") == a_new_product()
    assert table.get("XES").session_calendar() == XES_SESSIONS
    assert table.get("MES") == STATIC_TABLE.get("MES")


def test_without_saved_instruments_the_table_is_the_static_one(tmp_path: Path) -> None:
    assert instrument_table(tmp_path) is STATIC_TABLE


def test_a_built_in_calendar_id_and_an_own_calendar_round_trip_through_json() -> None:
    for instrument in (STATIC_TABLE.get("ES"), a_new_product()):
        assert Instrument.model_validate_json(instrument.model_dump_json()) == instrument


def test_saving_the_same_specification_again_changes_nothing(tmp_path: Path) -> None:
    save_instrument(tmp_path, a_new_product())
    path = tmp_path / "instruments" / "XES.json"
    written = path.stat().st_mtime_ns

    assert not save_instrument(tmp_path, a_new_product())
    assert path.stat().st_mtime_ns == written


def test_another_specification_of_a_saved_root_is_refused(tmp_path: Path) -> None:
    save_instrument(tmp_path, a_new_product())

    with pytest.raises(ValueError, match="keeps the specification its first import saved"):
        save_instrument(tmp_path, a_new_product(tick_size="0.5"))


def test_a_root_fefat_knows_is_never_saved(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="an instrument FEAT knows"):
        save_instrument(tmp_path, STATIC_TABLE.get("MES"))


def test_a_saved_file_named_after_another_root_is_refused(tmp_path: Path) -> None:
    save_instrument(tmp_path, a_new_product())
    folder = tmp_path / "instruments"
    (folder / "XES.json").rename(folder / "XEU.json")

    with pytest.raises(ValueError, match="to hold the instrument XEU, got XES"):
        instrument_table(tmp_path)
