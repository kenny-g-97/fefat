"""The comparison report, `docs/validation/nautilus-comparison.md` (step 2.14, Done means 1 to
3): the versions of every engine and the data snapshot, the strategies and the profile, each
strategy's match rates and difference classes, the classes with the rules behind them, and the
NinjaTrader 8 section. It holds counts, rates, timestamps, and tick differences: never a price
of the licensed data, nor a path of this PC."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from fefat_xcheck.classify import MATCH, DifferenceClass, Summary, summarise
from fefat_xcheck.conventions import EngineConventions

CLASS_COLUMNS = tuple(str(kind) for kind in DifferenceClass)
"""The classes as the tables list them, `unknown` last."""
EXPLANATIONS = {
    DifferenceClass.BAR_BOUNDARY: (
        "A market order decided at a 5-minute close. NautilusTrader settles an order submitted "
        "from `on_bar` against the book the bar left, at that bar's close (its backtesting "
        "documentation: there is no next-bar-open fill mode). FEFAT activates the order at the "
        "close without latency and fills it at the open of the first 1-minute bar after it "
        "(F-ACT-02, F-MKT-03), which is also NinjaTrader 8's convention (the builder's spec, H1). "
        "The two prices agree whenever the next minute opens at the previous close; the entry "
        "and exit levels are set from the signal close, so the bracket is unmoved by it."
    ),
    DifferenceClass.BAR_PATH: (
        "One 1-minute bar reached both the stop and the target. FEFAT visits a bar's adverse "
        "extreme first while holding a position, so the stop fills (F-BAR-02) and the fill is "
        "flagged ambiguous (F-BAR-05). NautilusTrader visits the open, the high, the low, and "
        "the close in that order, or with `bar_adaptive_high_low_ordering` the extreme nearer "
        "the open first; NinjaTrader 8 the extreme nearer the open first, the high on a tie "
        "(H2). The predicate checks the bar's range covers both levels and that the other "
        "engine's order of extremes reaches the leg it took first."
    ),
    DifferenceClass.SAME_BAR_BRACKET: (
        "An entry filled inside a 1-minute bar. FEFAT places the exit plan at the entry's point "
        "of the bar's path and works it on the rest of the bar, the extremes not yet reached "
        "adverse first (F-OCO-02, F-BAR-04); the other engine's legs met the bar after instead, "
        "or the reverse. The predicate checks the early engine's exit fell in its entry's bar "
        "and that the bar's range reaches the leg it took."
    ),
    DifferenceClass.CASCADE: (
        "A trade one engine made while the other still held a position at that decision, after "
        "an earlier difference on the same trade date left the two in different states; the "
        "flat-by at 15:00 Chicago brings them back together each trade date."
    ),
}
NOT_EXERCISED = (
    (
        "Aggressor-side limit fills",
        "NautilusTrader fills a resting limit on trade ticks of the aggressor side opposite to "
        "it; at bar fidelity there are no trade ticks, and both engines fill a limit on a bar "
        "that touches its price (F-LMT-02, `prob_fill_on_limit=1.0`), at the limit price.",
    ),
    (
        "`ts_recv` ordering",
        "FEFAT's clock is `ts_recv` (F-CLK-01) and Databento buckets its bars on it; both "
        "engines read the vendor's bars stamped at their close (`bars_timestamp_on_close`), so "
        "no record is reordered.",
    ),
    (
        "Roll handling",
        "MESU2026 is the front contract for the whole window and the FEFAT runs crossed no "
        "roll (asserted by `scripts/xcheck.py`), so neither engine rolled.",
    ),
)


@dataclass(frozen=True)
class StrategyReport:
    """One strategy against one engine under one bar path: its classified trades and each
    engine's gross profit and loss."""

    strategy: str
    conventions: EngineConventions
    classified: pl.DataFrame
    fefat_gross_pnl: float
    other_gross_pnl: float

    def summary(self) -> Summary:
        return summarise(self.classified)


@dataclass(frozen=True)
class EngineReport:
    """One engine's section: its name with its version, the settings it ran under, the checks
    that both engines read the same data and decided alike, and its strategies."""

    engine: str
    settings: tuple[str, ...]
    data_checks: tuple[str, ...]
    strategies: tuple[StrategyReport, ...]


@dataclass(frozen=True)
class ReportInputs:
    """Everything the report prints: the day, FEFAT's facts (`fefat.json` of the Nautilus
    comparison), the cut's facts (`cut.json`), the Nautilus section, and the NinjaTrader 8
    section or the text standing in for it."""

    written_on: date
    fefat: dict[str, Any]
    cut: dict[str, Any]
    nautilus: EngineReport
    ninjatrader: EngineReport | None
    ninjatrader_pending: str


def unknown_count(inputs: ReportInputs) -> int:
    """The trades left `unknown` over every engine, strategy, and bar path."""
    engines = [inputs.nautilus] + ([inputs.ninjatrader] if inputs.ninjatrader else [])
    return sum(strategy.summary().unknown for engine in engines for strategy in engine.strategies)


def report_text(inputs: ReportInputs) -> str:
    """The report as markdown."""
    sections = [
        _title(inputs),
        _versions_and_data(inputs),
        _strategies(inputs.fefat),
        _engine_section("NautilusTrader", inputs.nautilus, inputs.fefat),
        _classes(inputs),
        _ninjatrader_section(inputs),
    ]
    return "\n".join(sections) + "\n"


def _title(inputs: ReportInputs) -> str:
    facts = inputs.fefat
    return "\n".join(
        [
            "# FEFAT against NautilusTrader and NinjaTrader 8",
            "",
            f"Written by `just xcheck` on {inputs.written_on} (step 2.14, `02-engine-and-data.md` "
            "§8 item 5, D-51, D-59): the same strategies on "
            f"{facts['instrument']['contract']} from {facts['window']['first']} to "
            f"{facts['window']['last']}, deciding on 5-minute closes and filling on 1-minute bars, "
            "FEFAT under the compatibility profile of the fill specification's §19. Every "
            "differing fill falls into a class below, each checked against the bars; the "
            "comparison matches trades by the decision that entered them and their side, a "
            "market fill by its price alone, since its stamp is a convention of its own "
            "(`bar_boundary`), and every other fill by its price and its bar.",
            "",
        ]
    )


def _versions_and_data(inputs: ReportInputs) -> str:
    facts, cut = inputs.fefat, inputs.cut
    versions = facts["versions"]
    snapshot = facts["snapshot"]
    profile = facts["profile"]
    ticks = profile["slippage_ticks"]
    fees = "; ".join(f"{fee} from {day}" for day, fee in facts["fee_table"]["schedules"])
    lines = [
        "## Versions and data",
        "",
        f"- FEFAT: engine {versions['engine']}, fill model {versions['fill_model']}, artifact "
        f"schema {versions['artifact_schema']} (crate {facts['engine_version']}, SDK "
        f"{facts['sdk_version']}).",
        f"- {inputs.nautilus.engine}.",
        f"- Data: `{snapshot['dataset']}`, contract {facts['instrument']['contract']}, trade "
        f"dates {facts['window']['first']} to {facts['window']['last']}; the store snapshot of "
        f"the request {snapshot['first']} to {snapshot['last']} (ADR-0019), the one each run "
        f"pinned: `{snapshot['sha256']}`.",
        f"- The raw Databento batch file `{cut['raw_file']['name']}` ({cut['raw_file']['vendor_version']}): "
        f"SHA-256 `{cut['raw_file']['sha256']}`"
        + (
            f", the vendor's `{cut['raw_file']['vendor_sha256']}`"
            if cut["raw_file"]["vendor_sha256"]
            else ""
        )
        + f". The month cut NautilusTrader read, `{cut['cut']['name']}` ({cut['cut']['from']} to "
        f"{cut['cut']['to']}, the raw file's own metadata): SHA-256 `{cut['cut']['sha256']}`.",
        f"- Profile: fidelity {profile['fidelity']}, latency {profile['latency_ms']} ms, slippage "
        f"{ticks['market']} ticks on market and {ticks['stop']} on stop orders, limit fill "
        f"{profile['limit_fill']}; fee table {facts['fee_table']['name']} ({fees}), not compared: "
        "fills do not depend on fees with fixed sizing, and the gross profit and loss is compared.",
    ]
    lines.extend(f"- {check}" for check in inputs.nautilus.data_checks)
    return "\n".join(lines) + "\n"


def _strategies(facts: dict[str, Any]) -> str:
    lines = ["## The strategies", ""]
    for strategy in facts["strategies"]:
        entry = {
            "market": "a market order",
            "limit": f"a limit {strategy['offset_ticks']} ticks from the close, cancelled at the "
            f"next decision if unfilled ({strategy['time_to_live_bars']} bar to live)",
            "stop": f"a stop {strategy['offset_ticks']} ticks from the close, cancelled at the "
            f"next decision if unfilled ({strategy['time_to_live_bars']} bar to live)",
        }[strategy["entry"]]
        lines.append(
            f"- `{strategy['name']}`: long when the 5-minute close is above the previous close, "
            f"short when below; the entry is {entry}; one lot; a stop {strategy['stop_ticks']} "
            f"ticks and a target {strategy['target_ticks']} ticks from the signal bar's close, "
            f"one OCO group; entries from {strategy['window'][0]} to {strategy['window'][1]} "
            f"{strategy['tz']}, flat-by {strategy['flat_by']}, so the engines start each trade "
            "date flat together."
        )
    return "\n".join(lines) + "\n"


def _engine_section(title: str, engine: EngineReport, facts: dict[str, Any]) -> str:
    lines = [f"## {title}", ""]
    lines.extend(f"- {setting}" for setting in engine.settings)
    lines += [
        "",
        "### Trades",
        "",
        _trades_table(engine),
        "",
        "### Fills",
        "",
        _fills_table(engine),
    ]
    lines += ["", "### Gross profit and loss", "", _pnl_table(engine, facts), ""]
    lines += ["### Examples", ""]
    lines.extend(_examples(engine))
    return "\n".join(lines) + "\n"


def _trades_table(engine: EngineReport) -> str:
    header = (
        "| Strategy | Bar path | FEFAT | Other | Matched | Exact | "
        + " | ".join(CLASS_COLUMNS)
        + " |"
    )
    rule = (
        "| --- | --- | ---: | ---: | ---: | ---: | "
        + " | ".join("---:" for _ in CLASS_COLUMNS)
        + " |"
    )
    rows = []
    for strategy in engine.strategies:
        summary = strategy.summary()
        counts = " | ".join(str(summary.trades_by_class.get(name, 0)) for name in CLASS_COLUMNS)
        rows.append(
            f"| {strategy.strategy} | {strategy.conventions.name} | {summary.fefat_trades} | "
            f"{summary.other_trades} | {summary.matched} | {summary.exact} | {counts} |"
        )
    return "\n".join([header, rule, *rows])


def _fills_table(engine: EngineReport) -> str:
    header = "| Strategy | Bar path | Fills compared | Equal | " + " | ".join(CLASS_COLUMNS) + " |"
    rule = "| --- | --- | ---: | ---: | " + " | ".join("---:" for _ in CLASS_COLUMNS) + " |"
    rows = []
    for strategy in engine.strategies:
        summary = strategy.summary()
        counts = " | ".join(str(summary.fills_by_class.get(name, 0)) for name in CLASS_COLUMNS)
        rows.append(
            f"| {strategy.strategy} | {strategy.conventions.name} | {summary.fills_compared} | "
            f"{summary.equal_fills} | {counts} |"
        )
    return "\n".join([header, rule, *rows])


def _pnl_table(engine: EngineReport, facts: dict[str, Any]) -> str:
    currency = "USD"
    header = f"| Strategy | Bar path | FEFAT ({currency}) | Other ({currency}) |"
    rows = [
        f"| {strategy.strategy} | {strategy.conventions.name} | {strategy.fefat_gross_pnl:,.2f} | "
        f"{strategy.other_gross_pnl:,.2f} |"
        for strategy in engine.strategies
    ]
    return "\n".join([header, "| --- | --- | ---: | ---: |", *rows])


def _examples(engine: EngineReport) -> list[str]:
    lines = []
    for strategy in engine.strategies:
        shown = strategy.classified.filter(pl.col("outcome") != MATCH).sort("entry_decision")
        for name in CLASS_COLUMNS:
            first = shown.filter(pl.col("outcome") == name).head(1)
            if first.is_empty():
                continue
            row = first.row(0, named=True)
            ticks = []
            if row["entry_ticks"] is not None and row["entry_ticks"] != 0:
                ticks.append(f"entry {row['entry_ticks']:+d} ticks")
            if row["exit_ticks"] is not None and row["exit_ticks"] != 0:
                ticks.append(f"exit {row['exit_ticks']:+d} ticks")
            delta = ", ".join(ticks) if ticks else "the same prices"
            lines.append(
                f"- `{strategy.strategy}`, {strategy.conventions.name}, `{name}`: the {row['side']} "
                f"decided at {_utc(row['entry_decision'])}, {row['note']}; FEFAT less the other "
                f"engine: {delta}."
            )
    return lines or ["- Every trade matched."]


def _utc(instant: int) -> str:
    return datetime.fromtimestamp(instant / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _classes(inputs: ReportInputs) -> str:
    lines = ["## Difference classes", ""]
    for kind, explanation in EXPLANATIONS.items():
        lines += [f"### `{kind}`", "", explanation, ""]
    lines += ["### Classes the data cannot exercise", ""]
    lines.extend(f"- **{name}.** {reason}" for name, reason in NOT_EXERCISED)
    unknown = unknown_count(inputs)
    lines += ["", f"Differences without a class, unknown: {unknown}.", ""]
    return "\n".join(lines)


def _ninjatrader_section(inputs: ReportInputs) -> str:
    if inputs.ninjatrader is None:
        return "\n".join(["## NinjaTrader 8", "", inputs.ninjatrader_pending, ""])
    return _engine_section("NinjaTrader 8", inputs.ninjatrader, inputs.fefat)
