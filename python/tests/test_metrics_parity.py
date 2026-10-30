"""`fefat_engine.metrics` against their definitions in plain Python (`metrics_by_definition`) on
1,000 runs drawn from a fixed seed (step 2.11, Done means 1): each run's trades on ES, MES, or a
perpetual's lots, with their excursions, their moves between them, their costs, and their stops,
and its account after each decision over up to 60 trade dates. Counts, money, and trade dates
must be equal; a float must lie within 1e-9 of the definition's, relative, or 1e-12 absolute,
and a metric that cannot be worked out is none in both. The robustness summary's inputs to the
skill's script are their definitions, and its scores, verdict, and red flags are the script's on
the inputs it records. Every example's output also reads as
`fefat.backtest.metrics.Metrics`, so the model holds every field the engine writes."""

import json
import math
import time
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import fefat_engine
import pytest
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from fefat.backtest.metrics import Metrics
from fefat.reference.orders import OrderRole
from metrics_by_definition import NANO_UNITS, metrics_by_definition, scripts_summary

PARITY_SEED = 20261030
EXAMPLES = 1_000
INSTRUMENTS = (
    {"tick_size": 250_000_000, "money_per_point": 50_000_000},
    {"tick_size": 250_000_000, "money_per_point": 5_000_000},
    {"tick_size": 100_000_000, "money_per_point": 1_000},
)
"""ES, 12.50 USD a tick; MES, 1.25; and BTCUSDT-PERP's lots of 0.001 BTC, 0.0001 USD a tick."""
FIDELITIES = ("tbbo", "trades", "1s", "1m", "5m")
FIRST_TRADE_DATE = date(2024, 12, 20)
RELATIVE, ABSOLUTE = 1e-9, 1e-12

type Json = dict[str, Any]


@st.composite
def trade_outcomes(draw: st.DrawFn, instrument: Json, trade_dates: list[str]) -> Json:
    """A trade whose exit lies between its worst and best marks, a tick or two beyond at most,
    which pays up to 50 ticks of costs and up to 20 ticks of funding either way."""
    lots = draw(st.integers(min_value=1, max_value=5))
    tick = Fraction(instrument["tick_size"] * instrument["money_per_point"] * lots, NANO_UNITS)
    mae, mfe = draw(st.integers(0, 400)), draw(st.integers(0, 400))
    move = draw(st.integers(-mae - 2, mfe + 2))
    gross = round(move * tick) + draw(st.integers(-1, 1))
    costs = round(draw(st.integers(0, 50)) * tick) - round(draw(st.integers(-20, 20)) * tick)
    stop = draw(st.none() | st.integers(min_value=1, max_value=400))
    return {
        "pnl": gross - costs,
        "gross_pnl": gross,
        "lots": lots,
        "initial_risk": None if stop is None else math.ceil(stop * tick),
        "mae_ticks": mae,
        "mfe_ticks": mfe,
        "entry_trade_date": draw(st.sampled_from(trade_dates)),
        "entry_hour": draw(st.integers(0, 23)),
        "exit_reason": draw(st.sampled_from([role.value for role in OrderRole])),
        "fidelity": draw(st.sampled_from(FIDELITIES)),
    }


@st.composite
def metrics_inputs(draw: st.DrawFn) -> Json:
    """A run: its capital, instrument, trials, large daily loss, its trades on its trade dates,
    and its account after each decision, one to six a trade date, around the capital, or, for a
    steady account, moving by the same step each trade date."""
    capital = draw(st.integers(min_value=10**9, max_value=10**12))
    gaps = draw(st.lists(st.integers(min_value=1, max_value=4), max_size=60))
    trade_dates = [
        FIRST_TRADE_DATE + timedelta(days=sum(gaps[:index])) for index in range(len(gaps))
    ]
    texts = [day.isoformat() for day in trade_dates] or [FIRST_TRADE_DATE.isoformat()]
    swing = capital // draw(st.sampled_from([5, 50, 5_000]))
    steady = draw(st.none() | st.integers(-swing // 60, swing // 60))
    equity = [
        {
            "trade_date": text,
            "equity": capital
            + (draw(st.integers(-swing, swing)) if steady is None else (day + 1) * steady),
        }
        for day, text in enumerate(texts[: len(trade_dates)])
        for _ in range(draw(st.integers(min_value=1, max_value=6)))
    ]
    instrument = draw(st.sampled_from(INSTRUMENTS))
    return {
        "capital": capital,
        "instrument": instrument,
        "trials": draw(st.sampled_from([1, 1, 2, 7, 100, 10_000])),
        "large_daily_loss": draw(st.sampled_from([20_000_000, 1_000_000, 100_000_000])),
        "pnl_at_plus_one_tick": draw(st.integers(-(10**10), 10**10)),
        "window": {
            "start": (FIRST_TRADE_DATE - timedelta(days=draw(st.integers(0, 400)))).isoformat(),
            "end": (
                date.fromisoformat(texts[-1]) + timedelta(days=draw(st.integers(0, 4_400)))
            ).isoformat(),
        },
        "parameters": draw(st.integers(min_value=0, max_value=12)),
        "friction_tested": draw(st.booleans()),
        "trades": draw(st.lists(trade_outcomes(instrument, texts), max_size=250)),
        "equity": equity,
    }


def differences(engine: Any, expected: Any, path: str = "metrics") -> list[str]:
    """Where `engine`, the engine's JSON, differs from `expected`, the definition's."""
    if isinstance(expected, dict):
        if not isinstance(engine, dict) or set(engine) != set(expected):
            return [f"{path}: keys {sorted(engine)} != {sorted(expected)}"]
        return [
            found
            for key in expected
            for found in differences(engine[key], expected[key], f"{path}.{key}")
        ]
    if isinstance(expected, Decimal):
        same = isinstance(engine, str) and Decimal(engine) == expected
    elif isinstance(expected, float):
        same = isinstance(engine, float) and math.isclose(
            engine, expected, rel_tol=RELATIVE, abs_tol=ABSOLUTE
        )
    else:
        same = type(engine) is type(expected) and engine == expected
    return [] if same else [f"{path}: engine {engine!r} != definition {expected!r}"]


def coverage_of(inputs: Json, expected: Json) -> Counter[str]:
    """The kinds of run an example drew, which the test requires each at least once."""
    trades, daily, drawdown = expected["trades"], expected["daily"], expected["drawdown"]
    reached = Counter[str]()
    reached["no trades"] += not inputs["trades"]
    reached["no losing trade"] += bool(inputs["trades"]) and trades["profit_factor"] is None
    reached["a profit factor"] += trades["profit_factor"] is not None
    reached["trades without a stop"] += any(t["initial_risk"] is None for t in inputs["trades"])
    reached["one trade date"] += daily["days"] == 1
    reached["a Sharpe ratio"] += daily["sharpe"] is not None
    reached["a Sortino ratio without a Sharpe ratio"] += (
        daily["sortino"] is not None and daily["sharpe"] is None
    )
    reached["a deflated Sharpe ratio below the probabilistic"] += (
        daily["deflated_sharpe"] is not None
        and daily["deflated_sharpe"] < daily["probabilistic_sharpe"]
    )
    reached["a large daily loss"] += daily["large_daily_losses"] > 0
    reached["a best day's share"] += daily["best_day_share"] is not None
    reached["a drawdown"] += drawdown["peak"] is not None
    reached["several trades a trade date"] += len(
        {trade["entry_trade_date"] for trade in inputs["trades"]}
    ) < len(inputs["trades"])
    robustness = expected["robustness"]
    reached[f"the verdict {robustness['verdict']}"] += 1
    reached["a red flag"] += bool(robustness["red_flags"])
    reached["a run fragile to slippage"] += robustness["fragile_to_slippage"]
    return reached


def test_the_engines_metrics_are_their_definitions_on_1000_random_runs(
    draws_of_the_seed_alone: None, capsys: pytest.CaptureFixture[str]
) -> None:
    reached = Counter[str]()

    @seed(PARITY_SEED)
    @settings(
        max_examples=EXAMPLES,
        deadline=None,
        database=None,
        print_blob=True,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    @given(metrics_inputs())
    def the_metrics_agree(inputs: Json) -> None:
        engine = json.loads(fefat_engine.metrics(json.dumps(inputs)))
        Metrics.model_validate(engine)
        expected = metrics_by_definition(inputs)
        expected["robustness"] |= scripts_summary(engine["robustness"]["inputs"])
        found = differences(engine, expected)
        assert not found, f"Seed {PARITY_SEED}:\n" + "\n".join(found)
        reached.update(coverage_of(inputs, expected))

    started = time.perf_counter()
    the_metrics_agree()
    elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(f"\n{EXAMPLES} runs' metrics through both in {elapsed:.1f} s, seed {PARITY_SEED}")
        print("reached:", ", ".join(f"{kind} {count}" for kind, count in sorted(reached.items())))
    missing = [kind for kind, count in reached.items() if count == 0]
    assert len(reached) == 17
    assert not missing, f"Expected each kind of run at least once, got none of: {missing}"
