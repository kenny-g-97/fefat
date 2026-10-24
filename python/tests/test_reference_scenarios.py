"""Step 2.1's scenario format: the scenarios in `fixtures/scenarios/` validate against
`fefat.reference.scenarios`, each cites rules that `docs/spec/fill-semantics.md` defines, and
together they cite every rule of it (Done means 2)."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fefat.reference.orders import StopOrder
from fefat.reference.scenarios import Scenario, load_scenario, load_scenarios, specified_rules
from fefat.reference.settings import LimitFill, RunSettings, SlippageTicks
from fefat.reference.units import instant_nanoseconds, instant_text, price_units

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "fixtures" / "scenarios"
SPECIFICATION = ROOT / "docs" / "spec" / "fill-semantics.md"
FIRST_THIRTY = {f"S-fill-{number:03d}" for number in range(1, 31)}
PLACED = "2026-03-06T14:30:00.000Z"
RECEIVED = "2026-03-06T14:30:00.200Z"


def defined_rules() -> set[str]:
    return set(specified_rules(SPECIFICATION.read_text(encoding="utf-8")))


def cited_rules() -> set[str]:
    return {rule for scenario in load_scenarios(SCENARIOS) for rule in scenario.rules}


def a_scenario(**changes: object) -> dict[str, object]:
    """A scenario that loads, a buy market order filled on one ES trade, with `changes`."""
    scenario: dict[str, object] = {
        "id": "S-fill-900",
        "title": "A buy market order fills at the first trade plus a tick",
        "fidelity": "trades",
        "instrument": "ES",
        "orders": [
            {"id": 1, "placed_at": PLACED, "side": "buy", "kind": "market", "quantity": 1},
        ],
        "tape": [{"ts": RECEIVED, "price": "5000.00", "size": 1}],
        "expected": {
            "fills": [{"order": 1, "ts": RECEIVED, "price": "5000.25", "rule": "F-MKT-02"}],
        },
        "rules": ["F-MKT-02"],
    }
    return {**scenario, **changes}


def test_the_first_thirty_scenarios_load_each_named_by_its_id() -> None:
    ids = [scenario.id for scenario in load_scenarios(SCENARIOS)]

    assert set(ids) >= FIRST_THIRTY
    assert len(ids) == len(set(ids))


def test_the_scenarios_cite_only_rules_the_specification_defines() -> None:
    assert cited_rules() - defined_rules() == set()


def test_together_the_scenarios_cite_every_rule_of_the_specification() -> None:
    assert defined_rules() - cited_rules() == set()


def test_every_scenario_shows_its_arithmetic_in_a_comment() -> None:
    def shows_arithmetic(path: Path) -> bool:
        lines = path.read_text(encoding="utf-8").splitlines()
        return any(line.startswith("#") and "=" in line for line in lines)

    files = sorted(SCENARIOS.glob("*.yaml"))

    assert files
    assert [path.name for path in files if not shows_arithmetic(path)] == []


def test_the_scenarios_folder_holds_only_yaml_scenarios_and_its_readme() -> None:
    others = [path.name for path in SCENARIOS.iterdir() if path.suffix != ".yaml"]

    assert others == ["README.md"]


def a_perpetual_scenario(**changes: object) -> dict[str, object]:
    """A scenario that loads, a buy market order filled on one BTCUSDT-PERP trade."""
    fills = {"order": 1, "ts": RECEIVED, "price": "65000.1", "rule": "F-MKT-02"}
    perpetual: dict[str, object] = {
        "instrument": "BTCUSDT-PERP",
        "tape": [{"ts": RECEIVED, "price": "65000.0", "size": 3}],
        "expected": {"fills": [fills]},
    }
    return a_scenario(**{**perpetual, **changes})


def test_a_funding_payment_off_the_funding_times_is_refused() -> None:
    funding = [{"ts": "2026-03-06T16:00:00.000Z", "rate": "0.0001"}]
    paid = {"ts": "2026-03-06T08:00:00.000Z", "amount": "-0.10"}
    fills = {"order": 1, "ts": RECEIVED, "price": "65000.1", "rule": "F-MKT-02"}
    off_time = a_perpetual_scenario(funding=funding, expected={"fills": [fills], "funding": [paid]})

    with pytest.raises(ValidationError, match=re.escape("got ['2026-03-06T08:00:00Z']")):
        Scenario.model_validate(off_time)


def test_the_readme_lists_every_scenario_with_its_fidelity_and_title() -> None:
    readme = (SCENARIOS / "README.md").read_text(encoding="utf-8")
    rows = {
        f"| [{scenario.id}]({scenario.id}.yaml) | {scenario.fidelity} | {scenario.title} |"
        for scenario in load_scenarios(SCENARIOS)
    }

    assert {row for row in rows if row not in readme} == set()


def test_a_stop_gapped_through_fills_at_the_first_trade_past_it() -> None:
    scenario = load_scenario(SCENARIOS / "S-fill-012.yaml")
    assert isinstance(scenario, Scenario)
    (stop,) = scenario.orders
    (fill,) = scenario.expected.fills

    assert isinstance(stop, StopOrder)
    assert stop.price == price_units("4995.00")
    assert fill.price == price_units("4990.25")


def test_a_price_is_read_from_its_quoted_decimal_into_nano_units() -> None:
    assert price_units("4990.25") == 4_990_250_000_000
    assert price_units("-37.63") == -37_630_000_000
    assert price_units("65000.1") == 65_000_100_000_000


@pytest.mark.parametrize("text", [4990.25, 4990, "4990.2500000001", "1e3", "4,990.25", ""])
def test_a_price_not_written_as_a_quoted_decimal_is_refused(text: object) -> None:
    with pytest.raises(ValueError, match="price"):
        price_units(text)


def test_an_instant_is_read_from_its_quoted_utc_time_into_nanoseconds() -> None:
    half_past_two = int(datetime(2026, 3, 6, 14, 30, tzinfo=UTC).timestamp()) * 1_000_000_000

    assert instant_nanoseconds("2026-03-06T14:30:00Z") == half_past_two
    assert instant_nanoseconds("2026-03-06T14:30:00.100Z") == half_past_two + 100_000_000
    assert instant_nanoseconds("2026-03-06T14:30:00.000000001Z") == half_past_two + 1
    assert instant_text(half_past_two + 100_000_000) == "2026-03-06T14:30:00.1Z"
    assert instant_text(-(10**18)) == "1938-04-24T22:13:20Z"


@pytest.mark.parametrize(
    "text",
    ["2026-03-06T14:30:00.100", "2026-03-06 14:30:00Z", 52200, "2026-03-06T14:30:00.1234567891Z"],
)
def test_an_instant_not_written_as_a_quoted_utc_time_is_refused(text: object) -> None:
    with pytest.raises(ValueError, match="instant"):
        instant_nanoseconds(text)


def test_a_scenario_without_settings_takes_the_specifications_defaults() -> None:
    quote = {"bid": "4999.75", "ask": "5000.00", "bid_size": 5, "ask_size": 5}
    on_tbbo = a_scenario(
        fidelity="tbbo",
        tape=[{"ts": RECEIVED, "price": "5000.00", "size": 1, **quote}],
        expected={"fills": [{"order": 1, "ts": RECEIVED, "price": "5000.00", "rule": "F-MKT-01"}]},
        rules=["F-MKT-01"],
    )

    assert Scenario.model_validate(a_scenario()).settings == RunSettings(
        latency_ms=100,
        slippage_ticks=SlippageTicks(market=1, stop=1),
        limit_fill=LimitFill.THROUGH,
    )
    assert Scenario.model_validate(on_tbbo).settings.slippage_ticks == SlippageTicks(
        market=0, stop=0
    )


def test_a_price_off_the_instruments_tick_is_refused() -> None:
    off_the_tick = a_scenario(tape=[{"ts": RECEIVED, "price": "5000.10", "size": 1}])

    with pytest.raises(ValidationError, match=re.escape("tick of 0.25, got 5000.1.")):
        Scenario.model_validate(off_the_tick)


def test_a_tape_unlike_its_fidelity_is_refused() -> None:
    with pytest.raises(ValidationError, match="Expected a tape of bars for fidelity 1m"):
        Scenario.model_validate(a_scenario(fidelity="1m"))


def test_a_tape_out_of_time_order_is_refused() -> None:
    backwards = [
        {"ts": RECEIVED, "price": "5000.00", "size": 1},
        {"ts": PLACED, "price": "5000.25", "size": 1},
    ]

    with pytest.raises(ValidationError, match="time order"):
        Scenario.model_validate(a_scenario(tape=backwards))


def test_a_fill_of_an_order_the_scenario_lacks_is_refused() -> None:
    stray = {"order": 2, "ts": RECEIVED, "price": "5000.25", "rule": "F-MKT-02"}

    with pytest.raises(ValidationError, match="order 2"):
        Scenario.model_validate(a_scenario(expected={"fills": [stray]}))


def test_a_fill_priced_by_a_rule_the_scenario_does_not_cite_is_refused() -> None:
    with pytest.raises(ValidationError, match="F-MKT-02"):
        Scenario.model_validate(a_scenario(rules=["F-ACT-01"]))


def test_a_fee_is_expected_on_every_fill_exactly_when_the_scenario_has_fees() -> None:
    with pytest.raises(ValidationError, match="fee"):
        Scenario.model_validate(a_scenario(fees={"kind": "futures", "per_contract_side": "2.50"}))


def test_an_inline_instrument_counts_quantities_in_its_lot_step() -> None:
    crypto = {"tick_size": "0.10", "point_value": "1", "lot_step": "0.001"}
    order = {"id": 1, "placed_at": PLACED, "side": "buy", "kind": "market", "quantity": "0.013"}
    tape = [{"ts": RECEIVED, "price": "65000.0", "size": 3}]
    fills = {"fills": [{"order": 1, "ts": RECEIVED, "price": "65000.1", "rule": "F-MKT-02"}]}
    scenario = a_scenario(instrument=crypto, orders=[order], tape=tape, expected=fills)

    assert Scenario.model_validate(scenario).orders[0].quantity == Decimal("0.013")
    with pytest.raises(ValidationError, match=re.escape("lot step of 0.001, got 0.0135.")):
        Scenario.model_validate({**scenario, "orders": [{**order, "quantity": "0.0135"}]})


def test_a_bracket_whose_stop_is_not_on_the_losing_side_is_refused() -> None:
    bracket = {"stop": {"id": 2, "price": "5010.00"}, "target": {"id": 3, "price": "4990.00"}}
    order = {"id": 1, "placed_at": PLACED, "side": "buy", "kind": "market", "quantity": 1}

    with pytest.raises(ValidationError, match="bracket stop below its target"):
        Scenario.model_validate(a_scenario(orders=[{**order, "bracket": bracket}]))


def test_a_file_named_otherwise_than_its_id_is_refused(tmp_path: Path) -> None:
    misnamed = tmp_path / "S-fill-901.yaml"
    misnamed.write_text(yaml.safe_dump(a_scenario()), encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape("named by its id, S-fill-900.yaml.")):
        load_scenario(misnamed)


def test_a_key_given_twice_in_a_scenario_file_is_refused(tmp_path: Path) -> None:
    written = tmp_path / "S-fill-900.yaml"
    text = yaml.safe_dump(a_scenario(), sort_keys=False)
    written.write_text(text.replace("rule: F-MKT-02", "rule: F-MKT-02\n    price: '4994.75'"))

    with pytest.raises(ValueError, match=re.escape("each key once in a mapping, got ['price']")):
        load_scenario(written)


def test_an_order_filled_twice_is_refused() -> None:
    fill = {"order": 1, "ts": RECEIVED, "price": "5000.25", "rule": "F-MKT-02"}

    with pytest.raises(ValidationError, match=re.escape("to fill once at most, got [1] again")):
        Scenario.model_validate(a_scenario(expected={"fills": [fill, fill]}))


def test_both_orders_of_an_oco_group_filled_is_refused() -> None:
    stop = {"id": 1, "placed_at": PLACED, "side": "buy", "kind": "stop", "price": "5000.00"}
    limit = {"id": 2, "placed_at": PLACED, "side": "buy", "kind": "limit", "price": "5000.50"}
    orders = [{**stop, "quantity": 1, "oco": "entry"}, {**limit, "quantity": 1, "oco": "entry"}]
    fills = [
        {"order": 1, "ts": RECEIVED, "price": "5000.25", "rule": "F-STP-03"},
        {"order": 2, "ts": RECEIVED, "price": "5000.50", "rule": "F-LMT-03"},
    ]
    both = a_scenario(orders=orders, expected={"fills": fills}, rules=["F-STP-03", "F-LMT-03"])

    with pytest.raises(ValidationError, match=re.escape("in each OCO group of S-fill-900")):
        Scenario.model_validate(both)


def test_a_bracket_leg_filled_without_its_entry_is_refused() -> None:
    bracket = {"stop": {"id": 2, "price": "4995.00"}, "target": {"id": 3, "price": "5010.00"}}
    order = {"id": 1, "placed_at": PLACED, "side": "buy", "kind": "market", "quantity": 1}
    leg = {"order": 3, "ts": RECEIVED, "price": "5010.00", "rule": "F-LMT-03"}
    alone = a_scenario(
        orders=[{**order, "bracket": bracket}], expected={"fills": [leg]}, rules=["F-LMT-03"]
    )

    with pytest.raises(ValidationError, match="leg 3 of S-fill-900 to fill after its entry"):
        Scenario.model_validate(alone)


def test_a_bar_longer_than_its_fidelity_is_refused() -> None:
    bar = {"open": "5000.00", "high": "5000.25", "low": "5000.00", "close": "5000.25", "volume": 9}
    five_minutes = {"ts_open": "2026-03-06T14:30:00Z", "ts_close": "2026-03-06T14:35:00Z", **bar}
    fill = {"order": 1, "ts": "2026-03-06T14:35:00Z", "price": "5000.25", "rule": "F-MKT-03"}
    on_one_minute = a_scenario(
        fidelity="1m", tape=[five_minutes], expected={"fills": [fill]}, rules=["F-MKT-03"]
    )

    with pytest.raises(ValidationError, match="bars of 1m at most, got record 1 longer"):
        Scenario.model_validate(on_one_minute)


def test_a_record_lacking_a_field_of_its_fidelity_names_the_field() -> None:
    no_quote = a_scenario(fidelity="tbbo", rules=["F-MKT-02"])

    with pytest.raises(ValidationError, match=r"tape of TBBO records for fidelity tbbo[\s\S]*bid"):
        Scenario.model_validate(no_quote)


def test_fees_or_funding_that_do_not_fit_the_instrument_are_refused() -> None:
    crypto_fee = {"kind": "crypto", "maker_bps": "2", "taker_bps": "5"}
    funding = [{"ts": "2026-03-06T16:00:00.000Z", "rate": "0.0001"}]

    with pytest.raises(ValidationError, match="Expected futures fees for ES"):
        Scenario.model_validate(a_scenario(fees=crypto_fee))
    with pytest.raises(ValidationError, match="Expected funding rates on a perpetual only"):
        Scenario.model_validate(a_scenario(funding=funding))
    assert Scenario.model_validate(a_perpetual_scenario(funding=funding)).funding


def test_an_inline_tick_finer_than_a_price_unit_is_refused() -> None:
    fine = {"tick_size": "0.0000000001", "point_value": "1", "lot_step": "1"}

    with pytest.raises(ValidationError, match="tick size in whole 1e-9 units"):
        Scenario.model_validate(a_scenario(instrument=fine))
