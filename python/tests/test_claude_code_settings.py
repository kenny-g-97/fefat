import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = ROOT / ".claude"
# scripts/test_hooks.py runs each hook script directly, so only this test notices a script
# that .claude/settings.json never runs, as the reviewer guard was until the Phase 0 exit.
REGISTRATIONS = {
    "guard-file-paths.mjs": ("PreToolUse", "Edit|Write|NotebookEdit"),
    "guard-shell-commands.mjs": ("PreToolUse", "Bash|PowerShell"),
    "reviewer-shell-commands.mjs": ("PreToolUse", "Bash|PowerShell"),
    "format-on-edit.mjs": ("PostToolUse", "Edit|Write"),
    "session-brief.mjs": ("SessionStart", "startup|resume|clear|compact"),
}


def registered_hooks() -> set[tuple[str, str, str]]:
    settings = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    return {
        (Path(argument).name, event, group["matcher"])
        for event, groups in settings["hooks"].items()
        for group in groups
        for hook in group["hooks"]
        for argument in hook.get("args", [])
    }


def test_every_hook_script_is_registered_for_its_event_and_tools() -> None:
    scripts = {path.name for path in (CLAUDE / "hooks").glob("*.mjs")}
    expected = {(script, event, matcher) for script, (event, matcher) in REGISTRATIONS.items()}

    assert scripts == set(REGISTRATIONS)
    assert expected <= registered_hooks()
