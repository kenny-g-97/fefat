#!/usr/bin/env node
/**
 * PostToolUse hook for Edit and Write (.claude/settings.json): formats the
 * file Claude just changed, the way `just check` expects it.
 *
 *   .rs        rustfmt, with the edition from engine/Cargo.toml
 *   .py .pyi   ruff format, from the project's .venv (or through uv run)
 *   web/       prettier, once web/node_modules/prettier exists; the Phase 4
 *              kickoff chooses between prettier and oxfmt, and until then web
 *              files are left as they are
 *
 * Markdown, TOML, YAML, and everything under .claude/skills/ (the design
 * skills stay verbatim) are never touched. It never blocks and never fails a
 * tool call: problems reach Claude as one line of context, and it always
 * exits 0. When the formatter changed the file, Claude is told to read it
 * again, because Claude Code refuses to edit a file that changed since it was
 * last read.
 *
 * Its cases are in scripts/test_hooks.py.
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { readHookInput } from "./lib/hook-input.mjs";
import { addContextAfterToolCall } from "./lib/hook-reply.mjs";
import { describeFilePath, projectDirectory } from "./lib/project-paths.mjs";

const FORMAT_TIMEOUT_MS = 15000;
const LARGEST_FORMATTED_FILE_BYTES = 2 * 1024 * 1024;
const SKIPPED_FOLDERS = new Set(["node_modules", ".venv", "target", "dist", ".git"]);
const WEB_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".css", ".html"]);
const RUST_EDITION = /^\s*edition\s*=\s*"(\d{4})"/m;

function formatterFor(file, project) {
  if (file.inProjectFolded === null || file.inProjectFolded.startsWith(".claude/skills/")) {
    return null;
  }
  if (file.inProjectFolded.split("/").some((folder) => SKIPPED_FOLDERS.has(folder))) {
    return null;
  }
  const extension = path.posix.extname(file.nameFolded);
  if (extension === ".rs") {
    return rustFormatter(file, project);
  }
  if (extension === ".py" || extension === ".pyi") {
    return pythonFormatter(file, project);
  }
  if (file.inProjectFolded.startsWith("web/") && WEB_EXTENSIONS.has(extension)) {
    return webFormatter(file, project);
  }
  return null;
}

function rustFormatter(file, project) {
  const edition = rustEdition(project);
  if (edition === null) {
    return { problem: "the Rust edition could not be read from engine/Cargo.toml, so the file was not formatted" };
  }
  return { name: "rustfmt", program: "rustfmt", args: ["--edition", edition, "--quiet", file.absolute], directory: project };
}

function rustEdition(project) {
  try {
    const match = RUST_EDITION.exec(fs.readFileSync(`${project}/engine/Cargo.toml`, "utf8"));
    return match === null ? null : match[1];
  } catch {
    return null;
  }
}

function pythonFormatter(file, project) {
  const ruff = process.platform === "win32" ? `${project}/.venv/Scripts/ruff.exe` : `${project}/.venv/bin/ruff`;
  if (fs.existsSync(ruff)) {
    return { name: "ruff format", program: ruff, args: ["format", "--quiet", file.absolute], directory: project };
  }
  return {
    name: "ruff format",
    program: "uv",
    args: ["run", "--no-sync", "ruff", "format", "--quiet", file.absolute],
    directory: project,
  };
}

function webFormatter(file, project) {
  const prettier = `${project}/web/node_modules/prettier/bin/prettier.cjs`;
  if (!fs.existsSync(prettier)) {
    return null;
  }
  return {
    name: "prettier",
    program: process.execPath,
    args: [prettier, "--write", "--log-level", "warn", file.absolute],
    directory: `${project}/web`,
  };
}

function contentsIfSmall(absolute) {
  try {
    const stats = fs.statSync(absolute);
    return stats.isFile() && stats.size <= LARGEST_FORMATTED_FILE_BYTES ? fs.readFileSync(absolute) : null;
  } catch {
    return null;
  }
}

function firstLine(text) {
  return text.trim().split("\n")[0].trim();
}

function format(file, formatter) {
  const before = contentsIfSmall(file.absolute);
  if (before === null) {
    return;
  }
  const result = spawnSync(formatter.program, formatter.args, {
    cwd: formatter.directory,
    encoding: "utf8",
    timeout: FORMAT_TIMEOUT_MS,
    windowsHide: true,
  });
  if (result.error !== undefined || result.status !== 0) {
    const detail = result.error === undefined ? firstLine(`${result.stderr}\n${result.stdout}`) : result.error.message;
    addContextAfterToolCall(`format-on-edit: ${formatter.name} could not format ${file.inProject}: ${detail}`);
    return;
  }
  const after = contentsIfSmall(file.absolute);
  if (after !== null && !after.equals(before)) {
    addContextAfterToolCall(`format-on-edit: ${formatter.name} reformatted ${file.inProject}; read it again before the next edit.`);
  }
}

async function main() {
  process.exitCode = 0;
  const reading = await readHookInput();
  const rawPath = reading.ok ? reading.input.tool_input?.file_path : undefined;
  if (typeof rawPath !== "string" || rawPath === "") {
    return;
  }
  const project = projectDirectory(reading.input);
  const file = describeFilePath(rawPath, reading.input, project);
  const formatter = formatterFor(file, project);
  if (formatter === null) {
    return;
  }
  if (formatter.problem !== undefined) {
    addContextAfterToolCall(`format-on-edit: ${file.inProject}: ${formatter.problem}`);
    return;
  }
  format(file, formatter);
}

main().catch(() => {
  process.exitCode = 0;
});
