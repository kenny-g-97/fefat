import subprocess
import sys
from pathlib import Path

import pytest

import masterplan_step

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "masterplan_step.py"


def test_step_0_4_is_read_with_its_meta_line_and_done_means() -> None:
    step = masterplan_step.find_step("0.4")

    assert step.title == "Configure Claude Code for this repository"
    path, line = step.location.split(":")
    assert path == "docs/masterplan/phases/P00-foundations.md"
    heading = (ROOT / path).read_text(encoding="utf-8").splitlines()[int(line) - 1]
    assert heading == "### 0.4 Configure Claude Code for this repository"
    assert step.depends_on == ("0.3",)
    assert step.plan_mode == "required"
    assert step.reviews == ("step-reviewer",)
    assert step.model_hint == "hard"
    assert len(step.done_means) == 5
    assert step.done_means[0].startswith("`uv run python scripts/test_hooks.py`")
    assert "Not in this step" in step.section("Prompt")


def test_every_step_in_the_phase_files_has_numbered_done_means() -> None:
    steps = [masterplan_step.read_step(parsed) for parsed in masterplan_step.parsed_steps()]

    assert len(steps) > 100
    assert [step.step_id for step in steps if not step.done_means] == []


def test_a_step_id_with_leading_zeros_names_the_same_step() -> None:
    assert masterplan_step.normalized_step_id(" 2.06 ") == "2.6"


def test_text_that_is_not_a_step_id_is_rejected_with_what_was_given() -> None:
    with pytest.raises(masterplan_step.UnknownStepError, match="'two'"):
        masterplan_step.normalized_step_id("two")


def test_an_unknown_step_exits_with_code_2_and_names_it() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "brief", "99.9"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == masterplan_step.EXIT_UNKNOWN_STEP
    assert "99.9" in completed.stderr


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Data policy, synthetic fixtures, commit guard", "data-policy-synthetic"),
        ("CI on Windows and Linux", "ci-windows-linux"),
        ("Hello-world slice: Rust to Python to a notebook", "hello-world-slice"),
        ("Metrics and `run.explain`", "metrics-run-explain"),
    ],
)
def test_branch_slugs_keep_three_words_without_stop_words(title: str, expected: str) -> None:
    assert masterplan_step.slug(title) == expected


def test_progress_rows_keep_empty_cells_and_the_phase_table() -> None:
    progress = masterplan_step.parse_progress(
        "| 0.3 | Configure the GitHub repository | P0 | done | #1 | 2026-10-09 | merged |\n"
        "| 0.4 | Configure Claude Code for this repository | P0 | todo | | | Amended |\n"
        "| P0 | (no kickoff) | | | | |\n"
        "| P1 | | | | | |\n"
    )

    assert progress.steps["0.3"].describe() == "done (#1, 2026-10-09)"
    assert progress.steps["0.4"].pull_request == ""
    assert progress.steps["0.4"].describe() == "todo"
    assert progress.kickoff_recorded(0)
    assert not progress.kickoff_recorded(1)


def test_a_status_outside_the_list_in_progress_md_is_rejected() -> None:
    with pytest.raises(masterplan_step.MasterplanError, match="'Done'"):
        masterplan_step.parse_progress("| 0.4 | Configure Claude Code | P0 | Done | | | |\n")


def progress_table(rows: list[tuple[str, str, str]], phases: list[str]) -> str:
    step_lines = [
        f"| {step} | Title {step} | {phase} | {status} | | | |" for step, phase, status in rows
    ]
    return "\n".join([*step_lines, *phases])


def test_the_next_action_closes_a_finished_phase_before_the_next_one() -> None:
    progress = masterplan_step.parse_progress(
        progress_table(
            [("0.8", "P0", "done"), ("1.1", "P1", "todo")],
            ["| P0 | (no kickoff) | | | | |", "| P1 | | | | | |"],
        )
    )

    action = masterplan_step.next_action(progress)

    assert action is not None
    assert action.command == "/phase-exit 0"


def test_the_next_action_opens_a_phase_before_its_first_step() -> None:
    progress = masterplan_step.parse_progress(
        progress_table(
            [("0.8", "P0", "done"), ("1.1", "P1", "todo")],
            ["| P0 | (no kickoff) | | #9 | 2026-10-20 | phase-0 |", "| P1 | | | | | |"],
        )
    )

    action = masterplan_step.next_action(progress)

    assert action is not None
    assert action.command == "/phase-kickoff 1"


def test_the_next_action_is_the_first_step_still_to_do() -> None:
    progress = masterplan_step.parse_progress(
        progress_table(
            [("0.4", "P0", "done"), ("0.5", "P0", "todo"), ("0.6", "P0", "todo")],
            ["| P0 | (no kickoff) | | | | |"],
        )
    )

    action = masterplan_step.next_action(progress)

    assert action is not None
    assert action.command == "/step 0.5"


def test_the_next_action_continues_an_open_or_amended_step_first() -> None:
    progress = masterplan_step.parse_progress(
        progress_table(
            [("0.8", "P0", "amended"), ("1.1", "P1", "todo")],
            ["| P0 | (no kickoff) | | | | |", "| P1 | | | | | |"],
        )
    )

    action = masterplan_step.next_action(progress)

    assert action is not None
    assert action.command == "/step 0.8"


def skills_for(step_id: str) -> list[str]:
    step = masterplan_step.find_step(step_id)
    return [suggestion.skill for suggestion in masterplan_step.suggest_skills(step)]


def test_engine_steps_load_the_backtest_skill_and_ui_steps_the_frontend_skill() -> None:
    assert "backtest-expert" in skills_for("2.6")
    assert "frontend-design:frontend-design" in skills_for("5.9")
    assert skills_for("0.5") == ["software-design-principles"]


def test_the_runner_reads_the_statuses_the_checker_accepts() -> None:
    import check_masterplan

    satisfied_open_or_todo = (
        masterplan_step.SATISFIED_STATUSES
        | masterplan_step.OPEN_STATUSES
        | {masterplan_step.TODO_STATUS}
    )
    assert masterplan_step.KNOWN_STATUSES == check_masterplan.STATUSES == satisfied_open_or_todo


def test_the_brief_lists_the_backlog_lines_whose_target_names_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The kickoff pulls backlog lines into its steps once; a line that arrives after it reaches
    # its step through the brief, by the step id in its Target, 2.1 and not 2.10. Each kickoff
    # empties the real backlog of its phase's targets, so the test writes the lines it reads.
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "- **Goldens, scenario tables, and the commit guard** — the guard refuses CSV goldens."
        " Target: before the first scenario table (step 2.1). Source: D-48.\n"
        "- **How a run picks its fee schedule** — the tables start in 2026."
        " Target: steps 2.9 and 2.10. Source: step 1.2.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(masterplan_step, "BACKLOG", backlog)
    lines = masterplan_step.backlog_lines_for("2.1")

    assert any("Goldens, scenario tables, and the commit guard" in line for line in lines)
    assert not any("fee schedule" in line for line in lines)
