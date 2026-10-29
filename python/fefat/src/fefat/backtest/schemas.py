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
  excursions in ticks, money, and R, and the value of each feature at its entry, as
  `<feature>_at_entry`, beside the columns of `TRADES`;
- `equity`: the account after each decision, at each signal bar's close;
- `equity_daily`: the account at each trade date's last decision and the day's profit and loss;
- `signals`: the signal frame the engine read, the strategy's features among its columns.
"""

import polars as pl

from fefat.strategy.signal_frame import REQUIRED_SIGNAL_COLUMNS

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
    "equity": EQUITY,
    "equity_daily": EQUITY_DAILY,
    "signals": SIGNALS,
}
"""Each artifact of a run by name, its file `<name>.parquet`, with the columns it holds at least."""
