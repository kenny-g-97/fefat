/**
 * The answers a hook gives Claude Code on standard output.
 *
 * A PreToolUse guard that has nothing against a call prints nothing ("no
 * decision"), and the permission rules in .claude/settings.json then apply as
 * usual. The guards never answer "allow": an "allow" from a hook approves the
 * call without the usual permission check, and a guard only knows what is
 * forbidden, not what is safe.
 */
import process from "node:process";

/** Stops the tool call; Claude sees the reason. */
export function denyToolCall(reason) {
  writePreToolUseDecision("deny", reason);
}

/** Shows the builder a permission prompt with the reason before the call runs. */
export function askBeforeToolCall(reason) {
  writePreToolUseDecision("ask", reason);
}

/** No decision: the permission rules decide, as if the guard were not there. */
export function leaveToolCallToPermissionRules() {
  process.exitCode = 0;
}

/** After a tool call: adds a line of context for Claude (PostToolUse cannot block). */
export function addContextAfterToolCall(text) {
  writeJsonLine({ hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: text } });
}

function writePreToolUseDecision(permissionDecision, reason) {
  writeJsonLine({
    hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision, permissionDecisionReason: reason },
  });
}

function writeJsonLine(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
  process.exitCode = 0;
}
