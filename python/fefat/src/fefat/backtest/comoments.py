"""How one series of days moved with another (step 5.23, D-123): a run's days with the market's, as
`fefat.backtest.exposure` pairs them, each a change in micro-units. From exact whole-number sums,
divided once, come the correlation; the beta, the covariance over the market's variance; the share
of the run's variance the market explains, the correlation squared; the alpha, the run's days
summed less the beta's share of the market's; and the volatility ratio, the run's standard
deviation over the market's. Fewer than `FEWEST_DAYS` days, a market whose days never differed,
or a run whose days never differed leave a figure none, and `Uncounted` says which, in that
order; a run whose days never differed keeps a beta of nothing and an alpha of its days summed.

    moments = Comoments.of(market_days, run_days)
    moments.days_exposure().correlation, moments.exposure().alpha
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from pydantic import Field

from fefat.market.engine_units import MONEY_SCALE
from fefat.market.schema import FrozenModel

FEWEST_DAYS = 3
"""The fewest days a correlation, a beta, or a volatility is counted over."""


class Uncounted(StrEnum):
    """Why a figure of a market exposure is none."""

    TOO_FEW_DAYS = "too_few_days"
    """Fewer than `FEWEST_DAYS` days."""
    MARKET_NEVER_DIFFERED = "market_never_differed"
    """The market's days were all alike, so it has no variance to measure against."""
    RUN_NEVER_DIFFERED = "run_never_differed"
    """The run's days were all alike, as a run that never trades has them."""


class DaysExposure(FrozenModel):
    """How the run's days moved with the market's over `days` of them: the correlation and the
    beta in lots, each none where `uncounted` says why."""

    days: int = Field(ge=0)
    correlation: float | None
    beta_lots: float | None
    uncounted: Uncounted | None


class Exposure(DaysExposure):
    """How the run's days moved with the market's over all of them, with the share of the run's
    variance the market explains and the alpha in the currency, each none where `uncounted` says
    why."""

    explained_share: float | None
    alpha: float | None


@dataclass(frozen=True)
class Comoments:
    """The market's and the run's days, paired, in micro-units: their count, their sums, and each
    count times the sum of the products of their deviations from their means, the market's with
    itself, the run's with itself, and the two together, exact in whole numbers."""

    days: int
    market_sum: int
    run_sum: int
    market_variation: int
    run_variation: int
    covariation: int

    @classmethod
    def of(cls, market: Sequence[int], run: Sequence[int]) -> "Comoments":
        days, market_sum, run_sum = len(market), sum(market), sum(run)
        products = sum(moved * made for moved, made in zip(market, run, strict=True))
        return cls(
            days=days,
            market_sum=market_sum,
            run_sum=run_sum,
            market_variation=days * sum(moved * moved for moved in market) - market_sum**2,
            run_variation=days * sum(made * made for made in run) - run_sum**2,
            covariation=days * products - market_sum * run_sum,
        )

    def uncounted(self) -> Uncounted | None:
        """Why the correlation is none, or none where it is counted."""
        if self.days < FEWEST_DAYS:
            return Uncounted.TOO_FEW_DAYS
        if self.market_variation == 0:
            return Uncounted.MARKET_NEVER_DIFFERED
        if self.run_variation == 0:
            return Uncounted.RUN_NEVER_DIFFERED
        return None

    def beta(self) -> Fraction | None:
        """The covariance over the market's variance, exactly: none without three days and a
        market whose days differed."""
        if self.uncounted() in (Uncounted.TOO_FEW_DAYS, Uncounted.MARKET_NEVER_DIFFERED):
            return None
        return Fraction(self.covariation, self.market_variation)

    def explained(self) -> Fraction | None:
        """The correlation squared, exactly: none where the correlation is."""
        if self.uncounted() is not None:
            return None
        return Fraction(self.covariation**2, self.market_variation * self.run_variation)

    def correlation(self) -> float | None:
        """The square root of `explained` with the covariance's sign."""
        explained = self.explained()
        if explained is None:
            return None
        return math.copysign(math.sqrt(explained), self.covariation)

    def alpha(self) -> float | None:
        """The run's days summed less what the beta's lots of the market made over them, in the
        currency."""
        beta = self.beta()
        if beta is None:
            return None
        return float((self.run_sum - beta * self.market_sum) / MONEY_SCALE)

    def volatility_lots(self) -> float:
        """The lots whose days have the run's standard deviation, the run's over the market's,
        refused for days whose correlation does not count."""
        why = self.uncounted()
        if why is not None:
            raise ValueError(
                f"Expected days whose correlation counts for a volatility, got {why} over "
                f"{self.days} days."
            )
        return math.sqrt(Fraction(self.run_variation, self.market_variation))

    def days_exposure(self) -> DaysExposure:
        beta = self.beta()
        return DaysExposure(
            days=self.days,
            correlation=self.correlation(),
            beta_lots=None if beta is None else float(beta),
            uncounted=self.uncounted(),
        )

    def exposure(self) -> Exposure:
        explained = self.explained()
        return Exposure(
            **dict(self.days_exposure()),
            explained_share=None if explained is None else float(explained),
            alpha=self.alpha(),
        )
