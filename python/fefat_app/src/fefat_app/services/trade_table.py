"""A saved run's trades as the table shows them (step 5.8, D-124): a page of its trades, sorted
and filtered, after the cursor the page before gave; its trades under the table's filter and its
executions, one row a fill, as the app's first downloads (D-119), each a CSV named by the
strategy, the run key's first twelve digits, and what it holds; and the trader's one SELECT over
its artifacts. The trades and the query are read through `ArtifactQueries`, which never opens the
database, and the fills through the SDK; the run is found, and its files refused, as its
results are (`Runs.reading`)."""

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from fefat.backtest import Run
from fefat.backtest.schemas import UNIT_COLUMNS, Unit
from fefat.market.calendar import utc_text
from fefat.market.engine_units import money_text, price_text
from fefat.strategy.versions import STRATEGY_NAME
from fefat_app.ports import ArtifactQueries
from fefat_app.services.runs import Runs
from fefat_app.trades import (
    ExportedFile,
    QueryAnswer,
    TradeCursor,
    TradePage,
    TradeRow,
    TradesAsked,
    TradesShown,
)

NOTEBOOK_RUN = "run"
"""The name a file of a run takes where the run names no saved strategy, as a notebook's does."""


@dataclass(frozen=True)
class TradeTable:
    """A saved run's trades, files, and queries (module docstring)."""

    runs: Runs
    queries: ArtifactQueries

    def page(self, run: str, shown: TradesShown, cursor: str | None, limit: int) -> TradePage:
        """At most `limit` of the trades of the saved run `run` that `shown` keeps, in its order,
        after the trade `cursor` ends on; `TradeCursorError` for a cursor no page of this order
        gave, and refused as the run's results are."""
        after = None if cursor is None else TradeCursor.read(cursor, shown)
        with self.runs.reading(run) as opened:
            found = self.queries.trades(
                opened.folder, TradesAsked(shown=shown, after=after, limit=limit)
            )
        last = found.rows[-1] if found.more else None
        return TradePage(
            trades=tuple(TradeRow.of(raw) for raw in found.rows),
            next_cursor=None if last is None else TradeCursor.after(last, shown).text(),
            total=found.total,
        )

    def trades_file(self, run: str, shown: TradesShown) -> ExportedFile:
        """Every trade of the saved run `run` that `shown` keeps, in its order, as the table's
        pages give them, a row each under the names of their columns."""
        with self.runs.reading(run) as opened:
            found = self.queries.trades(
                opened.folder, TradesAsked(shown=shown, after=None, limit=None)
            )
        rows = [TradeRow.of(raw).model_dump(mode="json") for raw in found.rows]
        return ExportedFile(
            name=_file_name(opened, "trades"),
            text=_csv(tuple(TradeRow.model_fields), [list(row.values()) for row in rows]),
        )

    def executions_file(self, run: str) -> ExportedFile:
        """Every fill of the saved run `run`, one row an execution, in the order the run made
        them, under the names of the fills' columns (D-119), each sent as the phase's header
        says: an instant as ISO 8601 in UTC, a price and money as decimal text."""
        units = UNIT_COLUMNS["fills"]
        with self.runs.reading(run) as opened:
            fills = opened.fills
            rows = [
                [_in_units(value, units.get(column), column) for column, value in fill.items()]
                for fill in fills.iter_rows(named=True)
            ]
        return ExportedFile(name=_file_name(opened, "executions"), text=_csv(fills.columns, rows))

    def query(self, run: str, sql: str) -> QueryAnswer:
        """The answer of the one SELECT `sql` over the artifacts of the saved run `run`;
        `QueryRefusedError` as the reader refuses it, and refused as the run's results are."""
        with self.runs.reading(run) as opened:
            return self.queries.select(opened.folder, sql)


def _file_name(run: Run, holds: str) -> str:
    """The name of a file of `run` that `holds` its trades or its executions: its strategy's,
    `NOTEBOOK_RUN` where it names no saved strategy, its run key's first twelve digits, and what
    it holds, `breakout-a73de4516bee-trades.csv`."""
    pin = run.record.strategy.saved_version
    named = pin is not None and re.fullmatch(STRATEGY_NAME, pin.name) is not None
    strategy = pin.name if pin is not None and named else NOTEBOOK_RUN
    return f"{strategy}-{run.hash[:12]}-{holds}.csv"


def _in_units(value: object, unit: Unit | None, column: str) -> object:
    """A value of the fills in the instrument's units, as the phase's header sends it; a column
    `UNIT_COLUMNS` names holds whole engine units, and anything else there is refused."""
    if value is None or unit is None:
        return value
    if type(value) is not int:
        raise ValueError(
            f"Expected a whole number of {unit} units in the fills' {column}, got {value!r}."
        )
    match unit:
        case Unit.INSTANT:
            return utc_text(value)
        case Unit.MONEY:
            return money_text(value)
        case Unit.PRICE | Unit.RATE:
            return price_text(value)


def _cell(value: object) -> str:
    """A value as a CSV holds it: None empty, a flag `true` or `false`, a date as ISO 8601."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _csv(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """`rows` under `header` as CSV (RFC 4180)."""
    written = io.StringIO()
    writer = csv.writer(written)
    writer.writerow(header)
    writer.writerows([_cell(value) for value in row] for row in rows)
    return written.getvalue()
