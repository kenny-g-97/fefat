"""Saved feature versions (step 3.1, D-71, D-11): `save` writes a feature's version record, which
never changes, to `<FEFAT_HOME>/workspaces/default/features/<name>/v<n>.json`, `n` counting from
1 per name, and returns the version a saved record of the same hash already has rather than
writing another; `load` reads a version back and refuses a record whose content no longer gives
its hash. The database of step 4.1 imports these files (`01-architecture.md` §4 and §5).

    version = ff.features.save(rsi)
    ff.features.load("rsi", version.version)

One writer at a time: two processes saving different code under one name at once could take the
same number, which the database of step 4.1 settles (`BACKLOG.md`). A Pydantic release that
writes the JSON schema of the same parameters otherwise gives unchanged code a new version; a
version saved before still loads, since its hash is worked out again from the schema it keeps."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from fefat.config import resolve_paths
from fefat.features.definition import FeatureDef, content_hash
from fefat.features.inputs import DeclaredInput, OutputKind
from fefat.market.schema import FrozenModel
from fefat.market.store_files import json_writer, parsed_json, write_atomically

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
        warmup=definition.warmup if isinstance(definition.warmup, int) else definition.warmup_text,
        created_at=datetime.now(UTC),
    )
    write_atomically(folder / f"v{record.version}.json", json_writer(record))
    return record


def load(name: str, version: int) -> FeatureVersion:
    """The saved version `version` of the feature `name`, refused when its file holds another
    feature or version, or when its content no longer gives its hash."""
    path = _folder(name) / f"v{version}.json"
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
    return record


def _folder(name: str) -> Path:
    """The folder of the feature `name`'s versions in the workspace."""
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
