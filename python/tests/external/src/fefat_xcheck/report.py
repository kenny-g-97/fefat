"""The comparison report, `docs/validation/nautilus-comparison.md` (step 2.14, Done means 1 to
3): the versions of every engine and the data snapshot, the strategies and the profile, each
engine's section with its settings, its data checks, each strategy's match rates and difference
classes, and the classes with the rules behind them. It holds counts, rates, timestamps, and
tick differences: never a price of the licensed data, nor a path of this PC."""

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
        "A 1-minute bar the position was held through from its open, a later bar or the bar a "
        "market entry filled at the open of, reached both the stop and the target. FEFAT visits "
        "a bar's adverse extreme first while holding a position, so the stop fills (F-BAR-02, "
        "F-BAR-04) and the fill is flagged ambiguous (F-BAR-05). NautilusTrader visits the open, "
        "the high, the low, "
        "and the close in that order, or with `bar_adaptive_high_low_ordering` the extreme nearer "
        "the open first, the low on a tie; NinjaTrader 8 the extreme nearer the open first, the "
        "high on a tie (H2). The replay of both paths gives each engine the leg it took."
    ),
    DifferenceClass.ENTRY_BAR_PATH: (
        "A limit or stop entry filled inside a 1-minute bar, and the two engines visit the rest "
        "of the bar in different orders. Flat, FEFAT visits the extreme favourable to the entry "
        "first, the high for a buy (F-BAR-03); after the fill, the extremes not yet reached come "
        "adverse first, then the close (F-BAR-04), the exit plan working from the entry's point "
        "(F-OCO-02). NautilusTrader visits the open, the high, the low, and the close in its "
        "fixed or adaptive order whatever the entry, so an extreme FEFAT visited before the "
        "fill can come after it there, or the reverse: one engine fills a leg on the rest of the "
        "bar while the other carries the position into the next bar, or they fill different "
        "legs. The replay of both paths on the entry's bar (`fefat_xcheck.replay`) gives each "
        "engine the exit it made."
    ),
    DifferenceClass.LEG_RELEASED_THROUGH: (
        "A limit or stop entry filled inside a 1-minute bar on a tick already past one of its "
        "legs. NautilusTrader releases the stop and the target on the tick that fills the entry, "
        "and a leg whose level that tick's price is past fills at that price: a buy limit filled "
        "on the low tick has its stop filled at the low, below the stop's level; a buy stop "
        "filled on the high tick has its target filled at the high, above the target's level. "
        "FEFAT works the legs on the rest of the path from the entry's point and fills a stop at "
        "its level (F-STP-04) and a target at its price, never better (F-LMT-03). The replay of "
        "both paths gives each engine the price it filled at."
    ),
    DifferenceClass.GAP_LIMIT_CLAMPED: (
        "A bar opened past a resting limit's price in its favour and stayed past it. FEFAT "
        "fills the limit at its price, never better and never clamped into the range of prices "
        "traded in its interval (F-LMT-03, F-SLP-01); NinjaTrader 8 fills it at its price "
        "clamped into the bar, the bar's high for a buy limit or its low for a sell limit, so "
        "the fill is better than the limit by the gap (the builder's spec, H4: a limit fills at "
        "its own price, also when the bar opens beyond it, clamped into the bar). NautilusTrader "
        "fills a resting limit at its price, as FEFAT does."
    ),
    DifferenceClass.CASCADE: (
        "A trade one engine made, as its rules give it, while the other still held a position at "
        "that decision, after an earlier difference on the same trade date left the two in "
        "different states; the flat-by at 15:00 Chicago brings them back together each trade "
        "date."
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
        "MESU2026 and MNQU2026 are the front contracts for the whole window and the FEFAT runs "
        "read one contract each and crossed no roll (asserted by `scripts/xcheck.py`), so no "
        "engine rolled.",
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
    of what both engines read and decided on, and its strategies."""

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
        _engine_section("NautilusTrader", inputs.nautilus),
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
            "FEFAT under the compatibility profile (touch fills, no slippage ticks, no latency, "
            "FEFAT's own bar path), and the market strategy on MNQU2026 against NinjaTrader 8. "
            "Trades are matched by the decision that entered them and their side. Each engine's "
            "trade is held to a replay of its own documented rules on the 1-minute bars "
            "(`fefat_xcheck.replay`), so a difference is explained only where both fills are what "
            "the rules give, and every explained difference falls into a class below. A market "
            "entry and a flat-by exit are compared by their prices, since their stamps are a "
            "convention of their own (`bar_boundary`); every other fill by its price and its "
            "bar. A pair is exact when both its fills match.",
            "",
        ]
    )


def _versions_and_data(inputs: ReportInputs) -> str:
    facts, cut = inputs.fefat, inputs.cut
    versions = facts["versions"]
    snapshot = facts["snapshot"]
    profile = facts["profile"]
    ticks = profile["slippage_ticks"]
    fees = _fee_in_force(facts)
    vendor = cut["raw_file"]["vendor_sha256"]
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
        f"- The raw Databento batch file `{cut['raw_file']['name']}` "
        f"({cut['raw_file']['vendor_version']}): SHA-256 `{cut['raw_file']['sha256']}`"
        + (f", the vendor's `{vendor}`" if vendor else "")
        + f". The month cut NautilusTrader read, `{cut['cut']['name']}` ({cut['cut']['from']} to "
        f"{cut['cut']['to']}, the raw file's own metadata): SHA-256 `{cut['cut']['sha256']}`.",
        f"- Profile: fidelity {profile['fidelity']}, latency {profile['latency_ms']} ms, slippage "
        f"{ticks['market']} ticks on market and {ticks['stop']} on stop orders, limit fill "
        f"{profile['limit_fill']}; fee table {facts['fee_table']['name']} ({fees} on the "
        "window), not compared: fills do not depend on fees with fixed sizing, and the gross "
        "profit and loss is compared.",
    ]
    return "\n".join(lines) + "\n"


def _fee_in_force(facts: dict[str, Any]) -> str:
    """The fee table's schedule on the window's first trade date: the last that took effect by
    then, or the table's first for a date before it, which such a date takes (F-FEE-01)."""
    schedules = facts["fee_table"]["schedules"]
    in_force = [fee for day, fee in schedules if day <= facts["window"]["first"]]
    return in_force[-1] if in_force else schedules[0][1]


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


def _engine_section(title: str, engine: EngineReport) -> str:
    lines = [f"## {title}", "", f"- {engine.engine}."]
    lines.extend(f"- {setting}" for setting in engine.settings)
    lines.extend(f"- {check}" for check in engine.data_checks)
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
    lines += ["", "### Gross profit and loss", "", _pnl_table(engine), "", "### Examples", ""]
    lines.extend(_examples(engine))
    return "\n".join(lines) + "\n"


def _trades_table(engine: EngineReport) -> str:
    header = (
        "| Strategy | Bar path | FEFAT | Other | Matched | Exact | Exact of matched | "
        + " | ".join(CLASS_COLUMNS)
        + " |"
    )
    rule = (
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
        + " | ".join("---:" for _ in CLASS_COLUMNS)
        + " |"
    )
    rows = []
    for strategy in engine.strategies:
        summary = strategy.summary()
        counts = " | ".join(str(summary.trades_by_class.get(name, 0)) for name in CLASS_COLUMNS)
        rows.append(
            f"| {strategy.strategy} | {strategy.conventions.name} | {summary.fefat_trades} | "
            f"{summary.other_trades} | {summary.matched} | {summary.exact} | "
            f"{_rate(summary.exact, summary.matched)} | {counts} |"
        )
    return "\n".join([header, rule, *rows])


def _fills_table(engine: EngineReport) -> str:
    header = (
        "| Strategy | Bar path | Fills compared | Equal | Equal of compared | "
        + " | ".join(CLASS_COLUMNS)
        + " |"
    )
    rule = "| --- | --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in CLASS_COLUMNS) + " |"
    rows = []
    for strategy in engine.strategies:
        summary = strategy.summary()
        counts = " | ".join(str(summary.fills_by_class.get(name, 0)) for name in CLASS_COLUMNS)
        rows.append(
            f"| {strategy.strategy} | {strategy.conventions.name} | {summary.fills_compared} | "
            f"{summary.equal_fills} | {_rate(summary.equal_fills, summary.fills_compared)} | "
            f"{counts} |"
        )
    return "\n".join([header, rule, *rows])


def _rate(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "n/a"


def _pnl_table(engine: EngineReport) -> str:
    header = "| Strategy | Bar path | FEFAT (USD) | Other (USD) |"
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
    return _engine_section("NinjaTrader 8", inputs.ninjatrader)
