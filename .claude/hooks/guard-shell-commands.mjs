#!/usr/bin/env node
/**
 * PreToolUse guard for the Bash and PowerShell tools (.claude/settings.json,
 * matcher "Bash|PowerShell").
 *
 * Denies what CLAUDE.md and docs/masterplan/05-build-process.md section 8
 * forbid: skipping the commit gate (--no-verify, git commit -n), changing or
 * overriding core.hooksPath, writing .git/config directly, force pushes, and
 * pushes to main. Asks before golden regeneration, merges and other changes
 * on GitHub, edits of .githooks/, commits on main, pushes whose branch it
 * cannot tell, commands it cannot read, and anything that mentions Databento
 * (downloads cost money). Everything else gets no decision, so the permission
 * rules apply as usual.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import { readHookInput } from "./lib/hook-input.mjs";
import { askBeforeToolCall, denyToolCall, leaveToolCallToPermissionRules } from "./lib/hook-reply.mjs";
import { currentBranch } from "./lib/git-facts.mjs";
import { absolutePath, projectDirectory, withForwardSlashes } from "./lib/project-paths.mjs";
import {
  BASH,
  POWERSHELL,
  commandsIn,
  gitInvocationsIn,
  isDiscardedOutput,
  programIndex,
  programName,
} from "./lib/shell-commands.mjs";

const MAIN = "main";
const CURRENT_BRANCH = Symbol("the current branch");
const MATCHING_BRANCHES = Symbol("all matching branches");

const REASONS = {
  noVerify:
    "--no-verify (or git commit -n) skips the commit gate in .githooks/pre-commit, which this repository never allows; fix what the gate reports instead.",
  hooksPath:
    "core.hooksPath must stay .githooks, the commit gate; this repository never changes or overrides it.",
  gitConfigFile:
    "Writing .git/config directly could change core.hooksPath; use git config for other settings.",
  forcePush:
    "Force pushes are never used here (docs/masterplan/05-build-process.md section 8); push new commits instead.",
  pushToMain:
    "main changes only through pull requests that the builder merges (docs/masterplan/05-build-process.md section 8); push the step branch with `git push -u origin HEAD` instead.",
  pushEverything:
    "Pushing all branches or mirroring would update main as well; push the step branch with `git push -u origin HEAD` instead.",
  unknownBranch:
    "The guard cannot tell which branch this push would update; confirm that it is not main.",
  deleteBranch: "This push deletes a branch on GitHub; confirm that it is the right one.",
  commitOnMain:
    "This commit lands on main, but steps work on step/N.M-<slug> branches (docs/masterplan/05-build-process.md section 2); confirm, or switch branches first.",
  commitGate: "This changes the commit gate in .githooks/; confirm the change.",
  goldens:
    "This regenerates or overwrites goldens or snapshots, which change only with the builder's approval and a changelog entry (the engine-golden skill).",
  github:
    "Merging pull requests and changing the repository on GitHub are the builder's routine (docs/masterplan/05-build-process.md section 8); confirm first.",
  databento:
    "This mentions Databento, whose downloads cost money: confirm the importer's cost preview first (docs/masterplan/07-tools-and-costs.md section 3).",
  opaque: (what) => `The guard cannot read ${what}; confirm that it does not push, force, or skip hooks.`,
};

const COMMIT_OPTION_LETTERS_WITH_VALUE = new Set(["m", "F", "C", "c", "t", "S", "u"]);
const CONFIG_WRITE_WORDS = new Set(["--unset", "--unset-all", "--add", "--replace-all", "set", "unset", "--edit", "-e", "edit"]);
const CONFIG_SECTION_WORDS = new Set(["--remove-section", "--rename-section", "remove-section", "rename-section"]);
const CONFIG_OPTIONS_WITH_VALUE = new Set(["--default", "--type", "--comment", "--file", "-f", "--blob", "--value"]);
const PUSH_OPTIONS_WITH_VALUE = new Set(["--repo", "--receive-pack", "--exec", "--push-option", "-o"]);
const WRITING_PROGRAMS = new Set([
  "cp", "mv", "rm", "tee", "touch", "copy", "move", "del", "erase", "xcopy", "robocopy", "ren",
  "rename", "copy-item", "move-item", "remove-item", "rename-item", "new-item", "set-content",
  "add-content", "out-file", "clear-content", "cpi", "mi", "ri", "ni", "sc", "ac",
]);
const IN_PLACE_EDITORS = new Set(["sed", "perl"]);
const SNAPSHOT_UPDATE_OPTIONS = ["--snapshot-update", "--update-snapshots", "--update-goldens", "--force-regen"];
const INSTA_UPDATES = new Set(["accept", "review", "reject", "--accept", "--review", "--force-update-snapshots", "--accept-unseen"]);
const JAVASCRIPT_RUNNERS = new Set(["pnpm", "npm", "npx", "yarn", "vitest", "bun", "bunx", "playwright"]);
const GOLDEN_ENVIRONMENT = /\b(INSTA_UPDATE|INSTA_FORCE_PASS|UPDATE_GOLDENS|UPDATE_SNAPSHOTS)\s*=/i;
const GIT_CONFIG_ENVIRONMENT = /^(\$env:)?GIT_CONFIG\w*/i;

function deny(reason) {
  return { decision: "deny", reason };
}

function ask(reason) {
  return { decision: "ask", reason };
}

function isMain(branch) {
  return branch.toLowerCase() === MAIN;
}

function findingsFor(commandLine, shell, startDirectory) {
  const branchAt = branchLookup();
  const findings = [];
  for (const command of commandsIn(commandLine, shell, startDirectory)) {
    findings.push(...commandFindings(command));
    for (const git of gitInvocationsIn(command)) {
      findings.push(...gitFindings(git, branchAt));
    }
  }
  return findings;
}

function branchLookup() {
  const known = new Map();
  return (directory) => {
    if (directory === null) {
      return null;
    }
    if (!known.has(directory)) {
      known.set(directory, currentBranch(directory));
    }
    return known.get(directory);
  };
}

function commandFindings(command) {
  const findings = [];
  if (command.opaque !== null) {
    findings.push(ask(REASONS.opaque(command.opaque)));
  }
  if (setsHooksPathThroughEnvironment(command.words)) {
    findings.push(deny(REASONS.hooksPath));
  }
  const written = writtenPaths(command);
  if (written.some((target) => /(^|\/)\.git\/config$/.test(target))) {
    findings.push(deny(REASONS.gitConfigFile));
  }
  if (written.some((target) => /(^|\/)\.githooks(\/|$)/.test(target))) {
    findings.push(ask(REASONS.commitGate));
  }
  if (written.some(isGoldenPath) || regeneratesGoldens(command.words) || GOLDEN_ENVIRONMENT.test(command.text)) {
    findings.push(ask(REASONS.goldens));
  }
  if (changesGitHub(command.words)) {
    findings.push(ask(REASONS.github));
  }
  if (/databento/i.test(command.text)) {
    findings.push(ask(REASONS.databento));
  }
  return findings;
}

function setsHooksPathThroughEnvironment(words) {
  return words.some((word, index) => {
    if (!GIT_CONFIG_ENVIRONMENT.test(word)) {
      return false;
    }
    const assignment = words.slice(index, index + 3).join(" ").toLowerCase();
    return assignment.includes("hookspath");
  });
}

function writtenPaths(command) {
  const index = programIndex(command.words);
  const program = index < command.words.length ? programName(command.words[index]) : "";
  const args = command.words.slice(index + 1);
  const targets = [...command.outputTargets];
  if (WRITING_PROGRAMS.has(program)) {
    targets.push(...args);
  }
  if (IN_PLACE_EDITORS.has(program) && args.some((arg) => /^-[A-Za-z]*i/.test(arg) || arg.startsWith("--in-place"))) {
    targets.push(...args);
  }
  return targets
    .filter((target) => !isDiscardedOutput(target))
    .map((target) => withForwardSlashes(target).toLowerCase());
}

function isGoldenPath(target) {
  return target.includes("fixtures/goldens") || /\.snap(\.new)?$/.test(target) || target.includes("__snapshots__");
}

function regeneratesGoldens(words) {
  const index = programIndex(words);
  if (index >= words.length) {
    return false;
  }
  const program = programName(words[index]);
  const args = words.slice(index + 1);
  if (args.some((arg) => SNAPSHOT_UPDATE_OPTIONS.some((option) => arg === option || arg.startsWith(`${option}=`)))) {
    return true;
  }
  if (program === "cargo" && args[0] === "insta") {
    return args.slice(1).some((arg) => INSTA_UPDATES.has(arg));
  }
  if (program === "just") {
    return args.some((arg) => /golden/i.test(arg));
  }
  if (JAVASCRIPT_RUNNERS.has(program)) {
    return args.some((arg) => arg === "-u" || arg === "--update");
  }
  return false;
}

function changesGitHub(words) {
  const index = words.findIndex((word) => programName(word) === "gh");
  if (index === -1) {
    return false;
  }
  const [area, action] = words.slice(index + 1);
  if (area === "pr" && action === "merge") {
    return true;
  }
  if (area === "repo" && ["edit", "delete", "rename", "archive"].includes(action)) {
    return true;
  }
  return area === "api" && apiWrites(words.slice(index + 2));
}

function apiWrites(args) {
  return args.some((arg, index) => {
    if (arg === "-X" || arg === "--method") {
      return String(args[index + 1]).toUpperCase() !== "GET";
    }
    if (arg.startsWith("--method=")) {
      return arg.slice("--method=".length).toUpperCase() !== "GET";
    }
    if (/^-X[A-Za-z]+$/.test(arg)) {
      return arg.slice(2).toUpperCase() !== "GET";
    }
    return ["-f", "-F", "--field", "--raw-field", "--input"].includes(arg) || /^--(raw-)?field=/.test(arg);
  });
}

function gitFindings(git, branchAt) {
  const findings = [];
  if (git.configs.some((config) => config.toLowerCase().startsWith("core.hookspath"))) {
    findings.push(deny(REASONS.hooksPath));
  }
  if (git.args.some(isNoVerifyOption)) {
    findings.push(deny(REASONS.noVerify));
  }
  if (git.subcommand === "commit") {
    findings.push(...commitFindings(git, branchAt));
  }
  if (git.subcommand === "config" && configWritesHooksPath(git.args)) {
    findings.push(deny(REASONS.hooksPath));
  }
  if (git.subcommand === "push") {
    findings.push(...pushFindings(git, branchAt));
  }
  return findings;
}

function isNoVerifyOption(arg) {
  return arg.length >= "--no-veri".length && "--no-verify".startsWith(arg);
}

function commitFindings(git, branchAt) {
  const findings = [];
  if (git.args.some(isCommitNoVerifyCluster)) {
    findings.push(deny(REASONS.noVerify));
  }
  const branch = branchAt(git.directory);
  if (branch !== null && isMain(branch)) {
    findings.push(ask(REASONS.commitOnMain));
  }
  return findings;
}

function isCommitNoVerifyCluster(arg) {
  if (!/^-[A-Za-z]+$/.test(arg)) {
    return false;
  }
  for (const option of arg.slice(1)) {
    if (option === "n") {
      return true;
    }
    if (COMMIT_OPTION_LETTERS_WITH_VALUE.has(option)) {
      return false;
    }
  }
  return false;
}

function configWritesHooksPath(args) {
  const lowered = args.map((arg) => arg.toLowerCase());
  if (lowered.some((arg) => CONFIG_SECTION_WORDS.has(arg)) && lowered.includes("core")) {
    return true;
  }
  const keyIndex = lowered.findIndex((arg) => arg === "core.hookspath" || arg.startsWith("core.hookspath="));
  if (keyIndex === -1) {
    return false;
  }
  if (lowered[keyIndex].includes("=") || lowered.some((arg) => CONFIG_WRITE_WORDS.has(arg))) {
    return true;
  }
  for (let index = keyIndex + 1; index < args.length; index += 1) {
    if (CONFIG_OPTIONS_WITH_VALUE.has(lowered[index])) {
      index += 1;
    } else if (!args[index].startsWith("-")) {
      return true;
    }
  }
  return false;
}

function pushFindings(git, branchAt) {
  const push = parsePushArguments(git.args);
  const findings = [];
  if (push.force || push.refspecs.some((refspec) => refspec.startsWith("+"))) {
    findings.push(deny(REASONS.forcePush));
  }
  if (push.everything) {
    findings.push(deny(REASONS.pushEverything));
  }
  if (push.deletes) {
    for (const refspec of push.refspecs) {
      const branch = refspec.replace(/^\+/, "").replace(/^refs\/heads\//, "");
      findings.push(isMain(branch) ? deny(REASONS.pushToMain) : ask(REASONS.deleteBranch));
    }
    return findings;
  }
  if (push.refspecs.length === 0 && !push.tags) {
    findings.push(...currentBranchPushFindings(git.directory, branchAt));
  }
  for (const refspec of push.refspecs) {
    const destination = refspecDestination(refspec);
    if (destination === MATCHING_BRANCHES) {
      findings.push(deny(REASONS.pushEverything));
    } else if (destination === CURRENT_BRANCH) {
      findings.push(...currentBranchPushFindings(git.directory, branchAt));
    } else if (isMain(destination)) {
      findings.push(deny(REASONS.pushToMain));
    }
  }
  return findings;
}

function parsePushArguments(args) {
  const push = { force: false, everything: false, deletes: false, tags: false };
  const positionals = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--") {
      positionals.push(...args.slice(index + 1));
      break;
    }
    if (PUSH_OPTIONS_WITH_VALUE.has(arg)) {
      index += 1;
    } else if (arg.startsWith("--")) {
      applyLongPushOption(push, arg.split("=")[0]);
    } else if (arg.startsWith("-") && arg.length > 1) {
      index += applyShortPushOptions(push, arg) ? 1 : 0;
    } else {
      positionals.push(arg);
    }
  }
  return { ...push, refspecs: positionals.slice(1) };
}

function applyLongPushOption(push, name) {
  if (name.startsWith("--force")) {
    push.force = true;
  } else if (name === "--mirror" || name === "--all" || name === "--branches") {
    push.everything = true;
  } else if (name === "--delete") {
    push.deletes = true;
  } else if (name === "--tags") {
    push.tags = true;
  }
}

/** Applies a cluster such as -uf; true when it ends in -o, whose value is the next word. */
function applyShortPushOptions(push, cluster) {
  for (let index = 1; index < cluster.length; index += 1) {
    const option = cluster[index];
    if (option === "f") {
      push.force = true;
    } else if (option === "d") {
      push.deletes = true;
    } else if (option === "o") {
      return index === cluster.length - 1;
    }
  }
  return false;
}

function refspecDestination(refspec) {
  const spec = refspec.replace(/^\+/, "");
  if (spec === ":") {
    return MATCHING_BRANCHES;
  }
  const colon = spec.indexOf(":");
  const source = colon === -1 ? spec : spec.slice(0, colon);
  const destination = colon === -1 || colon === spec.length - 1 ? source : spec.slice(colon + 1);
  if (destination === "HEAD" || destination === "@") {
    return CURRENT_BRANCH;
  }
  return destination.replace(/^refs\/heads\//, "");
}

function currentBranchPushFindings(directory, branchAt) {
  const branch = branchAt(directory);
  if (branch === null) {
    return [ask(REASONS.unknownBranch)];
  }
  return isMain(branch) ? [deny(REASONS.pushToMain)] : [];
}

function reply(findings) {
  const denials = [...new Set(findings.filter((finding) => finding.decision === "deny").map((finding) => finding.reason))];
  if (denials.length > 0) {
    denyToolCall(denials.join(" "));
    return;
  }
  const questions = [...new Set(findings.filter((finding) => finding.decision === "ask").map((finding) => finding.reason))];
  if (questions.length > 0) {
    askBeforeToolCall(questions.join(" "));
    return;
  }
  leaveToolCallToPermissionRules();
}

function startDirectory(input) {
  if (typeof input.cwd === "string" && input.cwd !== "") {
    return absolutePath(input.cwd, input.cwd);
  }
  return projectDirectory(input);
}

async function main() {
  const reading = await readHookInput();
  if (!reading.ok) {
    askBeforeToolCall(`The shell guard could not read its input (${reading.reason}); check this command by hand.`);
    return;
  }
  const commandLine = reading.input.tool_input?.command;
  if (typeof commandLine !== "string") {
    leaveToolCallToPermissionRules();
    return;
  }
  const shell = reading.input.tool_name === "PowerShell" ? POWERSHELL : BASH;
  reply(findingsFor(commandLine, shell, startDirectory(reading.input)));
}

main().catch((error) => {
  askBeforeToolCall(`The shell guard failed (${error.message}); check this command by hand.`);
});
