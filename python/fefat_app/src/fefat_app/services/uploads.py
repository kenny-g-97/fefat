"""The name a file the browser sends is kept under (step 5.12, D-93): the file's own name, which
names its copy under `raw/user/<sha256>/` once imported, so one rule for both, checked before a
byte of the file is read. No control or format character, none of the characters Windows keeps
out of names, no dot or space at its end, which Windows drops, no stem Windows opens as a device,
at most `UPLOAD_NAME_BYTES` bytes, a suffix of `config.toml`'s `upload_suffixes`, a name the
raw manifest takes, and not the name of the upload's own record, `upload.json`."""

import unicodedata
from collections.abc import Sequence
from pathlib import PurePosixPath

from fefat.market.importers.file_import import USER_RAW_FOLDER
from fefat.market.layout import is_a_device_name
from fefat.market.raw_manifest import checked_raw_path
from fefat_app.import_sources import ends_in
from fefat_app.imports import UPLOAD_RECORD_NAME, UploadRefusedError

UPLOAD_NAME_BYTES = 120
"""The longest name of a file kept for an import, in UTF-8: its folder's path stays well within
Windows' 260 characters."""
_KEPT_OUT = frozenset('<>:"/\\|?*')
"""The characters Windows keeps out of a file's name."""
_SOME_HASH = "0" * 64
"""A SHA-256's place in the raw path a name is checked in."""


def checked_upload_name(name: str, suffixes: Sequence[str]) -> str:
    """`name`, as the name a file is kept under for an import (module docstring);
    `UploadRefusedError` otherwise."""
    if not _keepable(name, suffixes):
        raise UploadRefusedError(
            f"Expected a file name of at most {UPLOAD_NAME_BYTES} bytes ending in "
            f'{", ".join(suffixes)}, without a control character, any of < > : " / \\ | ? *, a '
            f"dot or a space at its end, or a name Windows keeps for a device, got {name!r}: "
            "rename the file, then choose it again."
        )
    return name


def _keepable(name: str, suffixes: Sequence[str]) -> bool:
    if not name or len(name.encode("utf-8")) > UPLOAD_NAME_BYTES:
        return False
    if any(character in _KEPT_OUT or _is_control(character) for character in name):
        return False
    if name.endswith((".", " ")) or is_a_device_name(name):
        return False
    if name.lower() == UPLOAD_RECORD_NAME or not ends_in(name, suffixes):
        return False
    try:
        checked_raw_path(PurePosixPath(USER_RAW_FOLDER, _SOME_HASH, name).as_posix())
    except ValueError:
        return False
    return True


def _is_control(character: str) -> bool:
    """Whether `character` is a control, format, surrogate, private, or unassigned one, which
    Unicode files under `C`, such as a newline or a right-to-left override."""
    return unicodedata.category(character).startswith("C")
