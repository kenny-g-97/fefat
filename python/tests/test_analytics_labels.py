"""Labels (step 3.8, `02-engine-and-data.md` §6 and its amendment, D-71): a forward return starts at
the open of the first bucket with volume after its bar, where a market order decided at the bar's
close fills, ends where the order decided h bars later fills, counts ticks of the forward-anchored
prices, and stays within its trade date; the excursions of an event study follow the same
entries and exits."""

from datetime import date

import polars as pl
import pytest
from pydantic import ValidationError

import fefat as ff
from fefat.analytics.labels import Label, excursions, forward_returns, is_label_column

TICK = 250_000_000
MONDAY, TUESDAY = date(2026, 1, 5), date(2026, 1, 6)
SESSIONS = [
    (MONDAY, 100, False),
    (MONDAY, 101, False),
    (MONDAY, 101, True),
    (MONDAY, 103, False),
    (MONDAY, 102, False),
    (MONDAY, 104, False),
    (TUESDAY, 200, False),
    (TUESDAY, 201, False),
    (TUESDAY, 199, False),
    (TUESDAY, 203, False),
]
"""Two trade dates of bars as trade date, open in ticks, and whether the bucket is empty: Monday's
third bucket holds no trade and repeats the price before it."""


def bars(rows: list[tuple[date, int, bool]], contract: str = "ESH2026") -> pl.LazyFrame:
    """Signal bars of `contract`, a row each of trade date, open in ticks, and whether its bucket
    is empty, each high two ticks above its open and each low two below."""
    return pl.LazyFrame(
        {
            "ts_close": list(range(1, len(rows) + 1)),
            "trade_date": [day for day, _, _ in rows],
            "contract": [contract] * len(rows),
            "open": [ticks * TICK for _, ticks, _ in rows],
            "high": [(ticks + 2) * TICK for _, ticks, _ in rows],
            "low": [(ticks - 2) * TICK for _, ticks, _ in rows],
            "zero_volume": [empty for _, _, empty in rows],
        }
    )


def entries(labelled: pl.DataFrame) -> list[float | None]:
    """Each bar's entry, `next_open`, in ticks."""
    return [None if price is None else price / TICK for price in labelled["next_open"]]


def test_a_label_starts_at_the_next_tradable_open_in_ticks() -> None:
    labelled = forward_returns(bars(SESSIONS), (1, 2), TICK).collect()

    assert entries(labelled) == [101, 103, 103, 102, 104, None, 201, 199, 203, None]
    assert labelled["forward_return_1"].to_list() == [2, 0, -1, 2, None, None, -2, 4, None, None]
    assert labelled["forward_return_2"].to_list() == [2, -1, 1, *[None] * 3, 2, *[None] * 3]


def test_a_label_stays_within_the_trade_date_and_holds_no_roll_gap() -> None:
    labelled = forward_returns(bars(SESSIONS), (3,), TICK).collect()
    monday = labelled.filter(pl.col("trade_date") == MONDAY)
    # June trades 40 ticks above March: the forward-anchored series shifts it down by the gap,
    # and the roll falls between two trade dates, which no label spans.
    march = bars([(MONDAY, 100, False), (MONDAY, 101, False), (MONDAY, 102, False)], "ESH2026")
    june = bars([(TUESDAY, 103, False), (TUESDAY, 104, False), (TUESDAY, 105, False)], "ESM2026")
    raw = pl.concat([march, june]).with_columns(
        close_raw=pl.col("open")
        + pl.when(pl.col("contract") == "ESM2026").then(40 * TICK).otherwise(0)
    )
    rolled = forward_returns(raw, (1,), TICK).collect()

    assert entries(monday)[-1] is None
    assert monday["forward_return_3"].to_list() == [1, 1, None, None, None, None]
    assert entries(rolled) == [101, 102, None, 104, 105, None]
    assert rolled["forward_return_1"].to_list() == [1, None, None, 1, None, None]


def test_a_contract_that_stopped_trading_has_no_label() -> None:
    stopped = [
        (MONDAY, 100, False),
        (MONDAY, 101, False),
        (MONDAY, 102, False),
        (MONDAY, 102, True),
        (MONDAY, 102, True),
    ]

    labelled = forward_returns(bars(stopped), (1,), TICK).collect()

    assert entries(labelled) == [101, 102, None, None, None]
    assert labelled["forward_return_1"].to_list() == [1, None, None, None, None]


def test_excursions_are_null_where_the_label_is_and_include_the_exit() -> None:
    empty_bucket_high = pl.when(pl.col("zero_volume")).then(150 * TICK).otherwise(pl.col("high"))
    stale = bars(SESSIONS[:6]).with_columns(high=empty_bucket_high)
    gap = bars([(MONDAY, 100, False), (MONDAY, 100, False), (MONDAY, 110, False)])

    held = excursions(forward_returns(stale, (2,), TICK), 2, TICK).collect()
    gapped = excursions(forward_returns(gap, (1,), TICK), 1, TICK).collect()

    assert held["mfe_ticks"].to_list() == [2, 2, 2, None, None, None]
    assert held["mae_ticks"].to_list() == [2, 2, 3, None, None, None]
    assert gapped["forward_return_1"][0] == 10
    assert gapped["mfe_ticks"][0] == 10
    assert gapped["mae_ticks"][0] == 2


def test_a_label_needs_a_whole_horizon_of_one_bar_at_least_and_a_tick() -> None:
    assert Label(5).column == "forward_return_5"
    assert is_label_column("forward_return_5")
    assert not is_label_column("stretch")
    with pytest.raises(ValueError, match="horizon as a whole number of bars from 1, got 0"):
        Label(0)
    with pytest.raises(ValueError, match="got True"):
        Label(True)
    with pytest.raises(ValueError, match="Expected a tick of at least one 1e-9 unit"):
        forward_returns(bars(SESSIONS), (1,), 0)


def strategy(**fields: object) -> ff.SignalStrategy:
    """A strategy of ES's 5-minute bars, which never enters, with `fields` in place of its own."""
    return ff.SignalStrategy.model_validate(
        {
            "instrument": "ES",
            "timeframe": "5m",
            "long_entry": pl.lit(False),
            "short_entry": pl.lit(False),
            "execution": ff.Execution(
                entry=ff.Market(), stop=ff.Stop(ticks=12), sizing=ff.Fixed(1)
            ),
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("fields", "refused"),
    [
        ({"features": {"ahead": Label(5)}}, "the label forward_return_5 in the slot ahead"),
        ({"features": {"forward_return_5": pl.col("close")}}, "the slot forward_return_5"),
        (
            {"features": {"up": pl.when(pl.col("forward_return_5") > 0).then(1).otherwise(0)}},
            "the label column forward_return_5 read by the feature up",
        ),
        (
            {"long_entry": pl.col("close") > pl.col("open") + pl.col("forward_return_1")},
            "the label column forward_return_1 read by long_entry",
        ),
    ],
)
def test_a_strategy_refuses_a_label(fields: dict[str, object], refused: str) -> None:
    # Step 3.8, Done means 2: a label reads the future, so no slot or signal of a strategy holds
    # or reads one.
    with pytest.raises(ValidationError, match=f"{refused}: a label reads the future"):
        strategy(**fields)
