"""A saved run's trades in context (step 5.9, D-93): a page of its chart, its bars from the store at
the prices each contract traded at, with the trades the page shows, their fills on its bars and
their levels, and the strategy's features beside the bars (`fefat.backtest.review_window`); and
a trade's explanation, an `explain` job, since a replay through the reference engine can take
seconds (`fefat_app.jobs.trade_explanations`). The run is found, and its files refused, as its
results are (`Runs.reading`); a window the SDK refuses is refused apart, as the bars' route
refuses it."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fefat.backtest import ReviewWindow, review_window
from fefat.backtest.record import RunRecord
from fefat.market.calendar import utc_text
from fefat.market.engine_units import money_text, price_text
from fefat.market.store import Store
from fefat.reference.orders import OrderRole, PositionSide, Side
from fefat_app.job_models import Job, JobKind
from fefat_app.runs import ResultsRefusedError
from fefat_app.services.jobs import Jobs
from fefat_app.services.market_bars import (
    BarPrices,
    BarsPage,
    BarsRequest,
    NoSuchInstrumentError,
    bars_page_rows,
)
from fefat_app.services.runs import Runs
from fefat_app.trade_review import (
    ChartFeature,
    ChartFill,
    ChartPage,
    ChartTrade,
    ExplainPayload,
    FeatureUnit,
    NoSuchTradeError,
    StopLevels,
)

_NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class TradeReview:
    """A saved run's chart, over its runs and the store's bars, and its trades' explanations, as
    the jobs run them (module docstring)."""

    runs: Runs
    store: Store
    cache_folder: Path
    jobs: Jobs

    def explain(self, run: str, trade_id: int) -> Job:
        """The `explain` job of the trade `trade_id`, its entry order, of the saved run `run`,
        queued, or the one queued or running and not asked to stop; refused with
        `NoSuchTradeError` for an id no trade has, so that no job is queued to fail, and as the
        run's results are."""
        with self.runs.reading(run) as opened:
            ids = opened.trades.get_column("entry_order")
            known = ids.is_in([trade_id]).any()
        if not known:
            shown = ", ".join(str(each) for each in ids.head(5).to_list())
            raise NoSuchTradeError(
                f"Expected the id of a trade of run {opened.hash[:12]}, its entry order, such "
                f"as {shown or 'none'}, got {trade_id}."
            )
        payload = ExplainPayload(run_key=opened.hash, trade_id=trade_id)
        return self.jobs.start_unless_under_way(JobKind.EXPLAIN, payload.model_dump(mode="json"))

    def chart(self, run: str, start: str, end: date) -> ChartPage:
        """The page of the saved run `run`'s chart from `start`, a trade date or the instant a
        page opens at, to the trade date `end`: refused as the run's results are, and with
        `BarsRefusedError` for a window the SDK refuses, outside the run's own refusals, which
        would read any refusal as the folder's."""
        with self.runs.reading(run) as opened:
            asked = _bars_asked(opened.record, start, end)
        try:
            page, rows = bars_page_rows(self.store, self.cache_folder, asked)
        except NoSuchInstrumentError as unknown:
            raise ResultsRefusedError(
                f"Expected the instrument run {opened.hash[:12]} traded, got none: {unknown}"
            ) from unknown
        with self.runs.reading(run):
            window = review_window(opened, rows)
        return _chart_page(page, opened.record, window)


def _bars_asked(record: RunRecord, start: str, end: date) -> BarsRequest:
    """The bars a run's chart draws: the run's one contract, or its instrument's root spliced as
    the run read it, from the provider it read, in the strategy's timeframe, at the prices each
    bar's contract traded at, those its fills hold."""
    contract = record.config.contract
    return BarsRequest(
        instrument=record.instrument.root if contract is None else contract,
        timeframe=str(record.strategy.spec["timeframe"]),
        provider=record.config.provider,
        start=start,
        end=end,
        prices=BarPrices.RAW,
    )


def _chart_page(page: BarsPage, record: RunRecord, window: ReviewWindow) -> ChartPage:
    """The page of bars with the trades and the features of `window`, and the warnings of the
    features no chart can draw beside `load`'s."""
    left_out = tuple(
        f"The feature {name} holds no numbers, so the chart leaves it out."
        for name in window.left_out
    )
    return ChartPage(
        instrument=page.instrument,
        timeframe=page.timeframe,
        provider=page.provider,
        bars=page.bars,
        next_from=page.next_from,
        warnings=(*page.warnings, *left_out),
        tick_size=record.instrument.tick_size,
        features=_features(window),
        trades=_trades(window),
    )


def _features(window: ReviewWindow) -> tuple[ChartFeature, ...]:
    """Each feature the window holds, beside the bars, by its column's name."""
    return tuple(
        ChartFeature(
            name=name,
            unit=FeatureUnit.PRICE if name in window.distances else FeatureUnit.AS_STORED,
            values=tuple(window.features.get_column(name).to_list()),
        )
        for name in window.features.columns
        if name != "ts_close"
    )


def _trades(window: ReviewWindow) -> tuple[ChartTrade, ...]:
    """Each trade of the window, with its fills in the order they were made."""
    fills: dict[int, list[ChartFill]] = {}
    for fill in window.fills.iter_rows(named=True):
        fills.setdefault(fill["trade"], []).append(_fill(fill))
    return tuple(
        ChartTrade(
            trade=trade["trade"],
            entry_order=trade["entry_order"],
            side=PositionSide(trade["side"]),
            lots=trade["lots"],
            pnl=Decimal(money_text(trade["pnl"])),
            fills=tuple(fills.get(trade["trade"], ())),
            stop=StopLevels(first=_level(trade["stop_first"]), last=_level(trade["stop_last"])),
            targets=_targets(trade["targets"]),
        )
        for trade in window.trades.iter_rows(named=True)
    )


def _fill(fill: dict[str, Any]) -> ChartFill:
    """A fill as the chart takes it, from a row of the window's fills in the engines' units."""
    bar_open = fill["bar_open"]
    return ChartFill(
        order=fill["order"],
        role=OrderRole(fill["role"]),
        side=Side(fill["side"]),
        lots=fill["lots"],
        time=utc_text(fill["ts"]),
        bar_time=None if bar_open is None else bar_open // _NANOSECONDS_PER_SECOND,
        price=price_text(fill["price"]),
        fidelity=fill["fidelity"],
    )


def _level(units: int | None) -> str | None:
    """A level in 1e-9 units as decimal text, none where there is none."""
    return None if units is None else price_text(units)


def _targets(levels: list[int] | None) -> tuple[str, ...]:
    """A trade's targets as decimal text, none where the trade placed no bracket."""
    return () if levels is None else tuple(price_text(level) for level in levels)
