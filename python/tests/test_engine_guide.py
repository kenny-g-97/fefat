"""The engine guide (step 2.15) gives every option of the execution template a one-line meaning,
names every option of its rules and every run setting, describes every file of a run folder, and
links only to files and fill-rule sections that exist; from step 3.7 it gives every kind of a
combination's description a row with its fields, and from step 3.8 it names every analysis of
a feature study, every field of their results, and every column of their frames."""

import dataclasses
import inspect
import re
import typing
from pathlib import Path

import fefat as ff
from fefat.analytics import (
    Correlations,
    EventStudy,
    FeatureStudy,
    InformationCoefficient,
    QuantileReturns,
)
from fefat.analytics.events import EVENT_PATH_COLUMNS, EXCURSION_COLUMNS
from fefat.analytics.quantiles import QUANTILE_COLUMNS
from fefat.analytics.rank_correlation import CLUSTER_COLUMNS, IC_BY_YEAR_COLUMNS
from fefat.backtest import RunConfig
from fefat.backtest.schemas import ARTIFACT_SCHEMAS
from fefat.features.combinations import TERMS
from fefat.market.fees import TABLES
from fefat.reference.settings import LimitFill, Replay, RollHandling
from fefat.strategy.exits import (
    AfterTargetTrigger,
    BarsCooldown,
    EntryWindow,
    Limits,
    MinutesCooldown,
    RMultipleTrigger,
    TicksTrigger,
    TimeRules,
    TrailUpdate,
)
from fefat.strategy.signal_strategy import SignalStrategy
from fefat.strategy.spec import Execution, OppositeSignal

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "engine-guide.md"
FILL_SPECIFICATION = ROOT / "docs" / "spec" / "fill-semantics.md"
RULE_HELPERS = (
    ff.Market,
    ff.Limit,
    ff.StopEntry,
    ff.Stop,
    ff.Target,
    ff.Breakeven,
    ff.Trailing,
    ff.Fixed,
    ff.Notional,
    ff.RiskPerTrade,
)
RULE_MODELS = (TimeRules, EntryWindow, Limits, BarsCooldown, MinutesCooldown)
WORDS = (OppositeSignal, TrailUpdate, LimitFill, RollHandling, Replay)


def guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def code_blocks() -> list[str]:
    return re.findall(r"```.*?```", guide_text(), re.DOTALL)


def inline_code() -> list[str]:
    """The guide's inline code, such as `Fixed(units)`, read once its code blocks are out of the
    way, whose fences would pair the backticks wrongly."""
    prose = re.sub(r"```.*?```", " ", guide_text(), flags=re.DOTALL)
    return re.findall(r"`([^`\n]+)`", prose)


def unnamed(names: list[str]) -> list[str]:
    """The names the guide never writes as a word of its code."""
    code = " ".join([*code_blocks(), *inline_code()])
    return sorted({name for name in names if not re.search(rf"\b{re.escape(name)}\b", code)})


def test_every_execution_option_has_a_row_with_a_one_line_meaning() -> None:
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| ([^|]*[a-z][^|]*) \|", guide_text(), re.MULTILINE))

    assert [name for name in Execution.model_fields if name not in rows] == []


def test_every_strategy_field_and_run_setting_is_named() -> None:
    assert unnamed([*SignalStrategy.model_fields, *RunConfig.model_fields]) == []


def test_every_option_of_the_rules_is_named() -> None:
    parameters = [name for helper in RULE_HELPERS for name in inspect.signature(helper).parameters]
    fields = [name for model in RULE_MODELS for name in model.model_fields if name != "kind"]
    helpers = [helper.__name__ for helper in RULE_HELPERS]
    triggers = [
        trigger.__name__ for trigger in (TicksTrigger, RMultipleTrigger, AfterTargetTrigger)
    ]

    assert unnamed([*parameters, *fields, *helpers, *triggers]) == []


def test_every_word_a_setting_takes_and_every_fee_table_is_named() -> None:
    assert unnamed([str(word) for words in WORDS for word in words] + list(TABLES)) == []


def test_every_file_of_a_run_folder_is_described() -> None:
    assert unnamed([f"{name}.parquet" for name in ARTIFACT_SCHEMAS] + ["run.json"]) == []


def test_every_repository_file_the_guide_names_exists() -> None:
    pattern = r"(?:docs|notebooks|python|engine|fixtures|scripts)/[^<>* ]+"
    named = [code for code in inline_code() if re.fullmatch(pattern, code)]

    assert named
    assert [path for path in named if not (ROOT / path).exists()] == []


def test_every_link_into_the_fill_specification_names_one_of_its_sections() -> None:
    headings = re.findall(
        r"^## (.+)$", FILL_SPECIFICATION.read_text(encoding="utf-8"), re.MULTILINE
    )
    anchors = {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}
    links = re.findall(r"\(spec/fill-semantics\.md#([^)]+)\)", guide_text())

    assert links
    assert [link for link in links if link not in anchors] == []


def test_every_kind_of_a_combinations_description_has_a_row_with_its_fields() -> None:
    # Step 3.7, Done means 3: the description of a combination is documented for the builder of
    # Phase 6, each kind in a row of the guide's table with every field its model holds.
    heading = "### The description of a combination"
    assert heading in guide_text()
    section = guide_text().split(heading, 1)[1].split("\n#", 1)[0]
    rows = re.findall(r"^\| ((?:`[a-z_]+`(?:, )?)+) \| ([^|]+) \|", section, re.MULTILINE)
    documented = {kind: fields for kinds, fields in rows for kind in re.findall(r"`(\w+)`", kinds)}
    kinds = {
        kind: [field for field in model.model_fields if field != "kind"]
        for model in TERMS
        for kind in typing.get_args(model.model_fields["kind"].annotation)
    }

    assert [kind for kind in kinds if kind not in documented] == []
    assert [
        (kind, field)
        for kind, fields in kinds.items()
        for field in fields
        if f"`{field}`" not in documented[kind]
    ] == []


def test_every_analysis_of_a_feature_study_and_every_column_of_its_frames_is_named() -> None:
    # Step 3.8: "Judging a feature" names what a study gives, for you and for the analytics page
    # of step 6.5, which shows the same frames.
    analyses = [name for name in vars(FeatureStudy) if not name.startswith("_")]
    results = (QuantileReturns, InformationCoefficient, Correlations, EventStudy)
    fields = [field.name for result in results for field in dataclasses.fields(result)]
    schemas = (
        QUANTILE_COLUMNS,
        IC_BY_YEAR_COLUMNS,
        CLUSTER_COLUMNS,
        EVENT_PATH_COLUMNS,
        EXCURSION_COLUMNS,
    )
    columns = [column for schema in schemas for column in schema]
    types = ["FeatureStudy", "Label", "Trials", "PositionSide"]

    assert unnamed([*analyses, *fields, *columns, *types]) == []
