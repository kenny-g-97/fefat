"""A saved run's results for all its trades, its long trades, and its short trades (step 5.22,
D-119, D-122), worked out from its trades, trade paths, fills, and trade dates, with no change to
the engine or to the run.

Each figure the engine's metrics define is theirs. For all trades they are the run's own, whose
drawdown, longest spell under a peak, and Sharpe ratio mark open trades to market. For a side they
are the engine's metrics on its trades and on its closed-trade walk: the capital, then the equity
after each of its trades in the order they closed, on the trade date of its last exit, and at the
end of every trade date the run was valued on, so that a day without a trade of the side counts
nothing in its Sharpe ratio, as the metrics count a flat day, and the walk's peak is its last
point there, as an account valued at each decision has it.

Beside them stand what the trades hold: the gross profit and the gross loss, the winners' and the
losers' net P&L, whose ratio is the profit factor; the average win over the size of the average
loss; the commissions and fees, and a perpetual's funding received; the slippage, each fill's ticks
of slippage at its lots and the tick's value, rounded up as every amount is (F-FEE-03), a fill
counted to the trade whose path names it, and one that reverses a position (S-fill-042) to the
trade it closes at the lots that trade held and to the trade it opens at the rest, as the engine
shares its fee; the trades a day over the run's trade dates; and the average time from a trade's
entry to its last exit, breaks and nights counted, and its MAE and MFE in ticks. Sums and closed
trades alone: a position still open when the run ends is in none of them. A side the run made no
trade on is none; elsewhere a figure with nothing to count is none, as the metrics leave it, and a
sum over no trade is zero.

    sides = ff.backtest.results_by_side(run)
    sides.all_trades.net_pnl, sides.long.slippage, sides.short is None
"""

from dataclasses import dataclass
from decimal import Decimal

import fefat_engine
import polars as pl
from pydantic import Field

from fefat.backtest.artifacts import read_artifact
from fefat.backtest.metrics import Metrics, TradeStatistics
from fefat.backtest.metrics_inputs import metrics_inputs_json
from fefat.backtest.record import Window
from fefat.backtest.runs import Run
from fefat.backtest.schemas import PathPointKind
from fefat.market.engine_units import (
    InstrumentParameters,
    instrument_parameters,
    micro_units,
    money_text,
)
from fefat.market.instruments import InstrumentKind
from fefat.market.schema import FrozenModel
from fefat.reference.orders import PositionSide

NANOSECONDS_A_MINUTE = 60_000_000_000
UNREAD_TIME_ZONE = "UTC"
"""The time zone a side's entry hours are read in: they feed the breakdowns of its metrics alone,
which are not read, so no exchange's is looked up."""


class SideResults(FrozenModel):
    """The figures of a run's trades of one side, or of all of them (module docstring), money in
    the instrument's currency, the time held in minutes, and the excursions in ticks."""

    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None
    net_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: float | None
    expectancy: float | None
    expectancy_r: float | None
    average_win: float | None
    average_loss: float | None
    win_loss_ratio: float | None
    fees: Decimal
    funding: Decimal | None
    slippage: Decimal
    trades_per_day: float | None
    average_minutes_held: float | None
    average_mae_ticks: float | None
    average_mfe_ticks: float | None
    max_drawdown: Decimal
    longest_drawdown_days: int = Field(ge=0)
    sharpe: float | None


class ResultsBySide(FrozenModel):
    """A run's figures for all its trades, and for its long and its short trades, each none where
    the run made no trade on that side."""

    all_trades: SideResults
    long: SideResults | None
    short: SideResults | None


@dataclass(frozen=True)
class SideAccount:
    """What a side's figures are worked out against: the run's capital in micro-units, its
    instrument, its window, its fills, the trade dates it was valued on, in order, and whether it
    trades a perpetual."""

    capital: int
    parameters: InstrumentParameters
    window: Window
    fills: pl.DataFrame
    days: pl.Series
    perpetual: bool

    def side(self, trades: pl.DataFrame, side: PositionSide) -> SideResults | None:
        """The figures of the trades of `side` among `trades`, charged as `charged_trades` charges
        them; none without one."""
        sided = trades.filter(pl.col("side") == str(side))
        if sided.is_empty():
            return None
        return self.figures(sided, self.metrics_of(sided))

    def metrics_of(self, trades: pl.DataFrame) -> Metrics:
        """The engine's metrics of `trades` alone on their closed-trade walk (`walk`). Their
        breakdowns and robustness summary are not read, so what those alone read, the entry's hour,
        the rerun at one more tick, the parameters, and the friction, is left at nothing."""
        document = metrics_inputs_json(
            {"trades": trades, "fills": self.fills, "equity": self.walk(trades)},
            capital=self.capital,
            instrument=self.parameters,
            window=self.window,
            time_zone=UNREAD_TIME_ZONE,
            pnl_at_plus_one_tick=0,
            parameters=0,
            friction_tested=False,
        )
        return Metrics.model_validate_json(fefat_engine.metrics(document))

    def walk(self, trades: pl.DataFrame) -> pl.DataFrame:
        """The account of `trades` alone, `trade_date` and `equity` (module docstring): after each
        in the order they closed, on the trade date of its last exit, and at the end of each trade
        date the run was valued on; refused for a trade whose last exit falls on none of them."""
        dates = self.days.to_frame("trade_date")
        exits = trades.select(pl.col("exit_trade_date").alias("trade_date"), "pnl")
        stray = exits.join(dates, on="trade_date", how="anti")
        if not stray.is_empty():
            raise ValueError(
                "Expected each trade's last exit on a trade date the run was valued on, got "
                f"{stray.item(0, 'trade_date')}."
            )
        after_each = exits.select("trade_date", equity=pl.col("pnl").cum_sum() + self.capital)
        made = exits.group_by("trade_date").agg(pl.col("pnl").sum())
        at_each_day = dates.join(made, on="trade_date", how="left", maintain_order="left").select(
            "trade_date", equity=pl.col("pnl").fill_null(0).cum_sum() + self.capital
        )
        return pl.concat([after_each, at_each_day]).sort("trade_date", maintain_order=True)

    def figures(self, trades: pl.DataFrame, metrics: Metrics) -> SideResults:
        """The figures of `trades`, charged as `charged_trades` charges them, those the metrics
        define taken from `metrics`."""
        statistics, pnl, count = metrics.trades, trades.get_column("pnl"), trades.height
        held = _total(trades.get_column("exit_ts") - trades.get_column("entry_ts"))
        return SideResults(
            trades=statistics.trades,
            wins=statistics.wins,
            losses=statistics.losses,
            win_rate=statistics.win_rate,
            net_pnl=metrics.pnl,
            gross_profit=_money(pnl.filter(pnl > 0)),
            gross_loss=_money(pnl.filter(pnl < 0)),
            profit_factor=statistics.profit_factor,
            expectancy=statistics.expectancy,
            expectancy_r=statistics.expectancy_r,
            average_win=statistics.average_win,
            average_loss=statistics.average_loss,
            win_loss_ratio=_win_loss_ratio(statistics),
            fees=_money(trades.get_column("fees")),
            funding=_money(trades.get_column("funding")) if self.perpetual else None,
            slippage=_money(trades.get_column("slippage")),
            trades_per_day=_ratio(count, self.days.len()),
            average_minutes_held=_ratio(held, count * NANOSECONDS_A_MINUTE),
            average_mae_ticks=_ratio(_total(trades.get_column("mae_ticks")), count),
            average_mfe_ticks=_ratio(_total(trades.get_column("mfe_ticks")), count),
            max_drawdown=metrics.drawdown.max_drawdown,
            longest_drawdown_days=metrics.drawdown.longest_drawdown_days,
            sharpe=metrics.daily.sharpe,
        )


def results_by_side(run: Run) -> ResultsBySide:
    """The figures of `run`'s trades, all of them, its long ones, and its short ones (module
    docstring)."""
    parameters, fills = instrument_parameters(run.record.instrument), run.fills
    trades = charged_trades(run.trades, run.trade_paths, fills, parameters)
    account = SideAccount(
        capital=micro_units(run.config.capital),
        parameters=parameters,
        window=run.record.window,
        fills=fills,
        days=valued_trade_dates(read_artifact(run.folder, "equity")),
        perpetual=run.record.instrument.kind == InstrumentKind.PERPETUAL,
    )
    return ResultsBySide(
        all_trades=account.figures(trades, run.metrics),
        long=account.side(trades, PositionSide.LONG),
        short=account.side(trades, PositionSide.SHORT),
    )


def charged_trades(
    trades: pl.DataFrame,
    paths: pl.DataFrame,
    fills: pl.DataFrame,
    parameters: InstrumentParameters,
) -> pl.DataFrame:
    """`trades` with `slippage`, what their fills' slippage cost in micro-units, and
    `exit_trade_date`, the trade date of their last exit (module docstring), each fill found by
    the order and the instant its path names."""
    numbered = trades.with_row_index("trade").with_columns(pl.col("trade").cast(pl.Int64))
    opened = numbered.select(
        pl.col("entry_order").alias("order"),
        pl.col("entry_ts").alias("ts"),
        pl.col("trade").alias("opened"),
        pl.col("lots").alias("opened_lots"),
    )
    points = paths.filter(pl.col("kind") == str(PathPointKind.FILL)).select("trade", "order", "ts")
    named = fills.select("order", "ts", "lots", "slippage_ticks", "trade_date")
    paired = points.join(named, on=["order", "ts"], how="left", validate="m:1")
    _refuse_unpaired(paired, numbered)
    shared = pl.col("lots") - pl.col("opened_lots").fill_null(0)
    lots = pl.when(pl.col("trade") == pl.col("opened")).then("opened_lots").otherwise(shared)
    tick_lots = paired.join(opened, on=["order", "ts"], how="left").select(
        "trade", "ts", "trade_date", tick_lots=pl.col("slippage_ticks") * lots
    )
    worth = {
        ticks: parameters.worth_of_ticks(ticks, 1)
        for ticks in tick_lots.get_column("tick_lots").unique().to_list()
    }
    charged = tick_lots.group_by("trade").agg(
        slippage=pl.col("tick_lots").replace_strict(worth, return_dtype=pl.Int64).sum(),
        exit_trade_date=pl.col("trade_date").sort_by("ts").last(),
    )
    return numbered.join(charged, on="trade", how="left", maintain_order="left").drop("trade")


def valued_trade_dates(equity: pl.DataFrame) -> pl.Series:
    """The trade dates on which `equity`, a run's account after each decision, was valued, in
    order, the days its metrics count."""
    valued = equity.filter(pl.col("equity").is_not_null())
    return valued.get_column("trade_date").unique(maintain_order=True)


def _refuse_unpaired(paired: pl.DataFrame, trades: pl.DataFrame) -> None:
    """Refuses a fill a trade's path names that the run's fills lack, and a trade whose path names
    no fill, as a folder another program changed would hold them."""
    lacking = paired.filter(pl.col("lots").is_null())
    if not lacking.is_empty():
        trade, order = lacking.row(0)[:2]
        raise ValueError(
            "Expected each fill a trade's path names among the run's fills, got order "
            f"{order} on the path of trade {trade} alone."
        )
    bare = trades.join(paired, on="trade", how="anti")
    if not bare.is_empty():
        raise ValueError(
            f"Expected a fill on the path of each trade, got none on trade {bare.item(0, 'trade')}."
        )


def _win_loss_ratio(statistics: TradeStatistics) -> float | None:
    """The average win over the size of the average loss, none without a win or a loss."""
    if statistics.average_win is None or statistics.average_loss is None:
        return None
    return statistics.average_win / -statistics.average_loss


def _money(amounts: pl.Series) -> Decimal:
    """The sum of `amounts`, in micro-units, in the currency, exactly."""
    return Decimal(money_text(_total(amounts)))


def _total(values: pl.Series) -> int:
    """The sum of `values`, whole numbers, in Python's integers, which no sum overflows."""
    return sum(values.to_list())


def _ratio(part: int, whole: int) -> float | None:
    """`part` over `whole`, divided in Python, which rounds once; none over nothing."""
    return None if whole == 0 else part / whole
