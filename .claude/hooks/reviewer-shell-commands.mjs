#!/usr/bin/env node
/**
 * PreToolUse hook for the read-only reviewer subagents (step-reviewer,
 * engine-accuracy-reviewer, leakage-auditor, design-reviewer), registered in
 * .claude/settings.json for the Bash and PowerShell tools of every session.
 * It acts only on calls whose agent_type names a reviewer, because Claude
 * Code (2.1.295 and 2.1.296) does not run hooks declared in an agent's
 * frontmatter.
 *
 * A reviewer may read the repository and run the checks and tests; it may
 * not change anything. Every command in a call must match the read-only list
 * below, and no output may go into a file; anything else is denied with a
 * message that tells the reviewer to describe the change instead. The main
 * session's guards (guard-shell-commands.mjs) still apply on top.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import { readHookInput } from "./lib/hook-input.mjs";
import { denyToolCall, leaveToolCallToPermissionRules } from "./lib/hook-reply.mjs";
import { commandStartDirectory, withForwardSlashes } from "./lib/project-paths.mjs";
import {
  BASH,
  FIND_ACTIONS_THAT_WRITE,
  POWERSHELL,
  commandsIn,
  gitInvocationsIn,
  isDiscardedOutput,
  parseGitInvocation,
  programIndex,
  programName,
} from "./lib/shell-commands.mjs";

/** The agents in .claude/agents/; scripts/test_hooks.py probes each one. */
const REVIEWERS = new Set(["design-reviewer", "engine-accuracy-reviewer", "leakage-auditor", "step-reviewer"]);
const BRANCH_CHANGING_OPTIONS = new Set([
  "--delete", "--move", "--copy", "--force", "--unset-upstream", "--edit-description", "--track", "--no-track",
]);
const BRANCH_CHANGING_LETTERS = /^-[A-Za-z]*[dDmMcCfut]/;
const BRANCH_LISTING_OPTIONS = new Set(["--list", "-l", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"]);
// --config can set a runner program for cargo to start, and -Z flags switch on unstable behaviour.
const CARGO_RUNNER_OPTIONS = ["--config", /^-Z/];
const SAFE_GIT_GLOBAL_OPTIONS = new Set(["-C", "--no-pager", "-P", "--paginate", "-p", "--no-optional-locks", "--literal-pathspecs"]);

function readOnly(pattern, { forbids = [], requiresOneOf = [], accepts = () => true } = {}) {
  return { words: pattern.split(" "), forbids, requiresOneOf, accepts };
}

function listsBranchesOnly(rest) {
  if (rest.some((word) => BRANCH_CHANGING_OPTIONS.has(word) || word.startsWith("--set-upstream-to") || BRANCH_CHANGING_LETTERS.test(word))) {
    return false;
  }
  const positionals = rest.filter((word) => !word.startsWith("-"));
  return positionals.length === 0 || rest.some((word) => BRANCH_LISTING_OPTIONS.has(word));
}

const READ_ONLY_COMMANDS = [
  readOnly("git diff", { forbids: ["--output"] }),
  readOnly("git log", { forbids: ["--output"] }),
  readOnly("git show", { forbids: ["--output"] }),
  // A short option counts inside a cluster too (-nO, -qo): /^-[A-Za-z]*O/ and the like.
  readOnly("git grep", { forbids: [/^-[A-Za-z]*O/, /^--op/] }),
  ...["status", "blame", "rev-parse", "rev-list", "ls-files", "merge-base", "describe", "cat-file", "for-each-ref", "shortlog"].map(
    (subcommand) => readOnly(`git ${subcommand}`),
  ),
  readOnly("git branch", { accepts: listsBranchesOnly }),
  // just runs every recipe named after the first, so `just check strip-notebooks` would write.
  readOnly("just check", { accepts: (rest) => rest.length === 0 }),
  readOnly("just test", { accepts: (rest) => rest.length === 0 }),
  readOnly("cargo test", { forbids: [...CARGO_RUNNER_OPTIONS, "--logfile"] }),
  readOnly("cargo check", { forbids: CARGO_RUNNER_OPTIONS }),
  readOnly("cargo metadata", { forbids: CARGO_RUNNER_OPTIONS }),
  readOnly("cargo tree", { forbids: CARGO_RUNNER_OPTIONS }),
  readOnly("cargo clippy", { forbids: ["--fix", ...CARGO_RUNNER_OPTIONS] }),
  readOnly("cargo fmt", { requiresOneOf: ["--check"] }),
  readOnly("uv run pytest", {
    forbids: [
      "--snapshot-update", "--force-regen", "--junitxml", "--junit-xml", "--result-log", "--html", "--basetemp",
      "--log-file", "--debug", /^-[A-Za-z]*o/, "--override-ini",
    ],
  }),
  readOnly("uv run pyright", { forbids: ["--createstub", "--writebaseline"] }),
  readOnly("uv run lint-imports"),
  readOnly("uv run ruff check", {
    forbids: ["--fix", "--fix-only", "--unsafe-fixes", "--add-noqa", "--output-file", /^-[A-Za-z]*o/, "--config"],
  }),
  readOnly("uv run ruff format", { requiresOneOf: ["--check", "--diff"] }),
  readOnly("uv run python docs/masterplan/tools/check_masterplan.py"),
  readOnly("uv run python scripts/test_hooks.py"),
  readOnly("uv run python scripts/masterplan_step.py"),
  readOnly("uv run --no-project python docs/masterplan/tools/check_masterplan.py"),
  readOnly("uv run --no-project python scripts/masterplan_step.py"),
  readOnly("pnpm --dir web lint", { forbids: ["--fix", "--fix-suggestions", "--fix-dangerously"] }),
  readOnly("pnpm --dir web typecheck"),
  readOnly("pnpm --dir web test", { forbids: ["-u", "--update", /^--outputFile/, /^--coverage/, /^--reporter/] }),
  readOnly("node --check", { accepts: (rest) => rest.every((word) => !word.startsWith("-")) }),
  readOnly("find", { forbids: FIND_ACTIONS_THAT_WRITE }),
  readOnly("sort", { forbids: [/^-[A-Za-z]*o/, /^--o/] }),
  readOnly("rg", { forbids: ["--pre"] }),
  ...[
    "grep", "ls", "cat", "head", "tail", "wc", "diff", "echo", "pwd", "cd", "which", "file", "stat",
    "basename", "dirname", "realpath", "true",
    "get-content", "gc", "get-childitem", "gci", "dir", "select-string", "sls", "get-location",
    "set-location", "test-path", "get-item", "resolve-path", "split-path", "join-path", "write-output",
  ].map((program) => readOnly(program)),
];

function commandWords(command) {
  const words = command.words.slice(programIndex(command.words));
  if (words.length > 0 && programName(words[0]) === "git") {
    const invocation = parseGitInvocation(words.slice(1), command.directory);
    return invocation === null ? words : ["git", invocation.subcommand, ...invocation.args];
  }
  return words;
}

function matchesReadOnly(rule, words) {
  if (words.length < rule.words.length || programName(words[0]) !== rule.words[0]) {
    return false;
  }
  for (let index = 1; index < rule.words.length; index += 1) {
    if (withForwardSlashes(words[index]) !== rule.words[index]) {
      return false;
    }
  }
  const rest = words.slice(rule.words.length);
  if (rest.some((word) => rule.forbids.some((option) => forbidden(option, word)))) {
    return false;
  }
  if (rule.requiresOneOf.length > 0 && !rest.some((word) => rule.requiresOneOf.includes(word))) {
    return false;
  }
  return rule.accepts(rest);
}

function forbidden(option, word) {
  if (option instanceof RegExp) {
    return option.test(word);
  }
  return word === option || word.startsWith(`${option}=`);
}

function gitProblem(command) {
  const unsafe = gitInvocationsIn(command).some(
    (git) => git.configs.length > 0 || git.globalOptions.some((option) => !SAFE_GIT_GLOBAL_OPTIONS.has(option)),
  );
  return unsafe ? `"${command.text}" passes git options that can run programs (-c, --exec-path, and the like)` : null;
}

function problemsWith(commands) {
  const problems = [];
  for (const command of commands) {
    if (command.opaque !== null) {
      problems.push(`it cannot read ${command.opaque}`);
      continue;
    }
    const targets = command.outputTargets.filter((target) => !isDiscardedOutput(target));
    const unsafeGit = gitProblem(command);
    if (programIndex(command.words) > 0) {
      problems.push(`"${command.text}" sets environment variables or starts with a prefix such as env or sudo`);
    } else if (unsafeGit !== null) {
      problems.push(unsafeGit);
    } else if (targets.length > 0) {
      problems.push(`"${command.text}" writes to ${targets.join(", ")}`);
    } else if (!READ_ONLY_COMMANDS.some((rule) => matchesReadOnly(rule, commandWords(command)))) {
      problems.push(`"${command.text}" is not on the read-only list`);
    }
  }
  return problems;
}

/** The agent's own name, without a prefix such as "project:" that a later Claude Code might add. */
function agentName(agentType) {
  return typeof agentType === "string" ? agentType.slice(agentType.lastIndexOf(":") + 1) : "";
}

async function main() {
  const reading = await readHookInput();
  // The main session and other agents are not this guard's business; the shell guard asks about input it cannot read.
  if (!reading.ok || !REVIEWERS.has(agentName(reading.input.agent_type))) {
    leaveToolCallToPermissionRules();
    return;
  }
  const commandLine = reading.input.tool_input?.command;
  if (typeof commandLine !== "string") {
    leaveToolCallToPermissionRules();
    return;
  }
  const shell = reading.input.tool_name === "PowerShell" ? POWERSHELL : BASH;
  const problems = problemsWith(commandsIn(commandLine, shell, commandStartDirectory(reading.input)));
  if (problems.length === 0) {
    leaveToolCallToPermissionRules();
    return;
  }
  denyToolCall(
    `Reviewers are read-only: ${problems.join("; ")}. Use read-only commands (git diff, git log, git show, just check, just test, cargo test, uv run pytest, rg, cat) and describe any change or experiment for the main session instead.`,
  );
}

main().catch((error) => {
  denyToolCall(`Reviewers are read-only, and this command could not be checked (${error.message}).`);
});
