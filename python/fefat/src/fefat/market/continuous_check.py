"""The roll check: a roll calendar's front contract on each trade date against a vendor's
continuous mapping, such as Databento's `MES.v.0` (`02-engine-and-data.md` §1.5, step 1.7).

Databento's continuous symbols (`.v.0` the volume leader, `.n.0` open interest, `.c.0` the
nearest expiry) name one contract for each UTC date from the day before's figures, and its free
symbology endpoint (`symbology.resolve`) returns the mapping as intervals: from `d0` to the day
before `d1`, the symbol named the instrument_id `s`. The mapping switches at 00:00 UTC, which
falls inside the CME session of the trade date of the same day (it opens at 17:00 Chicago the
evening before), so the vendor's contract on UTC date D is compared with the front of trade
date D. A difference whose vendor contract is our front of the session before, or after, is a
roll a session later, or earlier, than ours; the vendor ranks by UTC days and may roll back,
where the calendar ranks by sessions and never does.

    mapping = parse_databento_mapping(store.raw.read(path), "MES.v.0")
    print(compare_fronts(calendar, mapping, bars, "MES.v.0").summary())
"""

from datetime import date
from enum import StrEnum

import polars as pl
from pydantic import BaseModel, ConfigDict, ValidationError

from fefat.market.continuous import CONTRACT_BAR_COLUMNS, RollCalendar
from fefat.market.schema import FrozenModel, require_columns

VENDOR_MAPPING_COLUMNS = pl.Schema(
    {"start_date": pl.Date, "end_date": pl.Date, "instrument_id": pl.UInt32}
)
"""A vendor's continuous mapping: from `start_date` to the day before `end_date`, UTC dates, the
continuous symbol named `instrument_id`."""


class _MappingInterval(FrozenModel):
    d0: date
    d1: date
    s: str


class _SymbologyResponse(BaseModel):
    """The part of a `symbology.resolve` response the check reads; the rest is ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    result: dict[str, tuple[_MappingInterval, ...]]


class DifferenceKind(StrEnum):
    """How a vendor's contract on a trade date relates to the calendar's fronts."""

    VENDOR_A_SESSION_LATER = "vendor-a-session-later"
    VENDOR_A_SESSION_EARLIER = "vendor-a-session-earlier"
    NOT_IN_THE_BARS = "not-in-the-bars"
    OTHER = "other"


class FrontDifference(FrozenModel):
    """A trade date on which the vendor's contract is not the calendar's front."""

    trade_date: date
    ours: str
    vendors: str
    kind: DifferenceKind


class FrontComparison(FrozenModel):
    """What `compare_fronts` found: the trade dates both name a contract for, and those on
    which they differ, in order."""

    root: str
    vendor_symbol: str
    trade_dates_compared: int
    differences: tuple[FrontDifference, ...]

    def summary(self) -> str:
        """A heading with the counts, then a line per difference."""
        count = len(self.differences)
        differ = "none differ" if count == 0 else f"{count} differ{'s' if count == 1 else ''}"
        compared = f"{self.trade_dates_compared:,} trade dates compared"
        heading = f"Fronts of {self.root} against {self.vendor_symbol}: {compared}, {differ}."
        lines = (
            f"  {difference.trade_date}: ours {difference.ours}, {self.vendor_symbol} "
            f"{difference.vendors} ({difference.kind})"
            for difference in self.differences
        )
        return "\n".join([heading, *lines])


def parse_databento_mapping(content: bytes, symbol: str) -> pl.DataFrame:
    """The intervals of `symbol` in a response of Databento's `symbology.resolve` with
    `stype_out` `instrument_id`, with the columns of `VENDOR_MAPPING_COLUMNS`, sorted."""
    try:
        parsed = _SymbologyResponse.model_validate_json(content)
    except ValidationError as error:
        raise ValueError(f"Expected a symbology response, got: {error}") from error
    if symbol not in parsed.result:
        found = ", ".join(sorted(parsed.result)) or "no symbol"
        raise ValueError(f"Expected {symbol} in the result of the symbology response, got {found}.")
    rows = []
    for interval in parsed.result[symbol]:
        if not interval.s.isdigit():
            raise ValueError(
                f"Expected an instrument_id for {symbol} from {interval.d0} to before "
                f"{interval.d1}, got {interval.s!r}."
            )
        rows.append((interval.d0, interval.d1, int(interval.s)))
    mapping = pl.DataFrame(rows, schema=VENDOR_MAPPING_COLUMNS, orient="row")
    return mapping.sort("start_date")


def compare_fronts(
    calendar: RollCalendar, mapping: pl.DataFrame, bars: pl.DataFrame, vendor_symbol: str
) -> FrontComparison:
    """The calendar's front on each of its trade dates that `mapping` covers against the
    contract the vendor named that UTC date, found by its instrument_id among `bars`, which have
    the columns of `CONTRACT_BAR_COLUMNS`."""
    require_columns(VENDOR_MAPPING_COLUMNS, mapping.schema, f"the mapping of {vendor_symbol}")
    require_columns(CONTRACT_BAR_COLUMNS, bars.schema, f"the bars compared with {vendor_symbol}")
    named = contracts_by_instrument(bars)
    vendor_days = (
        mapping.select(
            "instrument_id",
            trade_date=pl.date_ranges("start_date", "end_date", closed="left"),
        )
        .explode("trade_date")
        .join(named, on="instrument_id", how="left")
        .select(
            "trade_date",
            in_the_bars=pl.col("contract").is_not_null(),
            vendors=pl.col("contract").fill_null(
                pl.format("instrument_id {}, in none of the bars", "instrument_id")
            ),
        )
    )
    fronts = calendar.rows.select(
        "trade_date",
        ours="contract",
        before=pl.col("contract").shift(1),
        after=pl.col("contract").shift(-1),
    )
    compared = fronts.join(vendor_days, on="trade_date").sort("trade_date")
    differing = compared.filter(pl.col("ours") != pl.col("vendors"))
    return FrontComparison(
        root=calendar.root,
        vendor_symbol=vendor_symbol,
        trade_dates_compared=compared.height,
        differences=tuple(_difference(row) for row in differing.iter_rows(named=True)),
    )


def contracts_by_instrument(bars: pl.DataFrame) -> pl.DataFrame:
    """The contract each instrument_id of `bars` names; one naming two is refused, since the
    vendor's mapping gives the instrument_id alone."""
    named = bars.select("instrument_id", "contract").unique()
    reused = named.filter(pl.col("instrument_id").is_duplicated()).sort(pl.all())
    if not reused.is_empty():
        instrument_id = reused.item(0, "instrument_id")
        contracts = reused.filter(pl.col("instrument_id") == instrument_id).get_column("contract")
        raise ValueError(
            f"Expected each instrument_id of the bars to name one contract, got {instrument_id} "
            f"naming {', '.join(contracts.to_list())}."
        )
    return named


def _difference(row: dict[str, object]) -> FrontDifference:
    vendors = row["vendors"]
    kind = DifferenceKind.OTHER
    if not row["in_the_bars"]:
        kind = DifferenceKind.NOT_IN_THE_BARS
    elif vendors == row["before"]:
        kind = DifferenceKind.VENDOR_A_SESSION_LATER
    elif vendors == row["after"]:
        kind = DifferenceKind.VENDOR_A_SESSION_EARLIER
    return FrontDifference.model_validate(
        {"trade_date": row["trade_date"], "ours": row["ours"], "vendors": vendors, "kind": kind}
    )
