"""The name a file the browser sends is kept under (step 5.12, the plan's Security section): the
file's own name, which names its copy under `raw/user/` too, refused for any character, ending,
stem, length, or suffix that could leave its folder, open a device, or read otherwise on
Windows."""

import pytest

from fefat.config import UPLOAD_SUFFIXES
from fefat_app.imports import UploadRefusedError
from fefat_app.services.uploads import checked_upload_name


@pytest.mark.parametrize(
    "name",
    ["ES 03-26.Last.txt", "CME_MINI_ESH2026, 1.csv", "glbx.ohlcv-1m.csv.gz", "Kurse März.csv"],
)
def test_an_exports_own_name_is_kept(name: str) -> None:
    assert checked_upload_name(name, UPLOAD_SUFFIXES) == name


@pytest.mark.parametrize(
    "name",
    [
        "D:x.csv",
        "a.txt:b.csv",
        "NUL .csv",
        "com1.csv",
        "a\\b.csv",
        "../x.csv",
        "x.csv ",
        "x.csv.",
        "line\nbreak.csv",
        "right‮to-left.csv",
        "a|b.csv",
        "x.exe",
        ".csv",
        "",
        f"{'a' * 117}.csv",
        f"{'é' * 59}.csv",
    ],
)
def test_a_name_that_could_leave_its_folder_or_read_otherwise_is_refused(name: str) -> None:
    with pytest.raises(UploadRefusedError, match="rename the file"):
        checked_upload_name(name, UPLOAD_SUFFIXES)


def test_a_suffix_config_toml_adds_is_kept_and_one_it_leaves_out_is_refused() -> None:
    assert checked_upload_name("bars.dat", (".dat",)) == "bars.dat"
    with pytest.raises(UploadRefusedError):
        checked_upload_name("bars.csv", (".dat",))


@pytest.mark.parametrize("name", ["upload.json", "Upload.JSON"])
def test_the_name_of_an_uploads_own_record_is_refused_whatever_the_suffixes(name: str) -> None:
    # A file named as the record beside it would be written over by it (from the reviews).
    assert checked_upload_name("bars.json", (".json",)) == "bars.json"
    with pytest.raises(UploadRefusedError, match="rename the file"):
        checked_upload_name(name, (".json",))
