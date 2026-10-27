"""The batch `fefat-cli run` reads and writes (step 2.6), a development tool of the repository
until the Python bindings of step 2.10: cases, each a scenario and the hours its market trades
in, as `run.json` and the Arrow files of their records and signal rows; and the outputs read back
as each case's fills, event log, and ledger at its end, in the reference engine's terms. The
formats are those `engine/crates/fefat-cli/src/run/` reads and writes. A case's records carry the
UTC day of their instant as their trade date, since nothing on ticks reads a fill's trade date
yet."""

import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.fidelity import TickFidelity
from fefat.reference.event_log import LogEntry
from fefat.reference.hours import AlwaysOpen, CalendarHours
from fefat.reference.ledger import Fill
from fefat.reference.orders import Order, PricedOrder
from fefat.reference.scenario_runner import held_lots
from fefat.reference.scenarios import AnyScenario, TemplateScenario
from fefat.reference.tape import BarRecord, Record, TbboRecord
from fefat.reference.units import (
    PRICE_DECIMALS,
    InstrumentParameters,
    instrument_parameters,
    lots_of,
)

CAPITAL = 50_000_000_000
"""The run's capital in micro-units, 50,000 USD (D-51): the ledger's starting cash."""
NANOSECONDS_PER_DAY = 86_400 * 1_000_000_000
_SIGNALS = ("ts_close", "long_entry", "short_entry", "long_exit", "short_exit")
_OPTIONAL_SIGNALS = ("stop_price", "target_price", "size_mult", "wake")
_FLAGS = ("ambiguous", "size_exceeded")


@dataclass(frozen=True, slots=True)
class EngineCase:
    """A scenario as both engines run it: with the hours its market trades in and, for an
    instrument of the table, its session table, which a template's flat-by reads."""

    scenario: AnyScenario
    hours: AlwaysOpen | CalendarHours
    sessions: SessionTable | None = None


class FillView(NamedTuple):
    """What the engines compare of a fill (F-TAG-01), but its fee, which costs bring in step 2.9:
    the order, when, at what price, the rule that priced it, its flags, its liquidity, its
    slippage in ticks, its lots, side, and role, its fidelity, and what its value moved the cash
    by (F-FEE-03)."""

    order: int
    ts: int
    price: int
    rule: str
    flags: tuple[str, ...]
    liquidity: str
    slippage_ticks: int
    lots: int
    side: str
    role: str
    fidelity: str
    cash: int

    @classmethod
    def of(cls, fill: Fill) -> "FillView":
        """The reference engine's fill."""
        return cls(
            fill.order,
            fill.ts,
            fill.price,
            fill.rule,
            tuple(sorted(str(flag) for flag in fill.flags)),
            str(fill.liquidity),
            fill.slippage_ticks,
            fill.lots,
            str(fill.side),
            str(fill.role),
            str(fill.fidelity),
            fill.cash,
        )

    @classmethod
    def of_row(cls, row: dict[str, Any]) -> "FillView":
        """A row of `fills.arrow`."""
        flags = tuple(sorted(flag for flag in _FLAGS if row[flag]))
        return cls(
            row["order"],
            row["ts"],
            row["price"],
            row["rule"],
            flags,
            row["liquidity"],
            row["slippage_ticks"],
            row["lots"],
            row["side"],
            row["role"],
            row["fidelity"],
            row["cash"],
        )


class LogView(NamedTuple):
    """What the engines compare of an entry of the event log: when, what, of which order, and
    under which rule; the words of its text may differ."""

    ts: int
    kind: str
    order: int | None
    rule: str | None

    @classmethod
    def of(cls, entry: LogEntry) -> "LogView":
        """The reference engine's entry."""
        return cls(entry.ts, str(entry.kind), entry.order, entry.rule)


@dataclass(frozen=True, slots=True)
class RustOutcome:
    """A case's outputs from `fefat-cli run`: its fills, its event log, and its ledger at its
    end, the lots held, positive long, and the cash in micro-units."""

    fills: tuple[FillView, ...]
    log: tuple[LogView, ...]
    position: int
    cash: int


def write_batch(cases: Sequence[EngineCase], folder: Path) -> None:
    """The batch of `cases` in `folder`: `run.json`, and the Arrow files of their records and
    signal rows, each row tagged with its case's place in `run.json`."""
    for case in cases:
        if not isinstance(case.scenario.fidelity, TickFidelity):
            raise ValueError(
                f"Expected cases on ticks, tbbo or trades, got {case.scenario.id} on "
                f"{case.scenario.fidelity}: bar fidelities arrive in step 2.7."
            )
    folder.mkdir(parents=True)
    manifest = {"cases": [_case_document(case) for case in cases]}
    (folder / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    for fidelity, frame in _tapes(cases).items():
        frame.write_ipc(folder / f"{fidelity}.arrow", compression="uncompressed")
    signals = _signal_rows(cases)
    if signals is not None:
        signals.write_ipc(folder / "signals.arrow", compression="uncompressed")


def read_outcomes(folder: Path, cases: int) -> list[RustOutcome]:
    """Each case's fills, event log, and ledger from the outputs of `fefat-cli run`."""
    fills, log, ledgers = (_read(folder / f"{name}.arrow") for name in ("fills", "log", "ledger"))
    outcomes = []
    for case in range(cases):
        of_case = pl.col("case") == case
        rows = fills.filter(of_case).iter_rows(named=True)
        entries = log.filter(of_case).iter_rows(named=True)
        ledger = ledgers.filter(of_case).row(0, named=True)
        outcomes.append(
            RustOutcome(
                fills=tuple(FillView.of_row(row) for row in rows),
                log=tuple(
                    LogView(entry["ts"], entry["kind"], entry["order"], entry["rule"])
                    for entry in entries
                ),
                position=ledger["position"],
                cash=ledger["cash"],
            )
        )
    return outcomes


def _case_document(case: EngineCase) -> dict[str, object]:
    scenario = case.scenario
    parameters = instrument_parameters(scenario.instrument)
    settings = scenario.settings
    return {
        "id": scenario.id,
        "fidelity": str(scenario.fidelity),
        "contract": scenario.id,
        "instrument": {
            "tick_size": parameters.tick,
            "money_per_point": parameters.money_per_point,
            "lot_step": int(parameters.lot_step.scaleb(PRICE_DECIMALS)),
        },
        "settings": {
            "latency_ms": settings.latency_ms,
            "slippage_ticks": {
                "market": settings.slippage_ticks.market,
                "stop": settings.slippage_ticks.stop,
            },
            "limit_fill": str(settings.limit_fill),
        },
        "hours": _hours_document(case.hours),
        "capital": CAPITAL,
        "position": _position_document(scenario),
        "market_data": {"kind": "tape"},
        "decisions": _decisions_document(scenario, parameters),
    }


def _hours_document(hours: AlwaysOpen | CalendarHours) -> dict[str, object]:
    if isinstance(hours, AlwaysOpen):
        return {"kind": "always"}
    sessions = [
        {
            "open": session.open,
            "close": session.close,
            "halts": [{"start": halt.start, "end": halt.end} for halt in session.halts],
        }
        for session in hours.sessions()
    ]
    return {"kind": "sessions", "sessions": sessions}


def _position_document(scenario: AnyScenario) -> dict[str, object] | None:
    if scenario.position is None:
        return None
    lots = abs(held_lots(scenario))
    return {"side": str(scenario.position.side), "lots": lots, "price": scenario.position.price}


def _decisions_document(
    scenario: AnyScenario, parameters: InstrumentParameters
) -> dict[str, object]:
    if isinstance(scenario, TemplateScenario):
        return {"kind": "template", "strategy": scenario.strategy.document()}
    groups: dict[str, int] = {}
    for order in scenario.orders:
        if order.oco is not None:
            groups.setdefault(order.oco, len(groups) + 1)
    orders = [_order_document(order, groups, parameters) for order in scenario.orders]
    return {"kind": "orders", "orders": orders}


def _order_document(
    order: Order, groups: dict[str, int], parameters: InstrumentParameters
) -> dict[str, object]:
    bracket = order.bracket
    legs = None
    if bracket is not None:
        legs = {
            "stop": {"id": bracket.stop.id, "price": bracket.stop.price},
            "target": {"id": bracket.target.id, "price": bracket.target.price},
        }
    return {
        "id": order.id,
        "placed_at": order.placed_at,
        "side": str(order.side),
        "kind": order.kind,
        "price": order.price if isinstance(order, PricedOrder) else None,
        "lots": lots_of(order.quantity, parameters.lot_step),
        "oco": None if order.oco is None else groups[order.oco],
        "bracket": legs,
    }


def _tapes(cases: Sequence[EngineCase]) -> dict[str, pl.DataFrame]:
    """Each fidelity's records of every case, in the columns of the engine cache, with the case
    and the trade date."""
    columns: dict[str, dict[str, list[int]]] = {}
    for number, case in enumerate(cases):
        fidelity = str(case.scenario.fidelity)
        for record in case.scenario.tape:
            table = columns.setdefault(fidelity, {})
            for name, value in _record_values(number, record).items():
                table.setdefault(name, []).append(value)
    return {
        fidelity: pl.DataFrame(table, schema=dict.fromkeys(table, pl.Int64))
        for fidelity, table in columns.items()
    }


def _record_values(case: int, record: Record) -> dict[str, int]:
    if isinstance(record, BarRecord):
        raise ValueError("Expected trades or TBBO records, got a bar: bars arrive in step 2.7.")
    # shortcut: the UTC day stands in for the trade date, which nothing on ticks reads; use the
    # session table's trade date when step 2.7 replays bars by trade date.
    values = {
        "case": case,
        "trade_date": record.ts // NANOSECONDS_PER_DAY,
        "ts_recv": record.ts,
        "price": record.price,
        "size": record.size,
    }
    if isinstance(record, TbboRecord):
        quote = {"bid": record.bid, "ask": record.ask, "bid_size": record.bid_size}
        values |= {**quote, "ask_size": record.ask_size}
    return values


def _signal_rows(cases: Sequence[EngineCase]) -> pl.DataFrame | None:
    """The signal rows of the template cases, each tagged with its case: the four signals and the
    optional columns the template reads, absent ones null (D-53)."""
    frames = []
    for number, case in enumerate(cases):
        if not isinstance(case.scenario, TemplateScenario):
            continue
        frame = case.scenario.signal_frame()
        kept = [*_SIGNALS, *(name for name in _OPTIONAL_SIGNALS if name in frame.columns)]
        frames.append(frame.select(pl.lit(number, dtype=pl.Int64).alias("case"), *kept))
    return pl.concat(frames, how="diagonal") if frames else None


def _read(path: Path) -> pl.DataFrame:
    """An Arrow file read from its bytes, so that no map keeps the temporary folder open on
    Windows."""
    return pl.read_ipc(io.BytesIO(path.read_bytes()))
