"""The text of `docs/validation/ibkr-tick-check.md` (step 2.16) from the facts `scripts/tick_check.py`
gathers: counts, rates, timestamps, hashes, and tick differences, never a price (D-21)."""

from typing import Any

from fefat.backtest.fidelity_classes import FidelityClass

CLASSES = [str(name) for name in FidelityClass if name is not FidelityClass.MATCH]
EXPLANATIONS = {
    FidelityClass.BAR_BOUNDARY: (
        "IBKR stamps its prints to the second, so the prints of the second a 5-minute bar "
        "closes in carry the decision's own instant. On prints they are received at the "
        "decision, so they come before it (F-CLK-02): the mark at the decision is the last of "
        "them, and an order decided there never sees them, so a market order fills on the first "
        "print after that second (F-MKT-02). At one minute they open the bar that starts at the "
        "decision: the mark is the close of the bar before, and an order decided there sees "
        "that bar from its open (F-ACT-02), so a market order fills at its open, the first of "
        "them (F-MKT-03). The two runs therefore fill a market entry and a flat-by exit on "
        "different prints, place a limit or stop entry from different marks (F-ENT-02), and can "
        "reach a resting entry on those prints at the decision that places it on bars alone, or "
        "at the decision that cancels it on prints alone (F-ENT-03). A fill is of this class "
        "when the reference engine, replaying the prints with each print stamped at a "
        "decision's instant moved one nanosecond after it, where the bars put it, fills it "
        "otherwise than the prints: those prints alone moved it. A trade of one run alone is of "
        "this class too when the replay settles it otherwise than its run, the decision second "
        "having made or prevented it, at once or through a position it left open on one run at "
        "a later decision."
    ),
    FidelityClass.BAR_PATH: (
        "A 1-minute bar the position was held through reached both legs of the bracket. The "
        "bar's path takes the adverse extreme first, so the run on bars filled the stop "
        "(F-BAR-02, F-BAR-04) and flagged the fill ambiguous (F-BAR-05), while the prints "
        "reached the target first in that minute."
    ),
    FidelityClass.ENTRY_BAR_PATH: (
        "A limit or stop entry filled inside a 1-minute bar. After the fill the bar's path "
        "visits the extremes it has not reached yet, the adverse one first, then the close "
        "(F-BAR-03, F-BAR-04), while the prints after the fill went their own way: one run "
        "filled a leg in the entry's minute where the other carried the position out of it."
    ),
    FidelityClass.STOP_THROUGH: (
        "A stop, an entry or a leg, triggered by a print beyond its level that the print before "
        "had not reached. On prints it fills at that print, the worse of its level and the "
        "trigger (F-STP-03); on the bar's path it fills at its level (F-STP-04)."
    ),
    FidelityClass.CASCADE: (
        "A trade of one run alone that the restamped replay settles as its run does, made at a "
        "decision where the other run still held a position after an earlier difference of "
        "the bar's path on the same trade date. A knock-on of the decision second is "
        "`bar_boundary` instead. Flat by 15:00 Chicago, the runs start each trade date together."
    ),
}
OTHER_ENGINES = (
    "`leg_released_through` and `gap_limit_clamped` of step 2.14 name conventions of "
    "NautilusTrader and NinjaTrader 8: a leg released on its entry's tick and filled at that "
    "tick's price, and a limit filled at its price clamped into a bar that opened past it. Both "
    "runs here are FEFAT's, whose legs work from the record after the entry's fill and whose "
    "limits fill at their price (F-OCO-02, F-LMT-03), so neither class can arise."
)
NOT_EXERCISED = (
    "- **Aggressor sides and quotes.** IBKR's prints carry no aggressor side and no quotes, so "
    "the fills on prints follow FEFAT's rules for trades (F-MKT-02, F-STP-03, F-LMT-02); a run "
    "on TBBO is not checked here.",
    "- **Rolls.** The runs read the contract unspliced (`RunConfig.contract`) and cross no roll.",
    "- **Latency, slippage, and limits filled through their price.** The compatibility profile "
    "has no latency or slippage and fills a limit on a touch of its price (F-LMT-02); the "
    "defaults, 100 ms, one tick, and a limit filled by a print through its price (D-51, "
    "F-LMT-01), are not checked here.",
)


def report_text(facts: dict[str, Any]) -> str:
    """The report, section by section."""
    sections = [
        _title(facts),
        _versions_and_data(facts),
        _strategies(facts),
        _bars(facts),
        _differential(facts),
        _ticks_against_minutes(facts),
        _determinism(facts),
        _classes(facts),
    ]
    return "\n\n".join(sections) + "\n"


def _title(facts: dict[str, Any]) -> str:
    check, window = facts["check"], facts["window"]
    return (
        "# The tick engine on Interactive Brokers' prints\n\n"
        f"Written by `just tick-check` on {facts['written']} (step 2.16, "
        "`02-engine-and-data.md` §8 items 2 and 4, D-67): the three strategies of step 2.14 on "
        f"{check['contract']}'s sessions from {window['first']} to {window['last']} in the "
        f"store's `{check['provider']}` datasets, Interactive Brokers' Time and Sales and its "
        "own 1-minute bars, run through the Rust engine at fidelity `trades` and at one minute "
        "under step 2.14's compatibility profile, and through the Python reference engine on "
        "the same prints and bars. The bars rebuilt from the prints are held to the provider's "
        f"own and counted against `{check['reference_provider']}`'s; every fill of the "
        "reference engine is the Rust engine's; every fill that differs between the run on "
        "prints and its 1-minute rerun has a class; and each run's fills hold on a second run "
        "and on its first sessions alone. The report holds counts, rates, timestamps, hashes, "
        "and tick differences: no price (D-21)."
    )


def _versions_and_data(facts: dict[str, Any]) -> str:
    versions, settings = facts["versions"], facts["profile"]
    ticks = settings["slippage_ticks"]
    lines = [
        "## Versions and data",
        "",
        f"- FEFAT: engine {versions['engine']}, fill model {versions['fill_model']}, artifact "
        f"schema {versions['artifact_schema']} (crate {facts['engine_version']}, SDK "
        f"{facts['sdk_version']}).",
        *(
            f"- Data: `{dataset['dataset']}`, the store snapshot of the request "
            f"{dataset['first']} to {dataset['last']} the runs pinned (ADR-0019): "
            f"`{dataset['sha256']}`."
            for dataset in facts["datasets"]
        ),
        "- Sessions:",
        *(f"  - {_session(session)}" for session in facts["sessions"]),
        f"- Profile: latency {settings['latency_ms']} ms, slippage {ticks['market']} ticks on "
        f"market and {ticks['stop']} on stop orders, limit fill {settings['limit_fill']}, fee "
        f"table {settings['fee_table']}; the run on prints at fidelity `trades`, each trade "
        "date on its finest cached level (D-58), and the run on bars at `1m`.",
        f"- The reference engine replayed a strategy's sessions of prints in about "
        f"{facts['replay_seconds']['prints']:.1f} s on this PC.",
    ]
    return "\n".join(lines)


def _session(session: dict[str, Any]) -> str:
    head = f"{session['trade_date']}: {session['prints']:,} prints"
    if session["fidelity"] == "trades":
        return f"{head}, filled on trade prints."
    reason = session["left_out"]
    why = "" if reason is None else f": the engine cache leaves its prints out, since {reason}"
    return f"{head}, filled on 1-minute bars{why}."


def _strategies(facts: dict[str, Any]) -> str:
    lines = ["## The strategies", ""]
    for strategy in facts["strategies"]:
        definition = strategy["definition"]
        window = definition["window"]
        lines.append(
            f"- `{definition['name']}`: long when the 5-minute close is above the previous "
            f"close, short when below; the entry is {_entry(definition)}; one lot; a stop "
            f"{definition['stop_ticks']} ticks and a target {definition['target_ticks']} ticks "
            f"from the signal bar's close, one OCO group; entries from {window[0]} to "
            f"{window[1]} {definition['tz']}, flat-by {definition['flat_by']}."
        )
    return "\n".join(lines)


def _entry(definition: dict[str, Any]) -> str:
    if definition["entry"] == "market":
        return "a market order"
    return (
        f"a {definition['entry']} {definition['offset_ticks']} ticks from the mark at the "
        f"decision (F-ENT-02), cancelled at the next decision if unfilled "
        f"({definition['time_to_live_bars']} bar to live)"
    )


def _bars(facts: dict[str, Any]) -> str:
    check = facts["check"]
    provider, reference = check["provider"], check["reference_provider"]
    lines = [
        "## Bars",
        "",
        f"`fefat data verify-bars {check['root']} <date>` rebuilds each session's 1-minute bars "
        f"from its prints and compares them with `{provider}`'s own. `{reference}`'s bars of "
        f"the same minutes are counted against `{provider}`'s: IBKR filters block and spread "
        "trades and stamps prints to the second (D-67).",
        "",
        "| Session | Rebuilt bars compared | Differences | Columns |",
        "| --- | ---: | ---: | --- |",
        *(_rebuilt_row(row) for row in facts["bars"]),
        "",
        f"| Session | Minutes in both | `{provider}`'s alone | `{reference}`'s alone | Volume "
        f"differs | A price differs | `{provider}`'s volume of `{reference}`'s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(_reference_row(row, reference) for row in facts["bars"]),
    ]
    ends = [
        f"- `{reference}`'s bars of {row['trade_date']} end at {row['reference']['ends']}, so "
        "the later minutes of that session are not compared."
        for row in facts["bars"]
        if row["reference"] is not None and row["reference"]["ends"] is not None
    ]
    return "\n".join([*lines, *([""] if ends else []), *ends])


def _rebuilt_row(row: dict[str, Any]) -> str:
    rebuilt = row["rebuilt"]
    columns = "none"
    if rebuilt["differences"]:
        columns = f"{', '.join(rebuilt['columns'])} at {', '.join(rebuilt['minutes'])}"
    return (
        f"| {row['trade_date']} | {rebuilt['compared']:,} | {rebuilt['differences']} | {columns} |"
    )


def _reference_row(row: dict[str, Any], reference: str) -> str:
    counted = row["reference"]
    if counted is None:
        return f"| {row['trade_date']} | no `{reference}` bars of the session | | | | | |"
    share = counted["volume_share"]
    shown = "" if share is None else f"{share:.2%}"
    return (
        f"| {row['trade_date']} | {counted['both']:,} | {counted['alone']} | "
        f"{counted['reference_alone']} | {counted['volume_differs']} | "
        f"{counted['price_differs']} | {shown} |"
    )


def _differential(facts: dict[str, Any]) -> str:
    lines = [
        "## Reference engine against the Rust engine",
        "",
        "The reference engine (`fefat.reference`, D-10) replays each strategy from flat on the "
        "sessions on prints, deciding on the run's own signal rows under its fee table, and its "
        "fills are held to the Rust engine's field by field: order, instant, price, rule, "
        "flags, liquidity, slippage, lots, side, role, fidelity, cash, fee, and contract, in "
        "the integer units of ADR-0019.",
        "",
        "| Strategy | Sessions | Prints | Decisions | Rust fills | Reference fills | Identical |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    bars, on_bars = [], []
    for strategy in facts["strategies"]:
        differential = strategy["differential"]
        sessions = differential["sessions"]
        lines.append(
            f"| {strategy['name']} | {sessions[0]} to {sessions[-1]} | "
            f"{differential['prints']:,} | {differential['decisions']:,} | "
            f"{differential['rust_fills']:,} | {differential['reference_fills']:,} | "
            f"{differential['identical']:,} |"
        )
        bars.append(
            f"{strategy['name']} {differential['minute_identical']:,} of "
            f"{differential['minute_fills']:,}"
        )
        on_bars.append(f"{strategy['name']} {differential['ticks_on_bars']['fills']:,}")
    every = facts["strategies"][0]["differential"]
    lines += [
        "",
        "- The runs on 1-minute bars too: the reference engine replays them on every session's "
        f"bars, {every['bar_sessions'][0]} to {every['bar_sessions'][-1]}, and their fills are "
        f"identical, {', '.join(bars)}.",
    ]
    rest = every["ticks_on_bars"]["sessions"]
    if rest:
        lines.append(
            f"- On {', '.join(rest)}, of which the engine cache holds no prints, the runs on "
            "prints fill on the bars (D-58), and their fills are the runs on bars' fills of it, "
            f"order ids apart, which number each run's own orders: {', '.join(on_bars)}."
        )
    return "\n".join(lines)


def _ticks_against_minutes(facts: dict[str, Any]) -> str:
    lines = [
        "## Ticks against minutes",
        "",
        "The fidelity check at one minute (`fidelity_check`, step 2.12) reruns the sessions on "
        "prints from flat on their 1-minute bars under the run's own settings; the run on bars "
        "here is that rerun, pair for pair and tick for tick, which the command holds to each "
        "other. Trades are matched by the decision that entered them and their side; a fill on "
        "prints and a fill on a bar are alike at one price inside the bar's minute.",
        "",
        *(_fidelity_check(strategy) for strategy in facts["strategies"]),
        "",
        "### Trades",
        "",
        "| Strategy | Ticks | Minutes | Matched | Exact | Exact of matched | Exits alike of "
        f"matched | {' | '.join(CLASSES)} |",
        f"| --- | ---: | ---: | ---: | ---: | ---: | ---: | {' | '.join(['---:'] * len(CLASSES))} |",
        *(_trades_row(strategy) for strategy in facts["strategies"]),
        "",
        "### Fills",
        "",
        f"| Strategy | Fills compared | Equal | Equal of compared | {' | '.join(CLASSES)} |",
        f"| --- | ---: | ---: | ---: | {' | '.join(['---:'] * len(CLASSES))} |",
        *(_fills_row(strategy) for strategy in facts["strategies"]),
        "",
        "Each trade counts once, by its first class; each fill that differs counts once, a pair's "
        "entry or exit, and a trade of one run alone with both its fills.",
        "",
        "### How far apart",
        "",
        "The differing fills of the matched pairs, the fill on prints less the fill on bars in "
        "ticks, by class, and how many ticks more the pairs made on prints than on bars, a lot "
        "each, long and short alike.",
        "",
        "| Strategy | Class | Fills | Mean ticks apart | Largest |",
        "| --- | --- | ---: | ---: | ---: |",
        *(
            _apart_row(strategy["name"], row)
            for strategy in facts["strategies"]
            for row in strategy["fidelity"]["measured"]["by_class"]
        ),
        "",
        *(_net_ticks(strategy) for strategy in facts["strategies"]),
        "",
        "### The decision second",
        "",
        *_decision_second(facts),
        "",
        "### Examples",
        "",
        *(
            _example(strategy["name"], example)
            for strategy in facts["strategies"]
            for example in strategy["fidelity"]["examples"]
        ),
    ]
    return "\n".join(lines)


def _fidelity_check(strategy: dict[str, Any]) -> str:
    check = strategy["fidelity"]["check"]
    return (
        f"- `{strategy['name']}`: the fidelity check of {check['first']} to {check['last']} "
        f"reran {check['minute_trades']} trades against the prints' {check['tick_trades']}: "
        f"{check['pairs']} matched pairs, {check['moved']} with a fill price moved, "
        f"{check['unmatched']} of the prints' trades and {check['extra']} of its own without "
        "a pair."
    )


def _rate(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else ""


def _trades_row(strategy: dict[str, Any]) -> str:
    fidelity = strategy["fidelity"]
    classes = [str(fidelity["trades_by_class"].get(name, 0)) for name in CLASSES]
    matched = fidelity["matched"]
    return (
        f"| {strategy['name']} | {fidelity['tick_trades']} | {fidelity['minute_trades']} | "
        f"{matched} | {fidelity['exact']} | {_rate(fidelity['exact'], matched)} | "
        f"{_rate(fidelity['exits_alike'], matched)} | {' | '.join(classes)} |"
    )


def _fills_row(strategy: dict[str, Any]) -> str:
    fidelity = strategy["fidelity"]
    classes = [str(fidelity["fills_by_class"].get(name, 0)) for name in CLASSES]
    compared = fidelity["fills_compared"]
    return (
        f"| {strategy['name']} | {compared} | {fidelity['equal_fills']} | "
        f"{_rate(fidelity['equal_fills'], compared)} | {' | '.join(classes)} |"
    )


def _apart_row(name: str, row: dict[str, Any]) -> str:
    return (
        f"| {name} | `{row['outcome']}` | {row['fills']} | {row['mean']:.1f} | {row['largest']} |"
    )


def _net_ticks(strategy: dict[str, Any]) -> str:
    measured = strategy["fidelity"]["measured"]
    net, pairs = measured["net_ticks"], measured["pairs"]
    more = "more" if net >= 0 else "less"
    each = f", {abs(net) / pairs:.2f} a trade" if pairs else ""
    return (
        f"- `{strategy['name']}`: over its {pairs} matched pairs the trades on prints made "
        f"{abs(net)} ticks {more} than those on bars{each}."
    )


def _decision_second(facts: dict[str, Any]) -> list[str]:
    second = facts["decision_second"]
    path_classes = [name for name in CLASSES if name != str(FidelityClass.BAR_BOUNDARY)]
    return [
        f"{second['with_prints']} of the {second['decisions']} decisions on the sessions on "
        f"prints have prints stamped at their own instant, {second['prints']:,} of the "
        f"{second['of_prints']:,} prints. With those prints moved one nanosecond after their "
        "decision, the reference engine's trades on the prints are those on the bars but for "
        "the trades below, each classed by where the bar's path parts from the prints; every "
        "other difference of the runs on prints from those on bars is the decision second's, "
        "`bar_boundary`.",
        "",
        f"| Strategy | Trades apart | {' | '.join(path_classes)} |",
        f"| --- | ---: | {' | '.join(['---:'] * len(path_classes))} |",
        *(_restamped_row(strategy, path_classes) for strategy in facts["strategies"]),
    ]


def _restamped_row(strategy: dict[str, Any], path_classes: list[str]) -> str:
    restamped = strategy["fidelity"]["restamped"]
    counts = [str(restamped["trades_by_class"].get(name, 0)) for name in path_classes]
    return f"| {strategy['name']} | {restamped['trades_apart']} | {' | '.join(counts)} |"


def unknown_count(facts: dict[str, Any]) -> int:
    """The differences without a class: of the runs on prints against those on bars, and of
    the restamped replays against those on bars."""
    return sum(
        strategy["fidelity"]["unknown"] + strategy["fidelity"]["restamped"]["unknown"]
        for strategy in facts["strategies"]
    )


def _example(name: str, example: dict[str, Any]) -> str:
    ticks = []
    if example["entry_ticks"]:
        ticks.append(f"entry {example['entry_ticks']:+d} ticks")
    if example["exit_ticks"]:
        ticks.append(f"exit {example['exit_ticks']:+d} ticks")
    apart = f"; ticks less minutes: {', '.join(ticks)}" if ticks else ""
    return (
        f"- `{name}`, `{example['outcome']}`: the {example['side']} decided at "
        f"{example['decision']}, {example['note']}{apart}."
    )


def _determinism(facts: dict[str, Any]) -> str:
    strategies = facts["strategies"]
    throughs = [prefix["through"] for prefix in strategies[0]["determinism"]["prefixes"]]
    lines = [
        "## Determinism",
        "",
        "| Strategy | Run key | Key again | Fills | Second run | Saved | "
        + " | ".join(f"Through {through}" for through in throughs)
        + " |",
        "| --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in throughs) + " |",
        *(_determinism_row(strategy) for strategy in strategies),
        "",
        "- Each run's key (`02` §4) is worked out again from its inputs. Two fresh runs of the "
        "engine give fills of one hash (`fefat_engine.table_hash`), which is the saved run's. "
        "The runs on its first sessions alone, fresh from the engine as well, give the whole "
        "run's fills of those sessions.",
        *(_shared_seconds(strategy) for strategy in strategies),
    ]
    return "\n".join(lines)


def _determinism_row(strategy: dict[str, Any]) -> str:
    determinism = strategy["determinism"]
    fills = determinism["fills_hash"]
    cells = [
        f"`{determinism['run_key'][:16]}`",
        _alike(determinism["key_again"], determinism["run_key"]),
        f"`{fills[:16]}`",
        _alike(determinism["second_fills_hash"], fills),
        _alike(determinism["saved_fills_hash"], fills),
        *("equal" if prefix["equal"] else "different" for prefix in determinism["prefixes"]),
    ]
    return f"| {strategy['name']} | {' | '.join(cells)} |"


def _alike(first: str, second: str) -> str:
    return "equal" if first == second else "different"


def _shared_seconds(strategy: dict[str, Any]) -> str:
    shared = strategy["determinism"]["shared_seconds"]
    otherwise = shared["trades_reversed_otherwise"]
    reading = (
        "so their order matters, and the Rust engine's fills are those of the stored order "
        "(F-CLK-03)"
        if otherwise
        else "so their order changes no trade of these sessions"
    )
    return (
        f"- `{strategy['name']}`: {shared['fills_in_shared_seconds']:,} of its "
        f"{shared['fills']:,} fills on prints fell in a second holding more than one print. "
        "Replayed with each second's prints in the reverse of their stored order, the "
        f"reference engine makes {otherwise} of its {shared['trades']} trades otherwise, "
        f"{reading}."
    )


def _classes(facts: dict[str, Any]) -> str:
    unknown = unknown_count(facts)
    lines = ["## Difference classes"]
    for name, explanation in EXPLANATIONS.items():
        lines += ["", f"### `{name}`", "", explanation]
    lines += [
        "",
        "### Step 2.14's other classes",
        "",
        OTHER_ENGINES,
        "",
        "### What the data cannot exercise",
        "",
        *NOT_EXERCISED,
        "",
        f"Differences without a class, unknown: {unknown}.",
    ]
    return "\n".join(lines)
