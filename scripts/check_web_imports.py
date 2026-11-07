"""Hold the web app's import boundary (`docs/masterplan/08-code-design.md` section 1.5, D-83).

A file under `web/src/areas/<area>/` imports its own area's files, `ui/`, `api/`, `charts/`, and
`app/`, never another area; and a file under `ui/`, `api/`, or `charts/` imports none of the
areas or `app/`, which would let one area reach another through them. Each import is resolved,
through the `@/` alias or a relative path, so that `../runs/RunsPage` counts as the area
`runs`. The app and the entry files may import anything; packages are not checked.

    uv run --no-project python scripts/check_web_imports.py
    just check

Exits 1 with a line per import that crosses the boundary. Standard library only. oxlint has no
`import/no-restricted-paths`, and its `no-restricted-imports` patterns cannot resolve a relative
path (D-83).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE = Path(__file__).resolve().parents[1] / "web" / "src"
ALIAS = "@/"
SHARED = frozenset({"ui", "api", "charts"})
FOLDERS = SHARED | {"app", "areas"}
GENERATED = frozenset({"routeTree.gen.ts"})
STATIC_IMPORT = re.compile(
    r"^[ \t]*(?:import|export)\b[^;'\"]*?\bfrom[ \t]*[\"']([^\"']+)[\"']", re.MULTILINE
)
SIDE_EFFECT_IMPORT = re.compile(r"^[ \t]*import[ \t]*[\"']([^\"']+)[\"']", re.MULTILINE)
DYNAMIC_IMPORT = re.compile(r"\bimport\([ \t]*[\"']([^\"']+)[\"'][ \t]*\)")


@dataclass(frozen=True)
class Crossing:
    """An import across the boundary: the importing file, relative to the source folder, the
    line its statement starts on, and why it is refused."""

    path: PurePosixPath
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


def part_of(path: PurePosixPath) -> str:
    """The part of the app a path under the source folder belongs to, a file or a folder's
    index (`@/api`, `@/areas/lab`): `areas/<area>`, `app`, `ui`, `api`, `charts`, or `the entry
    files` for those beside the folders."""
    first, *rest = path.parts
    if first == "areas" and rest:
        return f"areas/{rest[0]}"
    return first if first in FOLDERS else "the entry files"


def resolved(specifier: str, importer: PurePosixPath) -> PurePosixPath | None:
    """Where `specifier`, imported by `importer`, lies under the source folder; None for a
    package or a path that leaves the folder."""
    if specifier.startswith(ALIAS):
        return PurePosixPath(specifier.removeprefix(ALIAS))
    if not specifier.startswith("."):
        return None
    parts = list(importer.parent.parts)
    for part in PurePosixPath(specifier).parts:
        if part != "..":
            parts.append(part)
        elif parts:
            parts.pop()
        else:
            return None
    return PurePosixPath(*parts) if parts else None


def refusal(importer: str, target: str, specifier: str) -> str | None:
    """Why a file of the part `importer` may not import `specifier` of the part `target`, or
    None where it may."""
    got = f"got {specifier!r}, which is in {target}."
    if importer.startswith("areas/"):
        if target == importer or target in SHARED | {"app"}:
            return None
        area = importer.removeprefix("areas/")
        return f"Expected an import of {area}'s own files, ui/, api/, charts/, or app/, {got}"
    if importer in SHARED and target not in SHARED:
        return f"Expected an import of ui/, api/, or charts/, {got}"
    return None


def imports_in(text: str) -> Iterator[tuple[int, str]]:
    """Each import's offset in `text` and its specifier, in the order they appear."""
    found = [
        (match.start(), match.group(1))
        for pattern in (STATIC_IMPORT, SIDE_EFFECT_IMPORT, DYNAMIC_IMPORT)
        for match in pattern.finditer(text)
    ]
    yield from sorted(found)


def source_files(source: Path) -> Iterator[Path]:
    """The TypeScript files under `source`, but declarations and generated files."""
    for file in sorted(source.rglob("*.ts*")):
        declaration = file.name.endswith(".d.ts")
        if file.suffix in {".ts", ".tsx"} and not declaration and file.name not in GENERATED:
            yield file


def crossings_in(source: Path) -> list[Crossing]:
    """Every import under `source` that crosses the boundary (module docstring)."""
    found: list[Crossing] = []
    for file in source_files(source):
        importer = PurePosixPath(file.relative_to(source).as_posix())
        text = file.read_text(encoding="utf-8")
        for offset, specifier in imports_in(text):
            target = resolved(specifier, importer)
            if target is None:
                continue
            reason = refusal(part_of(importer), part_of(target), specifier)
            if reason is not None:
                found.append(Crossing(importer, text.count("\n", 0, offset) + 1, reason))
    return found


def main() -> int:
    if not SOURCE.is_dir():
        print(f"Expected the web app's sources at {SOURCE}, got no folder.", file=sys.stderr)
        return 1
    found = crossings_in(SOURCE)
    for crossing in found:
        print(f"web/src/{crossing}")
    if found:
        print(f"{len(found)} imports cross the web app's boundary.", file=sys.stderr)
        return 1
    print("Web imports: every area imports only its own files, ui/, api/, charts/, and app/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
