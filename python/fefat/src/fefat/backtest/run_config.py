"""How a backtest runs (step 2.10, D-51, `docs/spec/fill-semantics.md` §18): the finest data it
fills on, the latency, the slippage ticks per order class, when limits fill, what a roll does
with an open position, the fee table, the capital, how the engine replays the records, and the
provider whose datasets it reads. A setting left out takes its default, which `applied` writes
in, so that a run's record names every value it ran under:

    config = RunConfig(fee_table="prop-topstep", slippage_ticks=SlippageTicks(market=2, stop=2))
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer, field_validator

from fefat.market.fees import TABLES
from fefat.market.fidelity import TickFidelity, parse_fidelity
from fefat.market.instruments import InstrumentKind
from fefat.market.schema import FrozenModel, Timeframe
from fefat.reference.settings import (
    DEFAULT_LATENCY_MS,
    LimitFill,
    Replay,
    RollHandling,
    RunSettings,
    SlippageTicks,
    default_slippage_ticks,
)

FidelityText = Annotated[
    TickFidelity | Timeframe,
    BeforeValidator(parse_fidelity),
    PlainSerializer(str, return_type=str),
]
"""A fidelity as a field written as its text, `trades` or `1m`, and read back from it."""

DEFAULT_FEE_TABLES = {
    InstrumentKind.FUTURES: "retail-default",
    InstrumentKind.PERPETUAL: "binance-default",
    InstrumentKind.SPOT: "binance-default",
}
"""The fee table a run of each kind of instrument names when its config names none."""

DEFAULT_CAPITAL = Decimal(50_000)
"""A run's capital in its instrument's currency, the ledger's starting cash (D-51)."""


class RunConfig(FrozenModel):
    """A backtest's settings: `fidelity`, the finest data it fills on, each trade date on its
    finest level at or coarser than it (D-58), the finest the store holds when left out;
    `latency_ms` from a decision to its orders' activation (F-ACT-01); `slippage_ticks` of market
    and stop orders, by default none on TBBO and one on every other fidelity, the run's fidelity
    setting deciding, whatever level a date falls back to (F-SLP-01); `limit_fill`
    (F-LMT-01, F-LMT-02); `roll_handling` (F-ROL-02, F-ROL-04); `fee_table`, a table of
    `fefat.market.fees`, by default `retail-default` for futures and `binance-default` for crypto;
    `capital`, in the instrument's currency; `replay`, skipping what no order can act on or in
    full, which give the same fills (`02` §4); and `provider`, as `load` takes it."""

    fidelity: FidelityText | None = None
    latency_ms: int = Field(default=DEFAULT_LATENCY_MS, ge=0)
    slippage_ticks: SlippageTicks | None = None
    limit_fill: LimitFill = LimitFill.THROUGH
    roll_handling: RollHandling = RollHandling.TRANSFER
    fee_table: str | None = None
    capital: Decimal = Field(default=DEFAULT_CAPITAL, gt=0)
    replay: Replay = Replay.SKIPPING
    provider: str | None = None

    @field_validator("fee_table")
    @classmethod
    def _a_named_table(cls, name: str | None) -> str | None:
        if name is not None and name not in TABLES:
            raise ValueError(f"Expected a fee table ({', '.join(sorted(TABLES))}), got {name!r}.")
        return name

    def applied(
        self, finest: TickFidelity | Timeframe, kind: InstrumentKind, provider: str
    ) -> "AppliedRunConfig":
        """The config with every setting left out given its default: the finest data the store
        holds, its slippage ticks, the fee table of the instrument's kind, and the provider the
        run reads."""
        fidelity = finest if self.fidelity is None else self.fidelity
        slippage = self.slippage_ticks
        if slippage is None:
            slippage = default_slippage_ticks(fidelity)
        return AppliedRunConfig(
            fidelity=fidelity,
            latency_ms=self.latency_ms,
            slippage_ticks=slippage,
            limit_fill=self.limit_fill,
            roll_handling=self.roll_handling,
            fee_table=DEFAULT_FEE_TABLES[kind] if self.fee_table is None else self.fee_table,
            capital=self.capital,
            replay=self.replay,
            provider=provider,
        )


class AppliedRunConfig(FrozenModel):
    """A run's settings with every default applied (D-51), as its record keeps them: those of
    `RunConfig`, each given."""

    fidelity: FidelityText
    latency_ms: int = Field(ge=0)
    slippage_ticks: SlippageTicks
    limit_fill: LimitFill
    roll_handling: RollHandling
    fee_table: str
    capital: Decimal = Field(gt=0)
    replay: Replay
    provider: str

    def run_settings(self) -> RunSettings:
        """The settings the engines fill under."""
        return RunSettings(
            latency_ms=self.latency_ms,
            slippage_ticks=self.slippage_ticks,
            limit_fill=self.limit_fill,
            roll_handling=self.roll_handling,
        )
