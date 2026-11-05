"""Saved feature versions (step 3.1, D-71, D-11): `save` writes a feature's version record, which
never changes, to `<FEFAT_HOME>/workspaces/default/features/<name>/v<n>.json`, `n` counting from
1 per name, and returns the version a saved record of the same hash already has rather than
writing another; `load` reads a version back and refuses a record whose content no longer gives
its hash, or whose declarations are not those its code writes. The database of step 4.1 imports
these files (`01-architecture.md` §4 and §5).

    version = ff.features.save(rsi)
    ff.features.load("rsi", version.version)
    ff.features.ref("rsi", version=version.version, n=14)  # the feature with its parameters
    ff.features.library()  # a row for each saved version

A version's file is only ever created, whole: written beside its place, flushed, and linked in, so
a second process saving under the same number at the same moment is refused, to save again,
rather than replacing the first, and a crash never leaves half a record. A Pydantic release that
writes the JSON schema of the same parameters otherwise gives unchanged code a new version; a
version saved before still loads, since its hash is worked out again from the schema it keeps.
The leak detector keeps each hash's latest validation beside the versions, in `validations/`.

From step 3.7, `save` saves first the features a feature reads that this process defined, so
that the library holds what each version reads, and keeps a combination's description; and
`ref` reads a saved version by its name and number as a feature with its parameters, which a
strategy pins in its runs: the definition this process defined of its hash, or else the one its
code and the features it reads build again (`ff.features.from_source`), refused where its code
no longer gives its hash, as a Pydantic release would make it, or calls a helper its version does
not keep. `library` lists the saved versions."""

import dataclasses
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import Field

from fefat.config import resolve_paths
from fefat.features.combinations import Combination
from fefat.features.declarations import inputs_as_written, written_declarations
from fefat.features.definition import FeatureDef, content_hash
from fefat.features.evaluation import FeatureSpec
from fefat.features.inputs import DeclaredInput, FeatureInput, OutputKind
from fefat.features.registry import register, registered
from fefat.features.source_code import from_source
from fefat.market.schema import FrozenModel
from fefat.market.store_files import create_atomically, json_writer, parsed_json

_VERSION_FILE = re.compile(r"v([1-9][0-9]*)\.json")
_CONTENT_HASH = re.compile(r"[0-9a-f]{64}")
LIBRARY_COLUMNS = pl.Schema(
    {
        "name": pl.String,
        "version": pl.Int64,
        "hash": pl.String,
        "created_at": pl.Datetime("us", "UTC"),
        "combined": pl.Boolean,
    }
)
"""A row of `library`: a saved version's name, number, content hash, when it was saved, and
whether it is a combination (`fefat.features.combine`)."""


class FeatureVersion(FrozenModel):
    """A saved version of a feature, as its file keeps it: its name and number, its content
    hash, its normalised source, its parameter schema, the inputs it declares beside the bars,
    its outputs with their kinds, its warm-ups in bars and in sessions, each a number or the
    lambda its decorator writes, none in sessions in a version saved before step 3.6, when it
    was saved, and, from step 3.7, a combination's description, from which its code was
    generated (`fefat.features.combine`)."""

    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    hash: str
    code: str
    parameter_schema: dict[str, Any]
    inputs: tuple[DeclaredInput, ...]
    outputs: dict[str, OutputKind]
    warmup: int | str
    warmup_sessions: int | str = 0
    created_at: datetime
    combination: Combination | None = None

    def content_hash(self) -> str:
        """The hash its code, the features it reads, and its parameter schema give."""
        return content_hash(self.code, self.inputs, self.parameter_schema)


def save(definition: FeatureDef) -> FeatureVersion:
    """Save `definition` as the next version of its name, or return the saved version whose
    hash it has, writing nothing; the features it reads that this process defined first."""
    for declared in definition.inputs:
        read = registered(declared.hash) if isinstance(declared, FeatureInput) else None
        if read is not None:
            save(read)
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
        warmup_sessions=definition.written_warmup_sessions,
        created_at=datetime.now(UTC),
        combination=definition.combination,
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


def ref(name: str, *, version: int, **parameters: object) -> FeatureSpec:
    """Version `version` of the saved feature `name` with `parameters`, its defaults filling
    those left out (module docstring)."""
    return definition_of(load(name, version))(**parameters)


def definition_of(record: FeatureVersion) -> FeatureDef:
    """The definition of the saved version `record`: this process's of its hash, or else the one
    its code and the features it reads build again, kept as this process's (module docstring);
    those its decorator names by name are given to its code, and those it writes as inputs, as a
    combination does, are found by the runtime among this process's."""
    defined = registered(record.hash)
    if defined is not None:
        return defined
    written = written_declarations(record.name, record.code).input_names
    named = {}
    for declared, name in zip(record.inputs, written, strict=True):
        if not isinstance(declared, FeatureInput):
            continue
        read = saved_definition(declared.name, declared.hash, record.name)
        if name is not None:
            named[name] = read
    built = from_source(record.code, named)
    _require_its_hash(record, built)
    described = dataclasses.replace(built, combination=record.combination)
    register(described)
    return described


def _require_its_hash(record: FeatureVersion, built: FeatureDef) -> None:
    """Refuse a definition built again from `record`'s code that gives another hash: one whose
    code names a feature of the SDK, such as `ff.indicators.atr`, that is now another version,
    or whose parameters' schema a release of the libraries writes otherwise."""
    if built.hash == record.hash:
        return
    begun = f"Expected the code of version {record.version} of feature {record.name}"
    changed = [
        declared.name
        for declared, read in zip(record.inputs, built.inputs, strict=True)
        if isinstance(declared, FeatureInput) and declared != read
    ]
    if changed:
        raise ValueError(
            f"{begun} to read the features its version read, got another {', '.join(changed)}, "
            "which its code names where no version is pinned: define it again, so that it reads "
            "the features it reads now, and save it as a new version."
        )
    raise ValueError(
        f"{begun} to give its hash {record.hash[:12]} again, got {built.hash[:12]}: its "
        "parameter schema changed with a release of the libraries, so save the feature again as "
        "a new version."
    )


def saved_definition(name: str, content_hash: str, reader: str) -> FeatureDef:
    """The definition of the feature `name` of `content_hash` that `reader` reads: this
    process's, or that of the saved version of that hash (`definition_of`)."""
    defined = registered(content_hash)
    if defined is not None:
        return defined
    for number in _version_numbers(_folder(name)):
        record = load(name, number)
        if record.hash == content_hash:
            return definition_of(record)
    raise ValueError(
        f"Expected the feature {name} {content_hash[:12]} that {reader} reads defined in this "
        "process or saved in the library, got neither: define it, or save it with "
        "ff.features.save."
    )


def library() -> pl.DataFrame:
    """The saved features, a row for each version by name and then number, with the columns of
    `LIBRARY_COLUMNS`; none while nothing is saved."""
    folder = resolve_paths(os.environ).features_dir
    names = (
        sorted(each.name for each in folder.iterdir() if each.is_dir()) if folder.is_dir() else []
    )
    records = [load(name, number) for name in names for number in _version_numbers(folder / name)]
    rows = [
        (each.name, each.version, each.hash, each.created_at, each.combination is not None)
        for each in records
    ]
    return pl.DataFrame(rows, schema=LIBRARY_COLUMNS, orient="row")


def _require_declarations_of_its_code(record: FeatureVersion, path: Path) -> None:
    """Refuse a record whose name, outputs, inputs, or warm-ups are not those its code writes,
    which the hash covers through that text alone."""
    written = written_declarations(record.name, record.code)
    if (
        record.name == written.name
        and record.outputs == written.outputs
        and inputs_as_written(record.inputs, written.inputs)
        and record.warmup == written.warmup
        and record.warmup_sessions == written.warmup_sessions
    ):
        return
    raise ValueError(
        f"Expected the name, outputs, inputs, and warm-ups in {path} as its code writes them, got "
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


def validation_file(name: str, content_hash: str) -> Path:
    """The file beside the feature `name`'s versions where the leak detector keeps the latest
    validation of its content hash, `validations/<hash>.json` (`fefat.features.validation`); a
    hash that is not 64 hexadecimal digits is refused, so that no text reaches outside it."""
    if _CONTENT_HASH.fullmatch(content_hash) is None:
        raise ValueError(
            f"Expected a feature's content hash, 64 hexadecimal digits, got {content_hash!r}."
        )
    return _folder(name) / "validations" / f"{content_hash}.json"


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
