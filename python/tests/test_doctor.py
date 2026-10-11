import subprocess
from pathlib import Path

import pytest

import doctor


def test_rustc_and_cargo_answer_from_engine_where_the_pin_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders: list[Path | None] = []

    def recorded_run(arguments: list[str], directory: Path | None = None) -> str:
        folders.append(directory)
        return f"{Path(arguments[0]).stem} 1.99.0 (b940084d7 2026-09-28)"

    monkeypatch.setattr(doctor, "run_command", recorded_run)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"C:/rust/bin/{name}.exe")
    rust = [r for r in doctor.requirements() if r.name in {"rustc", "cargo"}]

    found = [requirement.locate() for requirement in rust]

    assert folders == [doctor.ENGINE, doctor.ENGINE]
    assert all(installation is not None for installation in found)


def test_a_check_never_lets_rustup_install_a_toolchain(monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, object] = {}

    def recorded_subprocess(
        arguments: list[str], **given: object
    ) -> subprocess.CompletedProcess[str]:
        options.update(given)
        return subprocess.CompletedProcess(arguments, 0, stdout="rustc 1.99.0", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", recorded_subprocess)

    assert doctor.run_command(["rustc", "--version"], doctor.ENGINE) == "rustc 1.99.0"
    environment = options["env"]
    assert isinstance(environment, dict)
    assert environment["RUSTUP_AUTO_INSTALL"] == "0"
