"""The units of a run's artifacts (step 5.8): every number of every artifact's schema is either
in the engines' units, which `UNIT_COLUMNS` names for a reader to convert, or one a reader shows
as it is, so that a column the engine adds is placed before an export or a query shows it."""

import polars as pl

from fefat.backtest.schemas import ARTIFACT_SCHEMAS, UNIT_COLUMNS
from fefat.strategy.signal_frame import OPTIONAL_SIGNAL_COLUMNS

AS_THEY_ARE = {
    "fills": {"order", "lots", "slippage_ticks"},
    "orders": {"id", "lots", "oco", "bracket_of"},
    "log": {"order"},
    "costs": {"order"},
    "trades": {
        "lots",
        "entry_order",
        "exits",
        "rolls",
        "initial_risk_ticks",
        "mae_ticks",
        "mfe_ticks",
        "max_drawdown_ticks",
        "r_multiple",
        "mae_r",
        "mfe_r",
    },
    "trade_paths": {"trade", "order"},
    "equity": {"position"},
    "equity_daily": {"position"},
    "signals": {"size_mult"},
}
"""The numbers of each artifact a reader shows as they are: ids, rows, counts, lots, ticks, R
multiples, and a factor of the size."""


SCHEMAS = {
    **ARTIFACT_SCHEMAS,
    "signals": pl.Schema({**ARTIFACT_SCHEMAS["signals"], **OPTIONAL_SIGNAL_COLUMNS}),
}
"""Every artifact's columns, the signal frame's optional ones among them."""


def test_every_number_of_every_artifact_has_its_unit_or_is_shown_as_it_is() -> None:
    assert set(UNIT_COLUMNS) == set(SCHEMAS)
    for name, schema in SCHEMAS.items():
        numbers = {column for column, dtype in schema.items() if dtype.is_numeric()}
        assert set(UNIT_COLUMNS[name]).isdisjoint(AS_THEY_ARE[name]), name
        assert numbers == set(UNIT_COLUMNS[name]) | AS_THEY_ARE[name], name


def test_a_unit_column_is_a_whole_number_but_an_average_price() -> None:
    for name, columns in UNIT_COLUMNS.items():
        for column in columns:
            expected = pl.Float64 if (name, column) == ("trades", "exit_price") else pl.Int64
            assert SCHEMAS[name][column] == expected, (name, column)
