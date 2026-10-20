"""The contracts of a trader's export (step 1.10): each record's root and contract, as the
import profile and the import name them (`fefat.market.importers.profile_records`).

A continuous series is the one contract `<root>-CONTINUOUS` of the profile's root. Otherwise the
contract is the one the import names; the one the profile's pattern finds in the file's name,
by its groups `contract`, or `root` and `year` (two or four digits) with `month` (a number) or
`code` (a letter); each row's symbol, a four-digit-year contract such as `ESH2026` or a venue's
outright such as `ESH6`, whose decade its dates decide (`fefat.market.contracts`), the rows of
spread and strategy symbols set aside and counted; or, for a perpetual or a spot pair, the root
itself. A file holds one product, and the root the import names, or the profile's, must be it.
"""

import re
from dataclasses import dataclass
from datetime import date

import polars as pl

from fefat.market.contracts import MONTH_CODES, OUTRIGHT_SYMBOL, expiry_month, parse_contract_name
from fefat.market.importers.profiles import ImportProfile, NewInstrument
from fefat.market.layout import SeriesKind

CONTINUOUS_CONTRACT_SUFFIX = "CONTINUOUS"
"""A continuous series is stored as the one contract `<root>-CONTINUOUS`."""


@dataclass(frozen=True)
class ImportFacts:
    """What an import knows besides its profile: the name of the file its records are in, and
    the contract, root, and time zone the command names, each None when it names none."""

    file_name: str
    contract: str | None
    root: str | None
    time_zone: str | None


def with_contracts(
    rows: pl.DataFrame, profile: ImportProfile, facts: ImportFacts
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
    if root is not None:
        return rows.with_columns(root=pl.lit(root), contract=pl.lit(root)), root, 0
    raise ValueError(
        f"Expected the contract of the records of {facts.file_name}: name it, such as "
        "--contract ESH2026, name the file as its platform does, or map a symbol column."
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


def _contract_in_name(profile: ImportProfile, facts: ImportFacts) -> str | None:
    """The contract the profile's pattern finds in the file's name, by the groups `contract`,
    or `root` and `year` (two or four digits) with `month` (a number) or `code` (a letter)."""
    if profile.contract_in_file_name is None:
        return None
    found = re.search(profile.contract_in_file_name, facts.file_name)
    if found is None:
        return None
    groups = {name: value for name, value in found.groupdict().items() if value is not None}
    if "contract" in groups:
        return groups["contract"]
    year = int(groups["year"])
    full_year = year + 2000 if year < 100 else year
    code = groups["code"] if "code" in groups else MONTH_CODES[int(groups["month"]) - 1]
    return f"{groups['root']}{code}{full_year:04d}"


def _contracts_of_symbols(
    rows: pl.DataFrame, root: str | None, file_name: str
) -> tuple[pl.DataFrame, str, int]:
    """Each row's contract from its symbol; the rows of spread and strategy symbols are set
    aside and counted."""
    first_day = pl.col("instant").min().cast(pl.Datetime("ns")).dt.date()
    last_day = pl.col("instant").max().cast(pl.Datetime("ns")).dt.date()
    symbols = rows.group_by("symbol").agg(first=first_day, last=last_day, rows=pl.len())
    named = {
        symbol: contract
        for symbol, first, last, _ in symbols.iter_rows()
        if (contract := _contract_of_symbol(symbol, first, last)) is not None
    }
    spread_rows = int(symbols.filter(~pl.col("symbol").is_in(list(named))).get_column("rows").sum())
    outrights = rows.filter(pl.col("symbol").is_in(list(named))).with_columns(
        contract=pl.col("symbol").replace_strict(named, return_dtype=pl.String)
    )
    roots = sorted({parse_contract_name(contract)[0] for contract in named.values()})
    if len(roots) != 1:
        raise ValueError(
            f"Expected the records of one product in {file_name}, got {', '.join(roots) or 'none'}: "
            "import each product's file apart."
        )
    _require_one_root(root, roots[0], named[next(iter(named))])
    return outrights.with_columns(root=pl.lit(roots[0])).drop("symbol"), roots[0], spread_rows


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
