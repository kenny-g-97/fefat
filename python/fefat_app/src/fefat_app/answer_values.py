"""The values of the trader's one SELECT as the API sends them (step 5.8, D-124): each value DuckDB
answered as a JSON value that a browser reads unchanged, a whole number past 2**53 and a decimal
as text, an instant as ISO 8601 in UTC; and every text naming no folder of this PC, the run's
folder named as the run and the trader's home folder as `~`, as a view's definition or a setting
of DuckDB's would carry them (`fefat_app.artifact_queries`)."""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue

FolderNames = tuple[tuple[str, str], ...]
"""Each text that names a folder of this PC, with what an answer shows in its place."""

_EXACT = 2**53
"""The whole numbers a browser's number holds exactly lie within this, either side of zero."""


def folder_names(folder: Path) -> FolderNames:
    """What names the run in `folder`, shown as `run <key12>`, and the trader's home folder,
    shown as `~`, each in its POSIX and its native form; the home is left out where it is the
    root, whose name begins every path."""
    run = f"run {folder.name[:12]}"
    names = [(folder.as_posix(), run), (str(folder), run)]
    home = Path.home()
    if home.parent != home:
        names += [(home.as_posix(), "~"), (str(home), "~")]
    return tuple(names)


def without_folders(text: str, names: FolderNames) -> str:
    """`text` with each of `names` in its stand-in's place (`folder_names`)."""
    for found, shown in names:
        text = text.replace(found, shown)
    return text


def json_value(value: Any, names: FolderNames) -> JsonValue:
    """A value DuckDB answered as a JSON value that a browser reads unchanged, a text naming no
    folder of this PC (`without_folders`)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return without_folders(value, names)
    if isinstance(value, int):
        return value if -_EXACT <= value <= _EXACT else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _instant_text(value)
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, timedelta | UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list | tuple):
        return [json_value(each, names) for each in cast("Sequence[Any]", value)]
    if isinstance(value, dict):
        entries = cast("dict[Any, Any]", value).items()
        return {without_folders(str(key), names): json_value(each, names) for key, each in entries}
    return without_folders(str(value), names)


def _instant_text(value: datetime) -> str:
    """An instant DuckDB answered as ISO 8601 in UTC: a timestamp without a zone, as the views'
    are, read as UTC. shortcut: DuckDB's Python client gives a `TIMESTAMP_NS` at microseconds,
    so an answer's instant drops its last three digits; `epoch_ns(column)` keeps them, until the
    agent needs them whole (Phase 8)."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return f"{value.isoformat()}Z"
