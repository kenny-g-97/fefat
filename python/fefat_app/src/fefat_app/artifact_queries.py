"""DuckDB over a saved run's Parquet files (step 5.8, D-93, D-124), the adapter behind
`fefat_app.ports.ArtifactQueries`. Each read opens a connection of its own in memory, which never
opens the app's database: it reads the run's artifact files alone (`allowed_paths`), and is locked
before any SQL runs, so that no other file is read, no extension loads, nothing spills to disk,
and no setting changes. A page of the trades reads the artifacts' own whole numbers, so that each
value converts exactly in Python; the trader's one SELECT reads views in the instrument's units,
an instant a `TIMESTAMP_NS`, a price and money a `DECIMAL`, and answers at most `most_rows` rows
of at most `most_bytes` of JSON, each run of it within `timeout_seconds`, its rows and its JSON
measured in DuckDB before Python reads a row, its values as `fefat_app.answer_values` writes
them, naming no folder of this PC. In-memory DuckDB cannot open read-only, and a folder it may read it may also
write, so a write is refused by DuckDB's own parser: one statement, a SELECT (`DESCRIBE` and
`SUMMARIZE` among them)."""

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from pydantic import JsonValue

from fefat.backtest.schemas import ARTIFACT_SCHEMAS, UNIT_COLUMNS, Unit
from fefat.market.engine_units import MONEY_DECIMALS, PRICE_DECIMALS, PRICE_SCALE
from fefat_app.answer_values import FolderNames, folder_names, json_value, without_folders
from fefat_app.runs import UnreadableArtifactError
from fefat_app.trades import (
    RAW_TRADE_COLUMNS,
    PnlSign,
    QueryAnswer,
    QueryColumn,
    QueryRefusedError,
    RawTrade,
    RawTrades,
    SortOrder,
    TradeCursor,
    TradeFilters,
    TradesAsked,
)

# shortcut: each connection may take 1 GB and nothing bounds how many run at once, which one
# trader's browser stays within; bound them, as with a semaphore, once the agent's queries run
# beside the trader's (Phase 8).
_CONFIGURATION: dict[str, str | bool | int | float | list[str]] = {
    "threads": 2,
    "memory_limit": "1GB",
    "temp_directory": "",
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
    "allow_community_extensions": False,
}
"""A connection's settings before it is locked: two threads and 1 GB, and no folder to spill to,
which DuckDB would otherwise add to the files it may read."""
_TRADE_ARTIFACTS = ("trades", "fills", "trade_paths")
"""The artifacts a page of the trades reads."""
_ENTRIES = (
    'entries AS (SELECT "order" AS entry_order, arg_min(fidelity, fill_row) AS fidelity '
    'FROM fills GROUP BY "order")'
)
_MARKS = (
    "marks AS (SELECT p.trade, bool_or(f.ambiguous) AS ambiguous FROM trade_paths p "
    'JOIN fills f ON f."order" = p."order" AND f.ts = p.ts WHERE p.kind = \'fill\' '
    "GROUP BY p.trade)"
)
_AMBIGUOUS_AMONG = (
    "SELECT DISTINCT p.trade FROM trade_paths p "
    'JOIN fills f ON f."order" = p."order" AND f.ts = p.ts '
    "WHERE p.kind = 'fill' AND f.ambiguous AND p.trade IN (SELECT unnest(?::BIGINT[]))"
)
_SIGNS = {PnlSign.POSITIVE: "pnl > 0", PnlSign.NEGATIVE: "pnl < 0", PnlSign.ZERO: "pnl = 0"}
_MEASURED = (
    "SELECT count(*), sum(strlen(to_json(COLUMNS(*))::VARCHAR)) "
    "FROM (SELECT * FROM (\n{select}\n) LIMIT {rows})"
)
"""How many rows a SELECT answers, up to one past the cap, and the bytes of each column's JSON,
worked out in DuckDB within its memory, so that an answer past either cap, such as one row that
lists every point of every path, is refused before Python reads it; each column is measured on
its own, so that no name the SELECT gives a column stands in for its rows."""


@dataclass(frozen=True)
class DuckDbQueries:
    """Reads of a saved run's artifacts through DuckDB (module docstring): the trader's SELECT
    answers at most `most_rows` rows of at most `most_bytes` of JSON within `timeout_seconds`."""

    timeout_seconds: float = 10.0
    most_rows: int = 10_000
    most_bytes: int = 4 * 1024 * 1024

    def trades(self, folder: Path, asked: TradesAsked) -> RawTrades:
        """The trades of the run in `folder` that `asked` keeps, in its order, after its cursor,
        at most its limit, with how many its filters keep; `FileNotFoundError` where an artifact
        is gone and `UnreadableArtifactError` where one does not read."""
        connection = _locked(folder, _TRADE_ARTIFACTS, converted=False)
        try:
            return _trades(connection, asked)
        except duckdb.Error as unreadable:
            raise UnreadableArtifactError(_scrubbed(unreadable, folder)) from unreadable
        finally:
            connection.close()

    def select(self, folder: Path, sql: str) -> QueryAnswer:
        """The answer of the one SELECT `sql` over the artifacts of the run in `folder`, each a
        view by its name; `QueryRefusedError` for any other statement, for what DuckDB refuses,
        and for an answer past the caps."""
        names = folder_names(folder)
        connection = _locked(folder, tuple(ARTIFACT_SCHEMAS), converted=True)
        try:
            select = _one_select(connection, sql, folder)
            columns, rows = self._fetched(connection, select, names)
        finally:
            connection.close()
        return self._answer(columns, rows, names)

    def _fetched(
        self, connection: duckdb.DuckDBPyConnection, select: str, names: FolderNames
    ) -> tuple[tuple[QueryColumn, ...], list[tuple[Any, ...]]]:
        """The columns of `select`'s answer and its rows, measured first (`_MEASURED`) and refused
        past `most_rows` or `most_bytes`, then read, and refused where the read answers more rows
        than its measure, as a sample may. shortcut: the SELECT runs twice, so an answer that
        changes between runs, as `random()` makes one, is measured on its first run alone; read
        it once into DuckDB's memory when the agent's queries need it (Phase 8)."""
        measured = _MEASURED.format(select=select, rows=self.most_rows + 1)
        rows, *sizes = self._within_time(connection, names, lambda: _one_row(connection, measured))
        self._refuse_past_caps(rows, sum(size for size in sizes if size is not None))

        def read() -> tuple[tuple[QueryColumn, ...], list[tuple[Any, ...]]]:
            connection.execute(select)
            columns = tuple(
                QueryColumn(name=without_folders(name, names), type=str(kind))
                for name, kind, *_ in connection.description
            )
            return columns, connection.fetchmany(self.most_rows + 1)

        columns, answered = self._within_time(connection, names, read)
        self._refuse_past_caps(len(answered), 0)
        return columns, answered

    def _within_time[T](
        self, connection: duckdb.DuckDBPyConnection, names: FolderNames, run: Callable[[], T]
    ) -> T:
        """What `run` gives, stopped once `timeout_seconds` have passed, with what DuckDB refuses
        as `QueryRefusedError` in words that name no folder of this PC."""
        timer = threading.Timer(self.timeout_seconds, connection.interrupt)
        timer.start()
        try:
            return run()
        except duckdb.InterruptException as stopped:
            raise QueryRefusedError(
                f"The query ran past {self.timeout_seconds:g} seconds, so FEAT stopped it: "
                "narrow it, or add a LIMIT."
            ) from stopped
        except duckdb.Error as refused:
            raise QueryRefusedError(without_folders(_first_line(refused), names)) from refused
        finally:
            timer.cancel()
            timer.join()

    def _refuse_past_caps(self, rows: int, size: int) -> None:
        """Refuse an answer of more than `most_rows` rows or of more than `most_bytes` of JSON."""
        if rows > self.most_rows:
            raise QueryRefusedError(
                f"The query answers more than {self.most_rows:,} rows: add a LIMIT, or "
                "aggregate the rows."
            )
        if size > self.most_bytes:
            raise QueryRefusedError(
                f"The query's answer passes {self.most_bytes:,} bytes: select fewer columns or "
                "rows."
            )

    def _answer(
        self, columns: tuple[QueryColumn, ...], rows: Sequence[tuple[Any, ...]], names: FolderNames
    ) -> QueryAnswer:
        """`rows` as JSON values, refused past `most_bytes` as the server writes them, which
        DuckDB's own JSON only measures."""
        answered: list[tuple[JsonValue, ...]] = []
        size = 0
        for row in rows:
            values = tuple(json_value(value, names) for value in row)
            size += len(json.dumps(values, ensure_ascii=False).encode())
            self._refuse_past_caps(len(answered), size)
            answered.append(values)
        return QueryAnswer(columns=columns, rows=tuple(answered))


def _locked(
    folder: Path, artifacts: Sequence[str], *, converted: bool
) -> duckdb.DuckDBPyConnection:
    """A connection in memory with a view of each of `artifacts` of the run in `folder`, in the
    engines' units or `converted` to the instrument's, then locked to their files alone (module
    docstring); `FileNotFoundError` where one is gone, `UnreadableArtifactError` where DuckDB does
    not read one."""
    files = {name: folder / f"{name}.parquet" for name in artifacts}
    for path in files.values():
        if not path.is_file():
            raise FileNotFoundError(f"Expected the artifact {path.name} in {folder}, got none.")
    connection = duckdb.connect(config=dict(_CONFIGURATION))
    try:
        for name, path in files.items():
            connection.execute(_view(connection, name, path, converted=converted))
        allowed = ", ".join(_literal(path.as_posix()) for path in files.values())
        connection.execute(f"SET allowed_paths = [{allowed}]")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
    except duckdb.Error as unreadable:
        connection.close()
        raise UnreadableArtifactError(_scrubbed(unreadable, folder)) from unreadable
    return connection


def _view(connection: duckdb.DuckDBPyConnection, name: str, path: Path, *, converted: bool) -> str:
    """The view of the artifact `name` in `path`: the trades numbered by their row from 0, which
    their paths name, the fills numbered too for a page, which reads the first of each order,
    and, `converted`, each column `UNIT_COLUMNS` names in the instrument's units."""
    source = f"read_parquet({_literal(path.as_posix())}, file_row_number = true)"
    numbered = {"trades": "file_row_number AS trade, "}
    if not converted:
        numbered["fills"] = "file_row_number AS fill_row, "
    replaced = ""
    if converted:
        types = {
            row[0]: row[1]
            for row in connection.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
        }
        converts = [
            f"{_converted(column, unit, types[column])} AS {_identifier(column)}"
            for column, unit in UNIT_COLUMNS[name].items()
            if column in types
        ]
        replaced = f" REPLACE ({', '.join(converts)})" if converts else ""
    selected = f"{numbered.get(name, '')}* EXCLUDE (file_row_number){replaced}"
    return f"CREATE VIEW {name} AS SELECT {selected} FROM {source}"


def _converted(column: str, unit: Unit, kind: str) -> str:
    """The column in the instrument's units: an instant as a `TIMESTAMP_NS`, a whole number of
    price, rate, or money as the `DECIMAL` it scales to, exactly, and a price a float holds, an
    average of exits, as a float."""
    name = _identifier(column)
    if unit is Unit.INSTANT:
        return f"make_timestamp_ns({name})"
    if kind == "DOUBLE":
        return f"{name} / {PRICE_SCALE}"
    places = MONEY_DECIMALS if unit is Unit.MONEY else PRICE_DECIMALS
    return f"CAST({name} AS DECIMAL(19, 0)) * {format(Decimal(1).scaleb(-places), 'f')}"


def _trades(connection: duckdb.DuckDBPyConnection, asked: TradesAsked) -> RawTrades:
    """The page `asked` of the trades the connection's views hold (`DuckDbQueries.trades`): the
    ambiguous flag worked out over every trade's path where a filter or an export needs it, and
    otherwise for the page's trades alone, so that a page never joins the whole of the paths."""
    shown = asked.shown
    marked = shown.ambiguous is not None or asked.limit is None
    terms, values = _filtered(shown)
    after, beyond = _after(asked.after, shown.sort)
    kept = " AND ".join([*terms, *after]) or "true"
    columns = ", ".join([*map(_identifier, RAW_TRADE_COLUMNS), *(["ambiguous"] if marked else [])])
    order = "DESC" if shown.order is SortOrder.DESC else "ASC"
    limit = "" if asked.limit is None else f" LIMIT {asked.limit + 1}"
    connection.execute(
        f"{_shown(marked)} SELECT {columns} FROM shown WHERE {kept} "
        f"ORDER BY {_identifier(shown.sort)} {order} NULLS LAST, trade{limit}",
        [*values, *beyond],
    )
    names = [column[0] for column in connection.description]
    found = [dict(zip(names, row, strict=True)) for row in connection.fetchall()]
    counted = f"{_shown(marked)} SELECT count(*) FROM shown WHERE {' AND '.join(terms) or 'true'}"
    total = int(_one_row(connection, counted, values)[0])
    more = asked.limit is not None and len(found) > asked.limit
    page = found[: asked.limit] if asked.limit is not None else found
    if not marked:
        ambiguous = _ambiguous_among(connection, [row["trade"] for row in page])
        page = [{**row, "ambiguous": row["trade"] in ambiguous} for row in page]
    return RawTrades(
        rows=tuple(RawTrade.model_validate(row) for row in page), more=more, total=total
    )


def _shown(marked: bool) -> str:
    """The trades with their time held and their entry's fidelity, and, `marked`, whether a fill
    of their path is ambiguous, as a common table `shown`."""
    if marked:
        return (
            f"WITH {_ENTRIES}, {_MARKS}, shown AS (SELECT t.*, t.exit_ts - t.entry_ts AS held, "
            "e.fidelity, coalesce(m.ambiguous, false) AS ambiguous FROM trades t "
            "LEFT JOIN entries e ON e.entry_order = t.entry_order "
            "LEFT JOIN marks m ON m.trade = t.trade)"
        )
    return (
        f"WITH {_ENTRIES}, shown AS (SELECT t.*, t.exit_ts - t.entry_ts AS held, e.fidelity "
        "FROM trades t LEFT JOIN entries e ON e.entry_order = t.entry_order)"
    )


def _filtered(filters: TradeFilters) -> tuple[list[str], list[object]]:
    """The terms that keep the trades `filters` asks for, each with its parameters."""
    terms: list[str] = []
    values: list[object] = []
    for column, value in (
        ("side", filters.side),
        ("exit_reason", filters.exit_reason),
        ("fidelity", filters.fidelity),
        ("ambiguous", filters.ambiguous),
    ):
        if value is not None:
            terms.append(f"{column} = ?")
            values.append(value if isinstance(value, bool) else str(value))
    if filters.start is not None:
        terms.append("entry_trade_date >= ?")
        values.append(filters.start)
    if filters.end is not None:
        terms.append("entry_trade_date <= ?")
        values.append(filters.end)
    if filters.pnl_sign is not None:
        terms.append(_SIGNS[filters.pnl_sign])
    return terms, values


def _after(cursor: TradeCursor | None, sort: str) -> tuple[list[str], list[object]]:
    """The term that keeps the trades after the one `cursor` ends on, in its order, a trade
    without the sort's figure last either way and ties by their row, with its parameters."""
    if cursor is None:
        return [], []
    key = _identifier(sort)
    if cursor.value is None:
        return [f"({key} IS NULL AND trade > ?)"], [cursor.trade]
    beyond = ">" if cursor.order is SortOrder.ASC else "<"
    term = f"({key} {beyond} ? OR ({key} = ? AND trade > ?) OR {key} IS NULL)"
    return [term], [cursor.value, cursor.value, cursor.trade]


def _ambiguous_among(connection: duckdb.DuckDBPyConnection, trades: list[int]) -> set[int]:
    """Those of `trades` with an ambiguous fill on their path."""
    if not trades:
        return set()
    connection.execute(_AMBIGUOUS_AMONG, [trades])
    return {row[0] for row in connection.fetchall()}


def _one_row(
    connection: duckdb.DuckDBPyConnection, sql: str, values: Sequence[object] = ()
) -> tuple[Any, ...]:
    """The one row the aggregate `sql` answers."""
    connection.execute(sql, values)
    found = connection.fetchone()
    if found is None:
        raise ValueError(f"Expected one row from {sql!r}, got none.")
    return found


def _one_select(connection: duckdb.DuckDBPyConnection, sql: str, folder: Path) -> str:
    """The one SELECT of `sql`, as DuckDB's own parser reads it, without the semicolon that may
    end it; refused unless `sql` is one SELECT."""
    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as unreadable:
        raise QueryRefusedError(_scrubbed(unreadable, folder)) from unreadable
    if [statement.type for statement in statements] == [duckdb.StatementType.SELECT]:
        return statements[0].query.strip().rstrip(";").rstrip()
    got = (
        f"a {statements[0].type.name} statement"
        if len(statements) == 1
        else f"{len(statements)} statements"
    )
    raise QueryRefusedError(
        f"Expected one SELECT statement over the run's artifacts, got {got}: FEAT reads them "
        "and never writes."
    )


def _scrubbed(error: Exception, folder: Path) -> str:
    """The first line of DuckDB's words, naming no folder of this PC (`without_folders`)."""
    return without_folders(_first_line(error), folder_names(folder))


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0] if str(error) else type(error).__name__


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
