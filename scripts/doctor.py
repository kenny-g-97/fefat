"""Report the tools FEFAT needs on this machine, each as OK, OLD, or MISSING.

Run it through uv (bare `python` is a Microsoft Store stub on this PC):

    uv run --no-project python scripts/doctor.py
    just doctor

Exits 1 when a required tool is missing, unreadable, or older than the minimum
from docs/masterplan/07-tools-and-costs.md section 1. Standard library only,
Python 3.12 or newer, PowerShell and Git Bash alike.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

COMMAND_TIMEOUT_SECONDS = 60
# rustup applies engine/rust-toolchain.toml only inside engine/, so Rust answers from there.
ENGINE = Path(__file__).resolve().parents[1] / "engine"
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
MSVC_WORKLOAD_COMPONENT = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
MSVC_LINKER_GLOB = r"VC\Tools\MSVC\**\bin\Hostx64\x64\link.exe"


class Status(Enum):
    OK = "OK"
    OLD = "OLD"
    MISSING = "MISSING"


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, text: str) -> Version | None:
        match = VERSION_PATTERN.search(text)
        if match is None:
            return None
        major, minor, patch = match.groups()
        return cls(int(major), int(minor), int(patch or 0))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Installation:
    path: Path
    version: Version | None


@dataclass(frozen=True)
class Requirement:
    name: str
    minimum: Version
    locate: Callable[[], Installation | None]
    how_to_install: str


@dataclass(frozen=True)
class Finding:
    requirement: Requirement
    status: Status
    installation: Installation | None

    @property
    def found(self) -> str:
        if self.installation is None:
            return "-"
        if self.installation.version is None:
            return "unreadable"
        return str(self.installation.version)

    @property
    def location_or_fix(self) -> str:
        if self.installation is None:
            return self.requirement.how_to_install
        return abbreviate_home(self.installation.path)


def run_command(arguments: list[str], directory: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            arguments,
            cwd=directory,
            # A check never installs: rustup would otherwise fetch a missing pinned toolchain.
            env={**os.environ, "RUSTUP_AUTO_INSTALL": "0"},
            capture_output=True,
            text=True,
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def command_on_path(
    executable: str, directory: Path | None = None
) -> Callable[[], Installation | None]:
    def locate() -> Installation | None:
        found = shutil.which(executable)
        if found is None:
            return None
        output = run_command([found, "--version"], directory)
        version = None if output is None else Version.parse(first_line(output))
        return Installation(Path(found), version)

    return locate


def cargo_subcommand(name: str) -> Callable[[], Installation | None]:
    """`cargo-<name>` on the PATH, its version asked through cargo from engine/, since
    `cargo-mutants --version` alone is refused."""

    def locate() -> Installation | None:
        found = shutil.which(f"cargo-{name}")
        if found is None:
            return None
        output = run_command(["cargo", name, "--version"], ENGINE)
        version = None if output is None else Version.parse(first_line(output))
        return Installation(Path(found), version)

    return locate


def uv_managed_python(requested: str) -> Installation | None:
    uv = shutil.which("uv")
    if uv is None:
        return None
    interpreter = run_command([uv, "python", "find", requested])
    if not interpreter:
        return None
    output = run_command([first_line(interpreter), "--version"])
    version = None if output is None else Version.parse(first_line(output))
    return Installation(Path(first_line(interpreter)), version)


def msvc_linker() -> Installation | None:
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86 is None:
        return None
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    output = run_command(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            MSVC_WORKLOAD_COMPONENT,
            "-find",
            MSVC_LINKER_GLOB,
            "-format",
            "value",
        ]
    )
    if not output:
        return None
    linkers = [Path(line.strip()) for line in output.splitlines() if line.strip()]
    newest = max(linkers, key=msvc_toolset_version)
    return Installation(newest, msvc_toolset_version(newest))


def msvc_toolset_version(linker: Path) -> Version:
    toolset_folder = linker.parents[3].name
    parsed = Version.parse(toolset_folder)
    if parsed is None:
        raise ValueError(
            f"Expected an MSVC toolset folder like 14.44.35207 in {linker}. Got {toolset_folder!r}."
        )
    return parsed


def c_compiler() -> Installation | None:
    found = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if found is None:
        return None
    output = run_command([found, "--version"])
    version = None if output is None else Version.parse(first_line(output))
    return Installation(Path(found), version)


def native_linker_requirement() -> Requirement:
    if platform.system() == "Windows":
        return Requirement(
            "MSVC linker",
            Version(14, 30),
            msvc_linker,
            "Visual Studio Installer > Build Tools 2022 > tick 'Desktop development with C++'",
        )
    return Requirement(
        "C compiler", Version(0, 0), c_compiler, "install build-essential (Debian) or Xcode tools"
    )


def requirements() -> list[Requirement]:
    return [
        Requirement("git", Version(2, 40), command_on_path("git"), "winget install Git.Git"),
        Requirement(
            "gh",
            Version(2, 40),
            command_on_path("gh"),
            "winget install GitHub.cli, then gh auth login",
        ),
        Requirement(
            "node", Version(24, 0), command_on_path("node"), "winget install OpenJS.NodeJS"
        ),
        Requirement(
            "pnpm",
            Version(10, 0),
            command_on_path("pnpm"),
            'corepack enable --install-directory "$env:APPDATA\\npm" then corepack install -g pnpm@latest',
        ),
        Requirement("uv", Version(0, 9), command_on_path("uv"), "winget install astral-sh.uv"),
        Requirement(
            "python 3.12 (uv)",
            Version(3, 12),
            lambda: uv_managed_python("3.12"),
            "uv python install 3.12",
        ),
        Requirement(
            "rustc",
            Version(1, 85),
            command_on_path("rustc", ENGINE),
            "winget install Rustlang.Rustup, then `rustup toolchain install` in engine/ (the pin)",
        ),
        Requirement("cargo", Version(1, 85), command_on_path("cargo", ENGINE), "comes with rustup"),
        Requirement(
            "cargo-mutants",
            Version(27, 1),
            cargo_subcommand("mutants"),
            "cargo install cargo-mutants --locked (mutation testing at the phase exits)",
        ),
        Requirement("just", Version(1, 38), command_on_path("just"), "winget install Casey.Just"),
        native_linker_requirement(),
    ]


def examine(requirement: Requirement) -> Finding:
    installation = requirement.locate()
    if installation is None:
        return Finding(requirement, Status.MISSING, None)
    if installation.version is None:
        return Finding(requirement, Status.MISSING, installation)
    if installation.version < requirement.minimum:
        return Finding(requirement, Status.OLD, installation)
    return Finding(requirement, Status.OK, installation)


def abbreviate_home(path: Path) -> str:
    try:
        return "~" + os.sep + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def render_table(findings: list[Finding]) -> str:
    header = ("Tool", "Status", "Found", "Minimum", "Where / how to install")
    rows = [
        (
            finding.requirement.name,
            finding.status.value,
            finding.found,
            f">= {finding.requirement.minimum}",
            finding.location_or_fix,
        )
        for finding in findings
    ]
    widths = [max(len(row[column]) for row in [header, *rows]) for column in range(len(header) - 1)]
    lines = [
        format_row(header, widths),
        format_row((*("-" * width for width in widths), "-" * 22), widths),
    ]
    lines.extend(format_row(row, widths) for row in rows)
    return "\n".join(lines)


def format_row(cells: tuple[str, ...], widths: list[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths, strict=False)]
    return "  ".join([*padded, cells[-1]]).rstrip()


def summary(findings: list[Finding]) -> str:
    problems = [finding for finding in findings if finding.status is not Status.OK]
    if not problems:
        return f"All {len(findings)} tools OK on {platform.system()} ({platform.machine()})."
    names = ", ".join(
        f"{finding.requirement.name} ({finding.status.value})" for finding in problems
    )
    return f"{len(problems)} of {len(findings)} tools need attention: {names}."


def main() -> int:
    findings = [examine(requirement) for requirement in requirements()]
    print(
        f"FEFAT doctor - Python {platform.python_version()} at {abbreviate_home(Path(sys.executable))}"
    )
    print()
    print(render_table(findings))
    print()
    print(summary(findings))
    return 0 if all(finding.status is Status.OK for finding in findings) else 1


if __name__ == "__main__":
    sys.exit(main())
