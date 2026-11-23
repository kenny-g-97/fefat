"""The paths the import wizard reads (step 5.12, D-93): a file, or a Databento batch folder or DBN
file, under one of the import roots of `config.toml`, which the trader writes by hand, so that the
app never widens what it may read, and never inside FEAT's home or the data folder, whose files
the app writes itself. A path is checked as it is written before the disk is touched: absolute,
on a drive rather than a network share or a device, without `..` or a stream's `:`, and under a
root; then resolved, links and all, and checked again against the roots resolved. Every refusal
is the same one, naming the roots, so that it tells nothing of the disk outside them.

shortcut: a path is checked when it is asked, not again when the import's job reads it, so that
a link changed in between is followed; the executor's own check once the roots guard more than
mistakes (`BACKLOG.md`, step 5.12): a logged-in client can run Python in the executor already."""

from collections.abc import Sequence
from pathlib import Path

from fefat.config import FefatPaths
from fefat.market.importers.databento_batch import DBN_SUFFIXES
from fefat_app.imports import PathRefusedError, ReadKind

_NETWORK_OR_DEVICE = "\\\\"
"""How the drive of a network share, `\\\\server\\share`, or of a device path, `\\\\?\\C:`,
starts on Windows."""


def confined_path(
    text: str, kind: ReadKind, roots: Sequence[Path], paths: FefatPaths, suffixes: Sequence[str]
) -> Path:
    """`text` resolved as the path of a file to read, of one of `suffixes`, or for a Databento
    import of a batch folder or DBN file, under one of `roots` and outside the folders of
    `paths`; `PathRefusedError` otherwise (module docstring)."""
    written = Path(text)
    if not _written_under_a_root(written, roots):
        raise _refused(text, roots, suffixes)
    try:
        resolved = written.resolve(strict=True)
    except (OSError, RuntimeError) as missing:
        raise _refused(text, roots, suffixes) from missing
    if not _readable(resolved, kind, roots, paths, suffixes):
        raise _refused(text, roots, suffixes)
    return resolved


def _written_under_a_root(path: Path, roots: Sequence[Path]) -> bool:
    if not path.is_absolute() or path.drive.startswith(_NETWORK_OR_DEVICE):
        return False
    if any(part == ".." or ":" in part for part in path.parts[1:]):
        return False
    return any(path.is_relative_to(root) or path.is_relative_to(root.resolve()) for root in roots)


def _readable(
    path: Path, kind: ReadKind, roots: Sequence[Path], paths: FefatPaths, suffixes: Sequence[str]
) -> bool:
    """Whether the resolved `path` lies under a resolved root, outside FEAT's home and the data
    folder, and is a file or a batch the importers read."""
    inside_the_app = any(
        path.is_relative_to(folder.resolve()) for folder in (paths.home, paths.data_dir)
    )
    if inside_the_app or not any(path.is_relative_to(root.resolve()) for root in roots):
        return False
    if kind is ReadKind.DATABENTO:
        return path.is_dir() or (path.is_file() and ends_in(path.name, DBN_SUFFIXES))
    return path.is_file() and ends_in(path.name, suffixes)


def ends_in(name: str, suffixes: Sequence[str]) -> bool:
    """Whether the file's `name` ends in one of `suffixes`, capitals ignored, after a stem."""
    lowered = name.lower()
    return any(lowered.endswith(suffix) and len(lowered) > len(suffix) for suffix in suffixes)


def _refused(text: str, roots: Sequence[Path], suffixes: Sequence[str]) -> PathRefusedError:
    named = ", ".join(str(root) for root in roots) or "none yet"
    return PathRefusedError(
        f"Expected a file ending in {', '.join(suffixes)}, or a Databento batch folder or DBN "
        f"file, under one of the import roots of config.toml ({named}) and outside FEAT's own "
        f"folders, got {text!r}: add the folder that holds it to import_roots, or choose the "
        "file instead."
    )
