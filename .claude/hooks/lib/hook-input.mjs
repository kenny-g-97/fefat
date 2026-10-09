/**
 * Reads the JSON object Claude Code writes to a hook's standard input.
 *
 * It never throws: it resolves to { ok: true, input } or { ok: false, reason },
 * and each hook decides what an unreadable input means for it (the guards
 * ask, the formatter and the session brief carry on).
 */
import process from "node:process";

const DEFAULT_TIMEOUT_MS = 3000;

/**
 * @param {{ timeoutMs?: number }} [options]
 * @returns {Promise<{ ok: true, input: Record<string, unknown> } | { ok: false, reason: string }>}
 */
export async function readHookInput({ timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  if (process.stdin.isTTY) {
    return { ok: false, reason: "expected JSON on standard input, got a terminal" };
  }
  const text = await readStream(process.stdin, timeoutMs);
  if (text.trim() === "") {
    return { ok: false, reason: "expected JSON on standard input, got nothing" };
  }
  try {
    const input = JSON.parse(text);
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
      return { ok: false, reason: `expected a JSON object on standard input, got ${typeof input}` };
    }
    return { ok: true, input };
  } catch (error) {
    return { ok: false, reason: `expected JSON on standard input, got text that does not parse (${error.message})` };
  }
}

async function readStream(stream, timeoutMs) {
  stream.setEncoding("utf8");
  let text = "";
  const timer = setTimeout(() => stream.destroy(), timeoutMs);
  try {
    for await (const chunk of stream) {
      text += chunk;
    }
  } catch {
    return text;
  } finally {
    clearTimeout(timer);
  }
  return text;
}
