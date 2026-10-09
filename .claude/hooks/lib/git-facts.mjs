/**
 * What the hooks ask git: the current branch, how far a branch is from
 * origin/main, and the working tree. git is run directly (git.exe on
 * Windows), never through a shell.
 */
import { spawnSync } from "node:child_process";

const GIT_TIMEOUT_MS = 5000;

/** git's standard output, or null when git fails (no repository, no such ref, no such folder). */
export function runGit(args, directory) {
  const result = spawnSync("git", args, {
    cwd: directory,
    encoding: "utf8",
    timeout: GIT_TIMEOUT_MS,
    windowsHide: true,
  });
  if (result.error !== undefined || result.status !== 0) {
    return null;
  }
  return result.stdout;
}

/** The checked-out branch ("HEAD" when detached), or null when it cannot be read. */
export function currentBranch(directory) {
  if (directory === null) {
    return null;
  }
  const output = runGit(["rev-parse", "--abbrev-ref", "HEAD"], directory);
  return output === null ? null : output.trim();
}
