"""Saved feature versions (step 3.1, D-71, D-11): `save` writes a feature's version record, which
never changes, to `<FEFAT_HOME>/workspaces/default/features/<name>/v<n>.json`, `n` counting from
1 per name, and returns the version a saved record of the same hash already has rather than
writing another; `load` reads a version back and refuses a record whose content no longer gives
its hash, or whose declarations are not those its code writes. The database of step 4.1 imports
these files (`01-architecture.md` §4 and §5).

    version = ff.features.save(rsi)
    ff.features.load("rsi", version.version)

A version's file is only ever created, whole: written beside its place, flushed, and linked in, so
a second process saving under the same number at the same moment is refused, to save again,
rather than replacing the first, and a crash never leaves half a record. A Pydantic release that
writes the JSON schema of the same parameters otherwise gives unchanged code a new version; a
version saved before still loads, since its hash is worked out again from the schema it keeps.
The leak detector keeps each hash's latest validation beside the versions, in `validations/`."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from fefat.config import resolve_paths
from fefat.features.declarations import inputs_as_written, written_declarations
from fefat.features.definition import FeatureDef, content_hash
from fefat.features.inputs import DeclaredInput, OutputKind
from fefat.market.schema import FrozenModel
from fefat.market.store_files import create_atomically, json_writer, parsed_json

_VERSION_FILE = re.compile(r"v([1-9][0-9]*)\.json")


class FeatureVersion(FrozenModel):
    """A saved version of a feature, as its file keeps it: its name and number, its content
    hash, its normalised source, its parameter schema, the inputs it declares beside the bars,
    its outputs with their kinds, its warm-up in bars or as the lambda its decorator writes, and
    when it was saved."""

    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    hash: str
    code: str
    parameter_schema: dict[str, Any]
    inputs: tuple[DeclaredInput, ...]
    outputs: dict[str, OutputKind]
    warmup: int | str
    created_at: datetime

    def content_hash(self) -> str:
        """The hash its code, the features it reads, and its parameter schema give."""
        return content_hash(self.code, self.inputs, self.parameter_schema)


def save(definition: FeatureDef) -> FeatureVersion:
    """Save `definition` as the next version of its name, or return the saved version whose
    hash it has, writing nothing."""
    folder = _folder(definition.name)
    numbers = _version_numbers(folder)
    for number in numbers:
        saved = load(definition.name, number)
        if saved.hash == definition.hash:
            return saved
    record = FeatureVersion(
        name=definition.name,
        version=max(numbers, default=0) + 1,
        hash=definition.hash,
        code=definition.code,
        parameter_schema=definition.parameter_schema,
        inputs=definition.inputs,
        outputs=dict(definition.outputs),
        warmup=definition.written_warmup,
        created_at=datetime.now(UTC),
    )
    _create(folder / f"v{record.version}.json", record)
    return record


def load(name: str, version: int) -> FeatureVersion:
    """The saved version `version` of the feature `name`, refused when its file holds another
    feature or version, when its content no longer gives its hash, or when its declarations are
    not those its code writes."""
    path = _folder(name) / f"v{version}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected version {version} of feature {name} at {path}, got no such file."
        )
    record = parsed_json(FeatureVersion, path.read_bytes(), str(path))
    if (record.name, record.version) != (name, version):
        raise ValueError(
            f"Expected version {version} of feature {name} in {path}, got version "
            f"{record.version} of feature {record.name}."
        )
    found = record.content_hash()
    if found != record.hash:
        raise ValueError(
            f"Expected the content of {path} to give its hash {record.hash}, got {found}: the "
            "file was changed after it was written."
        )
    _require_declarations_of_its_code(record, path)
    return record


def _require_declarations_of_its_code(record: FeatureVersion, path: Path) -> None:
    """Refuse a record whose name, outputs, inputs, or warm-up are not those its code writes,
    which the hash covers through that text alone."""
    written = written_declarations(record.name, record.code)
    if (
        record.name == written.name
        and record.outputs == written.outputs
        and inputs_as_written(record.inputs, written.inputs)
        and record.warmup == written.warmup
    ):
        return
    raise ValueError(
        f"Expected the name, outputs, inputs, and warm-up in {path} as its code writes them, got "
        "others: the file was changed after it was written."
    )


def _create(path: Path, record: FeatureVersion) -> None:
    """Write `record` whole to a new file at `path` (`create_atomically`): a version another
    process saved there first is refused, never replaced (D-11), and none is ever seen
    half-written, since every later save of the name reads it."""
    try:
        create_atomically(path, json_writer(record))
    except FileExistsError as error:
        raise ValueError(
            f"Expected to save version {record.version} of feature {record.name} as a new file, "
            f"got {path} saved by another process first: save it again."
        ) from error


def validations_folder(name: str) -> Path:
    """The folder beside the feature `name`'s versions where the leak detector keeps the latest
    validation of each content hash, `validations/<hash>.json` (`fefat.features.validation`)."""
    return _folder(name) / "validations"


def _folder(name: str) -> Path:
    """The folder of the feature `name`'s versions in the workspace, refused unless `name` is a
    feature's, a Python identifier, so that no name reaches outside the folder of features."""
    if not name.isidentifier():
        raise ValueError(f"Expected a feature's name, a Python identifier, got {name!r}.")
    return resolve_paths(os.environ).features_dir / name


def _version_numbers(folder: Path) -> list[int]:
    """The numbers of the versions saved in `folder`, in order, v10 after v9."""
    numbers = []
    for path in folder.glob("v*.json"):
        found = _VERSION_FILE.fullmatch(path.name)
        if found is None:
            raise ValueError(
                f"Expected version files named v<n>.json in {folder}, got {path.name}."
            )
        numbers.append(int(found[1]))
    return sorted(numbers)
