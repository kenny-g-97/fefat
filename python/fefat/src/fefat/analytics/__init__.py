"""Feature analytics (step 3.8, `02-engine-and-data.md` §6): how well a feature foretells the
returns after it, judged before any strategy exists. Its labels, the forward returns, read the
future and never feed a strategy (`fefat.analytics.labels`).

`fefat.strategy` imports these labels, so nothing in this package imports `fefat.strategy` or
`fefat.backtest`.
"""

from fefat.analytics.labels import LABEL_PREFIX, Label, forward_returns, is_label_column

__all__ = ["LABEL_PREFIX", "Label", "forward_returns", "is_label_column"]
