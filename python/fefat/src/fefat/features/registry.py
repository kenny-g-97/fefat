"""The features this process defined, by content hash (step 3.7, D-71): `@feature` keeps each
`FeatureDef` it makes, so that the runtime reads a feature another reads without a slot of its
own (`fefat.features.dependencies`), and `ff.features.ref` finds a saved version's definition
without running its code again (`fefat.features.versions`). Two definitions of one hash have one
normalised source, so the last kept differs from the one before only in the description of a
combination (`fefat.features.combine`), which the hash leaves out; a table of immutable values by
their identity, as `linecache` keeps sources by file."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fefat.features.definition import FeatureDef

_DEFINED: dict[str, "FeatureDef"] = {}


def register(definition: "FeatureDef") -> None:
    """Keep `definition` as the one of its content hash."""
    _DEFINED[definition.hash] = definition


def registered(content_hash: str) -> "FeatureDef | None":
    """The definition of `content_hash` this process kept last, or None."""
    return _DEFINED.get(content_hash)
