"""The columns that read the future, which no feature and no strategy may read (step 3.8,
`02-engine-and-data.md` §6, D-12): the forward returns of `fefat.analytics`, `forward_return_<h>`,
and their entries, `next_open`. The feature runtime refuses bars that hold one wherever a feature
is evaluated (`fefat.features.evaluation`), and `SignalStrategy` wherever it reads bars or names
a column; the names live here, apart from the analytics, so that both read them without
importing `fefat.analytics`, which imports the runtime."""

from collections.abc import Iterable

LABEL_PREFIX = "forward_return_"
"""The names of the labels' columns: `forward_return_<h>` for a horizon of h bars."""
NEXT_OPEN = "next_open"
"""The column of each bar's entry: the open of the first bucket with volume after it."""
LABEL_REFUSED = (
    "Expected features and the bars' columns, got {what}: a label reads the future, so it never "
    "feeds a feature or a strategy (02-engine-and-data.md §6)."
)
"""The refusal of a label, with what was found where."""


def is_label_column(name: str) -> bool:
    """Whether `name` is the column of a label, `forward_return_<h>`."""
    return name.startswith(LABEL_PREFIX)


def reads_ahead(name: str) -> bool:
    """Whether `name` is a column the labels add, each of which reads the future: a label's, or
    the entries', `next_open`."""
    return name == NEXT_OPEN or is_label_column(name)


def refuse_label_columns(columns: Iterable[str], where: str) -> None:
    """Refuse `columns`, those of `where`, such as "the bars of feature rsi", where one is a
    column the labels add."""
    ahead = [column for column in columns if reads_ahead(column)]
    if ahead:
        raise ValueError(LABEL_REFUSED.format(what=f"the label column {ahead[0]} in {where}"))
