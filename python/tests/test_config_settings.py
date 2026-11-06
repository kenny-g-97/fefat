"""The settings of step 4.1 (`01-architecture.md` sections 4, 6, and 8, D-83): what the server
needs before its database opens, read from `<FEFAT_HOME>/config.toml` into a frozen model."""

import os
import re
from pathlib import Path

import pytest

from fefat.config import Settings, load_settings


def test_without_a_config_file_the_settings_are_the_defaults(tmp_path: Path) -> None:
    # Port 8765 (D-83), the loopback alone (D-54), the logical processors less two (D-85), and
    # no import roots.
    processors = os.cpu_count()

    settings = load_settings(tmp_path / "config.toml")

    assert processors is not None
    assert settings == Settings()
    assert (settings.port, settings.bind_address, settings.import_roots) == (8765, "127.0.0.1", ())
    assert settings.process_pool_size == max(1, processors - 2)
    assert list(tmp_path.iterdir()) == []


def test_a_config_file_round_trips_through_the_settings(tmp_path: Path) -> None:
    exports, downloads = tmp_path / "exports", tmp_path / "downloads"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "port = 9001\n"
        "bind_address = '127.0.0.1'\n"
        "process_pool_size = 3\n"
        f"import_roots = ['{exports.as_posix()}', '{downloads.as_posix()}']\n",
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings == Settings(port=9001, process_pool_size=3, import_roots=(exports, downloads))
    with pytest.raises(ValueError, match="frozen"):
        settings.port = 9002


@pytest.mark.parametrize(
    "content",
    [
        "port = 0\n",
        "port = 65536\n",
        "port = '8765'\n",
        "bind_address = '0.0.0.0'\n",
        "process_pool_size = 0\n",
        "import_roots = ['exports']\n",
        "theme = 'dark'\n",
        "port = \n",
    ],
)
def test_a_config_file_that_breaks_the_settings_is_refused_naming_the_file(
    tmp_path: Path, content: str
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(content, encoding="utf-8")
    expected = f"Expected {config_file} to hold FEFAT's settings, got: "

    with pytest.raises(ValueError, match=re.escape(expected)):
        load_settings(config_file)


def test_a_config_file_saved_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    # Windows PowerShell 5.1's `Set-Content -Encoding utf8` writes one before the text.
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(b"\xef\xbb\xbfport = 9001\n")

    assert load_settings(config_file).port == 9001


def test_a_config_file_in_another_encoding_is_refused_naming_the_file(tmp_path: Path) -> None:
    # Windows PowerShell 5.1's `>` writes UTF-16.
    config_file = tmp_path / "config.toml"
    config_file.write_bytes("port = 9001\n".encode("utf-16"))
    expected = f"Expected {config_file} to hold FEFAT's settings, got: "

    with pytest.raises(ValueError, match=re.escape(expected)):
        load_settings(config_file)


def test_a_relative_import_root_is_named_in_the_refusal(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("import_roots = ['exports']\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected import_roots as absolute paths, got 'exports'"):
        load_settings(config_file)
