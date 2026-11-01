"""The engine guide (step 2.15) gives every option of the execution template a one-line meaning,
names every option of its rules and every run setting, describes every file of a run folder, and
links only to files and fill-rule sections that exist."""

import inspect
import re
from pathlib import Path

import fefat as ff
from fefat.backtest import RunConfig
from fefat.backtest.schemas import ARTIFACT_SCHEMAS
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
