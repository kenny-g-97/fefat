"""Contract identity: which dated contract of a futures product a record belongs to
(`02-engine-and-data.md` §1.2).

A contract is a root and an expiry month, written `ESZ2026`. Raw symbols carry one digit of
the year and come back every ten years (`ESZ6` traded in 2016 and trades again in 2026), so
a contract is resolved from the vendor's `instrument_id` or raw symbol on a given day, never
from the symbol alone, through the best source loaded, which the contract records:

1. Definition records (the `definitions` schema), which state the contract month, its
   activation, and its last trade. A definition answers only while its contract is alive,
   received by the day asked and not expired before it, so a reused `instrument_id` or raw
   symbol never names its old contract.
2. Else the symbology of the imported files: Databento's raw symbol to `instrument_id` by
   date interval (`SYMBOLOGY_COLUMNS`), which leaves the decade to infer (`expiry_month`).
3. Else the static instrument table (`fefat.market.instruments`), which knows the product
   but not the contract: the decade is the first the day asked allows, and a day before the
   product's first trade date is refused.

Days are UTC dates, as the vendor's symbology states them. Calendar spreads and strategy
symbols (`MCLF2-MCLG2`, `MCL:SA 03M F2`) are not contracts: `is_outright` tells them apart,
and resolving one is refused.
"""

import re
from datetime import date, timedelta
from enum import StrEnum
from typing import Any, Self

import polars as pl
from pydantic import Field, model_validator

from fefat.market.instruments import InstrumentTable
from fefat.market.layout import FolderName, YearMonth
from fefat.market.schema import FrozenModel, parse_schema_name, polars_schema, require_columns

MONTH_CODES = "FGHJKMNQUVXZ"
"""The futures month codes, January to December."""

OUTRIGHT_SYMBOL = re.compile(f"([A-Z0-9]{{1,4}})([{MONTH_CODES}])([0-9])")
"""A CME Globex outright: its root, its month code, and the last digit of its year (`ESZ6`)."""

CONTRACT_NAME = re.compile(f"([A-Z0-9]{{1,4}})([{MONTH_CODES}])([0-9]{{4}})")
"""A contract as `Contract` writes it: its root, its month code, and its year (`ESZ2026`)."""

OUTRIGHT_FUTURE = "F"
"""The `instrument_class` of an outright future in definition records; a spread's is `S`."""

DEFINITIONS_COLUMNS = polars_schema(parse_schema_name("definitions"))

SYMBOLOGY_COLUMNS = pl.Schema(
    {
        "raw_symbol": pl.String,
        "instrument_id": pl.UInt32,
        "start_date": pl.Date,
        "end_date": pl.Date,
    }
)
"""One interval of the imported files' symbology: `raw_symbol` named `instrument_id` from
`start_date` until the day before `end_date`, as the DBN metadata maps them."""

ACTIVE_DAYS_COLUMNS = pl.Schema({"instrument_id": pl.UInt32, "day": pl.Date})
"""The UTC dates on which each instrument_id has records in the imported files."""

SYMBOLOGY_CONTRACT_COLUMNS = pl.Schema(
    {**SYMBOLOGY_COLUMNS, "root": pl.String, "contract": pl.String, "expiry": pl.String}
)
"""A merged symbology interval with the root, the contract (`ESZ2026`), and the expiry month
(`2026-12`) of its outright, all three null for a spread or strategy symbol."""


class IdentitySource(StrEnum):
    """Where a contract's identity came from, best first."""

    DEFINITIONS = "definitions"
    SYMBOLOGY = "symbology"
    STATIC_TABLE = "static_table"


class Contract(FrozenModel):
    """One dated futures contract: a root and its expiry month, written `ESZ2026`.

    Its trade dates depend on its source: activation and the last eligible trade from
    definition records; the first and last day of its symbology interval (its listing and
    delisting, as far as the files cover them); none from the static table. `raw_symbols` are
    the vendor's symbols seen for it."""

    root: FolderName
    expiry: YearMonth
    first_trade_date: date | None
    last_trade_date: date | None
    raw_symbols: tuple[str, ...] = Field(min_length=1)
    identity_source: IdentitySource

    @model_validator(mode="after")
    def _is_dated_unless_from_the_static_table(self) -> Self:
        dated = self.identity_source is not IdentitySource.STATIC_TABLE
        dates = (self.first_trade_date, self.last_trade_date)
        if any((day is not None) != dated for day in dates):
            raise ValueError(
                f"Expected a contract from {self.identity_source} "
                f"{'with both' if dated else 'without'} trade dates, got first trade date "
                f"{self.first_trade_date} and last trade date {self.last_trade_date}."
            )
        return self

    def __str__(self) -> str:
        return f"{self.root}{MONTH_CODES[self.expiry.month - 1]}{self.expiry.year:04d}"


def parse_contract_name(name: str) -> tuple[str, YearMonth]:
    """The root and month of a contract written `ESZ2026`, as `Contract` writes it and the
    store names its `contract=` folders."""
    found = CONTRACT_NAME.fullmatch(name)
    if found is None:
        raise ValueError(
            f"Expected a contract written <root><month code><four-digit year>, got {name!r}."
        )
    return found[1], YearMonth(year=int(found[3]), month=MONTH_CODES.index(found[2]) + 1)


def is_outright(raw_symbol: str) -> bool:
    """Whether `raw_symbol` names one contract (`ESZ6`) rather than a calendar spread
    (`MCLF2-MCLG2`) or a strategy (`MCL:SA 03M F2`)."""
    return OUTRIGHT_SYMBOL.fullmatch(raw_symbol) is not None


def expiry_month(raw_symbol: str, first_seen: date, last_seen: date) -> YearMonth:
    """The contract month of an outright seen from `first_seen` to `last_seen`: the first
    month with its month code and year digit on or after `first_seen`'s month, ten years later
    while `last_seen` lies more than twelve months after it. A contract is listed before its
    month and gone within weeks after it, and its symbol comes back ten years on."""
    symbol = _outright(raw_symbol)
    month = MONTH_CODES.index(symbol[2]) + 1
    year = first_seen.year - first_seen.year % 10 + int(symbol[3])
    if (year, month) < (first_seen.year, first_seen.month):
        year += 10
    # shortcut: a listing ten years ahead (CL lists that far) seen for under a year resolves a
    # decade early; definition records settle it, so load them for such products.
    while (last_seen.year - year) * 12 + last_seen.month - month > 12:
        year += 10
    return YearMonth(year=year, month=month)


class ContractResolver:
    """Resolves contracts from definition records, then the symbology of the imported files,
    then an instrument table; a frame without rows means nothing of its source is loaded. A
    contract of a root the table lacks, or dated before the root's first trade date, is
    refused whatever its source."""

    def __init__(
        self, definitions: pl.DataFrame, symbology: pl.DataFrame, instruments: InstrumentTable
    ) -> None:
        require_columns(DEFINITIONS_COLUMNS, definitions.schema, "the definitions")
        require_columns(SYMBOLOGY_COLUMNS, symbology.schema, "the symbology")
        self._definitions = definitions
        self._symbology = _merged_intervals(symbology)
        self._instruments = instruments

    def by_instrument_id(self, instrument_id: int, on: date) -> Contract:
        """The contract that `instrument_id` named on the UTC date `on`."""
        contract = self._from_records(pl.col("instrument_id") == instrument_id, on)
        if contract is None:
            raise ValueError(
                f"Expected definitions or symbology covering instrument_id {instrument_id} on "
                f"{on}, got none among the {self._definitions.height} definition records and "
                f"{self._symbology.height} symbology intervals loaded."
            )
        return contract

    def by_symbol(self, raw_symbol: str, on: date) -> Contract:
        """The contract that the outright `raw_symbol` named on the UTC date `on`; without
        definitions or symbology covering it, the static table's product, in the decade that
        `on` allows."""
        root = _outright(raw_symbol)[1]
        contract = self._from_records(pl.col("raw_symbol") == raw_symbol, on)
        if contract is not None:
            return contract
        # shortcut: with no listing dates, a symbol asked after its contract expired names the
        # next decade's (ESZ5 on 2026-01-02 is ESZ2035); definitions or symbology settle it.
        return Contract(
            root=self._instruments.get(root, on).root,
            expiry=expiry_month(raw_symbol, on, on),
            first_trade_date=None,
            last_trade_date=None,
            raw_symbols=(raw_symbol,),
            identity_source=IdentitySource.STATIC_TABLE,
        )

    def _from_records(self, named: pl.Expr, on: date) -> Contract | None:
        contract = self._from_definitions(named, on)
        if contract is None:
            contract = self._from_symbology(named, on)
        if contract is not None:
            self._instruments.get(contract.root, on)
        return contract

    def _from_definitions(self, named: pl.Expr, on: date) -> Contract | None:
        alive = self._definitions.filter(
            named,
            _utc_date("ts_recv") <= on,
            pl.col("expiration").is_null() | (_utc_date("expiration") >= on),
        ).sort("ts_recv")
        if alive.is_empty():
            return None
        named_contracts = alive.select("raw_symbol", "instrument_id").unique().sort(pl.all())
        if named_contracts.height > 1:
            described = ", ".join(
                f"{raw_symbol} as instrument_id {instrument_id}"
                for raw_symbol, instrument_id in named_contracts.iter_rows()
            )
            raise ValueError(
                f"Expected the definitions alive on {on} to name one contract, got {described}."
            )
        latest = alive.tail(1).with_columns(
            _utc_date("activation").alias("first_trade_date"),
            _utc_date("expiration").alias("last_trade_date"),
        )
        return _contract_of(latest.row(0, named=True))

    def _from_symbology(self, named: pl.Expr, on: date) -> Contract | None:
        covering = self._symbology.filter(
            named, pl.col("start_date") <= on, pl.col("end_date") > on
        )
        if covering.height > 1:
            intervals = "; ".join(
                f"{interval['raw_symbol']} as {interval['instrument_id']} from "
                f"{interval['start_date']} until {interval['end_date']}"
                for interval in covering.iter_rows(named=True)
            )
            raise ValueError(f"Expected one symbology interval covering {on}, got {intervals}.")
        if covering.is_empty():
            return None
        return _symbology_contract(covering.row(0, named=True), on)


def symbology_contracts(symbology: pl.DataFrame, active_days: pl.DataFrame) -> pl.DataFrame:
    """Every interval of the imported files' symbology that has records, merged as the resolver
    merges them and ending the day after its last record (`active_days`, with the columns of
    `ACTIVE_DAYS_COLUMNS`), with the columns of `SYMBOLOGY_CONTRACT_COLUMNS`: an outright's
    root, contract, and expiry month, and nulls for a spread or strategy symbol. The vendor's
    interval can run on to the end of the query years after its contract expired (Databento
    maps MNQM3 until 2026-09-23), while a contract's records end with it, so the records settle
    its decade. The importer joins its records with it once rather than resolving each record."""
    require_columns(SYMBOLOGY_COLUMNS, symbology.schema, "the symbology")
    require_columns(ACTIVE_DAYS_COLUMNS, active_days.schema, "the active days")
    covering = pl.col("day").is_between(pl.col("start_date"), pl.col("end_date"), closed="left")
    active = (
        _merged_intervals(symbology)
        .join(active_days, on="instrument_id")
        .filter(covering)
        .group_by("raw_symbol", "instrument_id", "start_date")
        .agg(end_date=pl.col("day").max() + timedelta(days=1))
        .sort("raw_symbol", "instrument_id", "start_date")
    )
    labels = pl.DataFrame(
        [_contract_labels(interval) for interval in active.iter_rows(named=True)],
        schema={name: SYMBOLOGY_CONTRACT_COLUMNS[name] for name in ("root", "contract", "expiry")},
        orient="row",
    )
    return pl.concat([active, labels], how="horizontal")


def _contract_labels(interval: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    if not is_outright(interval["raw_symbol"]):
        return (None, None, None)
    contract = _symbology_contract(interval, interval["end_date"] - timedelta(days=1))
    return (contract.root, str(contract), str(contract.expiry))


def _symbology_contract(interval: dict[str, Any], last_seen: date) -> Contract:
    """The contract of a symbology interval, its decade taken as of `last_seen`: the day asked
    for a live contract, since the vendor's interval runs on to the end of its query."""
    raw_symbol = interval["raw_symbol"]
    last_day = interval["end_date"] - timedelta(days=1)
    return Contract(
        root=_outright(raw_symbol)[1],
        expiry=expiry_month(raw_symbol, interval["start_date"], last_seen),
        first_trade_date=interval["start_date"],
        last_trade_date=last_day,
        raw_symbols=(raw_symbol,),
        identity_source=IdentitySource.SYMBOLOGY,
    )


def _merged_intervals(symbology: pl.DataFrame) -> pl.DataFrame:
    """The intervals of each raw symbol and `instrument_id` joined where they overlap or touch,
    so a mapping that several files repeat, or split at their edges, reads as one interval;
    the same pair seen again after a gap, ten years on, stays apart."""
    pair = ["raw_symbol", "instrument_id"]
    starts_a_run = pl.col("start_date") > pl.col("end_date").cum_max().shift(1).over(pair)
    return (
        symbology.sort([*pair, "start_date"])
        .with_columns(starts_a_run.fill_null(True).cum_sum().over(pair).alias("run"))
        .group_by([*pair, "run"])
        .agg(pl.col("start_date").min(), pl.col("end_date").max())
        .drop("run")
        .sort([*pair, "start_date"])
    )


def _contract_of(definition: dict[str, Any]) -> Contract:
    described = f"instrument_id {definition['instrument_id']} ({definition['raw_symbol']})"
    if definition["instrument_class"] != OUTRIGHT_FUTURE:
        raise ValueError(
            f"Expected an outright future (instrument_class {OUTRIGHT_FUTURE}), got {described} "
            f"of instrument_class {definition['instrument_class']}."
        )
    stated = ("asset", "maturity_year", "maturity_month", "activation", "expiration")
    missing = [name for name in stated if definition[name] is None]
    if missing:
        raise ValueError(
            f"Expected the definition of {described} to state {', '.join(missing)}, got null."
        )
    return Contract(
        root=definition["asset"],
        expiry=YearMonth(year=definition["maturity_year"], month=definition["maturity_month"]),
        first_trade_date=definition["first_trade_date"],
        last_trade_date=definition["last_trade_date"],
        raw_symbols=(definition["raw_symbol"],),
        identity_source=IdentitySource.DEFINITIONS,
    )


def _outright(raw_symbol: str) -> re.Match[str]:
    found = OUTRIGHT_SYMBOL.fullmatch(raw_symbol)
    if found is None:
        raise ValueError(
            f"Expected an outright symbol <root><month code><year digit>, got {raw_symbol!r}."
        )
    return found


def _utc_date(column: str) -> pl.Expr:
    """A column of nanoseconds since the Unix epoch as its UTC date."""
    return pl.col(column).cast(pl.Datetime("ns")).dt.date()
