"""A trade's explanation as a job (step 5.9, D-93, `01-architecture.md` section 6): the trade
replayed through the reference engine on the run's saved spec, signals, and pinned data, as the
notebook's `Run.explain` replays it, in the worker itself, since it runs no code of the trader's
and needs no executor; the job's result is the replay's events and fills, or the replay's
refusal in its words, which name no folder of this PC. A replay can take seconds, the store's
data checked against the run's pins first."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from fefat.backtest.explain import EnginesDisagreementError, Explanation, explain
from fefat.backtest.saved_runs import saved_run
from fefat.config import FefatPaths
from fefat.market.calendar import utc_text
from fefat.market.engine_units import money_text, price_text
from fefat.market.fidelity import parse_fidelity
from fefat.reference.ledger import FillFlag, Liquidity
from fefat.reference.orders import OrderRole, Side
from fefat.reference.rust_batch import FillView
from fefat_app.jobs.progress import JobProgress
from fefat_app.trade_review import (
    ExplainedEvent,
    ExplainedFill,
    ExplainPayload,
    ExplanationRefused,
    TradeExplained,
)


class ReplayCrashedError(RuntimeError):
    """A replay that failed for a reason the engine did not give, in words that name no folder
    of this PC: the job fails with it, where a refusal is the job's answer."""


def run_explanation(
    paths: FefatPaths, payload: Mapping[str, Any], progress: JobProgress
) -> dict[str, Any]:
    """Replay the trade of `payload` of the run saved in `paths`' runs folder, reporting as it
    starts; the trade explained, or why the replay refused it; `ReplayCrashedError` where it
    crashed, since the worker keeps a crash's words as the job's error, which the page shows."""
    asked = ExplainPayload.model_validate(payload)
    progress.advance(0, f"Replaying trade {asked.trade_id} through the reference engine")
    try:
        explanation = explain(saved_run(paths.runs_dir, asked.run_key), asked.trade_id)
    except (ValueError, EnginesDisagreementError, FileNotFoundError) as refused:
        reason = without_folders(str(refused), paths, asked.run_key)
        return ExplanationRefused(trade_id=asked.trade_id, reason=reason).model_dump(mode="json")
    except Exception as crashed:
        words = without_folders(f"{type(crashed).__name__}: {crashed}", paths, asked.run_key)
        raise ReplayCrashedError(words) from crashed
    progress.advance(100, f"Replayed trade {asked.trade_id}")
    return _explained(explanation).model_dump(mode="json")


def _explained(explanation: Explanation) -> TradeExplained:
    """The explanation as the job's result: its heading, the first line `Run.explain` prints, the
    instant its replay started at, its log's entries, and its fills."""
    return TradeExplained(
        trade_id=explanation.trade_id,
        heading=explanation.lines[0],
        started_at=utc_text(explanation.started_at),
        events=tuple(
            ExplainedEvent(
                time=utc_text(entry.ts),
                kind=entry.kind,
                order=entry.order,
                rule=entry.rule,
                text=entry.text,
            )
            for entry in explanation.entries
        ),
        fills=tuple(_fill(fill) for fill in explanation.fills),
    )


def _fill(fill: FillView) -> ExplainedFill:
    """A fill of the replay, in the units the API sends."""
    return ExplainedFill(
        order=fill.order,
        role=OrderRole(fill.role),
        side=Side(fill.side),
        lots=fill.lots,
        time=utc_text(fill.ts),
        price=price_text(fill.price),
        rule=fill.rule,
        liquidity=Liquidity(fill.liquidity),
        slippage_ticks=fill.slippage_ticks,
        fee=Decimal(money_text(fill.fee)),
        flags=tuple(FillFlag(flag) for flag in fill.flags),
        fidelity=parse_fidelity(fill.fidelity),
        contract=fill.contract,
    )


def without_folders(reason: str, paths: FefatPaths, run_key: str) -> str:
    """`reason` naming the run's folder as the run, and the data folder and FEFAT's home in
    words, so that no folder of this PC reaches the page (D-80)."""
    return (
        reason.replace(str(paths.runs_dir / run_key), f"run {run_key[:12]}")
        .replace(str(paths.data_dir), "your data folder")
        .replace(str(paths.home), "FEFAT's home folder")
    )
