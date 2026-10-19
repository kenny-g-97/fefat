#!/usr/bin/env node
/**
 * PreToolUse guard for Edit, Write, and NotebookEdit (.claude/settings.json).
 *
 * Denies edits of .env files, private keys and certificates, git internals
 * (.git/), and market-data files anywhere outside fixtures/synthetic/
 * (licensed data lives under FEFAT_DATA_DIR, never in the repository: D-21,
 * docs/masterplan/05-build-process.md section 5). Asks before goldens and
 * snapshots change (they change only with the builder's approval: the
 * engine-golden skill). Everything else gets no decision, so the permission
 * rules apply as usual. Paths are compared with forward slashes and, on
 * Windows, without regard to case.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import { readHookInput } from "./lib/hook-input.mjs";
import { askBeforeToolCall, denyToolCall, leaveToolCallToPermissionRules } from "./lib/hook-reply.mjs";
import { describeFilePath, projectDirectory, usesWindowsAlias } from "./lib/project-paths.mjs";

const SYNTHETIC_FIXTURES = "fixtures/synthetic/";
const GOLDENS = "fixtures/goldens/";
const MARKET_DATA_SUFFIXES = [
  ".dbn.zst", ".csv.gz", ".duckdb.wal", ".dbn", ".zst", ".parquet", ".arrow", ".arrows", ".feather",
  ".ipc", ".zip", ".h5", ".hdf5", ".duckdb", ".sqlite", ".sqlite3", ".db", ".csv", ".tsv", ".jsonl",
  ".ndjson", ".xls", ".xlsx", ".gz", ".tar", ".7z", ".xz", ".bz2", ".lz4", ".ncd", ".scid",
];
const KEY_SUFFIXES = [".pem", ".key", ".pfx", ".p12"];
const SSH_PRIVATE_KEY = /^id_(rsa|dsa|ecdsa|ed25519)(_sk)?$/;
const SNAPSHOT_SUFFIXES = [".snap", ".snap.new", ".pending-snap"];
const SNAPSHOT_CONFIG_FILE =
  /(^|\/)(\.cargo\/config(\.toml)?|insta\.yaml|pyproject\.toml|pytest\.ini|setup\.cfg|tox\.ini|package\.json|justfile|vitest\.config\.[cm]?[jt]s|playwright\.config\.[cm]?[jt]s)$|(^|\/)\.github\/workflows\//;
const SNAPSHOT_UPDATE_SETTING =
  /\b(INSTA_UPDATE|INSTA_FORCE_PASS|UPDATE_GOLDENS|UPDATE_SNAPSHOTS)\b|--snapshot-update|--update-snapshots|--force-update-snapshots|^\s*update\s*:\s*(always|unseen|new)\b/im;

const RULES = [
  {
    applies: (file) => file.nameFolded === ".env.example",
    decision: null,
  },
  {
    // The names scripts/guard_data.py refuses: .env*, such as .envrc, and *.env, such as prod.env.
    applies: (file) => file.nameFolded.startsWith(".env") || file.nameFolded.endsWith(".env"),
    decision: "deny",
    reason: (file) =>
      `${file.absolute} is an .env file. Secrets never go into files here: keys live in the operating system's credential store (CLAUDE.md, Never).`,
  },
  {
    applies: (file) => KEY_SUFFIXES.some((suffix) => file.nameFolded.endsWith(suffix)) || SSH_PRIVATE_KEY.test(file.nameFolded),
    decision: "deny",
    reason: (file) =>
      `${file.absolute} looks like a private key or certificate. Keys live in the operating system's credential store, never in files Claude Code writes (CLAUDE.md, Never).`,
  },
  {
    // Any .git folder on the path, so a short-named parent (DOCUME~1) cannot hide the project's own.
    applies: (file) => file.absolute.toLowerCase().split("/").includes(".git"),
    decision: "deny",
    reason: (file) =>
      `${file.absolute} is inside a .git folder. Git's own files change only through git commands, so core.hooksPath and the commit gate cannot be bypassed.`,
  },
  {
    applies: (file) => marketDataSuffix(file) !== null && !isSyntheticFixture(file),
    decision: "deny",
    reason: (file) =>
      `${file.absolute} has the market-data extension ${marketDataSuffix(file)}. Licensed market data lives outside the repository under FEFAT_DATA_DIR, and only generated fixtures under fixtures/synthetic/ are data files in git (docs/masterplan/05-build-process.md section 5).`,
  },
  {
    applies: (file) => usesWindowsAlias(file.absolute),
    decision: "ask",
    reason: (file) =>
      `${file.absolute} names .git, .claude, or .githooks under another name Windows accepts (a short name such as GIT~1, or a trailing dot or space), which the other checks would not recognise; check the path.`,
  },
  {
    applies: (file, toolInput) =>
      file.inProjectFolded !== null &&
      SNAPSHOT_CONFIG_FILE.test(file.inProjectFolded) &&
      SNAPSHOT_UPDATE_SETTING.test(newText(toolInput)),
    decision: "ask",
    reason: (file) =>
      `${file.inProject} would make goldens or snapshots update by themselves (INSTA_UPDATE, --snapshot-update, or the like). Goldens change only with the builder's approval and a changelog entry (the engine-golden skill).`,
  },
  {
    applies: isGoldenFile,
    decision: "ask",
    reason: (file) =>
      `${file.inProject} is a golden or snapshot file. Goldens change only with the builder's approval, a fill-model version bump where fills change, and a changelog entry (the engine-golden skill).`,
  },
];

function newText(toolInput) {
  return ["content", "new_string", "new_source"]
    .map((field) => toolInput[field])
    .filter((value) => typeof value === "string")
    .join("\n");
}

function marketDataSuffix(file) {
  return MARKET_DATA_SUFFIXES.find((suffix) => file.nameFolded.endsWith(suffix)) ?? null;
}

function isSyntheticFixture(file) {
  return file.inProjectFolded !== null && file.inProjectFolded.startsWith(SYNTHETIC_FIXTURES);
}

function isGoldenFile(file) {
  if (file.inProjectFolded === null) {
    return false;
  }
  const inGoldens = file.inProjectFolded.startsWith(GOLDENS) && !file.inProjectFolded.endsWith(".md");
  const isSnapshot = SNAPSHOT_SUFFIXES.some((suffix) => file.nameFolded.endsWith(suffix));
  return inGoldens || isSnapshot || file.inProjectFolded.split("/").includes("__snapshots__");
}

function filePathOf(toolInput) {
  if (toolInput === null || typeof toolInput !== "object") {
    return null;
  }
  if (typeof toolInput.file_path === "string" && toolInput.file_path !== "") {
    return toolInput.file_path;
  }
  if (typeof toolInput.notebook_path === "string" && toolInput.notebook_path !== "") {
    return toolInput.notebook_path;
  }
  return null;
}

async function main() {
  const reading = await readHookInput();
  if (!reading.ok) {
    askBeforeToolCall(`The file guard could not read its input (${reading.reason}); check this edit by hand.`);
    return;
  }
  const rawPath = filePathOf(reading.input.tool_input);
  if (rawPath === null) {
    leaveToolCallToPermissionRules();
    return;
  }
  const file = describeFilePath(rawPath, reading.input, projectDirectory(reading.input));
  const rule = RULES.find((candidate) => candidate.applies(file, reading.input.tool_input));
  if (rule === undefined || rule.decision === null) {
    leaveToolCallToPermissionRules();
  } else if (rule.decision === "deny") {
    denyToolCall(rule.reason(file));
  } else {
    askBeforeToolCall(rule.reason(file));
  }
}

main().catch((error) => {
  askBeforeToolCall(`The file guard failed (${error.message}); check this edit by hand.`);
});
