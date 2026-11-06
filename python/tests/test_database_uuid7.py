"""The UUIDv7 ids of the app's rows (step 4.1, RFC 9562 section 5.7, D-83): Python 3.12's `uuid`
has no `uuid7`, so `fefat_app.database.uuid7` lays one out from a time and random bits."""

import time
import uuid

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from fefat_app.database.uuid7 import new_uuid7, uuid7_at

TIMESTAMPS = st.integers(min_value=0, max_value=2**48 - 1)
RANDOM_BITS = st.integers(min_value=0, max_value=2**74 - 1)


@given(TIMESTAMPS, RANDOM_BITS)
def test_a_uuid7_holds_its_time_its_version_its_variant_and_its_random_bits(
    timestamp_ms: int, random_bits: int
) -> None:
    made = uuid7_at(timestamp_ms, random_bits)

    assert made.version == 7
    assert made.variant == uuid.RFC_4122
    assert made.int >> 80 == timestamp_ms
    assert ((made.int >> 64) & 0xFFF) << 62 | (made.int & (2**62 - 1)) == random_bits


@given(TIMESTAMPS, TIMESTAMPS, RANDOM_BITS, RANDOM_BITS)
def test_a_later_millisecond_sorts_later_as_text(
    first: int, second: int, first_bits: int, second_bits: int
) -> None:
    assume(first != second)
    earlier, later = sorted((first, second))

    assert str(uuid7_at(earlier, first_bits)) < str(uuid7_at(later, second_bits))


@pytest.mark.parametrize(
    ("timestamp_ms", "random_bits"), [(-1, 0), (2**48, 0), (0, -1), (0, 2**74)]
)
def test_a_time_or_random_bits_out_of_range_are_refused(
    timestamp_ms: int, random_bits: int
) -> None:
    with pytest.raises(ValueError, match=r"^Expected .*, got -?[0-9]+[.]$"):
        uuid7_at(timestamp_ms, random_bits)


def test_a_new_uuid7_is_text_of_version_7_made_now() -> None:
    before = time.time_ns() // 1_000_000

    made = uuid.UUID(new_uuid7())

    after = time.time_ns() // 1_000_000
    assert made.version == 7
    assert before <= made.int >> 80 <= after
