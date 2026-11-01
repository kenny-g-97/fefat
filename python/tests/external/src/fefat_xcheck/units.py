"""The units the comparison's modules share, the store's (ADR-0019): prices as int64 counts of
1e-9 of the quote currency and instants as int64 nanoseconds since the Unix epoch, UTC."""

from datetime import UTC, date, datetime
from decimal import Decimal

UNITS_PER_POINT = 1_000_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
MINUTE = 60 * NANOSECONDS_PER_SECOND


def units_of(price: Decimal) -> int:
    """A price in 1e-9 units."""
    return int(price * UNITS_PER_POINT)


def whole_second(instant: int) -> int:
    """The instant cut to its second: NautilusTrader's build delay puts a decision and the fills
    it makes a microsecond after the bar's close (`nautilus_side.BUILD_DELAY_MICROSECONDS`)."""
    return instant // NANOSECONDS_PER_SECOND * NANOSECONDS_PER_SECOND


def utc_day(day: date) -> int:
    """The instant a UTC day starts."""
    return (
        int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * NANOSECONDS_PER_SECOND
    )
