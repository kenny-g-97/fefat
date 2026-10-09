#!/usr/bin/env node
/**
 * SessionStart hook (startup, resume, clear, compact): prints where the work
 * stands, and Claude Code adds it to the session's context, so a resumed or
 * compacted session starts from git, the step file, and PROGRESS.md rather
 * than from memory (docs/masterplan/05-build-process.md section 2).
 *
 * The summary comes from `scripts/masterplan_step.py session`, the one reader
 * of the masterplan. When that cannot run, the hook prints what git alone can
 * tell. It never blocks a session and always exits 0.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import process from "node:process";
import { spawnSync } from "node:child_process";
import { readHookInput } from "./lib/hook-input.mjs";
import { runGit } from "./lib/git-facts.mjs";
import { projectDirectory } from "./lib/project-paths.mjs";

const SUMMARY_TIMEOUT_MS = 20000;
const CHANGES_SHOWN = 8;

function masterplanSummary(project, source) {
  const result = spawnSync(
    "uv",
    ["run", "--no-project", "python", "scripts/masterplan_step.py", "session", "--source", source],
    { cwd: project, encoding: "utf8", timeout: SUMMARY_TIMEOUT_MS, windowsHide: true },
  );
  if (result.error !== undefined) {
    return { ok: false, problem: result.error.message };
  }
  if (result.status !== 0 || result.stdout.trim() === "") {
    const detail = `${result.stderr}`.trim().split("\n").pop();
    return { ok: false, problem: `the step reader exited with ${result.status}: ${detail}` };
  }
  return { ok: true, text: result.stdout.trimEnd() };
}

function gitOnlySummary(project, source, problem) {
  const branch = runGit(["rev-parse", "--abbrev-ref", "HEAD"], project);
  const lines = [
    branch === null
      ? `FEFAT session (${source}): ${project} is not a git repository.`
      : `FEFAT session (${source}): branch ${branch.trim()}`,
  ];
  const counts = runGit(["rev-list", "--left-right", "--count", "origin/main...HEAD"], project);
  if (counts !== null) {
    const [behind, ahead] = counts.trim().split(/\s+/);
    lines.push(`Commits: ${ahead} ahead of origin/main, ${behind} behind (as last fetched).`);
  }
  const changes = (runGit(["status", "--porcelain"], project) ?? "").split("\n").filter((line) => line.trim() !== "");
  if (changes.length > 0) {
    lines.push(`Uncommitted: ${changes.length} files`, ...changes.slice(0, CHANGES_SHOWN).map((line) => `  ${line}`));
  }
  lines.push(`Step summary unavailable (${problem}).`);
  lines.push("For the masterplan state run: uv run --no-project python scripts/masterplan_step.py next");
  return lines.join("\n");
}

async function main() {
  process.exitCode = 0;
  const reading = await readHookInput();
  const input = reading.ok ? reading.input : {};
  const source = typeof input.source === "string" && input.source !== "" ? input.source : "session start";
  const project = projectDirectory(input);
  const summary = masterplanSummary(project, source);
  process.stdout.write(`${summary.ok ? summary.text : gitOnlySummary(project, source, summary.problem)}\n`);
}

main().catch((error) => {
  process.stdout.write(`FEFAT session: the session brief failed (${error.message}).\n`);
  process.exitCode = 0;
});
