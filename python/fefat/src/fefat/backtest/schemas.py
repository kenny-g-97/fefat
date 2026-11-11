"""The artifacts of a run (step 2.10, `02` §7) as Polars schemas, checked when a run writes them
and when it reads them back, as the store's are (`fefat.market.schema`). Prices are int64 in
1e-9 units, money int64 in micro-units of the instrument's currency, and instants int64
nanoseconds since the Unix epoch, UTC. Each artifact is a Parquet file of the run's folder:

- `fills`: what F-TAG-01 records of each fill, the cash its value moved, its contract, and its
  trade date;
- `orders`: every order in its last state;
- `log`: the event log, each entry with its order and its rule;
- `costs`: each fee and funding payment, paid positive (F-FEE-01, F-FND-01);
- `trades`: a row per flat-to-flat trade (§20), its entry, its exits and their average price,
  its exit reason, the rolls it crossed, its money, its initial risk and R multiple, its
  excursions in ticks, money, and R, its deepest fall from its peak in ticks and money and its
  path's fidelity (step 2.13), and the value of each feature at its entry, as
  `<feature>_at_entry`, beside the columns of `TRADES`;
- `trade_paths`: a row per point of each trade's path (`03-prop-simulator.md` §4.2, step 2.13),
  `trade` its row in `trades` from 0, each fill at its own price with its `order`, each new
  favourable extreme and each new adverse one since the last favourable, the mark at each whole
  minute, and a bar's `possible_adverse` extreme, in the order they happened, every price in
  the trade's entry contract's prices;
- `equity`: the account after each decision, at each signal bar's close;
- `equity_daily`: the account at each trade date's last decision and the day's profit and loss;
- `signals`: the signal frame the engine read, the strategy's features among its columns.

From step 5.3 each column of states, such as a fill's role, is read back as one of its `StrEnum`'s
words, and each fidelity as a fidelity (`require_states`), as the Phase 2 exit's review asked:
text the engine never writes is refused, not read as a state. The `rule` columns stay text.
"""

from enum import StrEnum
from pathlib import Path

import polars as pl

from fefat.market.fidelity import parse_fidelity
from fefat.reference.event_log import EventKind
from fefat.reference.ledger import Liquidity
from fefat.reference.orders import OrderKind, OrderRole, OrderState, PositionSide, Side
from fefat.strategy.signal_frame import REQUIRED_SIGNAL_COLUMNS


class CostReason(StrEnum):
    """What a row of `costs` paid: a fill's fee (F-FEE-01) or a perpetual's funding (F-FND-01)."""

    FEE = "fee"
    FUNDING = "funding"


class PathPointKind(StrEnum):
    """A point of a trade's path (`TRADE_PATHS`): a fill, the mark at a whole minute, a new
    favourable extreme, a new adverse one since the last favourable, or a bar's possible adverse
    extreme (`03-prop-simulator.md` §4.2)."""

    FILL = "fill"
    MINUTE = "minute"
    FAVOURABLE = "favourable"
    ADVERSE = "adverse"
    POSSIBLE_ADVERSE = "possible_adverse"


FILLS = pl.Schema(
    {
        "order": pl.UInt64,
        "role": pl.String,
        "side": pl.String,
        "lots": pl.Int64,
        "ts": pl.Int64,
        "price": pl.Int64,
        "rule": pl.String,
        "fidelity": pl.String,
        "liquidity": pl.String,
        "slippage_ticks": pl.Int64,
        "ambiguous": pl.Boolean,
        "size_exceeded": pl.Boolean,
        "fee": pl.Int64,
        "cash": pl.Int64,
        "contract": pl.String,
        "trade_date": pl.Date,
    }
)
ORDERS = pl.Schema(
    {
        "id": pl.UInt64,
        "side": pl.String,
        "kind": pl.String,
        "price": pl.Int64,
        "lots": pl.Int64,
        "role": pl.String,
        "placed_at": pl.Int64,
        "activation": pl.Int64,
        "oco": pl.UInt64,
        "bracket_of": pl.UInt64,
        "state": pl.String,
    }
)
LOG = pl.Schema(
    {"ts": pl.Int64, "kind": pl.String, "order": pl.UInt64, "rule": pl.String, "text": pl.String}
)
COSTS = pl.Schema(
    {
        "ts": pl.Int64,
        "reason": pl.String,
        "order": pl.UInt64,
        "rate": pl.Int64,
        "amount": pl.Int64,
    }
)
ENGINE_TRADES = pl.Schema(
    {
        "side": pl.String,
        "lots": pl.Int64,
        "entry_order": pl.UInt64,
        "entry_decision": pl.Int64,
        "entry_ts": pl.Int64,
        "entry_price": pl.Int64,
        "entry_contract": pl.String,
        "exits": pl.Int64,
        "exit_price": pl.Float64,
        "exit_ts": pl.Int64,
        "exit_reason": pl.String,
        "exit_contract": pl.String,
        "rolls": pl.Int64,
        "gross_pnl": pl.Int64,
        "fees": pl.Int64,
        "funding": pl.Int64,
        "pnl": pl.Int64,
        "initial_risk_ticks": pl.Int64,
        "mae_ticks": pl.Int64,
        "mfe_ticks": pl.Int64,
        "mae": pl.Int64,
        "mfe": pl.Int64,
        "max_drawdown_ticks": pl.Int64,
        "max_drawdown": pl.Int64,
        "path_fidelity": pl.String,
    }
)
"""The trades as the engine records them (`fefat_run::trade_tables`)."""
TRADES = pl.Schema(
    {
        **ENGINE_TRADES,
        "entry_trade_date": pl.Date,
        "initial_risk": pl.Int64,
        "r_multiple": pl.Float64,
        "mae_r": pl.Float64,
        "mfe_r": pl.Float64,
    }
)
"""The trades artifact's columns but the features at entry: the engine's, the trade date of the
entry's fill, the initial risk over the entry's lots in micro-units, and the profit and loss and
the excursions over it, in R; the last four null for a trade without a stop."""
TRADE_PATHS = pl.Schema(
    {
        "trade": pl.Int64,
        "ts": pl.Int64,
        "price": pl.Int64,
        "kind": pl.String,
        "order": pl.UInt64,
    }
)
"""Each point of each trade's path (`fefat_run::trade_tables`): its trade's row in `trades`, its
instant and price, its kind, `fill`, `minute`, `favourable`, `adverse`, or `possible_adverse`,
and a fill's order, null for any other point."""
ENGINE_EQUITY = pl.Schema(
    {"ts": pl.Int64, "cash": pl.Int64, "position": pl.Int64, "mark": pl.Int64, "equity": pl.Int64}
)
"""The account after each decision as the engine records it (`fefat_run::trade_tables`)."""
EQUITY = pl.Schema(
    {
        "ts": pl.Int64,
        "trade_date": pl.Date,
        "cash": pl.Int64,
        "position": pl.Int64,
        "mark": pl.Int64,
        "equity": pl.Int64,
    }
)
EQUITY_DAILY = pl.Schema(
    {
        "trade_date": pl.Date,
        "cash": pl.Int64,
        "position": pl.Int64,
        "mark": pl.Int64,
        "equity": pl.Int64,
        "pnl": pl.Int64,
    }
)
SIGNALS = REQUIRED_SIGNAL_COLUMNS

ARTIFACT_SCHEMAS: dict[str, pl.Schema] = {
    "fills": FILLS,
    "orders": ORDERS,
    "log": LOG,
    "costs": COSTS,
    "trades": TRADES,
    "trade_paths": TRADE_PATHS,
    "equity": EQUITY,
    "equity_daily": EQUITY_DAILY,
    "signals": SIGNALS,
}
"""Each artifact of a run by name, its file `<name>.parquet`, with the columns it holds at least."""

STATE_COLUMNS: dict[str, dict[str, type[StrEnum]]] = {
    "fills": {"role": OrderRole, "side": Side, "liquidity": Liquidity},
    "orders": {"side": Side, "kind": OrderKind, "role": OrderRole, "state": OrderState},
    "log": {"kind": EventKind},
    "costs": {"reason": CostReason},
    "trades": {"side": PositionSide, "exit_reason": OrderRole},
    "trade_paths": {"kind": PathPointKind},
}
"""Each artifact's columns of states, with the `StrEnum` whose words they hold."""
FIDELITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "fills": ("fidelity",),
    "trades": ("path_fidelity",),
}
"""Each artifact's columns of fidelities, `trades` or `1m` (`parse_fidelity`)."""


def require_states(frame: pl.DataFrame, name: str, folder: Path) -> None:
    """Refuse the artifact `name` of the run in `folder` where a state, nulls aside, is none of
    its `StrEnum`'s words, or a fidelity no fidelity (module docstring)."""
    for column, words in STATE_COLUMNS.get(name, {}).items():
        unknown = [word for word in _words(frame, column) if word not in words]
        if unknown:
            raise ValueError(
                f"Expected the {name} artifact's {column} among {', '.join(words)}, got "
                f"{', '.join(unknown)} in {folder}."
            )
    for column in FIDELITY_COLUMNS.get(name, ()):
        for word in _words(frame, column):
            try:
                parse_fidelity(word)
            except ValueError as error:
                raise ValueError(
                    f"Expected the {name} artifact's {column} among the fidelities, got {word!r} "
                    f"in {folder}."
                ) from error


def _words(frame: pl.DataFrame, column: str) -> list[str]:
    """The column's distinct words, nulls aside, in order."""
    return frame.get_column(column).drop_nulls().unique().sort().to_list()
