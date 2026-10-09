/**
 * A small reader for the commands Claude Code runs through its Bash and
 * PowerShell tools. It knows enough of both languages to find every command a
 * tool call would run, its words, where its output goes, and which folder it
 * runs in; the guards judge the result.
 *
 * It is a guard's reader, not a shell. It follows `&&`, `||`, `;`, pipes,
 * subshells, `$(...)`, `bash -c`, `powershell -Command`, `cmd /c`,
 * `Invoke-Expression`, heredocs, and `cd`. Where it cannot follow a command
 * (an encoded PowerShell command, a command held in a variable), it marks the
 * command as opaque so a guard can ask instead of guessing.
 */
import os from "node:os";
import { absolutePath, isAbsolutePath, withForwardSlashes } from "./project-paths.mjs";

export const BASH = "bash";
export const POWERSHELL = "powershell";

const MAX_NESTING = 3;
const BASH_PROGRAMS = new Set(["bash", "sh", "zsh", "dash", "ksh"]);
const POWERSHELL_PROGRAMS = new Set(["powershell", "pwsh"]);
const CMD_PROGRAMS = new Set(["cmd"]);
const EXPRESSION_PROGRAMS = new Set(["invoke-expression", "iex"]);
const DIRECTORY_PROGRAMS = new Set(["cd", "chdir", "pushd", "set-location", "sl"]);
const UNKNOWN_DIRECTORY_PROGRAMS = new Set(["popd", "pop-location"]);
const COMMAND_PREFIXES = new Set(["sudo", "env", "command", "exec", "time", "nohup", "&", "."]);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const HEREDOC_START = /(?<!<)<<(?!<)(-?)\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\2/;
const HERE_STRING_START = /@(['"])\s*$/;
const SHELL_NAME = /\b(bash|sh|zsh|dash|ksh|pwsh|powershell)(\.exe)?\b/i;
const FILE_DESCRIPTOR_PREFIX = /^(\d+|&|\*)$/;
const POWERSHELL_COMMAND_PARAMETER = /^-c(o(m(m(a(n(d)?)?)?)?)?)?$/;
const POWERSHELL_PARAMETERS_WITH_VALUE = new Set([
  "-executionpolicy", "-ex", "-ep", "-windowstyle", "-w", "-version", "-v", "-workingdirectory",
  "-wd", "-inputformat", "-if", "-inf", "-outputformat", "-of", "-o", "-configurationname",
  "-settingsfile", "-psconsolefile", "-custompipename",
]);
const GIT_GLOBAL_OPTIONS_WITH_VALUE = new Set([
  "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path", "--list-cmds",
  "--attr-source",
]);
const DISCARDED_OUTPUTS = new Set(["/dev/null", "$null", "nul", "nul:"]);

/**
 * Every command a tool call would run, in order, nested ones included.
 *
 * @param {string} commandLine the tool input's `command`
 * @param {"bash" | "powershell"} shell the language of the tool that runs it
 * @param {string | null} startDirectory the folder the command starts in, absolute
 * @returns {Array<{ words: string[], outputTargets: string[], directory: string | null, text: string, opaque: string | null }>}
 */
export function commandsIn(commandLine, shell, startDirectory) {
  const commands = [];
  collectCommands(commandLine, shell, startDirectory, 0, commands);
  return commands;
}

/**
 * The git calls inside one command: `git [global options] <subcommand> <args>`,
 * with the folder each runs in (after `git -C`).
 */
export function gitInvocationsIn(command) {
  const invocations = [];
  command.words.forEach((word, index) => {
    if (programName(word) !== "git") {
      return;
    }
    const invocation = parseGitInvocation(command.words.slice(index + 1), command.directory);
    if (invocation !== null) {
      invocations.push(invocation);
    }
  });
  return invocations;
}

/** `git` arguments split into global options, the subcommand, and its arguments. */
export function parseGitInvocation(args, directory) {
  const configs = [];
  let workingDirectory = directory;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "-C") {
      workingDirectory = resolvedDirectory(args[index + 1], workingDirectory);
      index += 1;
    } else if (arg === "-c" || arg === "--config-env") {
      configs.push(args[index + 1] ?? "");
      index += 1;
    } else if (arg.startsWith("--config-env=")) {
      configs.push(arg.slice("--config-env=".length));
    } else if (GIT_GLOBAL_OPTIONS_WITH_VALUE.has(arg)) {
      index += 1;
    } else if (!arg.startsWith("-")) {
      return { subcommand: arg, args: args.slice(index + 1), configs, directory: workingDirectory };
    }
  }
  return null;
}

/** The index of the word that names the program, after `VAR=value` and `sudo`, `env`, `&`, ... */
export function programIndex(words) {
  let index = 0;
  while (index < words.length && (ASSIGNMENT.test(words[index]) || COMMAND_PREFIXES.has(words[index].toLowerCase()))) {
    index += 1;
  }
  return index;
}

/** A program's bare name: lower case, without its folder or `.exe` (C:\Git\cmd\git.exe -> git). */
export function programName(word) {
  const normalized = withForwardSlashes(word).toLowerCase();
  const name = normalized.slice(normalized.lastIndexOf("/") + 1);
  return name.endsWith(".exe") ? name.slice(0, -".exe".length) : name;
}

/** True for redirection targets that write nothing: /dev/null, $null, NUL. */
export function isDiscardedOutput(target) {
  return DISCARDED_OUTPUTS.has(withForwardSlashes(target).toLowerCase());
}

function collectCommands(text, shell, startDirectory, depth, commands) {
  let directory = startDirectory;
  for (const segment of segmentsOf(text, shell)) {
    const tokens = tokenize(segment, shell);
    const { words, outputTargets } = separateRedirections(tokens);
    if (words.length === 0) {
      continue;
    }
    const nested = nestedCommand(words);
    const tooDeep = nested !== null && depth >= MAX_NESTING;
    const opaque = tooDeep ? "a command nested too deeply" : nested?.kind === "opaque" ? nested.reason : null;
    commands.push({ words, outputTargets, directory, text: segment, opaque });
    if (nested?.kind === "command" && !tooDeep) {
      collectCommands(nested.text, nested.shell, directory, depth + 1, commands);
    }
    if (depth < MAX_NESTING) {
      for (const substitution of substitutionsIn(tokens, shell)) {
        collectCommands(substitution, shell, directory, depth + 1, commands);
      }
    }
    directory = directoryAfter(words, directory);
  }
}

function segmentsOf(text, shell) {
  const withoutDocuments = withoutHereDocuments(text.replaceAll("\r\n", "\n"), shell);
  return splitSegments(joinContinuations(withoutDocuments, shell), shell);
}

function withoutHereDocuments(text, shell) {
  const kept = [];
  let document = null;
  for (const line of text.split("\n")) {
    if (document === null) {
      const started = hereDocumentStartedBy(line, shell);
      kept.push(started === null ? line : started.openingLine);
      document = started;
      continue;
    }
    const remainder = document.remainderAfterEnd(line);
    if (remainder !== null) {
      kept.push(remainder);
      document = null;
    } else if (document.keepBody) {
      kept.push(line);
    }
  }
  return kept.join("\n");
}

function hereDocumentStartedBy(line, shell) {
  const keepBody = SHELL_NAME.test(line);
  if (shell === BASH) {
    const match = HEREDOC_START.exec(line);
    if (match === null) {
      return null;
    }
    const indented = match[1] === "-";
    const word = match[3];
    return {
      openingLine: line,
      keepBody,
      remainderAfterEnd: (candidate) => ((indented ? candidate.replace(/^\t+/, "") : candidate) === word ? "" : null),
    };
  }
  const match = HERE_STRING_START.exec(line);
  if (match === null) {
    return null;
  }
  const closing = `${match[1]}@`;
  return {
    openingLine: line.slice(0, match.index),
    keepBody,
    remainderAfterEnd: (candidate) => (candidate.startsWith(closing) ? candidate.slice(closing.length) : null),
  };
}

function joinContinuations(text, shell) {
  return shell === POWERSHELL ? text.replaceAll("`\n", " ") : text.replaceAll("\\\n", " ");
}

function splitSegments(text, shell) {
  const segments = [];
  let current = "";
  let quote = null;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quote !== null) {
      current += char;
      if (char === quote) {
        quote = null;
      } else if (quote === '"' && isEscape(char, shell) && next !== undefined) {
        current += next;
        index += 1;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      current += char;
      continue;
    }
    if (isEscape(char, shell) && next !== undefined) {
      current += char + next;
      index += 1;
      continue;
    }
    const length = separatorLength(text, index, shell);
    if (length > 0) {
      segments.push(current);
      current = "";
      index += length - 1;
      continue;
    }
    current += char;
  }
  segments.push(current);
  return segments.map((segment) => segment.trim()).filter((segment) => segment !== "");
}

function isEscape(char, shell) {
  return char === (shell === POWERSHELL ? "`" : "\\");
}

function separatorLength(text, index, shell) {
  const char = text[index];
  const next = text[index + 1];
  if (char === "\n" || char === ";" || char === "(" || char === ")") {
    return 1;
  }
  if (char === "`" && shell === BASH) {
    return 1;
  }
  if ((char === "&" && next === "&") || (char === "|" && next === "|")) {
    return 2;
  }
  if (char === "|") {
    return next === "&" ? 2 : 1;
  }
  if (char === "&") {
    const partOfRedirection = text[index - 1] === ">" || text[index - 1] === "<" || next === ">";
    return partOfRedirection ? 0 : 1;
  }
  return 0;
}

function tokenize(segment, shell) {
  const tokens = [];
  let token = null;
  let quote = null;
  const finish = () => {
    if (token !== null) {
      tokens.push(token);
    }
    token = null;
  };
  const extend = (text, quoteKind = null) => {
    token ??= { text: "", quoted: false, doubleQuoted: false, redirection: false };
    token.text += text;
    token.quoted ||= quoteKind !== null;
    token.doubleQuoted ||= quoteKind === '"';
  };
  for (let index = 0; index < segment.length; index += 1) {
    const char = segment[index];
    const next = segment[index + 1];
    if (quote !== null) {
      if (char === quote) {
        quote = null;
      } else if (quote === '"' && escapesInDoubleQuotes(char, next, shell)) {
        extend(next, quote);
        index += 1;
      } else {
        extend(char, quote);
      }
      continue;
    }
    if (/\s/.test(char)) {
      finish();
    } else if (char === "'" || char === '"') {
      quote = char;
      extend("", char);
    } else if (isEscape(char, shell) && next !== undefined) {
      extend(next);
      index += 1;
    } else if (char === ">" || char === "<") {
      if (token !== null && !token.quoted && FILE_DESCRIPTOR_PREFIX.test(token.text)) {
        token = null;
      }
      finish();
      const operator = redirectionAt(segment, index);
      tokens.push({ text: operator, quoted: false, doubleQuoted: false, redirection: true });
      index += operator.length - 1;
    } else {
      extend(char);
    }
  }
  finish();
  return tokens;
}

function escapesInDoubleQuotes(char, next, shell) {
  if (next === undefined || !isEscape(char, shell)) {
    return false;
  }
  return shell === POWERSHELL || ["$", "`", '"', "\\", "\n"].includes(next);
}

function redirectionAt(segment, index) {
  let end = index;
  while (end < segment.length && "<>&|".includes(segment[end])) {
    end += 1;
  }
  return segment.slice(index, end);
}

function separateRedirections(tokens) {
  const words = [];
  const outputTargets = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token.redirection) {
      words.push(token.text);
      continue;
    }
    const target = tokens[index + 1];
    if (target === undefined || target.redirection) {
      continue;
    }
    index += 1;
    const duplicatesDescriptor = /^\d+$/.test(target.text) || target.text === "-";
    if (token.text.includes(">") && !duplicatesDescriptor) {
      outputTargets.push(target.text);
    }
  }
  return { words, outputTargets };
}

function substitutionsIn(tokens, shell) {
  return tokens
    .filter((token) => token.doubleQuoted && (token.text.includes("$(") || (shell === BASH && token.text.includes("`"))))
    .map((token) => token.text);
}

function nestedCommand(words) {
  const index = programIndex(words);
  if (index >= words.length) {
    return null;
  }
  const program = programName(words[index]);
  const args = words.slice(index + 1);
  if (BASH_PROGRAMS.has(program)) {
    return bashInline(args);
  }
  if (POWERSHELL_PROGRAMS.has(program)) {
    return powershellInline(args);
  }
  if (CMD_PROGRAMS.has(program)) {
    const switchIndex = args.findIndex((arg) => /^\/[ck]$/i.test(arg));
    return switchIndex === -1 ? null : inlineCommand(POWERSHELL, args.slice(switchIndex + 1));
  }
  if (EXPRESSION_PROGRAMS.has(program)) {
    return expressionInline(args);
  }
  return null;
}

function bashInline(args) {
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (/^-[A-Za-z]*c[A-Za-z]*$/.test(arg)) {
      return inlineCommand(BASH, args.slice(index + 1, index + 2));
    }
    if (!arg.startsWith("-")) {
      return null;
    }
  }
  return null;
}

function powershellInline(args) {
  for (let index = 0; index < args.length; index += 1) {
    const lower = args[index].toLowerCase();
    if (lower === "-ec" || (lower.startsWith("-e") && "-encodedcommand".startsWith(lower))) {
      return { kind: "opaque", reason: "an encoded PowerShell command" };
    }
    if (POWERSHELL_COMMAND_PARAMETER.test(lower) || lower === "-commandwithargs" || lower === "-cwa") {
      return inlineCommand(POWERSHELL, args.slice(index + 1));
    }
    if (lower === "-file" || lower === "-f") {
      return null;
    }
    if (POWERSHELL_PARAMETERS_WITH_VALUE.has(lower)) {
      index += 1;
    } else if (!lower.startsWith("-")) {
      return lower.endsWith(".ps1") ? null : inlineCommand(POWERSHELL, args.slice(index));
    }
  }
  return null;
}

function expressionInline(args) {
  const command = args.find((arg) => arg.toLowerCase() !== "-command");
  if (command === undefined) {
    return null;
  }
  if (command.startsWith("$")) {
    return { kind: "opaque", reason: "a command held in a variable" };
  }
  return inlineCommand(POWERSHELL, [command]);
}

function inlineCommand(shell, words) {
  return words.length === 0 ? null : { kind: "command", shell, text: words.join(" ") };
}

function directoryAfter(words, directory) {
  const index = programIndex(words);
  if (index >= words.length) {
    return directory;
  }
  const program = programName(words[index]);
  if (UNKNOWN_DIRECTORY_PROGRAMS.has(program)) {
    return null;
  }
  if (!DIRECTORY_PROGRAMS.has(program)) {
    return directory;
  }
  const target = directoryArgument(words.slice(index + 1));
  if (target.kind === "home") {
    return withForwardSlashes(os.homedir());
  }
  return target.kind === "unknown" ? null : resolvedDirectory(target.path, directory);
}

function directoryArgument(args) {
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    const lower = arg.toLowerCase();
    if (lower === "-path" || lower === "-literalpath") {
      return directoryPath(args[index + 1]);
    }
    if (arg === "-") {
      return { kind: "unknown" };
    }
    if (lower !== "/d" && !arg.startsWith("-")) {
      return directoryPath(arg);
    }
  }
  return { kind: "home" };
}

function directoryPath(arg) {
  if (arg === undefined || /[$%`]/.test(arg)) {
    return { kind: "unknown" };
  }
  return { kind: "path", path: arg };
}

function resolvedDirectory(target, directory) {
  if (target === undefined || /[$%`]/.test(target)) {
    return null;
  }
  if (directory === null && !isAbsolutePath(target)) {
    return null;
  }
  return absolutePath(target, directory);
}
