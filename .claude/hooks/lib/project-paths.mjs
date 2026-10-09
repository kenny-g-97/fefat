/**
 * Paths the way the hooks compare them: forward slashes everywhere, Windows
 * drive paths treated as absolute on every system, and case folded on the
 * systems whose file systems ignore case (Windows, macOS). Claude Code sends
 * Windows paths with backslashes, and the same folder can arrive as c:\... or
 * C:\..., so every comparison goes through these functions.
 */
import os from "node:os";
import path from "node:path";
import process from "node:process";

const WINDOWS_DRIVE_PATH = /^[a-zA-Z]:\//;
const GIT_BASH_DRIVE_PATH = /^\/([a-zA-Z])\//;
const LONG_PATH_PREFIX = /^\/\/\?\//;
const CASE_INSENSITIVE_PLATFORMS = new Set(["win32", "darwin"]);

export function withForwardSlashes(text) {
  return text.replaceAll("\\", "/").replace(LONG_PATH_PREFIX, "");
}

export function isAbsolutePath(text) {
  const normalized = withForwardSlashes(text);
  return normalized.startsWith("/") || WINDOWS_DRIVE_PATH.test(normalized) || normalized.startsWith("~");
}

/**
 * The absolute, normalized form of a path; relative paths are resolved against
 * baseDirectory (itself absolute).
 */
export function absolutePath(text, baseDirectory) {
  let normalized = withForwardSlashes(text);
  if (process.platform === "win32") {
    normalized = normalized.replace(GIT_BASH_DRIVE_PATH, "$1:/");
  }
  if (normalized === "~" || normalized.startsWith("~/")) {
    normalized = `${withForwardSlashes(os.homedir())}${normalized.slice(1)}`;
  }
  const joined = isAbsolutePath(normalized) ? normalized : `${baseDirectory}/${normalized}`;
  const resolved = path.posix.normalize(joined);
  return resolved.length > 1 && resolved.endsWith("/") ? resolved.slice(0, -1) : resolved;
}

export function foldCase(text) {
  return CASE_INSENSITIVE_PLATFORMS.has(process.platform) ? text.toLowerCase() : text;
}

/** The project root: CLAUDE_PROJECT_DIR as Claude Code sets it, else the input's cwd. */
export function projectDirectory(input) {
  const fromEnvironment = process.env.CLAUDE_PROJECT_DIR;
  if (typeof fromEnvironment === "string" && fromEnvironment !== "") {
    return absolutePath(fromEnvironment, fromEnvironment);
  }
  if (typeof input.cwd === "string" && input.cwd !== "") {
    return absolutePath(input.cwd, input.cwd);
  }
  throw new Error("expected CLAUDE_PROJECT_DIR or the input's cwd, got neither");
}

/** The path relative to the project root, or null when it lies outside the project. */
export function pathInProject(absolute, project) {
  const folded = foldCase(absolute);
  const foldedProject = foldCase(project);
  if (folded === foldedProject) {
    return "";
  }
  if (!folded.startsWith(`${foldedProject}/`)) {
    return null;
  }
  return absolute.slice(project.length + 1);
}

/**
 * Everything the guards need to know about a file path from a tool input.
 *
 * @returns {{ absolute: string, inProject: string | null, inProjectFolded: string | null, nameFolded: string }}
 */
export function describeFilePath(rawPath, input, project) {
  const base = typeof input.cwd === "string" && input.cwd !== "" ? absolutePath(input.cwd, project) : project;
  const absolute = absolutePath(rawPath, base);
  const inProject = pathInProject(absolute, project);
  return {
    absolute,
    inProject,
    inProjectFolded: inProject === null ? null : foldCase(inProject),
    nameFolded: absolute.slice(absolute.lastIndexOf("/") + 1).toLowerCase(),
  };
}
