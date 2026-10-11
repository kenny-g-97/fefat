#!/usr/bin/env node
/**
 * PreToolUse guard for the Bash and PowerShell tools (.claude/settings.json,
 * matcher "Bash|PowerShell").
 *
 * Denies what CLAUDE.md and docs/masterplan/05-build-process.md section 8
 * forbid: skipping the commit gate (--no-verify, git commit -n), changing or
 * overriding core.hooksPath, writing .git/config directly or through
 * git config --edit, force pushes, and pushes to main. Asks before golden regeneration, merges and other changes
 * on GitHub, edits of .githooks/, commits on main, pushes whose branch it
 * cannot tell, commands it cannot read, and anything that mentions Databento
 * (downloads cost money). Everything else gets no decision, so the permission
 * rules apply as usual.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import { existsSync } from "node:fs";
import path from "node:path";
import { readHookInput } from "./lib/hook-input.mjs";
import { askBeforeToolCall, denyToolCall, leaveToolCallToPermissionRules } from "./lib/hook-reply.mjs";
import { currentBranch, runGit } from "./lib/git-facts.mjs";
import { commandStartDirectory, foldCase, usesWindowsAlias, withForwardSlashes } from "./lib/project-paths.mjs";
import {
  BASH,
  FIND_ACTIONS_THAT_WRITE,
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
const NOT_SWITCHED = Symbol("no branch switch so far");
const UNKNOWN_DESTINATION = Symbol("a destination computed when the command runs");

const REASONS = {
  noVerify:
    "--no-verify (or git commit -n) skips the commit gate in .githooks/pre-commit, which this repository never allows; fix what the gate reports instead.",
  hooksPath:
    "core.hooksPath must stay .githooks, the commit gate; `just setup` sets it in a new clone, and nothing else changes or overrides it.",
  gitConfigFile:
    "Writing .git/config directly could change core.hooksPath; use git config for other settings.",
  gitConfigOption:
    "git -c and --config-env can define aliases, includes, or push targets that the guard cannot see; confirm the setting.",
  windowsAlias:
    "This writes to .git, .claude, or .githooks under another name Windows accepts (a short name such as GIT~1, or a trailing dot or space), which the other checks would not recognise; confirm the path.",
  forcePush:
    "Force pushes are never used here (docs/masterplan/05-build-process.md section 8); push new commits instead.",
  pushToMain:
    "main changes only through pull requests that the builder merges (docs/masterplan/05-build-process.md section 8); push the step branch with `git push -u origin HEAD` instead.",
  pushEverything:
    "Pushing all branches or mirroring would update main as well; push the step branch with `git push -u origin HEAD` instead.",
  unknownBranch:
    "The guard cannot tell which branch this push would update; confirm that it is not main.",
  deleteBranch: "This push deletes a branch on GitHub; confirm that it is the right one.",
  pushAsks: "Every git push waits for the builder's approval (CLAUDE.md, docs/masterplan/05-build-process.md section 8).",
  commitOnMain:
    "This commit lands on main, but steps work on step/N.M-<slug> branches (docs/masterplan/05-build-process.md section 2); confirm, or switch branches first.",
  commitGate: "This changes the commit gate in .githooks/; confirm the change.",
  guardrails:
    "This writes to Claude Code's own guardrails (.claude/settings.json, .claude/hooks/, or a design skill under .claude/skills/); confirm the change.",
  goldens:
    "This regenerates or overwrites goldens or snapshots, which change only with the builder's approval and a changelog entry (the engine-golden skill).",
  github:
    "Merging pull requests and changing the repository on GitHub are the builder's routine (docs/masterplan/05-build-process.md section 8); confirm first.",
  databento:
    "This mentions Databento, whose downloads cost money: confirm the importer's cost preview first (docs/masterplan/07-tools-and-costs.md section 3).",
  opaque: (what) => `The guard cannot read ${what}; confirm that it does not push, force, or skip hooks.`,
};

const COMMIT_OPTION_LETTERS_WITH_VALUE = new Set(["m", "F", "C", "c", "t", "S", "u"]);
const CONFIG_WRITE_WORDS = new Set(["--unset", "--unset-all", "--add", "--replace-all", "set", "unset"]);
const CONFIG_EDIT_WORDS = new Set(["--edit", "-e", "edit"]);
const CONFIG_SECTION_WORDS = new Set(["--remove-section", "--rename-section", "remove-section", "rename-section"]);
const CONFIG_OPTIONS_WITH_VALUE = new Set(["--default", "--type", "--comment", "--file", "-f", "--blob", "--value"]);
const PUSH_OPTIONS_WITH_VALUE = new Set(["--repo", "--receive-pack", "--exec", "--push-option", "-o"]);
const EVERYTHING_PUSH_OPTIONS = ["--mirror", "--all", "--branches"];
// git reads a destination heads/main as refs/heads/main.
const BRANCH_REF_PREFIX = /^(refs\/)?heads\//;
const WRITING_PROGRAMS = new Set([
  "cp", "mv", "rm", "tee", "touch", "copy", "move", "del", "erase", "xcopy", "robocopy", "ren",
  "rename", "copy-item", "move-item", "remove-item", "rename-item", "new-item", "set-content",
  "add-content", "out-file", "clear-content", "cpi", "mi", "ri", "ni", "sc", "ac", "ln", "install",
  "dd", "rsync", "mklink",
]);
const IN_PLACE_EDITORS = new Set(["sed", "perl"]);
const SNAPSHOT_UPDATE_OPTIONS = ["--snapshot-update", "--update-snapshots", "--update-goldens", "--force-regen"];
const INSTA_SUBCOMMANDS = new Set(["accept", "review", "reject"]);
const INSTA_UPDATE_OPTIONS = ["--accept", "--review", "--force-update-snapshots", "--accept-unseen", "--unreferenced"];
const JAVASCRIPT_RUNNERS = new Set(["pnpm", "npm", "npx", "yarn", "vitest", "bun", "bunx", "playwright"]);
const GOLDEN_ENVIRONMENT =
  /\b(INSTA_UPDATE|INSTA_FORCE_PASS|UPDATE_GOLDENS|UPDATE_SNAPSHOTS)\s*=|\bsetx\s+(INSTA_UPDATE|INSTA_FORCE_PASS|UPDATE_GOLDENS|UPDATE_SNAPSHOTS)\b/i;
const GUARDRAIL_PATH =
  /(^|\/)\.claude(\/skills)?$|(^|\/)\.claude\/(settings(\.local)?\.json$|hooks(\/|$))|(^|\/)\.claude\/skills\/(apple-design|backtest-expert|designing-architecture|software-design-principles)(\/|$)/;
const READING_PROGRAMS = new Set([
  "cat", "head", "tail", "less", "more", "rg", "grep", "ls", "dir", "wc", "diff", "file", "stat", "tree",
  "echo", "type", "get-content", "gc", "get-childitem", "gci", "select-string", "sls", "test-path",
]);
const READING_GIT_SUBCOMMANDS = new Set(["diff", "log", "show", "status", "ls-files", "blame", "grep", "add"]);
const BRANCH_CREATING_OPTIONS = new Set(["-c", "-C", "--create", "--force-create", "-b", "-B", "--orphan"]);
const TRACKING_OPTIONS = new Set(["-t", "--track"]);
const RESTORE_OPTIONS = new Set(["-p", "--patch", "--ours", "--theirs", "--pathspec-from-file"]);
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
  const branches = branchTracker();
  const findings = [];
  for (const command of commandsIn(commandLine, shell, startDirectory)) {
    findings.push(...commandFindings(command));
    for (const git of gitInvocationsIn(command)) {
      findings.push(...gitFindings(git, branches.branchAt));
      branches.follow(git);
    }
  }
  return findings;
}

/**
 * The branch each git call works on: what git reports before the command
 * runs, until a `git switch` or `git checkout` earlier in the same command
 * line changes it (unknown when the target cannot be read).
 */
function branchTracker() {
  const known = new Map();
  let switchedTo = NOT_SWITCHED;
  return {
    branchAt(directory) {
      if (switchedTo !== NOT_SWITCHED) {
        return switchedTo;
      }
      if (directory === null) {
        return null;
      }
      const key = foldCase(directory);
      if (!known.has(key)) {
        known.set(key, currentBranch(directory));
      }
      return known.get(key);
    },
    follow(git) {
      if (git.subcommand !== "switch" && git.subcommand !== "checkout") {
        return;
      }
      const target = switchTarget(git);
      if (target !== NOT_SWITCHED) {
        switchedTo = target;
      }
    },
  };
}

function switchTarget(git) {
  if (git.subcommand === "checkout" && restoresFiles(git)) {
    return NOT_SWITCHED;
  }
  for (let index = 0; index < git.args.length; index += 1) {
    const arg = git.args[index];
    if (BRANCH_CREATING_OPTIONS.has(arg)) {
      return git.args[index + 1] ?? null;
    }
    if (TRACKING_OPTIONS.has(arg)) {
      const upstream = git.args[index + 1];
      return upstream === undefined ? null : upstream.replace(/^[^/]+\//, "");
    }
    if (arg === "--detach" || arg === "-d") {
      return "HEAD";
    }
    if (arg === "-") {
      return null;
    }
    if (!arg.startsWith("-")) {
      return arg;
    }
  }
  return NOT_SWITCHED;
}

/** `git checkout [<tree-ish>] [--] <paths>` and `git checkout <path>` restore files and stay on the branch. */
function restoresFiles(git) {
  if (git.args.some((arg) => arg === "--" || RESTORE_OPTIONS.has(arg.split("=")[0]))) {
    return true;
  }
  if (git.args.some((arg) => BRANCH_CREATING_OPTIONS.has(arg) || TRACKING_OPTIONS.has(arg))) {
    return false;
  }
  const positionals = git.args.filter((arg) => !arg.startsWith("-"));
  return positionals.length > 1 || (positionals.length === 1 && namesFile(positionals[0], git.directory));
}

/** A path on disk or in git's index: what git checkout takes a lone argument for when it is one. */
function namesFile(word, directory) {
  if (directory === null) {
    return false;
  }
  return existsSync(path.resolve(directory, word)) || runGit(["ls-files", "--error-unmatch", "--", word], directory) !== null;
}

function commandFindings(command) {
  const findings = [];
  if (command.opaque !== null) {
    findings.push(ask(REASONS.opaque(command.opaque)));
  }
  if (setsHooksPathThroughEnvironment(command.words)) {
    findings.push(deny(REASONS.hooksPath));
  }
  const { named, edited } = writtenPaths(command);
  const written = [...named, ...edited];
  if (written.some((target) => /(^|\/)\.git\/config$/.test(target))) {
    findings.push(deny(REASONS.gitConfigFile));
  }
  if (written.some((target) => /(^|\/)\.githooks(\/|$)/.test(target))) {
    findings.push(ask(REASONS.commitGate));
  }
  if (written.some((target) => GUARDRAIL_PATH.test(target))) {
    findings.push(ask(REASONS.guardrails));
  }
  // A sed or perl script is no path, so only the targets a command names can be Windows aliases.
  if (named.some(usesWindowsAlias)) {
    findings.push(ask(REASONS.windowsAlias));
  }
  const touchesGoldens = written.some(isGoldenPath) || mentionsGoldensOutsideReading(command.words);
  if (touchesGoldens || regeneratesGoldens(command.words) || GOLDEN_ENVIRONMENT.test(command.text)) {
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

/**
 * The paths a command writes: the ones it names (redirections, the arguments of
 * cp, rm, git rm, and the like), and every argument of an in-place editor
 * (sed -i, perl -i), whose script cannot be told apart from its files.
 */
function writtenPaths(command) {
  const index = programIndex(command.words);
  const program = index < command.words.length ? programName(command.words[index]) : "";
  const args = command.words.slice(index + 1);
  const named = [...command.outputTargets];
  if (WRITING_PROGRAMS.has(program)) {
    named.push(...args);
  }
  for (const git of gitInvocationsIn(command)) {
    if (git.subcommand === "rm" || git.subcommand === "mv") {
      named.push(...git.args);
    }
  }
  const editsInPlace =
    IN_PLACE_EDITORS.has(program) && args.some((arg) => /^-[A-Za-z]*i/.test(arg) || arg.startsWith("--in-place"));
  return { named: normalizedPaths(named), edited: editsInPlace ? normalizedPaths(args) : [] };
}

function normalizedPaths(targets) {
  return targets
    .filter((target) => !isDiscardedOutput(target))
    .map((target) => path.posix.normalize(withForwardSlashes(target).toLowerCase().replace(/^of=/, "")));
}

/** A program other than a reader that names a path under fixtures/goldens/, such as a generator's output folder. */
function mentionsGoldensOutsideReading(words) {
  const index = programIndex(words);
  if (index >= words.length || readsOnly(programName(words[index]), words.slice(index + 1))) {
    return false;
  }
  return words.slice(index + 1).some((word) => withForwardSlashes(word).toLowerCase().includes("fixtures/goldens"));
}

function readsOnly(program, args) {
  if (program === "git") {
    return READING_GIT_SUBCOMMANDS.has(args.find((arg) => !arg.startsWith("-")));
  }
  if (program === "find") {
    return !args.some((arg) => FIND_ACTIONS_THAT_WRITE.includes(arg));
  }
  return READING_PROGRAMS.has(program);
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
    const instaArgs = args.slice(1);
    const updatesByOption = instaArgs.some((arg) =>
      INSTA_UPDATE_OPTIONS.some((option) => arg === option || arg.startsWith(`${option}=`)),
    );
    return INSTA_SUBCOMMANDS.has(instaArgs[0]) || updatesByOption;
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
  const [area, action] = ghSubcommand(words.slice(index + 1));
  if (area === "pr" && action === "merge") {
    return true;
  }
  if (area === "repo" && ["edit", "delete", "rename", "archive"].includes(action)) {
    return true;
  }
  return area === "api" && apiWrites(words.slice(index + 2));
}

function ghSubcommand(args) {
  const positionals = [];
  for (let index = 0; index < args.length && positionals.length < 2; index += 1) {
    if (args[index] === "-R" || args[index] === "--repo" || args[index] === "--hostname") {
      index += 1;
    } else if (!args[index].startsWith("-")) {
      positionals.push(args[index]);
    }
  }
  return positionals;
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
  } else if (git.configs.length > 0) {
    findings.push(ask(REASONS.gitConfigOption));
  }
  if (!READING_GIT_SUBCOMMANDS.has(git.subcommand) && git.args.some(isNoVerifyOption)) {
    findings.push(deny(REASONS.noVerify));
  }
  if (git.subcommand === "commit") {
    findings.push(...commitFindings(git, branchAt));
  }
  if (git.subcommand === "config" && configWritesHooksPath(git.args)) {
    findings.push(deny(REASONS.hooksPath));
  }
  if (git.subcommand === "config" && git.args.some((arg) => CONFIG_EDIT_WORDS.has(arg))) {
    findings.push(deny(REASONS.gitConfigFile));
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
      const branch = refspec.replace(/^\+/, "").replace(BRANCH_REF_PREFIX, "");
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
    } else if (destination === UNKNOWN_DESTINATION) {
      findings.push(ask(REASONS.unknownBranch));
    } else if (isMain(destination)) {
      findings.push(deny(REASONS.pushToMain));
    }
  }
  return findings.some((finding) => finding.decision === "deny") ? findings : [...findings, ask(REASONS.pushAsks)];
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
  } else if (EVERYTHING_PUSH_OPTIONS.some((option) => abbreviates(name, option))) {
    push.everything = true;
  } else if (abbreviates(name, "--delete")) {
    push.deletes = true;
  } else if (abbreviates(name, "--tags")) {
    push.tags = true;
  }
}

/** git takes any unique start of a long option (--mirr for --mirror); one it finds ambiguous fails anyway. */
function abbreviates(name, option) {
  return name.length >= "--x".length && option.startsWith(name);
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
  if (/[$`%]/.test(refspec)) {
    return UNKNOWN_DESTINATION;
  }
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
  return destination.replace(BRANCH_REF_PREFIX, "");
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
  reply(findingsFor(commandLine, shell, commandStartDirectory(reading.input)));
}

main().catch((error) => {
  askBeforeToolCall(`The shell guard failed (${error.message}); check this command by hand.`);
});
