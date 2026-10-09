"""Read one masterplan step and the state around it.

One reader for the masterplan, used by the `step` skill (/step N.M) and by the
SessionStart hook (.claude/hooks/session-brief.mjs). It parses step headings,
meta lines, and sections with the patterns of
docs/masterplan/tools/check_masterplan.py, so the two never drift apart.

Run it through uv (bare `python` is a Microsoft Store stub on this PC):

    uv run --no-project python scripts/masterplan_step.py brief 0.5
    uv run --no-project python scripts/masterplan_step.py status 0.5
    uv run --no-project python scripts/masterplan_step.py next
    uv run --no-project python scripts/masterplan_step.py session --source startup

brief    the step as its phase file states it, the skills to load, the branch
status   its prerequisites as PROGRESS.md records them here and on origin/main,
         the branches that already exist for it, and the working tree
next     the steps still open and the next command to run
session  the short summary the SessionStart hook adds to every session

`brief`, `status`, and `next` also take --json. Exit codes: 0 done, 1 the
masterplan or git could not be read, 2 no such step. Standard library only;
git is the one program it runs, and it never fetches, so run
`git fetch origin` first when origin/main matters. Output is UTF-8.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs" / "masterplan" / "tools"))

import check_masterplan  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNKNOWN_STEP = 2

MAIN_BRANCH = "main"
MAIN_REFERENCE = "origin/main"
PROGRESS_PATH_IN_GIT = "docs/masterplan/PROGRESS.md"
GIT_TIMEOUT_SECONDS = 30

STEP_ID_PATTERN = re.compile(r"(\d+)\.(\d+)")
PHASE_LABEL_PATTERN = re.compile(r"P(\d+)")
STEP_BRANCH_PATTERN = re.compile(r"step/(\d+\.\d+)-.+")
PHASE_BRANCH_PATTERN = re.compile(r"(kickoff|exit)/P(\d+)")
NUMBERED_ITEM_PATTERN = re.compile(r"\d+\.\s+(.*)")
SKILLS_NOTE_PREFIX = "**Skills.**"
KICKOFF_HEADING = "## Kickoff"
EXIT_HEADING = "## Phase exit"

PLAN_REQUIRED = "required"
TODO_STATUS = "todo"
SATISFIED_STATUSES = frozenset({"done", "skipped"})
OPEN_STATUSES = frozenset({"in progress", "pr open"})

SLUG_STOP_WORDS = frozenset(
    {"a", "an", "and", "at", "by", "for", "from", "in", "its", "of", "on", "the", "this", "to"}
    | {"with", "your"}
)
SLUG_WORD_COUNT = 3
SLUG_MAX_LENGTH = 28

SESSION_ITEM_WIDTH = 240
SESSION_CHANGES_SHOWN = 8
PHASE_PROMPT_WIDTH = 400

BACKTEST_PHASES = frozenset({2, 7, 11})
AGENT_PHASE = 8
SKILL_NAMES_PATTERN = re.compile(
    r"backtest-expert|engine-golden|engine-accuracy-reviewer|frontend-design"
    r"|software-design-principles|designing-architecture|claude-api"
)
BACKTEST_PATTERN = re.compile(
    r"engine/|fefat-(?:core|engine|prop|metrics|data)"
    r"|fefat/(?:reference|backtest|prop|research|analytics|indicators)"
    r"|\bbacktests?\b|\bprop\b|\bmetrics\b|\bresults\b",
    re.IGNORECASE,
)
ARCHITECTURE_PATTERN = re.compile(
    r"ports\.py|container\.py|\bseams?\b|\badapters?\b|\bnew (?:crate|package|module)\b"
    r"|\btraits?\b|\bProtocols?\b"
)
WEB_PATTERN = re.compile(r"\bweb/")
GOLDEN_PATTERN = re.compile(r"engine/|fixtures/(?:scenarios|goldens)|\bgoldens?\b", re.IGNORECASE)
ANTHROPIC_PATTERN = re.compile(r"\bAnthropic\b|Messages API|\bClaude API\b")


class MasterplanError(Exception):
    """The masterplan or the repository could not be read as expected."""


class UnknownStepError(MasterplanError):
    """The phase files have no step with the requested ID."""


@dataclass(frozen=True)
class Section:
    heading: str
    body: str


@dataclass(frozen=True)
class MasterplanStep:
    """One step as its phase file states it: heading, meta line, and sections."""

    step_id: str
    phase: int
    number: int
    title: str
    file: Path
    line: int
    depends_on: tuple[str, ...]
    plan_mode: str
    reviews: tuple[str, ...]
    security: str
    model_hint: str
    sections: tuple[Section, ...]

    @property
    def location(self) -> str:
        return f"{self.file.relative_to(ROOT).as_posix()}:{self.line}"

    @property
    def meta_line(self) -> str:
        depends = ", ".join(self.depends_on) if self.depends_on else "none"
        reviews = ", ".join(self.reviews) if self.reviews else "none"
        return (
            f"Depends on: {depends} | Plan mode: {self.plan_mode} | Reviews: {reviews}"
            f" | Security: {self.security} | Model hint: {self.model_hint}"
        )

    def section(self, heading: str) -> str:
        for section in self.sections:
            if section.heading == heading:
                return section.body
        headings = [section.heading for section in self.sections]
        raise MasterplanError(
            f"Expected a '{heading}' section in step {self.step_id} ({self.location}), "
            f"got the sections {headings}."
        )

    @property
    def done_means(self) -> list[str]:
        return numbered_items(self.section("Done means"))


@dataclass(frozen=True)
class ProgressRow:
    step_id: str
    title: str
    phase: int
    status: str
    pull_request: str
    date: str
    notes: str

    def describe(self) -> str:
        details = [detail for detail in (self.pull_request, self.date) if detail]
        return f"{self.status} ({', '.join(details)})" if details else self.status


@dataclass(frozen=True)
class PhaseRow:
    phase: int
    kickoff_pull_request: str
    exit_pull_request: str

    @property
    def kickoff_recorded(self) -> bool:
        return self.kickoff_pull_request != ""

    @property
    def exit_recorded(self) -> bool:
        return self.exit_pull_request != ""


@dataclass(frozen=True)
class Progress:
    """The two status tables of docs/masterplan/PROGRESS.md."""

    steps: dict[str, ProgressRow]
    phases: dict[int, PhaseRow]

    def status_of(self, step_id: str) -> str | None:
        row = self.steps.get(step_id)
        return None if row is None else row.status

    def phase_finished(self, phase: int) -> bool:
        rows = [row for row in self.steps.values() if row.phase == phase]
        return bool(rows) and all(row.status in SATISFIED_STATUSES for row in rows)

    def kickoff_recorded(self, phase: int) -> bool:
        row = self.phases.get(phase)
        return row is not None and row.kickoff_recorded

    def exit_recorded(self, phase: int) -> bool:
        row = self.phases.get(phase)
        return row is not None and row.exit_recorded


@dataclass(frozen=True)
class Prerequisite:
    step_id: str
    status_here: str | None
    status_on_main: str | None
    merge_commit: str | None

    @property
    def met(self) -> bool:
        return self.status_on_main in SATISFIED_STATUSES


@dataclass(frozen=True)
class SkillSuggestion:
    skill: str
    reason: str


@dataclass(frozen=True)
class Divergence:
    ahead: int
    behind: int


@dataclass(frozen=True)
class NextAction:
    command: str
    description: str


def normalized_step_id(text: str) -> str:
    match = STEP_ID_PATTERN.fullmatch(text.strip())
    if match is None:
        raise UnknownStepError(f"Expected a step ID like 0.5 or 2.11, got {text!r}.")
    return f"{int(match.group(1))}.{int(match.group(2))}"


def parsed_steps() -> list[check_masterplan.Step]:
    steps: list[check_masterplan.Step] = []
    for path in sorted(check_masterplan.PHASES.glob("P*.md")):
        steps.extend(check_masterplan.parse_phase(path))
    return steps


def find_step(step_id: str) -> MasterplanStep:
    wanted = normalized_step_id(step_id)
    for parsed in parsed_steps():
        if parsed.id == wanted:
            return read_step(parsed)
    raise UnknownStepError(
        f"Expected a step ID from docs/masterplan/phases/P*.md, got {wanted}: "
        f"no heading '### {wanted} <title>' exists."
    )


def read_step(parsed: check_masterplan.Step) -> MasterplanStep:
    if not parsed.meta_ok:
        raise MasterplanError(
            f"Expected a meta line under step {parsed.id} ({parsed.file.name}:{parsed.line}), "
            "got none; run docs/masterplan/tools/check_masterplan.py."
        )
    lines = parsed.file.read_text(encoding="utf-8").splitlines()
    block = lines[parsed.line : step_block_end(lines, parsed.line)]
    return MasterplanStep(
        step_id=parsed.id,
        phase=parsed.phase,
        number=parsed.num,
        title=parsed.title,
        file=parsed.file,
        line=parsed.line,
        depends_on=tuple(parsed.depends),
        plan_mode=parsed.plan,
        reviews=split_reviews(parsed.reviews),
        security=parsed.security,
        model_hint=parsed.model,
        sections=split_sections(block),
    )


def step_block_end(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index].startswith(("## ", "### ")):
            return index
    return len(lines)


def split_reviews(text: str) -> tuple[str, ...]:
    if text.strip() == "none":
        return ()
    return tuple(review.strip() for review in text.split(",") if review.strip())


def split_sections(block: list[str]) -> tuple[Section, ...]:
    sections: list[Section] = []
    heading: str | None = None
    body: list[str] = []
    for line in block:
        if line.startswith("#### "):
            if heading is not None:
                sections.append(Section(heading, "\n".join(body).strip()))
            heading = line.removeprefix("#### ").strip()
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append(Section(heading, "\n".join(body).strip()))
    return tuple(sections)


def numbered_items(body: str) -> list[str]:
    items: list[str] = []
    for line in body.splitlines():
        match = NUMBERED_ITEM_PATTERN.match(line)
        if match is not None:
            items.append(match.group(1).strip())
        elif line.strip() and items:
            items[-1] = f"{items[-1]} {line.strip()}"
    return items


def phase_file(phase: int) -> Path:
    matches = sorted(check_masterplan.PHASES.glob(f"P{phase:02d}-*.md"))
    if len(matches) != 1:
        names = [match.name for match in matches]
        raise MasterplanError(f"Expected one phase file P{phase:02d}-*.md, got {names}.")
    return matches[0]


def phase_skills_note(phase: int) -> str | None:
    for line in phase_file(phase).read_text(encoding="utf-8").splitlines():
        if line.startswith(SKILLS_NOTE_PREFIX):
            return line.removeprefix(SKILLS_NOTE_PREFIX).strip()
        if line.startswith("## "):
            return None
    return None


def phase_prompt(phase: int, heading: str) -> str | None:
    """The fenced prompt under a heading such as '## Kickoff' in a phase file."""
    lines = phase_file(phase).read_text(encoding="utf-8").splitlines()
    if heading not in lines:
        return None
    fenced: list[str] = []
    inside = False
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("```"):
            if inside:
                return "\n".join(fenced).strip()
            inside = True
        elif inside:
            fenced.append(line)
        elif line.startswith("## "):
            return None
    return None


def table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def parse_progress(text: str) -> Progress:
    steps: dict[str, ProgressRow] = {}
    phases: dict[int, PhaseRow] = {}
    for line in text.splitlines():
        cells = table_cells(line)
        if len(cells) >= 7 and STEP_ID_PATTERN.fullmatch(cells[0]):
            steps[cells[0]] = progress_row(cells)
            continue
        phase_match = PHASE_LABEL_PATTERN.fullmatch(cells[0]) if len(cells) == 6 else None
        if phase_match is not None:
            phase = int(phase_match.group(1))
            phases[phase] = PhaseRow(phase, cells[1], cells[3])
    return Progress(steps, phases)


def progress_row(cells: list[str]) -> ProgressRow:
    phase_match = PHASE_LABEL_PATTERN.fullmatch(cells[2])
    if phase_match is None:
        raise MasterplanError(
            f"Expected a phase like P0 in the PROGRESS.md row of step {cells[0]}, got {cells[2]!r}."
        )
    return ProgressRow(
        step_id=cells[0],
        title=cells[1],
        phase=int(phase_match.group(1)),
        status=cells[3],
        pull_request=cells[4],
        date=cells[5],
        notes=" | ".join(cells[6:]),
    )


def progress_here() -> Progress:
    return parse_progress(check_masterplan.PROGRESS.read_text(encoding="utf-8"))


def git(*arguments: str) -> str | None:
    """The standard output of a git command run in the repository, or None when it fails."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def current_branch() -> str | None:
    output = git("rev-parse", "--abbrev-ref", "HEAD")
    return None if output is None else output.strip()


def progress_on_main() -> Progress | None:
    text = git("show", f"{MAIN_REFERENCE}:{PROGRESS_PATH_IN_GIT}")
    return None if text is None else parse_progress(text)


def merge_commit_on_main(step_id: str) -> str | None:
    output = git(
        "log",
        MAIN_REFERENCE,
        "--fixed-strings",
        f"--grep=(step {step_id})",
        "-n",
        "1",
        "--format=%h %s",
    )
    if output is None or output.strip() == "":
        return None
    return output.strip()


def step_branches(step_id: str) -> list[str]:
    output = git(
        "for-each-ref",
        "--format=%(refname:short)",
        f"refs/heads/step/{step_id}-*",
        f"refs/remotes/origin/step/{step_id}-*",
    )
    if output is None:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def working_tree_changes() -> list[str] | None:
    output = git("status", "--porcelain")
    if output is None:
        return None
    return [line for line in output.splitlines() if line.strip()]


def divergence_from_main() -> Divergence | None:
    output = git("rev-list", "--left-right", "--count", f"{MAIN_REFERENCE}...HEAD")
    if output is None:
        return None
    counts = output.split()
    if len(counts) != 2:
        raise MasterplanError(f"Expected two counts from git rev-list, got {output!r}.")
    return Divergence(ahead=int(counts[1]), behind=int(counts[0]))


def prerequisites(
    step: MasterplanStep, here: Progress, on_main: Progress | None
) -> list[Prerequisite]:
    return [
        Prerequisite(
            step_id=dependency,
            status_here=here.status_of(dependency),
            status_on_main=None if on_main is None else on_main.status_of(dependency),
            merge_commit=merge_commit_on_main(dependency),
        )
        for dependency in step.depends_on
    ]


def suggest_skills(step: MasterplanStep) -> list[SkillSuggestion]:
    """Skills to load for a step, from its phase and what its text names (08-code-design.md)."""
    text = SKILL_NAMES_PATTERN.sub(
        "",
        "\n".join(
            section.body
            for section in step.sections
            if section.heading in {"Purpose", "Prompt", "Done means"}
        ),
    )
    suggestions = [
        SkillSuggestion("software-design-principles", "any code (08-code-design.md section 3)")
    ]
    if step.phase in BACKTEST_PHASES or BACKTEST_PATTERN.search(text):
        suggestions.append(
            SkillSuggestion(
                "backtest-expert", "engine, prop, results, or research work (08 section 4)"
            )
        )
    if step.plan_mode == PLAN_REQUIRED or ARCHITECTURE_PATTERN.search(text):
        suggestions.append(
            SkillSuggestion(
                "designing-architecture",
                "a new module, crate, port, adapter, schema, or public surface (08 section 1)",
            )
        )
    if WEB_PATTERN.search(text) or "ui-verifier" in step.reviews:
        suggestions.append(
            SkillSuggestion(
                "frontend-design:frontend-design",
                "the step touches web/; read web/DESIGN.md first (08 section 5)",
            )
        )
    if GOLDEN_PATTERN.search(text):
        suggestions.append(
            SkillSuggestion("engine-golden", "engine, scenario, or golden files change")
        )
    if step.phase == AGENT_PHASE or ANTHROPIC_PATTERN.search(text):
        suggestions.append(SkillSuggestion("claude-api", "code that calls the Anthropic API"))
    return suggestions


def slug(title: str) -> str:
    words = [
        word
        for word in re.split(r"[^a-z0-9]+", title.lower())
        if word and word not in SLUG_STOP_WORDS
    ]
    if not words:
        raise MasterplanError(f"Expected a step title with at least one word, got {title!r}.")
    return "-".join(words[:SLUG_WORD_COUNT])[:SLUG_MAX_LENGTH].rstrip("-")


def suggested_branch(step: MasterplanStep) -> str:
    return f"step/{step.step_id}-{slug(step.title)}"


def branch_advice(step: MasterplanStep, branches: list[str]) -> str:
    if not branches:
        return f"none yet; create {suggested_branch(step)} from {MAIN_REFERENCE}"
    return f"reuse {', '.join(branches)}"


def next_action(progress: Progress) -> NextAction | None:
    first_todo = next((row for row in progress.steps.values() if row.status == TODO_STATUS), None)
    if first_todo is None:
        return None
    previous_phase = first_todo.phase - 1
    if (
        previous_phase >= 0
        and progress.phase_finished(previous_phase)
        and not progress.exit_recorded(previous_phase)
    ):
        return NextAction(
            f"/phase-exit {previous_phase}",
            f"close Phase {previous_phase} before step {first_todo.step_id}",
        )
    if first_todo.step_id.endswith(".1") and not progress.kickoff_recorded(first_todo.phase):
        return NextAction(
            f"/phase-kickoff {first_todo.phase}",
            f"open Phase {first_todo.phase}, then /step {first_todo.step_id}",
        )
    return NextAction(f"/step {first_todo.step_id}", first_todo.title)


def open_rows(progress: Progress) -> list[ProgressRow]:
    return [row for row in progress.steps.values() if row.status in OPEN_STATUSES]


def indented(text: str, prefix: str = "  ") -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in text.splitlines()]


def shortened(text: str, width: int) -> str:
    return text if len(text) <= width else f"{text[: width - 3].rstrip()}..."


def render_brief(step: MasterplanStep, row: ProgressRow | None, branches: list[str]) -> list[str]:
    lines = [
        f"Step {step.step_id} - {step.title}",
        f"  {step.location}",
        f"  {step.meta_line}",
        f"  PROGRESS.md: {'no row' if row is None else row.describe()}",
        "",
    ]
    for section in step.sections:
        lines.extend([section.heading, *indented(section.body), ""])
    note = phase_skills_note(step.phase)
    if note is not None:
        lines.extend([f"Phase {step.phase} skills note", f"  {note}", ""])
    lines.append(
        "Skills to load (suggested from the step's text; the phase note and judgement decide)"
    )
    lines.extend(
        f"  - {suggestion.skill}: {suggestion.reason}" for suggestion in suggest_skills(step)
    )
    lines.extend(["", f"Branch: {branch_advice(step, branches)}"])
    return lines


def brief_payload(
    step: MasterplanStep, row: ProgressRow | None, branches: list[str]
) -> dict[str, object]:
    return {
        "step_id": step.step_id,
        "title": step.title,
        "phase": step.phase,
        "location": step.location,
        "depends_on": list(step.depends_on),
        "plan_mode": step.plan_mode,
        "reviews": list(step.reviews),
        "security": step.security,
        "model_hint": step.model_hint,
        "progress_status": None if row is None else row.status,
        "sections": {section.heading: section.body for section in step.sections},
        "done_means": step.done_means,
        "phase_skills_note": phase_skills_note(step.phase),
        "skills": [
            {"skill": suggestion.skill, "reason": suggestion.reason}
            for suggestion in suggest_skills(step)
        ],
        "existing_branches": branches,
        "suggested_branch": suggested_branch(step),
    }


def describe_prerequisite(state: Prerequisite) -> str:
    here = "no row" if state.status_here is None else state.status_here
    on_main = "unknown" if state.status_on_main is None else state.status_on_main
    merged = "none" if state.merge_commit is None else state.merge_commit
    verdict = "met" if state.met else "NOT MET"
    return (
        f"  {state.step_id}: here {here}, on {MAIN_REFERENCE} {on_main},"
        f" merged commit: {merged} -> {verdict}"
    )


def render_status(
    step: MasterplanStep,
    states: list[Prerequisite],
    on_main_available: bool,
    branches: list[str],
    changes: list[str] | None,
) -> list[str]:
    depends = ", ".join(step.depends_on) if step.depends_on else "none"
    lines = [f"Prerequisites of step {step.step_id} (Depends on: {depends})"]
    if not on_main_available:
        lines.append(
            f"  {MAIN_REFERENCE} is not available here: run `git fetch origin` and try again"
        )
    lines.extend(describe_prerequisite(state) for state in states)
    met = all(state.met for state in states)
    lines.append(f"Prerequisites met: {'yes' if met else 'no'}")
    lines.append(f"Branch: {branch_advice(step, branches)}")
    lines.append(f"Working tree: {describe_changes(changes)}")
    return lines


def describe_changes(changes: list[str] | None) -> str:
    if changes is None:
        return "not a git repository"
    if not changes:
        return "clean"
    tracked = [change for change in changes if not change.startswith("??")]
    return f"{len(tracked)} changed and {len(changes) - len(tracked)} untracked files"


def render_next(progress: Progress) -> list[str]:
    lines = [f"Open: {row.step_id} {row.title} ({row.describe()})" for row in open_rows(progress)]
    action = next_action(progress)
    if action is None:
        lines.append("Every step in PROGRESS.md is done or skipped.")
        return lines
    lines.append(f"Next: {action.command} - {action.description}")
    if action.command.startswith("/step "):
        step_id = action.command.removeprefix("/step ")
        branches = step_branches(step_id)
        if branches:
            lines.append(
                f"Step {step_id} already has {', '.join(branches)}: /step {step_id} continues it"
                " (its pull request may be open: gh pr list)."
            )
    return lines


def session_summary(source: str) -> list[str]:
    branch = current_branch()
    if branch is None:
        return [f"FEFAT session ({source}): not inside a git repository."]
    lines = [f"FEFAT session ({source}): branch {branch}"]
    step_match = STEP_BRANCH_PATTERN.fullmatch(branch)
    phase_match = PHASE_BRANCH_PATTERN.fullmatch(branch)
    if step_match is not None:
        lines.extend(step_session(step_match.group(1)))
    elif phase_match is not None:
        lines.extend(phase_session(phase_match.group(1), int(phase_match.group(2))))
    else:
        lines.extend(main_session(branch))
    lines.extend(changes_summary())
    return lines


def step_session(step_id: str) -> list[str]:
    try:
        step = find_step(step_id)
    except UnknownStepError:
        return [f"The branch names step {step_id}, which is not in docs/masterplan/phases/P*.md."]
    row = progress_here().steps.get(step.step_id)
    lines = [
        f"Step {step.step_id} - {step.title} ({step.location})",
        step.meta_line,
        f"PROGRESS.md row: {'none' if row is None else row.describe()}",
        "Done means (each item needs evidence in the pull request):",
    ]
    lines.extend(
        f"  {number}. {shortened(item, SESSION_ITEM_WIDTH)}"
        for number, item in enumerate(step.done_means, start=1)
    )
    divergence = divergence_from_main()
    if divergence is not None:
        lines.append(
            f"Commits: {divergence.ahead} ahead of {MAIN_REFERENCE},"
            f" {divergence.behind} behind (as last fetched)."
        )
    lines.append(
        f"Continue with /step {step.step_id}: it resumes from the first unproven Done-means item."
    )
    return lines


def phase_session(kind: str, phase: int) -> list[str]:
    heading = KICKOFF_HEADING if kind == "kickoff" else EXIT_HEADING
    prompt = phase_prompt(phase, heading)
    lines = [f"Phase {phase} {kind} ({phase_file(phase).relative_to(ROOT).as_posix()})"]
    if prompt is not None:
        lines.append(shortened(" ".join(prompt.split()), PHASE_PROMPT_WIDTH))
    lines.append(f"Continue with /phase-{kind} {phase}.")
    return lines


def main_session(branch: str) -> list[str]:
    lines: list[str] = []
    if branch != MAIN_BRANCH:
        lines.append(f"{branch} is not a step branch (step/N.M-<slug>), kickoff/PN, or exit/PN.")
    lines.extend(render_next(progress_here()))
    divergence = divergence_from_main()
    if branch == MAIN_BRANCH and divergence is not None and divergence.behind > 0:
        lines.append(
            f"main is {divergence.behind} commits behind {MAIN_REFERENCE}: git pull --ff-only"
        )
    lines.append(
        "Steps work on step/N.M-<slug> branches and end with a pull request; never commit on main."
    )
    return lines


def changes_summary() -> list[str]:
    changes = working_tree_changes()
    if not changes:
        return []
    shown = [f"  {change}" for change in changes[:SESSION_CHANGES_SHOWN]]
    hidden = len(changes) - len(shown)
    more = [f"  ... and {hidden} more"] if hidden > 0 else []
    return [f"Uncommitted: {describe_changes(changes)}", *shown, *more]


def command_brief(arguments: argparse.Namespace) -> int:
    step = find_step(arguments.step_id)
    row = progress_here().steps.get(step.step_id)
    branches = step_branches(step.step_id)
    if arguments.json:
        print_json(brief_payload(step, row, branches))
    else:
        print("\n".join(render_brief(step, row, branches)))
    return EXIT_OK


def command_status(arguments: argparse.Namespace) -> int:
    step = find_step(arguments.step_id)
    on_main = progress_on_main()
    states = prerequisites(step, progress_here(), on_main)
    branches = step_branches(step.step_id)
    changes = working_tree_changes()
    if arguments.json:
        print_json(
            {
                "step_id": step.step_id,
                "origin_main_available": on_main is not None,
                "prerequisites": [
                    {
                        "step_id": state.step_id,
                        "status_here": state.status_here,
                        "status_on_main": state.status_on_main,
                        "merge_commit": state.merge_commit,
                        "met": state.met,
                    }
                    for state in states
                ],
                "prerequisites_met": all(state.met for state in states),
                "existing_branches": branches,
                "suggested_branch": suggested_branch(step),
                "working_tree_changes": changes,
            }
        )
    else:
        print("\n".join(render_status(step, states, on_main is not None, branches, changes)))
    return EXIT_OK


def command_next(arguments: argparse.Namespace) -> int:
    progress = progress_here()
    if arguments.json:
        action = next_action(progress)
        print_json(
            {
                "open": [row.step_id for row in open_rows(progress)],
                "next_command": None if action is None else action.command,
                "next_description": None if action is None else action.description,
            }
        )
    else:
        print("\n".join(render_next(progress)))
    return EXIT_OK


def command_session(arguments: argparse.Namespace) -> int:
    try:
        lines = session_summary(arguments.source)
    except MasterplanError as error:
        lines = [f"FEFAT session ({arguments.source}): the masterplan could not be read: {error}"]
    print("\n".join(lines))
    return EXIT_OK


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masterplan_step.py", description="Read one masterplan step and the state around it."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    brief = commands.add_parser("brief", help="the step as written, the skills to load, the branch")
    brief.add_argument("step_id", help="a step ID such as 0.5")
    brief.add_argument("--json", action="store_true", help="print JSON instead of text")
    brief.set_defaults(handler=command_brief)
    status = commands.add_parser("status", help="prerequisites, branches, and the working tree")
    status.add_argument("step_id", help="a step ID such as 0.5")
    status.add_argument("--json", action="store_true", help="print JSON instead of text")
    status.set_defaults(handler=command_status)
    upcoming = commands.add_parser("next", help="open steps and the next command to run")
    upcoming.add_argument("--json", action="store_true", help="print JSON instead of text")
    upcoming.set_defaults(handler=command_next)
    session = commands.add_parser("session", help="the summary the SessionStart hook prints")
    session.add_argument("--source", default="startup", help="startup, resume, clear, or compact")
    session.set_defaults(handler=command_session)
    return parser


def use_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def main(argv: Sequence[str]) -> int:
    use_utf8_output()
    arguments = build_parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except UnknownStepError as error:
        print(error, file=sys.stderr)
        return EXIT_UNKNOWN_STEP
    except MasterplanError as error:
        print(error, file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
