/**
 * A small reader for the commands Claude Code runs through its Bash and
 * PowerShell tools. It knows enough of both languages to find every command a
 * tool call would run, its words, where its output goes, and which folder it
 * runs in; the guards judge the result.
 *
 * It is a guard's reader, not a shell. It follows `&&`, `||`, `;`, pipes,
 * subshells, PowerShell script blocks, `$(...)` (also inside double quotes
 * and inside the body of an unquoted heredoc), `bash -c` and
 * `powershell -Command` wherever they appear in a command (also after
 * `uv run`, `xargs`, or `find -exec`), `eval`, `cmd /c`, `Invoke-Expression`,
 * `Start-Process`, heredocs and here-strings fed to a shell, comments, and
 * `cd`. Heredocs that only feed text to a program (a commit message, a
 * file) are skipped. Where it cannot follow a command (an encoded PowerShell
 * command, a command held in a variable), it marks the command as opaque so
 * a guard can ask instead of guessing.
 */
import os from "node:os";
import { absolutePath, isAbsolutePath, withForwardSlashes } from "./project-paths.mjs";

export const BASH = "bash";
export const POWERSHELL = "powershell";
/** The `find` actions that change files or run programs. */
export const FIND_ACTIONS_THAT_WRITE = [
  "-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls",
];

const MAX_NESTING = 3;
const BASH_PROGRAMS = new Set(["bash", "sh", "zsh", "dash", "ksh"]);
const POWERSHELL_PROGRAMS = new Set(["powershell", "pwsh"]);
const CMD_PROGRAMS = new Set(["cmd"]);
const EXPRESSION_PROGRAMS = new Set(["invoke-expression", "iex"]);
const START_PROCESS_PROGRAMS = new Set(["start-process", "saps", "start"]);
const START_PROCESS_PARAMETERS_WITH_VALUE = new Set([
  "-workingdirectory", "-credential", "-redirectstandardoutput", "-redirectstandardinput",
  "-redirectstandarderror", "-windowstyle", "-verb",
]);
const SHELL_PROGRAMS = new Set([...BASH_PROGRAMS, ...POWERSHELL_PROGRAMS, ...EXPRESSION_PROGRAMS]);
const DIRECTORY_PROGRAMS = new Set(["cd", "chdir", "pushd", "set-location", "sl"]);
const UNKNOWN_DIRECTORY_PROGRAMS = new Set(["popd", "pop-location"]);
const COMMAND_PREFIXES = new Set(["sudo", "env", "command", "exec", "time", "nohup", "&", "."]);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const HEREDOC_AT = /<<(-?)\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\2/y;
const HERE_STRING_AT = /^@(['"])\s*$/;
const PIPED_INTO_SHELL = /\|\s*(?:\S*[\\/])?(bash|sh|zsh|dash|ksh|pwsh|powershell|iex|invoke-expression)(\.exe)?(\s|$)/i;
const WORD_BOUNDARY = /[\s;&|()]/;
const VARIABLE_REFERENCE = /^\$(\{|[A-Za-z_])/;
const FILE_DESCRIPTOR_PREFIX = /^(\d+|&|\*)$/;
const BASH_OPTIONS_WITH_VALUE = new Set(["-o", "+o", "-O", "+O", "--rcfile", "--init-file"]);
const POWERSHELL_COMMAND_PARAMETER = /^-c(o(m(m(a(n(d)?)?)?)?)?)?$/;
const POWERSHELL_PARAMETERS_WITH_VALUE = new Set([
  "-executionpolicy", "-ex", "-ep", "-windowstyle", "-w", "-version", "-v", "-workingdirectory",
  "-wd", "-inputformat", "-if", "-inf", "-outputformat", "-of", "-o", "-configurationname",
  "-settingsfile", "-psconsolefile", "-custompipename",
]);
const GIT_GLOBAL_OPTIONS_WITH_VALUE = new Set([
  "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path", "--list-cmds",
  "--attr-source", "--shallow-file",
]);
const DISCARDED_OUTPUTS = new Set(["/dev/null", "$null", "nul", "nul:"]);
// Bash runs ( ... ) and $( ... ) in a subshell, so a cd inside ends at the ")"; PowerShell's parentheses keep the location.
const SUBSHELL_START = "(";
const SUBSHELL_END = ")";

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
  const globalOptions = [];
  let workingDirectory = directory;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (!arg.startsWith("-")) {
      return { subcommand: arg, args: args.slice(index + 1), configs, globalOptions, directory: workingDirectory };
    }
    globalOptions.push(arg.split("=")[0]);
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
  const outerDirectories = [];
  for (const segment of segmentsOf(text, shell)) {
    if (segment === SUBSHELL_START) {
      outerDirectories.push(directory);
      continue;
    }
    if (segment === SUBSHELL_END) {
      directory = outerDirectories.length > 0 ? outerDirectories.pop() : directory;
      continue;
    }
    const tokens = tokenize(segment, shell);
    const { words, outputTargets } = separateRedirections(tokens);
    if (words.length === 0) {
      continue;
    }
    const nested = nestedCommand(words, shell);
    const tooDeep = nested !== null && depth >= MAX_NESTING;
    const opaque = tooDeep
      ? "a command nested too deeply"
      : nested?.kind === "opaque"
        ? nested.reason
        : (runsVariable(words, shell) ?? gitSubcommandInVariable(words));
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

/** A command whose program is a variable (`$cmd args`, `& $cmd`): its text is not known before it runs. */
function runsVariable(words, shell) {
  const index = programIndex(words);
  if (index >= words.length || !VARIABLE_REFERENCE.test(words[index])) {
    return null;
  }
  const called = shell === BASH ? words[index + 1] !== "=" : ["&", "."].includes(words[index - 1]);
  return called ? "a command held in a variable" : null;
}

/** `git $sub ...`: which git command runs is not known before it runs. */
function gitSubcommandInVariable(words) {
  const held = words.some((word, index) => {
    const git = programName(word) === "git" ? parseGitInvocation(words.slice(index + 1), null) : null;
    return git !== null && /[$%`]/.test(git.subcommand);
  });
  return held ? "a git subcommand held in a variable" : null;
}

function segmentsOf(text, shell) {
  const withoutDocuments = withoutHereDocuments(text.replaceAll("\r\n", "\n"), shell);
  return splitSegments(joinContinuations(withoutDocuments, shell), shell);
}

/**
 * The command text with heredoc and here-string bodies replaced by what a
 * shell would run from them: the whole body when it feeds a shell, the
 * `$(...)` substitutions when the body is expanded, and nothing otherwise.
 * Quotes and `$(...)` nesting are tracked across lines, so a `<<word` inside
 * a quoted string starts nothing.
 */
function withoutHereDocuments(text, shell) {
  const kept = [];
  let stack = [{ quote: null, closer: null, depth: 0 }];
  let document = null;
  for (const line of text.split("\n")) {
    if (document !== null) {
      const remainder = document.remainderAfterEnd(line);
      if (remainder === null) {
        document.body.push(line);
        continue;
      }
      kept.push(...linesToRead(document, remainder, shell), remainder);
      document = null;
      continue;
    }
    const scan = scanLine(line, shell, stack);
    stack = scan.stack;
    document = scan.document;
    kept.push(document === null ? line : document.openingLine);
  }
  if (document !== null) {
    kept.push(...linesToRead(document, "", shell));
  }
  return kept.join("\n");
}

function linesToRead(document, remainder, shell) {
  if (document.feedsShell || PIPED_INTO_SHELL.test(remainder)) {
    return document.body;
  }
  return document.expands ? document.body.flatMap((line) => substitutionsInLine(line, shell)) : [];
}

function scanLine(line, shell, stackBefore) {
  const stack = stackBefore.map((context) => ({ ...context }));
  const escape = shell === POWERSHELL ? "`" : "\\";
  for (let index = 0; index < line.length; index += 1) {
    const context = stack[stack.length - 1];
    const char = line[index];
    if (context.quote === "'") {
      context.quote = char === "'" ? null : "'";
      continue;
    }
    if (char === escape) {
      index += 1;
      continue;
    }
    if (char === "$" && line[index + 1] === "(") {
      stack.push({ quote: null, closer: ")", depth: 0 });
      index += 1;
      continue;
    }
    if (char === "`" && shell === BASH) {
      if (context.quote === null && context.closer === "`") {
        stack.pop();
      } else {
        stack.push({ quote: null, closer: "`", depth: 0 });
      }
      continue;
    }
    if (context.quote === '"') {
      context.quote = char === '"' ? null : '"';
      continue;
    }
    const document = documentStartingAt(line, index, shell);
    if (document !== null) {
      return { stack, document };
    }
    if (char === "'" || char === '"') {
      context.quote = char;
    } else if (char === "#" && startsWord(line, index)) {
      break;
    } else if (char === "(") {
      context.depth += 1;
    } else if (char === ")") {
      closeParenthesis(stack, context);
    }
  }
  return { stack, document: null };
}

function closeParenthesis(stack, context) {
  if (context.depth > 0) {
    context.depth -= 1;
  } else if (context.closer === ")" && stack.length > 1) {
    stack.pop();
  }
}

function startsWord(text, index) {
  return index === 0 || WORD_BOUNDARY.test(text[index - 1]);
}

function documentStartingAt(line, index, shell) {
  if (shell === POWERSHELL) {
    const match = line[index] === "@" ? HERE_STRING_AT.exec(line.slice(index)) : null;
    return match === null ? null : hereString(line, index, match[1]);
  }
  if (line[index] !== "<" || line[index + 1] !== "<" || line[index + 2] === "<" || line[index - 1] === "<") {
    return null;
  }
  HEREDOC_AT.lastIndex = index;
  const match = HEREDOC_AT.exec(line);
  return match === null ? null : heredoc(line, index, match);
}

function heredoc(line, index, match) {
  const indented = match[1] === "-";
  const word = match[3];
  return {
    openingLine: line,
    body: [],
    expands: match[2] === "",
    feedsShell: feedsShell(line.slice(0, index), line.slice(index + match[0].length)),
    remainderAfterEnd: (candidate) => ((indented ? candidate.replace(/^\t+/, "") : candidate) === word ? "" : null),
  };
}

function hereString(line, index, quote) {
  const closing = `${quote}@`;
  return {
    openingLine: line.slice(0, index),
    body: [],
    expands: quote === '"',
    feedsShell: feedsShell(line.slice(0, index), ""),
    remainderAfterEnd: (candidate) => (candidate.startsWith(closing) ? candidate.slice(closing.length) : null),
  };
}

function feedsShell(before, after) {
  const lastCommand = before.split(/&&|\|\||[;|]/).pop().trim();
  const words = lastCommand.split(/\s+/).filter((word) => word !== "");
  const index = programIndex(words);
  return (index < words.length && SHELL_PROGRAMS.has(programName(words[index]))) || PIPED_INTO_SHELL.test(after);
}

function substitutionsInLine(line, shell) {
  const found = [];
  for (let index = line.indexOf("$("); index !== -1; index = line.indexOf("$(", index + 2)) {
    found.push(line.slice(index + 2));
  }
  if (shell === BASH) {
    const pieces = line.split("`");
    for (let index = 1; index < pieces.length; index += 2) {
      found.push(pieces[index]);
    }
  }
  return found;
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
    if (char === "#" && startsWord(text, index)) {
      const lineEnd = text.indexOf("\n", index);
      if (lineEnd === -1) {
        break;
      }
      index = lineEnd - 1;
      continue;
    }
    const length = separatorLength(text, index, shell);
    if (length > 0) {
      segments.push(current);
      current = "";
      if (shell === BASH && (char === "(" || char === ")")) {
        segments.push(char === "(" ? SUBSHELL_START : SUBSHELL_END);
      }
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
  if ((char === "{" || char === "}") && shell === POWERSHELL) {
    return 1;
  }
  if (char === "`" && shell === BASH) {
    return 1;
  }
  if ((char === "&" && next === "&") || (char === "|" && next === "|")) {
    return 2;
  }
  if (char === "|") {
    if (text[index - 1] === ">") {
      return 0;
    }
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

function nestedCommand(words, shell) {
  for (let index = 0; index < words.length; index += 1) {
    const nested = nestedCommandAt(programName(words[index]), words.slice(index + 1), shell);
    if (nested !== null) {
      return nested;
    }
  }
  return null;
}

function nestedCommandAt(program, args, shell) {
  if (BASH_PROGRAMS.has(program)) {
    return bashInline(args);
  }
  if (program === "eval" && shell === BASH) {
    return args.some((arg) => arg.includes("$"))
      ? { kind: "opaque", reason: "a command eval builds at run time" }
      : inlineCommand(BASH, args);
  }
  if (START_PROCESS_PROGRAMS.has(program)) {
    return startProcessInline(args);
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
    if (BASH_OPTIONS_WITH_VALUE.has(arg)) {
      index += 1;
    } else if (!arg.startsWith("-") && !arg.startsWith("+")) {
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

function startProcessInline(args) {
  const words = [];
  for (let index = 0; index < args.length; index += 1) {
    const lower = args[index].toLowerCase();
    if (lower === "-argumentlist" || lower === "-args") {
      words.push(...String(args[index + 1]).split(","));
      index += 1;
    } else if (lower === "-filepath") {
      words.unshift(String(args[index + 1]));
      index += 1;
    } else if (START_PROCESS_PARAMETERS_WITH_VALUE.has(lower)) {
      index += 1;
    } else if (!lower.startsWith("-")) {
      words.push(...args[index].split(","));
    }
  }
  return inlineCommand(POWERSHELL, words);
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
