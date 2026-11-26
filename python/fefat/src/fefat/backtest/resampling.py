"""A Monte Carlo over a run's trades (steps 5.20 and 5.21, D-118, D-119): how its outcome could
have varied, had its trades come in other draws. Each path draws as many trades as the run made,
with replacement, from one seed, each with its net P&L and its MAE and MFE in ticks, and walks the
capital through their net P&L in the order drawn, so that its maximum drawdown, the deepest fall of
its equity below the highest before it, the capital first, is of its closed trades; it sums the
profit of the winners it drew and every trade's excursions on the way, the losers' loss being the
rest of its equity's change. Beside the paths stand the run's own trades walked the same way in the
order it made them, since the metrics' maximum drawdown marks open trades to market and is not of
the same kind; a run's trades are flat to flat, each closed before the next opens, so that the
order the trades artifact holds them in is the order their P&L was made.

The report gives the net P&L and the maximum drawdown at the 5th, 25th, 50th, 75th, and 95th
percentiles, each the amount of the path at that rank, the nearest in the paths ordered from the
lowest (`percentiles_of`), so that it is an amount some path reached; the share of paths that end
below the capital; the share whose maximum drawdown exceeds the run's own; the equity fan, the
same percentiles of the paths' equity at no more than `max_points` counts of trades, spread evenly
from none, where every path holds the capital, to the run's trades, with the run's own walk at the
same counts; and, at each whole percent of the paths from 0 to 100, ranked the same way, their net
P&L, maximum drawdown, profit factor, the winners' profit over the losers' loss, none for a path
that drew no loser, which stands above every other, and average MAE and MFE in ticks, each beside
the run's own, whose profit factor is its metrics'. A path of trades drawn at random has no days,
so it has no Sharpe ratio. A run of fewer than two trades answers why.

The walk works a block of trade counts over every path at a time, `BLOCK_DRAWS` drawn trades a
block, each block's draws seeded in turn from the seed, so that it holds one block's walk whatever
the run, and works out the fan at the counts each block reaches. The same seed and paths give the
same report under the Polars of `uv.lock`, whose sampling draws the trades.

    report = ff.backtest.monte_carlo(run, paths=1000, seed=0)
    report.max_drawdown.p95, report.own_max_drawdown, report.net_loss_share
    report.by_percent.max_drawdown.at_percent[95], report.by_percent.profit_factor.own
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
paths of a run's 50,000 trades with a fan of 10,000 counts, the route's most, held 324 to 340 MiB
at their peak above the run's trades and took about 17 s on the PC of step 5.20, where blocks of
1,000,000 held up to 505 MiB in 11 s; on CI's Ubuntu they held 1,228 MiB, Polars' allocator there
keeping the walk's freed blocks resident, within the memory test's bound for each system. Each
drawn trade's excursions and the sums by path of step 5.21 took that to 347 to 364 MiB in about
20 s on Windows."""
DRAWN_COLUMNS = ("pnl", "mae_ticks", "mfe_ticks")
"""What a path draws of each trade from the trades artifact: its net P&L in micro-units and its MAE
and MFE in ticks."""
PERCENTILES = {"p5": 5, "p25": 25, "median": 50, "p75": 75, "p95": 95}
"""Each percentile's name and its whole percent of the paths ordered from the lowest."""
PERCENTS = 101
"""The whole percents of the paths each figure is reported at, from 0 to 100."""


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
    each column, the run's `own` equity after as many of its trades in the order made, and the
    `capital` they start from, in the instrument's currency, as numbers a chart draws: the first
    count is none, where every column holds the capital."""

    capital: float
    trades_made: tuple[int, ...]
    p5: tuple[float, ...]
    p25: tuple[float, ...]
    median: tuple[float, ...]
    p75: tuple[float, ...]
    p95: tuple[float, ...]
    own: tuple[float, ...]


class FigureByPercent(FrozenModel):
    """A figure of the paths at each whole percent of them from 0 to 100, `at_percent[95]` that of
    the path at the nearest rank of 95 % of the paths ordered from the lowest, as numbers a chart
    draws, beside the run's `own`."""

    at_percent: tuple[float, ...] = Field(min_length=PERCENTS, max_length=PERCENTS)
    own: float


class ProfitFactorByPercent(FrozenModel):
    """The paths' profit factors at each whole percent of them from 0 to 100, ranked from the
    lowest, none for a path that drew no losing trade, which stands above every other, beside the
    run's `own`, its metrics' profit factor, none for a run without a losing trade."""

    at_percent: tuple[float | None, ...] = Field(min_length=PERCENTS, max_length=PERCENTS)
    own: float | None


class FiguresByPercent(FrozenModel):
    """The paths' figures at each whole percent of them, each beside the run's own: the net P&L and
    the maximum drawdown in the instrument's currency, the profit factor, and the average MAE and
    MFE of a path's trades in ticks."""

    net_pnl: FigureByPercent
    max_drawdown: FigureByPercent
    profit_factor: ProfitFactorByPercent
    average_mae_ticks: FigureByPercent
    average_mfe_ticks: FigureByPercent


class MonteCarlo(FrozenModel):
    """`paths` walks of the run's `trades` trades drawn with replacement from `seed`, `kind`
    resampled (module docstring): the paths' net P&L and maximum drawdown at five percentiles, the
    run's own walk's net P&L and closed-trade maximum drawdown, the share of paths that end below
    the capital, the share whose maximum drawdown exceeds the run's own, the equity fan, and the
    paths' figures at each whole percent of them."""

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
    by_percent: FiguresByPercent


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
    trades = run.trades.select(DRAWN_COLUMNS)
    capital = micro_units(run.config.capital)
    return resampled_trades(trades, capital, paths=paths, seed=seed, max_points=max_points)


def resampled_trades(
    trades: pl.DataFrame, capital: int, *, paths: int, seed: int, max_points: int
) -> MonteCarlo | TooFewTrades:
    """The Monte Carlo of `trades` in the order made, each with the `DRAWN_COLUMNS` of the trades
    artifact, from `capital` in micro-units (module docstring); refused for no path, a negative
    seed, or a fan of fewer than `FEWEST_FAN_POINTS` counts."""
    _check_asked(paths, seed, max_points)
    made = trades.height
    if made < FEWEST_TRADES:
        counted = "no trade" if made == 0 else f"{made} trade"
        reason = f"This run made {counted}, and a Monte Carlo draws from at least {FEWEST_TRADES}."
        return TooFewTrades(trades=made, reason=reason)
    counts = _fan_counts(made, max_points)
    own, own_fan = _walked(_accounts(1, capital), trades, 0, counts)
    own_net_pnl, own_max_drawdown = own.select(pl.col("equity") - capital, "deepest").row(0)
    accounts, fan = _walked_paths(trades, capital, paths, seed, counts)
    return MonteCarlo(
        paths=paths,
        trades=made,
        seed=seed,
        net_pnl=percentiles_of(accounts.get_column("equity") - capital),
        max_drawdown=percentiles_of(accounts.get_column("deepest")),
        own_net_pnl=Decimal(money_text(own_net_pnl)),
        own_max_drawdown=Decimal(money_text(own_max_drawdown)),
        net_loss_share=accounts.select((pl.col("equity") < capital).mean()).item(),
        deeper_drawdown_share=accounts.select((pl.col("deepest") > own_max_drawdown).mean()).item(),
        fan=_fan(fan, own_fan, capital),
        by_percent=_by_percent(accounts, own, capital, made),
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
    """`paths` accounts at `capital`, one row a path: its `equity`, the `peak` it reached, the
    `deepest` fall below a peak so far, and the sums of the trades it drew so far, the winners'
    `profit` and every trade's `mae` and `mfe` in ticks; the losers' loss is the rest of the
    equity's change, `equity - capital - profit`."""
    zero = pl.repeat(0, paths, dtype=pl.Int64)
    return pl.select(
        equity=pl.repeat(capital, paths, dtype=pl.Int64),
        peak=pl.repeat(capital, paths, dtype=pl.Int64),
        deepest=zero,
        profit=zero,
        mae=zero,
        mfe=zero,
    )


def _walked_paths(
    trades: pl.DataFrame, capital: int, paths: int, seed: int, counts: Sequence[int]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """`paths` accounts from `capital` after as many trades as `trades` holds, drawn with
    replacement a block at a time, each block from the next seed that `seed` gives, and the fan's
    rows at the `counts` past none."""
    accounts = _accounts(paths, capital)
    seeds = random.Random(seed)
    steps = max(1, BLOCK_DRAWS // paths)
    fans = []
    for made_before in range(0, trades.height, steps):
        block = min(steps, trades.height - made_before)
        drawn = trades.sample(paths * block, with_replacement=True, seed=seeds.getrandbits(64))
        accounts, fan = _walked(accounts, drawn, made_before, counts)
        fans.append(fan)
    return accounts, pl.concat(fans)


def _walked(
    accounts: pl.DataFrame, drawn: pl.DataFrame, made_before: int, counts: Sequence[int]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """`accounts`, one row a path, after the trades of `drawn`, as many a path, path after path,
    with `made_before` trades made before them, and their equity's percentiles at the `counts` the
    block reaches, a row a count. Only these leave the function, so that a block's walk is freed
    before the next is drawn."""
    steps = drawn.height // accounts.height
    rows = drawn.with_row_index("row").select(
        *DRAWN_COLUMNS,
        path=(pl.col("row") // steps).set_sorted(),
        trades_made=pl.col("row") % steps + (made_before + 1),
    )
    carried = accounts.select(pl.col("equity", "peak").gather(rows.get_column("path")))
    walk = (
        rows.hstack(carried)
        .with_columns(equity=pl.col("equity") + pl.col("pnl").cum_sum().over("path"))
        .with_columns(peak=pl.max_horizontal("peak", pl.col("equity").cum_max().over("path")))
    )
    reached = [count for count in counts if made_before < count <= made_before + steps]
    fan = (
        walk.filter(pl.col("trades_made").is_in(reached))
        .group_by("trades_made")
        .agg(_ranked(pl.col("equity")))
    )
    return _accounts_after(accounts, walk), fan


def _accounts_after(accounts: pl.DataFrame, walk: pl.DataFrame) -> pl.DataFrame:
    """`accounts` after a block's `walk`, one row a path: where its equity and its peak ended, its
    deepest fall so far, and its sums with the block's trades added."""
    ends = walk.group_by("path", maintain_order=True).agg(
        pl.col("equity").last(),
        pl.col("peak").last(),
        (pl.col("peak") - pl.col("equity")).max().alias("deepest"),
        pl.col("pnl").clip(lower_bound=0).sum().alias("profit"),
        pl.col("mae_ticks").sum().alias("mae"),
        pl.col("mfe_ticks").sum().alias("mfe"),
    )
    return ends.select(
        "equity",
        "peak",
        deepest=pl.max_horizontal("deepest", accounts.get_column("deepest")),
        profit=pl.col("profit") + accounts.get_column("profit"),
        mae=pl.col("mae") + accounts.get_column("mae"),
        mfe=pl.col("mfe") + accounts.get_column("mfe"),
    )


def _ranked(amount: pl.Expr) -> list[pl.Expr]:
    """`amount` at each of `PERCENTILES`, the value at the nearest rank, as `_ranks` counts it."""
    return [
        amount.quantile(percent / 100, "nearest").alias(name)
        for name, percent in PERCENTILES.items()
    ]


def _ranks(paths: int) -> list[int]:
    """The rank of the path at each whole percent of `paths` ordered from the lowest, counted from
    none: `round((paths - 1) * percent / 100)`, a half rounded up, in whole numbers, where Polars'
    nearest quantile lands for each of `PERCENTILES` and every count of paths a client can ask."""
    return [((paths - 1) * percent * 2 + 100) // 200 for percent in range(PERCENTS)]


def _at_each_percent(ordered: pl.Series) -> pl.Series:
    """`ordered`, sorted from the lowest, at each whole percent of it (`_ranks`)."""
    return ordered.gather(_ranks(ordered.len()))


def percentiles_of(amounts: pl.Series) -> Percentiles:
    """`amounts`, whole micro-units, at each of `PERCENTILES`, in the currency: the amount at the
    rank `round((n - 1) * share)` of the `n` ordered from the lowest and counted from none, a half
    rounded up (`_ranks`), so that each is one of `amounts`."""
    ranked = _at_each_percent(amounts.sort()).to_list()
    return Percentiles.model_validate(
        {name: Decimal(money_text(ranked[percent])) for name, percent in PERCENTILES.items()}
    )


def _fan(rows: pl.DataFrame, own_rows: pl.DataFrame, capital: int) -> EquityFan:
    """The fan of the paths' `rows`, a row a count past none, after none at `capital`, with the
    run's own walk at the same counts from its `own_rows`, in which every percentile is its own."""
    at_capital = capital / MONEY_SCALE

    def column(fan_rows: pl.DataFrame, name: str) -> tuple[float, ...]:
        ordered = fan_rows.sort("trades_made").get_column(name).cast(pl.Int64)
        return (at_capital, *money_in_units(ordered))

    return EquityFan(
        capital=at_capital,
        trades_made=(0, *rows.get_column("trades_made").sort().to_list()),
        p5=column(rows, "p5"),
        p25=column(rows, "p25"),
        median=column(rows, "median"),
        p75=column(rows, "p75"),
        p95=column(rows, "p95"),
        own=column(own_rows, "median"),
    )


def _by_percent(
    accounts: pl.DataFrame, own: pl.DataFrame, capital: int, trades: int
) -> FiguresByPercent:
    """The figures at each whole percent of the paths whose `accounts` drew `trades` trades from
    `capital`, beside those of the run's `own` walk, each average a path's sum over its trades,
    which every path shares, so that the sums keep the averages' order and Python divides them
    exactly rounded."""

    def money(amount: pl.Expr) -> FigureByPercent:
        ranked = _at_each_percent(accounts.select(amount).to_series().sort())
        (own_amount,) = money_in_units(own.select(amount).to_series())
        return FigureByPercent(at_percent=money_in_units(ranked), own=own_amount)

    def average(total: str) -> FigureByPercent:
        ranked = _at_each_percent(accounts.get_column(total).sort()).to_list()
        return FigureByPercent(
            at_percent=tuple(summed / trades for summed in ranked),
            own=own.get_column(total).item() / trades,
        )

    return FiguresByPercent(
        net_pnl=money(pl.col("equity") - capital),
        max_drawdown=money(pl.col("deepest")),
        profit_factor=_profit_factors(accounts, own, capital),
        average_mae_ticks=average("mae"),
        average_mfe_ticks=average("mfe"),
    )


def _profit_factors(
    accounts: pl.DataFrame, own: pl.DataFrame, capital: int
) -> ProfitFactorByPercent:
    """The paths' profit factors from their `accounts` from `capital` at each whole percent of
    them, those of paths that drew no loser, none, ranked above every other, beside the run's
    `own` walk's."""
    ranked = _at_each_percent(_profit_factor_of(accounts, capital).sort(nulls_last=True))
    return ProfitFactorByPercent(
        at_percent=tuple(ranked.to_list()),
        own=_profit_factor_of(own, capital).item(),
    )


def _profit_factor_of(accounts: pl.DataFrame, capital: int) -> pl.Series:
    """Each account's profit factor: the winners' profit over the losers' loss, the rest of its
    equity's change from `capital`, each a float first, as `fefat-metrics` divides them, so that
    the run's own is its metrics'; none where no trade lost. Polars divides a column by a column
    exactly rounded, where it divides by a constant a bit off."""
    loss = pl.col("equity") - capital - pl.col("profit")
    return accounts.select(
        pl.when(loss < 0).then(pl.col("profit").cast(pl.Float64) / (-loss).cast(pl.Float64))
    ).to_series()
