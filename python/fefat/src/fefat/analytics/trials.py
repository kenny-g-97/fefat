"""The trials counter (step 3.8, `02-engine-and-data.md` §6): how many features and horizons a
feature study has examined, shown beside every result it gives, so that a promising number is read
against how much was tried to find it. It counts a feature and a horizon once the study has
compared the feature with that horizon's forward returns; a correlation of features with each
other compares no return and counts nothing. The more pairs examined, the further a t-statistic
must lie from 0 to keep 5 % significance across them: the line gives the bound Bonferroni's rule
sets, the data-mining rule of the backtest-expert skill, against a normal distribution."""

from dataclasses import dataclass
from statistics import NormalDist

from fefat.market.calendar import counted

SIGNIFICANCE = 0.05
"""The chance of a false discovery across all the pairs examined that the threshold allows."""


@dataclass(frozen=True)
class Trials:
    """The feature-horizon pairs a study had examined when a result was given."""

    pairs: frozenset[tuple[str, int]]

    @property
    def features(self) -> int:
        """The features examined against a horizon."""
        return len({feature for feature, _ in self.pairs})

    @property
    def horizons(self) -> int:
        """The horizons a feature was examined against."""
        return len({horizon for _, horizon in self.pairs})

    def line(self) -> str:
        """The counter as one line of text, with the t-statistic that keeps 5 % significance
        across the pairs examined."""
        if not self.pairs:
            return "Trials so far: none examined."
        bound = NormalDist().inv_cdf(1 - SIGNIFICANCE / (2 * len(self.pairs)))
        return (
            f"Trials so far: {counted(self.features, 'feature')} and "
            f"{counted(self.horizons, 'horizon')} examined, "
            f"{counted(len(self.pairs), 'feature-horizon pair')}; a t-statistic beyond "
            f"{bound:.2f} either way keeps 5 % significance across them."
        )
