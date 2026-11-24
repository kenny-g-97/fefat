"""A Monte Carlo over a run's trades (step 5.20, D-118): how its outcome could have varied, had its
trades come in other draws. Each path draws as many trades as the run made, with replacement,
from one seed, and walks the capital through their net P&L in the order drawn, so that its maximum
drawdown, the deepest fall of its equity below the highest before it, the capital first, is of its
closed trades. Beside the paths stand the run's own trades walked the same way in the order it made
them, since the metrics' maximum drawdown marks open trades to market and is not of the same kind;
a run's trades are flat to flat, each closed before the next opens, so that the order the trades
artifact holds them in is the order their P&L was made.

The report gives the net P&L and the maximum drawdown at the 5th, 25th, 50th, 75th, and 95th
percentiles, each the amount of the path at that rank, the nearest in the paths ordered from the
lowest (`percentiles_of`), so that it is an amount some path reached; the share of paths that end
below the capital; the share whose maximum drawdown exceeds the run's own; and the equity fan, the
same percentiles of the paths' equity at no more than `max_points` counts of trades, spread evenly
from none, where every path holds the capital, to the run's trades. A run of fewer than two trades
answers why.

The walk works a block of trade counts over every path at a time, `BLOCK_DRAWS` drawn trades a
block, each block's draws seeded in turn from the seed, so that it holds one block's walk whatever
the run, and works out the fan at the counts each block reaches. The same seed and paths give the
same report under the Polars of `uv.lock`, whose sampling draws the trades.

    report = ff.backtest.monte_carlo(run, paths=1000, seed=0)
    report.max_drawdown.p95, report.own_max_drawdown, report.net_loss_share
"""

import random
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Literal

import polars as pl
from pydantic import Field

from fefat.backtest.equity_curves import EQUITY_POINTS
from fefat.backtest.runs import Run
from fefat.market.engine_units import MONEY_SCALE, micro_units, money_in_units, money_text
from fefat.market.schema import FrozenModel

MONTE_CARLO_PATHS = 1000
"""The paths drawn unless others are asked for."""
MONTE_CARLO_SEED = 0
"""The seed of the draws unless another is asked for."""
FEWEST_TRADES = 2
"""The fewest trades a Monte Carlo draws from: a run of one trade has one path to walk."""
FEWEST_FAN_POINTS = 2
"""The fewest counts of the fan: none, and the run's trades."""
BLOCK_DRAWS = 500_000
"""The trades drawn at a time over every path, a block of `BLOCK_DRAWS // paths` counts: 10,000
paths of a run's 50,000 trades with a fan of 10,000 counts, the route's most, held 324 to 333 MiB
at their peak above the run's trades and took about 17 s on the PC of step 5.20, within the memory
test's bound, where blocks of 1,000,000 held up to 505 MiB in 11 s."""
PERCENTILES = {"p5": 0.05, "p25": 0.25, "median": 0.5, "p75": 0.75, "p95": 0.95}
"""Each percentile's name and its share of the paths ordered from the lowest."""


class Percentiles(FrozenModel):
    """An amount at five percentiles of the paths, each the amount of the path at that rank, the
    nearest in the paths ordered from the lowest, in the instrument's currency."""

    p5: Decimal
    p25: Decimal
    median: Decimal
    p75: Decimal
    p95: Decimal


class EquityFan(FrozenModel):
    """The paths' equity at five percentiles after each count of `trades_made`, one entry a count in
    each column, and the `capital` they start from, in the instrument's currency, as numbers a chart
    draws: the first count is none, where every percentile is the capital."""

    capital: float
    trades_made: tuple[int, ...]
    p5: tuple[float, ...]
    p25: tuple[float, ...]
    median: tuple[float, ...]
    p75: tuple[float, ...]
    p95: tuple[float, ...]


class MonteCarlo(FrozenModel):
    """`paths` walks of the run's `trades` trades drawn with replacement from `seed`, `kind`
    resampled (module docstring): the paths' net P&L and maximum drawdown at five percentiles, the
    run's own walk's net P&L and closed-trade maximum drawdown, the share of paths that end below
    the capital, the share whose maximum drawdown exceeds the run's own, and the equity fan."""

    kind: Literal["resampled"] = "resampled"
    paths: int = Field(ge=1)
    trades: int = Field(ge=FEWEST_TRADES)
    seed: int = Field(ge=0)
    net_pnl: Percentiles
    max_drawdown: Percentiles
    own_net_pnl: Decimal
    own_max_drawdown: Decimal
    net_loss_share: float = Field(ge=0, le=1)
    deeper_drawdown_share: float = Field(ge=0, le=1)
    fan: EquityFan


class TooFewTrades(FrozenModel):
    """The Monte Carlo of a run of fewer than `FEWEST_TRADES` trades, `kind` too_few_trades: the
    trades it made, and why it draws no path."""

    kind: Literal["too_few_trades"] = "too_few_trades"
    trades: int = Field(ge=0, lt=FEWEST_TRADES)
    reason: str


MonteCarloAnswer = Annotated[MonteCarlo | TooFewTrades, Field(discriminator="kind")]
"""A Monte Carlo, or why a run gives none, told apart by its `kind`."""


def monte_carlo(
    run: Run,
    paths: int = MONTE_CARLO_PATHS,
    seed: int = MONTE_CARLO_SEED,
    max_points: int = EQUITY_POINTS,
) -> MonteCarlo | TooFewTrades:
    """`paths` walks of the trades of `run` drawn from `seed`, with a fan of at most `max_points`
    counts (module docstring)."""
    pnl = run.trades.get_column("pnl")
    capital = micro_units(run.config.capital)
    return resampled_trades(pnl, capital, paths=paths, seed=seed, max_points=max_points)


def resampled_trades(
    pnl: pl.Series, capital: int, *, paths: int, seed: int, max_points: int
) -> MonteCarlo | TooFewTrades:
    """The Monte Carlo of the trades whose net P&L `pnl` holds in the order made, in micro-units,
    from `capital` in micro-units (module docstring); refused for no path, a negative seed, or a fan
    of fewer than `FEWEST_FAN_POINTS` counts."""
    _check_asked(paths, seed, max_points)
    trades = pnl.len()
    if trades < FEWEST_TRADES:
        made = "no trade" if trades == 0 else f"{trades} trade"
        reason = f"This run made {made}, and a Monte Carlo draws from at least {FEWEST_TRADES}."
        return TooFewTrades(trades=trades, reason=reason)
    own, _ = _walked(_accounts(1, capital), pnl, 0, ())
    own_net_pnl, own_max_drawdown = own.select(pl.col("equity") - capital, "deepest").row(0)
    counts = _fan_counts(trades, max_points)
    accounts, fan = _walked_paths(pnl, capital, paths, seed, counts)
    return MonteCarlo(
        paths=paths,
        trades=trades,
        seed=seed,
        net_pnl=percentiles_of(accounts.get_column("equity") - capital),
        max_drawdown=percentiles_of(accounts.get_column("deepest")),
        own_net_pnl=Decimal(money_text(own_net_pnl)),
        own_max_drawdown=Decimal(money_text(own_max_drawdown)),
        net_loss_share=accounts.select((pl.col("equity") < capital).mean()).item(),
        deeper_drawdown_share=accounts.select((pl.col("deepest") > own_max_drawdown).mean()).item(),
        fan=_fan(fan, capital),
    )


def _check_asked(paths: int, seed: int, max_points: int) -> None:
    if paths < 1:
        raise ValueError(f"Expected at least 1 path, got {paths}.")
    if seed < 0:
        raise ValueError(f"Expected a seed of 0 or more, got {seed}.")
    if max_points < FEWEST_FAN_POINTS:
        raise ValueError(
            f"Expected at least {FEWEST_FAN_POINTS} points of the fan, got {max_points}."
        )


def _fan_counts(trades: int, max_points: int) -> list[int]:
    """Every count of trades from none to `trades`, or `max_points` of them spread evenly, each
    rounded to the nearest, the first none and the last `trades`."""
    if trades < max_points:
        return list(range(trades + 1))
    last = max_points - 1
    return [(2 * point * trades + last) // (2 * last) for point in range(max_points)]


def _accounts(paths: int, capital: int) -> pl.DataFrame:
    """`paths` accounts at `capital`, one row a path: its `equity`, the `peak` it reached, and the
    `deepest` fall below a peak so far."""
    return pl.select(
        equity=pl.repeat(capital, paths, dtype=pl.Int64),
        peak=pl.repeat(capital, paths, dtype=pl.Int64),
        deepest=pl.repeat(0, paths, dtype=pl.Int64),
    )


def _walked_paths(
    pnl: pl.Series, capital: int, paths: int, seed: int, counts: Sequence[int]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """`paths` accounts from `capital` after as many trades as `pnl` holds, drawn with replacement
    a block at a time, each block from the next seed that `seed` gives, and the fan's rows at the
    `counts` past none."""
    accounts = _accounts(paths, capital)
    seeds = random.Random(seed)
    steps = max(1, BLOCK_DRAWS // paths)
    fans = []
    for made_before in range(0, pnl.len(), steps):
        block = min(steps, pnl.len() - made_before)
        drawn = pnl.sample(paths * block, with_replacement=True, seed=seeds.getrandbits(64))
        accounts, fan = _walked(accounts, drawn, made_before, counts)
        fans.append(fan)
    return accounts, pl.concat(fans)


def _walked(
    accounts: pl.DataFrame, drawn: pl.Series, made_before: int, counts: Sequence[int]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """`accounts`, one row a path, after the trades of `drawn`, as many a path, path after path,
    with `made_before` trades made before them, and their equity's percentiles at the `counts` the
    block reaches, a row a count. Only these leave the function, so that a block's walk is freed
    before the next is drawn."""
    steps = drawn.len() // accounts.height
    rows = (
        drawn.to_frame("pnl")
        .with_row_index("row")
        .select(
            path=(pl.col("row") // steps).set_sorted(),
            trades_made=pl.col("row") % steps + (made_before + 1),
            pnl="pnl",
        )
    )
    carried = accounts.select(pl.col("equity", "peak").gather(rows.get_column("path")))
    walk = (
        rows.hstack(carried)
        .with_columns(equity=pl.col("equity") + pl.col("pnl").cum_sum().over("path"))
        .with_columns(peak=pl.max_horizontal("peak", pl.col("equity").cum_max().over("path")))
    )
    ends = walk.group_by("path", maintain_order=True).agg(
        pl.col("equity").last(),
        pl.col("peak").last(),
        (pl.col("peak") - pl.col("equity")).max().alias("deepest"),
    )
    after = ends.select(
        "equity",
        "peak",
        deepest=pl.max_horizontal("deepest", accounts.get_column("deepest")),
    )
    reached = [count for count in counts if made_before < count <= made_before + steps]
    fan = (
        walk.filter(pl.col("trades_made").is_in(reached))
        .group_by("trades_made")
        .agg(_ranked(pl.col("equity")))
    )
    return after, fan


def _ranked(amount: pl.Expr) -> list[pl.Expr]:
    """`amount` at each of `PERCENTILES`, the value at the nearest rank (`percentiles_of`)."""
    return [amount.quantile(share, "nearest").alias(name) for name, share in PERCENTILES.items()]


def percentiles_of(amounts: pl.Series) -> Percentiles:
    """`amounts`, whole micro-units, at each of `PERCENTILES`, in the currency: the amount at the
    rank `round((n - 1) * share)` of the `n` ordered from the lowest and counted from none, a half
    rounded up, as Polars' nearest quantile counts it, so that each is one of `amounts`."""
    ranked = amounts.to_frame("amount").select(_ranked(pl.col("amount"))).row(0, named=True)
    return Percentiles.model_validate(
        {name: Decimal(money_text(int(value))) for name, value in ranked.items()}
    )


def _fan(rows: pl.DataFrame, capital: int) -> EquityFan:
    """The fan of the paths' `rows`, a row a count past none, after none at `capital`."""
    ordered = rows.sort("trades_made")
    at_capital = capital / MONEY_SCALE

    def column(name: str) -> tuple[float, ...]:
        return (at_capital, *money_in_units(ordered.get_column(name).cast(pl.Int64)))

    return EquityFan(
        capital=at_capital,
        trades_made=(0, *ordered.get_column("trades_made").to_list()),
        p5=column("p5"),
        p25=column("p25"),
        median=column("median"),
        p75=column("p75"),
        p95=column("p95"),
    )
