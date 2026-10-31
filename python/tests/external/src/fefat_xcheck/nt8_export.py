"""NinjaTrader 8's trade list, exported by hand from the Strategy Analyzer's Trades tab (D-59), read
as the comparison's trades. The export is a semicolon-separated table in the platform's own
culture: times on the platform clock, US Eastern on the builder's PC, written day first
(`03/08/2026 09:36:00`) or, with AM and PM, month first; numbers with the culture's separators
(`$ -63,20`, `24.786,00`, `24,800.25`, `($21.90)`). `Profit` is net of `Commission`."""

import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from fefat_xcheck.classify import MARKET

PLATFORM_TIME_ZONE = "America/New_York"
UNITS_PER_POINT = 1_000_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
MINUTE = 60 * NANOSECONDS_PER_SECOND
REQUIRED_COLUMNS = (
    "Market pos.",
    "Qty",
    "Entry price",
    "Exit price",
    "Entry time",
    "Exit time",
    "Entry name",
    "Exit name",
    "Profit",
    "Commission",
)
EXIT_REASONS = {"Stop loss": "stop", "Profit target": "target", "FlatBy": "flat_by"}
"""The Analyzer's exit names for the strategy's Set() orders, and the exit signal name
`FefatCrossCheck.cs` gives its flat-by."""
SIDES = {"Long": "long", "Short": "short"}
DAY_FIRST, MONTH_FIRST_WITH_MERIDIEM = "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"
EXPORT_COLUMNS = pl.Schema(
    {
        "entry_decision": pl.Int64,
        "side": pl.String,
        "entry_kind": pl.String,
        "entry_ts": pl.Int64,
        "entry_price": pl.Int64,
        "exit_ts": pl.Int64,
        "exit_price": pl.Int64,
        "exit_reason": pl.String,
        "gross_pnl": pl.Float64,
        "commission": pl.Float64,
    }
)
"""The comparison's trade columns the export gives, without the bracket's levels, which the
signal frame holds, and with the commission NT8 charged."""


def read_export(
    path: Path, point_value: int | Decimal, time_zone: str = PLATFORM_TIME_ZONE
) -> pl.DataFrame:
    """The export's trades with the columns of `EXPORT_COLUMNS`, prices in 1e-9 units and instants
    in nanoseconds UTC; `point_value` recovers the gross profit and loss from the prices, which
    the export rounds to cents."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file, delimiter=";"))
    if not rows or any(name not in rows[0] for name in REQUIRED_COLUMNS):
        raise ValueError(
            f"Expected the Strategy Analyzer's trade columns {REQUIRED_COLUMNS} in {path.name}, "
            f"got {rows[0] if rows else 'an empty file'}."
        )
    column = {name: rows[0].index(name) for name in REQUIRED_COLUMNS}
    zone = ZoneInfo(time_zone)
    trades = [
        _trade(row, column, zone, Decimal(point_value))
        for row in rows[1:]
        if len(row) > column["Profit"] and row[column["Profit"]].strip()
    ]
    return pl.DataFrame(trades, schema=EXPORT_COLUMNS).sort("entry_ts")


def _trade(
    row: list[str], column: dict[str, int], zone: ZoneInfo, point_value: Decimal
) -> dict[str, object]:
    cell = lambda name: row[column[name]].strip()  # noqa: E731
    entry_price, exit_price = parse_number(cell("Entry price")), parse_number(cell("Exit price"))
    side = SIDES[cell("Market pos.")]
    sign = 1 if side == "long" else -1
    quantity = int(parse_number(cell("Qty")))
    entry_ts = parse_platform_time(cell("Entry time"), zone)
    return {
        "entry_decision": entry_ts - MINUTE,
        "side": side,
        "entry_kind": MARKET,
        "entry_ts": entry_ts,
        "entry_price": _units(entry_price),
        "exit_ts": parse_platform_time(cell("Exit time"), zone),
        "exit_price": _units(exit_price),
        "exit_reason": _exit_reason(cell("Exit name")),
        "gross_pnl": float((exit_price - entry_price) * sign * quantity * point_value),
        "commission": float(parse_number(cell("Commission"))),
    }


def _exit_reason(name: str) -> str:
    if name not in EXIT_REASONS:
        raise ValueError(f"Expected an exit name of {sorted(EXIT_REASONS)}, got {name!r}.")
    return EXIT_REASONS[name]


def _units(price: Decimal) -> int:
    return int(price * UNITS_PER_POINT)


def parse_number(text: str) -> Decimal:
    """A number as the platform's culture writes it: a currency sign, a space, parentheses for a
    loss, and either separator as the decimal one, the thousands separator being the other, or
    a lone comma before three digits."""
    cleaned = text.replace("$", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    if "," in cleaned and "." in cleaned:
        decimal_separator = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        cleaned = cleaned.replace("." if decimal_separator == "," else ",", "")
        cleaned = cleaned.replace(decimal_separator, ".")
    elif "," in cleaned:
        lone_thousands = re.fullmatch(r"-?\d{1,3}(,\d{3})+", cleaned) is not None
        cleaned = cleaned.replace(",", "" if lone_thousands else ".")
    try:
        value = Decimal(cleaned)
    except ArithmeticError as error:
        raise ValueError(f"Expected a number as NinjaTrader writes one, got {text!r}.") from error
    return -value if negative else value


def parse_platform_time(text: str, zone: ZoneInfo) -> int:
    """A time on the platform's clock as nanoseconds UTC."""
    for layout in (DAY_FIRST, MONTH_FIRST_WITH_MERIDIEM):
        try:
            local = datetime.strptime(text, layout)
        except ValueError:
            continue
        return int(local.replace(tzinfo=zone).timestamp()) * NANOSECONDS_PER_SECOND
    raise ValueError(
        f"Expected a time as NinjaTrader writes one ({DAY_FIRST} or "
        f"{MONTH_FIRST_WITH_MERIDIEM}), got {text!r}."
    )
