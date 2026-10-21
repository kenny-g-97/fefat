"""The contracts of a trader's export (step 1.10): each record's root and contract, as the
import profile and the import name them (`fefat.market.importers.profile_records`).

A continuous series is the one contract `<root>-CONTINUOUS` of the profile's root. Otherwise the
contract is the one the import names; the one the profile's pattern finds in the file's name,
by its groups `contract`, or `root` and `year` (two or four digits) with `month` (1 to 12) or
`code` (a letter); each row's symbol, a four-digit-year contract such as `ESH2026` or a venue's
outright such as `ESH6`, whose decade the dates of its run of rows decide, a run ending where
the symbol's rows pause for over a year (`fefat.market.contracts`), the rows of spread and
strategy symbols set aside and counted; or, for a perpetual or a spot pair, which never expire,
the root itself. A file holds one product, and the root the import names, or the profile's,
must be it.
"""

import re
from dataclasses import dataclass
from datetime import date

import polars as pl

from fefat.market.contracts import MONTH_CODES, OUTRIGHT_SYMBOL, expiry_month, parse_contract_name
from fefat.market.importers.profiles import ImportProfile, NewInstrument, names_a_contract
from fefat.market.instruments import InstrumentKind, InstrumentTable
from fefat.market.layout import SeriesKind

CONTINUOUS_CONTRACT_SUFFIX = "CONTINUOUS"
"""A continuous series is stored as the one contract `<root>-CONTINUOUS`."""
_RUN_GAP = 366 * 24 * 3_600 * 1_000_000_000
"""The pause in a symbol's rows, in nanoseconds, after which they name another decade's
contract."""


@dataclass(frozen=True)
class ImportFacts:
    """What an import knows besides its profile: the name of the file its records are in, and
    the contract, root, and time zone the command names, each None when it names none."""

    file_name: str
    contract: str | None
    root: str | None
    time_zone: str | None


def with_contracts(
    rows: pl.DataFrame, profile: ImportProfile, facts: ImportFacts, instruments: InstrumentTable
) -> tuple[pl.DataFrame, str, int]:
    """The rows with their `root` and `contract`, the one root, and how many rows of spread
    symbols were set aside (module docstring)."""
    root = _named_root(profile, facts)
    if profile.series is not SeriesKind.CONTRACT:
        if root is None:
            raise ValueError(f"Expected the root of the {profile.series} series, got none.")
        contract = f"{root}-{CONTINUOUS_CONTRACT_SUFFIX}"
        return rows.with_columns(root=pl.lit(root), contract=pl.lit(contract)), root, 0
    contract = facts.contract if facts.contract is not None else _contract_in_name(profile, facts)
    if contract is not None:
        contract_root, _ = parse_contract_name(contract)
        _require_one_root(root, contract_root, contract)
        named = rows.with_columns(root=pl.lit(contract_root), contract=pl.lit(contract))
        return named, contract_root, 0
    if "symbol" in rows.columns:
        return _contracts_of_symbols(rows, root, facts.file_name)
    if root is not None and _never_expires(profile, root, instruments):
        return rows.with_columns(root=pl.lit(root), contract=pl.lit(root)), root, 0
    raise ValueError(
        f"Expected the contract of the records of {facts.file_name}: name it, such as "
        "--contract ESH2026, name the file as its platform does, map a symbol column"
        f"{_missing_symbol(profile)}, or import it with a profile of series continuous."
    )


def _named_root(profile: ImportProfile, facts: ImportFacts) -> str | None:
    """The root the import or the profile names, or None; the two must agree."""
    named = profile.instrument
    profile_root = named.root if isinstance(named, NewInstrument) else named
    if facts.root is not None and profile_root is not None and facts.root != profile_root:
        raise ValueError(
            f"Expected the root of the profile {profile.name}, {profile_root}, got {facts.root}."
        )
    return profile_root if facts.root is None else facts.root


def _require_one_root(root: str | None, contract_root: str, contract: str) -> None:
    if root is not None and root != contract_root:
        raise ValueError(f"Expected a contract of {root}, got {contract}.")


def _never_expires(profile: ImportProfile, root: str, instruments: InstrumentTable) -> bool:
    """Whether the root is a perpetual's or a spot pair's, whose records are the root's."""
    named = profile.instrument
    kind = named.kind if isinstance(named, NewInstrument) else instruments.get(root).kind
    return kind is not InstrumentKind.FUTURES


def _missing_symbol(profile: ImportProfile) -> str:
    """A note that the profile maps a symbol column, which the file then lacks."""
    symbol = profile.columns.symbol
    return "" if symbol is None else f" (the profile maps {symbol!r}, which the file lacks)"


def _contract_in_name(profile: ImportProfile, facts: ImportFacts) -> str | None:
    """The contract the profile's pattern finds in the file's name, by the groups `contract`,
    or `root` and `year` (two or four digits) with `month` (1 to 12) or `code` (a letter)."""
    if profile.contract_in_file_name is None:
        return None
    found = re.search(profile.contract_in_file_name, facts.file_name)
    if found is None:
        return None
    groups = {name: value for name, value in found.groupdict().items() if value is not None}
    if "contract" in groups:
        return groups["contract"]
    if not names_a_contract(set(groups)) or not groups["year"].isdigit():
        raise ValueError(
            f"Expected the pattern of the profile {profile.name} to find a contract, or a root, "
            f"a year, and a month or a code, in {facts.file_name}, got {groups}."
        )
    year = int(groups["year"])
    # shortcut: a two-digit year means 20xx; resolve it from the rows' dates, as
    # `expiry_month` does for symbols, when an export from before 2000 arrives.
    full_year = year + 2000 if year < 100 else year
    return f"{groups['root']}{_month_code(groups, facts.file_name)}{full_year:04d}"


def _month_code(groups: dict[str, str], file_name: str) -> str:
    """The month code a pattern found: its `code`, or the letter of its `month`, 1 to 12."""
    if "code" in groups:
        return groups["code"]
    month = groups["month"]
    if not month.isdigit() or not 1 <= int(month) <= 12:
        raise ValueError(f"Expected a month from 1 to 12 in {file_name}, got {month!r}.")
    return MONTH_CODES[int(month) - 1]


def _contracts_of_symbols(
    rows: pl.DataFrame, root: str | None, file_name: str
) -> tuple[pl.DataFrame, str, int]:
    """Each row's contract from its symbol and the dates of its run of rows; the rows of
    spread and strategy symbols are set aside and counted."""
    with_runs = rows.join(_symbol_runs(rows), on="row", maintain_order="left")
    first_day = pl.col("instant").min().cast(pl.Datetime("ns")).dt.date()
    last_day = pl.col("instant").max().cast(pl.Datetime("ns")).dt.date()
    runs = with_runs.group_by("symbol", "run").agg(first=first_day, last=last_day, rows=pl.len())
    named = pl.DataFrame(
        [
            (symbol, run, contract)
            for symbol, run, first, last, _ in runs.iter_rows()
            if (contract := _contract_of_symbol(symbol, first, last)) is not None
        ],
        schema={"symbol": pl.String, "run": pl.UInt32, "contract": pl.String},
        orient="row",
    )
    spread_rows = int(runs.join(named, on=["symbol", "run"], how="anti").get_column("rows").sum())
    outrights = with_runs.join(named, on=["symbol", "run"], maintain_order="left")
    roots = sorted({parse_contract_name(contract)[0] for contract in named.get_column("contract")})
    if len(roots) != 1:
        raise ValueError(
            f"Expected the records of one product in {file_name}, got {', '.join(roots) or 'none'}: "
            "import each product's file apart."
        )
    _require_one_root(root, roots[0], named.item(0, "contract"))
    named_rows = outrights.with_columns(root=pl.lit(roots[0])).drop("symbol", "run")
    return named_rows, roots[0], spread_rows


def _symbol_runs(rows: pl.DataFrame) -> pl.DataFrame:
    """Each row's run of its symbol: the symbol's rows in time order, a new run after a pause
    of over a year, as a one-digit-year symbol such as `ESH6` comes back ten years on."""
    paused = (pl.col("instant").diff() > _RUN_GAP).fill_null(False).cast(pl.UInt32)
    return (
        rows.select("row", "symbol", "instant")
        .sort("symbol", "instant")
        .select("row", run=paused.cum_sum().over("symbol").cast(pl.UInt32))
    )


def _contract_of_symbol(symbol: str, first: date, last: date) -> str | None:
    """The contract a symbol names, such as ESH2026 for `ESH2026`, or for `ESH6` seen in 2026;
    None for a spread or a strategy."""
    try:
        parse_contract_name(symbol)
    except ValueError:
        found = OUTRIGHT_SYMBOL.fullmatch(symbol)
        if found is None:
            return None
        month = expiry_month(symbol, first, last)
        return f"{found[1]}{MONTH_CODES[month.month - 1]}{month.year:04d}"
    return symbol
