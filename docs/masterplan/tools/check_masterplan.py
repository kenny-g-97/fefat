"""Consistency checks for the FEFAT masterplan.

Run from the repository root (or anywhere), through uv (bare `python` is a
Microsoft Store stub on the builder's PC):

    uv run --no-project python docs/masterplan/tools/check_masterplan.py            # check
    uv run --no-project python docs/masterplan/tools/check_masterplan.py --progress  # print PROGRESS.md rows

Checks: step headings parse, IDs are unique and sequential within a phase, every
`Depends on` resolves to an existing step (or "none"), every step has the six
sections in order (optionally followed by "Amendment" sections), every step has
a meta line, PROGRESS.md lists every step, and every decision marked ADR in
DECISIONS.md has its record in docs/adr/, in the log's order, with the five
sections and a link to its successor where it is superseded. Standard library only.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASES = ROOT / "phases"
PROGRESS = ROOT / "PROGRESS.md"
DECISIONS = ROOT / "DECISIONS.md"
ADRS = ROOT.parent / "adr"
ADR_ROW_RE = re.compile(r"^\| (D-\d+) \*\*ADR\*\*([^|]*)\|", re.M)
SUCCESSOR_RE = re.compile(r"superseded by (D-\d+)")
DECISION_LINK_RE = re.compile(r"^Decision log: \[(D-\d+)\]", re.M)
ADR_SECTIONS = ["Context", "Decision", "Consequences", "How we would know it is wrong", "Status"]

STEP_RE = re.compile(r"^### (\d+)\.(\d+) (.+?)\s*$")
META_RE = re.compile(
    r"^Depends on: (.+?) · Plan mode: (required|optional|skip) · Reviews: (.+?) · Security: (yes|no) · Model hint: (default|hard)\s*$"
)
SECTIONS = ["Purpose", "Prerequisites", "Prompt", "Done means", "Your checks", "If it fails"]


@dataclass
class Step:
    phase: int
    num: int
    title: str
    file: Path
    line: int
    depends: list[str] = field(default_factory=list)
    meta_ok: bool = False
    sections: list[str] = field(default_factory=list)
    plan: str = ""
    reviews: str = ""
    security: str = ""
    model: str = ""

    @property
    def id(self) -> str:
        return f"{self.phase}.{self.num}"


def parse_phase(path: Path) -> list[Step]:
    steps: list[Step] = []
    current: Step | None = None
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        m = STEP_RE.match(raw)
        if m:
            current = Step(int(m.group(1)), int(m.group(2)), m.group(3), path, i)
            steps.append(current)
            continue
        if current is None:
            continue
        mm = META_RE.match(raw)
        if mm and not current.meta_ok:
            current.meta_ok = True
            deps = mm.group(1).strip()
            current.depends = [] if deps == "none" else [d.strip() for d in deps.split(",")]
            current.plan, current.reviews, current.security, current.model = (
                mm.group(2),
                mm.group(3),
                mm.group(4),
                mm.group(5),
            )
            continue
        if raw.startswith("#### "):
            current.sections.append(raw[5:].strip())
        if raw.startswith("## ") and not raw.startswith("### "):
            # a top-level section (e.g. "## Phase exit") ends the step list
            current = None
    return steps


def adr_errors(decisions: Path, adrs: Path) -> list[str]:
    """The ways docs/adr/ falls out of step with the decisions DECISIONS.md marks ADR."""
    if not decisions.exists():
        return [f"{decisions.name} not found"]
    marked = ADR_ROW_RE.findall(decisions.read_text(encoding="utf-8"))
    records = sorted(
        path for path in adrs.glob("[0-9][0-9][0-9][0-9]-*.md") if path.name[:4] != "0000"
    )
    errors = []
    if len(records) != len(marked):
        errors.append(
            f"docs/adr: expected {len(marked)} records for the decisions marked ADR, got {len(records)}"
        )
    # Not strict: a missing or extra record is the count error above, and the rest still pair up.
    names = {decision: record.name for (decision, _), record in zip(marked, records, strict=False)}
    for number, (decision, note) in enumerate(marked[: len(records)], start=1):
        name = names[decision]
        text = (adrs / name).read_text(encoding="utf-8")
        link = DECISION_LINK_RE.search(text)
        if not name.startswith(f"{number:04d}-"):
            errors.append(
                f"docs/adr/{name}: expected number {number:04d}, the place of {decision} in the log"
            )
        if link is None or link.group(1) != decision:
            named = link.group(1) if link else "no decision"
            errors.append(
                f"docs/adr/{name}: expected its Decision log line to name {decision}, got {named}"
            )
        sections = re.findall(r"^## (.+?)\s*$", text, re.M)
        if sections != ADR_SECTIONS:
            errors.append(f"docs/adr/{name}: sections {sections} != {ADR_SECTIONS}")
        errors.extend(successor_errors(name, decision, note, text, names))
    return errors


def successor_errors(
    name: str, decision: str, note: str, text: str, names: dict[str, str]
) -> list[str]:
    """A superseded decision's record must link the record of the decision that supersedes it."""
    successor = SUCCESSOR_RE.search(note)
    if successor is None:
        return []
    record = names.get(successor.group(1))
    if record is None:
        return [
            f"docs/adr/{name}: {decision} is superseded by {successor.group(1)}, which has no record"
        ]
    if record not in text:
        return [
            f"docs/adr/{name}: {decision} is superseded by {successor.group(1)}, expected a link to its successor {record}"
        ]
    return []


def main(argv: list[str]) -> int:
    errors: list[str] = []
    steps: list[Step] = []
    for path in sorted(PHASES.glob("P*.md")):
        steps.extend(parse_phase(path))

    ids = {}
    for s in steps:
        if s.id in ids:
            errors.append(
                f"duplicate step id {s.id} in {s.file.name}:{s.line} and {ids[s.id].file.name}:{ids[s.id].line}"
            )
        ids[s.id] = s

    # sequential numbering within each phase
    by_phase: dict[int, list[Step]] = {}
    for s in steps:
        by_phase.setdefault(s.phase, []).append(s)
    for phase, ss in by_phase.items():
        nums = [s.num for s in ss]
        if nums != list(range(1, len(nums) + 1)):
            errors.append(f"phase {phase}: step numbers are not sequential: {nums}")

    for s in steps:
        if not s.meta_ok:
            errors.append(f"{s.id} ({s.file.name}:{s.line}): missing or malformed meta line")
        for d in s.depends:
            if d not in ids:
                errors.append(f"{s.id}: depends on unknown step {d}")
            elif ids[d].phase > s.phase or (ids[d].phase == s.phase and ids[d].num >= s.num):
                errors.append(f"{s.id}: depends on a later or same step {d}")
        required, extra = s.sections[: len(SECTIONS)], s.sections[len(SECTIONS) :]
        if required != SECTIONS or any(not x.startswith("Amendment") for x in extra):
            errors.append(
                f"{s.id} ({s.file.name}:{s.line}): sections {s.sections} != {SECTIONS} (+ optional Amendment)"
            )

    if "--progress" in argv:
        print("| Step | Title | Phase | Status | PR | Date | Notes |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for s in steps:
            print(f"| {s.id} | {s.title} | P{s.phase} | todo | | | |")
        return 0

    if PROGRESS.exists():
        text = PROGRESS.read_text(encoding="utf-8")
        for s in steps:
            if not re.search(rf"^\| {re.escape(s.id)} \|", text, flags=re.M):
                errors.append(f"PROGRESS.md: missing row for step {s.id}")
    else:
        errors.append("PROGRESS.md not found")
    errors.extend(adr_errors(DECISIONS, ADRS))

    print(f"{len(steps)} steps in {len(by_phase)} phases")
    for phase, ss in sorted(by_phase.items()):
        print(f"  P{phase}: {len(ss)} steps")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print("  -", e)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
