"""Step 2.3's strategy specification in Python (Done means 2): a `SignalStrategy`'s `to_spec()`
writes a `StrategySpec` document that validates against the JSON schema generated from the Rust
types and loads back equal; the models hold the fields, the required fields, and the defaults
the schema states; and the helpers of `02-engine-and-data.md` §5 build each rule from one choice.
"""

import copy
import typing
from typing import Any

import jsonschema
import polars as pl
import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python

import fefat as ff
from fefat.strategy import (
    AfterTargetTrigger,
    AtrStop,
    BarsCooldown,
    BreakevenRule,
    Cooldown,
    EntryOrder,
    EntryWindow,
    Execution,
    LimitEntryOffset,
    Limits,
    MinutesCooldown,
    OppositeSignal,
    ProfitTarget,
    ProfitTrigger,
    RiskPercentSize,
    RMultipleTarget,
    RMultipleTrigger,
    Sizing,
    StopRule,
    StrategySpec,
    TargetPrice,
    TicksStop,
    TicksTrigger,
    TimeRules,
    TrailBy,
    TrailingStop,
    TrailUpdate,
    Weekday,
    spec_schema,
)

SCHEMA = spec_schema()
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)

DOCUMENTED_SPEC: dict[str, Any] = {
    "spec_version": 1,
    "instrument": "ES",
    "timeframe": "5m",
    "execution": {
        "entry": {"kind": "market"},
        "on_opposite_signal": "ignore",
        "stop": {"kind": "atr", "multiple": 1.5, "feature": "atr"},
        "targets": [
            {"price": {"kind": "r_multiple", "multiple": 1.0}, "fraction": 0.5},
            {"price": {"kind": "r_multiple", "multiple": 2.0}, "fraction": 1.0},
        ],
        "breakeven": {"trigger": {"kind": "after_target", "target": 1}, "offset_ticks": 0},
        "time": {
            "tz": "America/Chicago",
            "windows": [{"start": "08:30", "end": "14:30"}],
            "flat_by": "15:05",
            "no_overnight": False,
            "no_weekend": False,
        },
        "limits": {"max_trades_per_day": 3, "fresh_signal": False},
        "sizing": {"kind": "fixed", "units": 1.0},
        "signal_exit": True,
    },
}
"""The strategy of 02 §5 as a document: the one the Rust tests of `fefat-core` read back."""

STRUCTS: dict[str, type[BaseModel]] = {
    "Execution": Execution,
    "Target": ProfitTarget,
    "Breakeven": BreakevenRule,
    "Trailing": TrailingStop,
    "TimeRules": TimeRules,
    "EntryWindow": EntryWindow,
    "Limits": Limits,
}
UNIONS: dict[str, object] = {
    "EntryOrder": EntryOrder,
    "StopRule": StopRule,
    "TargetPrice": TargetPrice,
    "ProfitTrigger": ProfitTrigger,
    "TrailBy": TrailBy,
    "Cooldown": Cooldown,
    "Sizing": Sizing,
}
ENUMS = {"OppositeSignal": OppositeSignal, "TrailUpdate": TrailUpdate, "Weekday": Weekday}


def documented_strategy() -> ff.SignalStrategy:
    """The strategy of `02-engine-and-data.md` §5, with inline Polars expressions for the RSI
    and the ATR that `fefat.indicators` brings in Phase 3."""
    change = pl.col("close").diff()
    gain, loss = change.clip(lower_bound=0), (-change).clip(lower_bound=0)
    rsi = 100 - 100 / (1 + gain.ewm_mean(alpha=1 / 14) / loss.ewm_mean(alpha=1 / 14))
    before = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - before).abs(),
        (pl.col("low") - before).abs(),
    )
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"rsi": rsi, "atr": true_range.ewm_mean(alpha=1 / 14)},
        long_entry=pl.col("rsi") < 30,
        short_entry=pl.col("rsi") > 70,
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(atr=1.5),
            targets=[ff.Target(r=1, fraction=0.5), ff.Target(r=2)],
            breakeven=ff.Breakeven(after_target=1),
            time=ff.TimeRules(
                windows=[EntryWindow(start="08:30", end="14:30")],
                flat_by="15:05",
                tz="America/Chicago",
            ),
            limits=ff.Limits(max_trades_per_day=3),
            sizing=ff.Fixed(1),
        ),
    )


def spec_with(**execution: Any) -> StrategySpec:
    """ES on 5-minute signal bars, a market entry and a fixed lot, with `execution`'s rules."""
    rules = {"entry": ff.Market(), "sizing": ff.Fixed(1), **execution}
    return StrategySpec(
        spec_version=1, instrument="ES", timeframe="5m", execution=Execution(**rules)
    )


EVERY_RULE = [
    spec_with(
        entry=ff.Limit(column=True, time_to_live_bars=3),
        on_opposite_signal=OppositeSignal.CLOSE,
        stop=ff.Stop(ticks=12),
        targets=[ff.Target(ticks=24)],
    ),
    spec_with(
        entry=ff.Limit(offset_ticks=2),
        on_opposite_signal=OppositeSignal.REVERSE,
        stop=ff.Stop(percent=0.5),
        targets=[ff.Target(atr=2, fraction=0.5), ff.Target(column=True)],
    ),
    spec_with(
        entry=ff.StopEntry(column=True),
        stop=ff.Stop(column=True),
        targets=[ff.Target(r=1.5)],
        breakeven=ff.Breakeven(ticks=8, offset_ticks=1),
    ),
    spec_with(
        entry=ff.StopEntry(offset_ticks=4, time_to_live_bars=1),
        breakeven=ff.Breakeven(r=1, offset_ticks=-1),
        trailing=ff.Trailing(
            ticks=8, step_ticks=2, activation=TicksTrigger(ticks=10), update=TrailUpdate.BAR_CLOSE
        ),
    ),
    spec_with(
        trailing=ff.Trailing(atr=3),
        time=ff.TimeRules(
            tz="UTC",
            windows=[
                EntryWindow(start="22:00", end="02:00", weekdays=[Weekday.MONDAY, Weekday.SUNDAY])
            ],
            max_bars=12,
            max_minutes=90,
            no_overnight=True,
            no_weekend=True,
        ),
    ),
    spec_with(
        trailing=ff.Trailing(column=True, activation=RMultipleTrigger(multiple=1)),
        limits=ff.Limits(
            blackout="news",
            max_trades_per_day=3,
            max_losses_per_day=2,
            daily_loss_stop=500,
            profit_lock=1_000,
            cooldown_after_loss=BarsCooldown(bars=6),
            fresh_signal=True,
        ),
        sizing=ff.Notional(25_000),
    ),
    spec_with(
        limits=ff.Limits(cooldown_after_loss=MinutesCooldown(minutes=30)),
        sizing=ff.RiskPerTrade(amount=250),
        signal_exit=False,
    ),
    spec_with(sizing=ff.RiskPerTrade(percent=1)),
]


def test_the_documented_strategy_writes_a_spec_the_schema_accepts_and_loads_back_equal() -> None:
    spec = documented_strategy().to_spec()

    VALIDATOR.validate(spec.document())
    assert StrategySpec.model_validate_json(spec.document_json()) == spec
    assert spec.document() == DOCUMENTED_SPEC


@pytest.mark.parametrize("spec", EVERY_RULE, ids=[f"spec {n}" for n in range(len(EVERY_RULE))])
def test_every_rule_writes_a_document_the_schema_accepts_and_loads_back_equal(
    spec: StrategySpec,
) -> None:
    VALIDATOR.validate(spec.document())
    assert StrategySpec.model_validate_json(spec.document_json()) == spec


def test_the_rules_written_cover_every_kind_the_schema_names() -> None:
    documents = [spec.document() for spec in EVERY_RULE] + [DOCUMENTED_SPEC]
    written = {kind for document in documents for kind in kinds_in(document)}

    named = {
        branch["properties"]["kind"]["const"]
        for name in UNIONS
        for branch in SCHEMA["$defs"][name]["oneOf"]
    }
    assert named - written == set()


def kinds_in(document: object) -> set[str]:
    if isinstance(document, dict):
        own = {document["kind"]} if "kind" in document else set()
        return own.union(*(kinds_in(value) for value in document.values()))
    if isinstance(document, list):
        return set().union(*(kinds_in(value) for value in document))
    return set()


def test_a_minimal_document_takes_the_defaults_and_validates() -> None:
    minimal = {
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {"entry": {"kind": "market"}, "sizing": {"kind": "fixed", "units": 1}},
    }

    VALIDATOR.validate(minimal)
    execution = StrategySpec.model_validate(minimal).execution
    assert execution.on_opposite_signal is OppositeSignal.IGNORE
    assert (execution.stop, execution.time, execution.targets) == (None, None, ())
    assert execution.limits == Limits()
    assert execution.signal_exit is True


def test_the_schema_is_draft_2020_12_named_for_the_spec_and_never_offers_null() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["title"] == "StrategySpec"
    assert "null" not in str(SCHEMA)


@pytest.mark.parametrize("name", ["StrategySpec", *STRUCTS])
def test_each_model_holds_the_fields_requirements_and_defaults_of_its_schema(name: str) -> None:
    model = StrategySpec if name == "StrategySpec" else STRUCTS[name]
    definition = SCHEMA if name == "StrategySpec" else SCHEMA["$defs"][name]

    assert fields_of(model) == fields_in(definition)


@pytest.mark.parametrize("name", list(UNIONS))
def test_each_rules_variants_hold_the_fields_requirements_and_defaults_of_its_schema(
    name: str,
) -> None:
    (members, *_) = typing.get_args(UNIONS[name])
    variants = {
        variant.model_fields["kind"].default: variant for variant in typing.get_args(members)
    }
    branches = {
        branch["properties"]["kind"]["const"]: branch for branch in SCHEMA["$defs"][name]["oneOf"]
    }

    assert set(variants) == set(branches)
    for kind, variant in variants.items():
        names, required, defaults = fields_of(variant)
        assert (names, required | {"kind"}, defaults) == fields_in(branches[kind]), kind


@pytest.mark.parametrize("name", list(ENUMS))
def test_each_choice_holds_the_values_of_its_schema(name: str) -> None:
    definition = SCHEMA["$defs"][name]
    values = (
        set(definition["enum"])
        if "enum" in definition
        else {branch["const"] for branch in definition["oneOf"]}
    )

    assert {choice.value for choice in ENUMS[name]} == values


def fields_of(model: type[BaseModel]) -> tuple[set[str], set[str], dict[str, Any]]:
    """A model's field names, its required fields, and its defaults other than none, as JSON
    writes them; a rule's `kind` is the variant's name, not a default."""
    fields = model.model_fields
    required = {name for name, field in fields.items() if field.is_required()}
    defaults = {
        name: to_jsonable_python(field.get_default(call_default_factory=True), exclude_none=True)
        for name, field in fields.items()
        if name != "kind" and not field.is_required()
    }
    return (
        set(fields),
        required,
        {name: value for name, value in defaults.items() if value is not None},
    )


def fields_in(definition: dict[str, Any]) -> tuple[set[str], set[str], dict[str, Any]]:
    properties = definition["properties"]
    defaults = {name: field["default"] for name, field in properties.items() if "default" in field}
    return set(properties), set(definition.get("required", ())), defaults


def changed(path: tuple[str, ...], value: object) -> dict[str, Any]:
    """The documented spec with the value at `path` replaced."""
    document = copy.deepcopy(DOCUMENTED_SPEC)
    *parents, last = path
    holder = document
    for key in parents:
        holder = holder[key]
    holder[last] = value
    return document


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("execution", "stop"), {"kind": "chandelier"}),
        (("execution", "stop"), {"kind": "atr", "multiple": 1.5, "feature": "atr", "period": 14}),
        (("execution", "entry"), {"kind": "market", "price": 1}),
        (("execution", "targets"), [{"price": {"kind": "ticks", "ticks": 4}, "fraction": 1.5}]),
        (("execution", "targets"), [{"price": {"kind": "ticks", "ticks": 4}}] * 4),
        (("execution", "stop"), {"kind": "ticks", "ticks": 0}),
        (("execution", "time"), {"flat_by": "15:05"}),
        (("execution", "time", "flat_by"), "24:05"),
        (("execution", "comment"), "a field no reader knows"),
        (("spec_version",), 2),
        (("timeframe",), "5 minutes"),
    ],
)
def test_a_document_the_schema_refuses_the_models_refuse(
    path: tuple[str, ...], value: object
) -> None:
    document = changed(path, value)

    assert not VALIDATOR.is_valid(document)
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(document)


def test_the_helpers_build_the_rule_of_their_one_choice() -> None:
    assert ff.Stop(ticks=12) == TicksStop(ticks=12)
    assert ff.Stop(atr=1.5) == AtrStop(multiple=1.5, feature="atr")
    assert ff.Target(r=2) == ProfitTarget(price=RMultipleTarget(multiple=2))
    assert ff.Breakeven(after_target=1) == BreakevenRule(trigger=AfterTargetTrigger(target=1))
    assert ff.Limit(offset_ticks=2) == LimitEntryOffset(ticks=2)
    assert ff.RiskPerTrade(percent=1) == RiskPercentSize(percent=1)


def test_a_breakeven_offset_beyond_the_schemas_64_bit_integers_is_refused() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 9223372036854775807"):
        ff.Breakeven(ticks=4, offset_ticks=2**70)


def test_entry_windows_may_be_given_as_pairs_of_local_times() -> None:
    rules = TimeRules.model_validate({"tz": "UTC", "windows": [("08:30", "14:30")]})

    assert rules.windows == (EntryWindow(start="08:30", end="14:30"),)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ff.Stop(),
        lambda: ff.Stop(ticks=12, column=True),
        lambda: ff.Target(),
        lambda: ff.Breakeven(ticks=4, r=1),
        lambda: ff.Limit(),
        lambda: ff.StopEntry(column=True, offset_ticks=2),
        lambda: ff.Trailing(ticks=4, atr=2),
        lambda: ff.RiskPerTrade(),
    ],
)
def test_a_helper_refuses_no_choice_and_two(build: typing.Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="Expected one of"):
        build()
