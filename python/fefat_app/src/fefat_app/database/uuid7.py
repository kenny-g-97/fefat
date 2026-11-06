"""UUIDv7 ids for the app's rows (RFC 9562 section 5.7, `01-architecture.md` section 5, D-83):
Python 3.12's `uuid` has no `uuid7`, so `uuid7_at` lays one out from a time and random bits, and
`new_uuid7` takes them from the clock and the operating system's random source. An id made in a
later millisecond sorts later, as a number and as text."""

import secrets
import time
import uuid

TIMESTAMP_BITS = 48
RANDOM_BITS = 74


def uuid7_at(timestamp_ms: int, random_bits: int) -> uuid.UUID:
    """The UUIDv7 of the Unix time `timestamp_ms`, in milliseconds, and the 74 bits
    `random_bits`: 48 bits of time, the version 7, 12 random bits, the variant `10`, and the
    other 62 random bits."""
    if not 0 <= timestamp_ms < 2**TIMESTAMP_BITS:
        raise ValueError(f"Expected a Unix time in milliseconds below 2**48, got {timestamp_ms}.")
    if not 0 <= random_bits < 2**RANDOM_BITS:
        raise ValueError(f"Expected 74 random bits, a number below 2**74, got {random_bits}.")
    leading, trailing = random_bits >> 62, random_bits & (2**62 - 1)
    return uuid.UUID(
        int=(timestamp_ms << 80) | (0x7 << 76) | (leading << 64) | (0b10 << 62) | trailing
    )


def new_uuid7() -> str:
    """A new UUIDv7 as text, the form the app's rows keep."""
    return str(uuid7_at(time.time_ns() // 1_000_000, secrets.randbits(RANDOM_BITS)))
