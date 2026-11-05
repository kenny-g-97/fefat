"""Feature analytics (step 3.8, `02-engine-and-data.md` §6): how well a feature foretells the
returns after it, judged before any strategy exists, with the trials counter beside every result
(`fefat.analytics.study` has the example). Its labels, the forward returns, read the future and
never feed a strategy (`fefat.analytics.labels`).

`fefat.strategy` imports these labels, so nothing in this package imports `fefat.strategy` or
`fefat.backtest`.
"""

from fefat.analytics.events import EventStudy
from fefat.analytics.labels import Label
from fefat.analytics.quantiles import QuantileReturns
from fefat.analytics.rank_correlation import Correlations, InformationCoefficient
from fefat.analytics.study import FeatureStudy
from fefat.analytics.trials import Trials
from fefat.reference.orders import PositionSide

__all__ = [
    "Correlations",
    "EventStudy",
    "FeatureStudy",
    "InformationCoefficient",
    "Label",
    "PositionSide",
    "QuantileReturns",
    "Trials",
]
