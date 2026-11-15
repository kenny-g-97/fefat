"""The paths the import wizard reads (step 5.12, the plan's Security section): a file or a
Databento batch under an import root, outside FEAT's home and the data folder, every other path
refused with one refusal that names the roots, those the disk would have to be read for among
them, before it is read."""

import os
import sys
from pathlib import Path

import pytest

from fefat.config import UPLOAD_SUFFIXES, FefatPaths, resolve_paths
from fefat_app.import_sources import confined_path
from fefat_app.imports import PathRefusedError, ReadKind

BACKSLASH = "\\"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """An import root beside the test's home, holding an export and a batch folder."""
    folder = tmp_path / "exports"
    (folder / "batch").mkdir(parents=True)
    (folder / "ES 03-26.Last.txt").write_text("20260304 230100;1;1;1;1;1\n", encoding="utf-8")
    (folder / "notes.docx").write_text("not an export", encoding="utf-8")
    return folder


@pytest.fixture
def paths() -> FefatPaths:
    return resolve_paths(os.environ)


def test_a_file_and_a_batch_under_a_root_are_read_where_they_resolve(
    root: Path, paths: FefatPaths
) -> None:
    export = root / "ES 03-26.Last.txt"

    assert confined_path(str(export), ReadKind.FILE, (root,), paths, UPLOAD_SUFFIXES) == (
        export.resolve()
    )
    assert (
        confined_path(str(root / "batch"), ReadKind.DATABENTO, (root,), paths, UPLOAD_SUFFIXES)
        == (root / "batch").resolve()
    )


@pytest.mark.parametrize(
    "written",
    [
        "relative/ES 03-26.Last.txt",
        "{root}/../exports/ES 03-26.Last.txt",
        "{root}/ES 03-26.Last.txt:stream.txt",
        "{root}/missing.csv",
        "{root}/notes.docx",
        "{root}/batch",
    ],
)
def test_a_path_the_rule_refuses_is_refused_with_the_roots_named(
    written: str, root: Path, paths: FefatPaths
) -> None:
    with pytest.raises(PathRefusedError, match="under one of the import roots") as refused:
        confined_path(written.format(root=root), ReadKind.FILE, (root,), paths, UPLOAD_SUFFIXES)

    assert str(root) in str(refused.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' network, device, and drive paths")
@pytest.mark.parametrize(
    "written",
    [
        f"{BACKSLASH * 2}server{BACKSLASH}share{BACKSLASH}x.csv",
        "//server/share/x.csv",
        f"{BACKSLASH * 2}?{BACKSLASH}C:{BACKSLASH}x.csv",
        f"{BACKSLASH * 2}.{BACKSLASH}C:{BACKSLASH}x.csv",
        "C:x.csv",
        f"{BACKSLASH}x.csv",
    ],
)
def test_a_network_device_or_drive_relative_path_is_refused_before_the_disk_is_read(
    written: str, root: Path, paths: FefatPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A network path read would send the trader's Windows credentials to the server it names.
    def no_disk(self: Path, strict: bool = False) -> Path:
        raise AssertionError(f"Expected no read of the disk, got one for {self}.")

    monkeypatch.setattr(Path, "resolve", no_disk)

    with pytest.raises(PathRefusedError, match="under one of the import roots"):
        confined_path(written, ReadKind.FILE, (root,), paths, UPLOAD_SUFFIXES)


def test_a_file_of_feats_own_folders_under_a_root_that_holds_them_is_refused(
    paths: FefatPaths,
) -> None:
    # A root that holds FEAT's home, such as the trader's own folder, still keeps config.toml,
    # the database, and the store out of the wizard's reach.
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text("port = 8765\n", encoding="utf-8")
    holder = paths.home.parent
    toml_too = (*UPLOAD_SUFFIXES, ".toml")

    with pytest.raises(PathRefusedError, match="outside FEAT's own folders"):
        confined_path(str(paths.config_file), ReadKind.FILE, (holder,), paths, toml_too)


def test_a_link_out_of_a_root_is_refused_where_it_resolves(
    root: Path, paths: FefatPaths, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi  # a junction, which Windows makes without the right a link needs

        _winapi.CreateJunction(str(outside), str(link))

    with pytest.raises(PathRefusedError):
        confined_path(str(link / "secret.csv"), ReadKind.FILE, (root,), paths, UPLOAD_SUFFIXES)
