import type { ImportPreviewAnswer, UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import { OUTCOME_SIGNS } from "./import-outcomes"
import { fileOf } from "./import-request"
import {
  type FileState,
  type Outcome,
  outcomeOf,
  shownState,
} from "./import-reviews"

type Schemas = components["schemas"]
type FileImportAsked = Schemas["FileImportAsked"]
type FilesImportAsked = Schemas["FilesImportAsked"]
type ImportSource = Schemas["ImportSource"]

/** How many files one import takes in a round, as the server's `FILES_AT_MOST` (D-102). */
export const FILES_AT_MOST = 200

/** A file of a round and its review. */
export type ReviewedFile = Readonly<{ upload: UploadedFile; state: FileState }>

/** Each of `uploads` with its review, `states` holding one for each in their order. */
export function reviewedFiles(
  uploads: readonly UploadedFile[],
  states: readonly FileState[]
): readonly ReviewedFile[] {
  requireOnePerFile(uploads.length, states)
  return uploads.map((upload, index) => ({ upload, state: states[index] }))
}

function requireOnePerFile(files: number, states: readonly FileState[]) {
  if (states.length !== files) {
    throw new Error(
      `Expected a review of each of the ${files} files, got ${states.length}.`
    )
  }
}

/** Whether an outcome sends its file with the round: it imports, as it is or without its
 * bars in a break. */
function imports(outcome: Outcome | null): boolean {
  return outcome === "imports" || outcome === "imports_without_bars"
}

/** Whether an outcome waits for the trader's decision before a round imports (D-105): a file
 * refused, with bars in a break, with records that differ, or not read; not one that imports,
 * was imported before, or holds nothing. */
function waitsForDecision(outcome: Outcome | null): boolean {
  return outcome !== null && OUTCOME_SIGNS[outcome] === "negative"
}

/** The files of `files` the trader did not skip (D-105). */
export function notSkipped(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): readonly ReviewedFile[] {
  return files.filter(({ upload }) => !skipped.includes(upload.id))
}

/** The files that do not import and wait for a decision, by their reviews or, while they are
 * read again, their last ones, those skipped aside (D-105). */
export function filesToDecide(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): readonly ReviewedFile[] {
  return notSkipped(files, skipped).filter(({ state }) =>
    waitsForDecision(outcomeOf(shownState(state)))
  )
}

/** The answer a round's layout is read against: its first file's not skipped, once read, so
 * that an offset of a file the trader skipped points at no field (D-105). */
export function leadAnswer(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): ImportPreviewAnswer | null {
  const [lead] = notSkipped(files, skipped)
  return lead !== undefined && lead.state.kind === "answered"
    ? lead.state.answer
    : null
}

/** The files whose reviews, or last reviews while they are read again, find bars in a break
 * that leaving out would let them import, or that are left out already, by their uploads'
 * ids (ADR-0022): those the round's Leave out the files' bars in a break names, the skipped
 * ones aside (D-105). */
export function filesWithBarsInBreaks(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): string[] {
  return notSkipped(files, skipped)
    .filter(({ state }) => {
      const shown = shownState(state)
      if (shown.kind !== "answered" || shown.answer.kind !== "file") {
        return false
      }
      const breaks = shown.answer.breaks_with_bars
      return (
        breaks !== null &&
        (breaks.left_out || shown.answer.verdict === "bars_in_breaks")
      )
    })
    .map(({ upload }) => upload.id)
}

/** How many files Import sends, by each file's review or, while it is read again, its last
 * one, so that Import's name holds still through a change, the skipped ones aside; none where
 * none imports. */
export function filesImporting(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): number | null {
  const count = notSkipped(files, skipped).filter(({ state }) =>
    imports(outcomeOf(shownState(state)))
  ).length
  return count === 0 ? null : count
}

/** The round Import sends (web/DESIGN.md, Patterns, Job in its card): the files whose own
 * review says they import as they are, through the profile and the options they share, and
 * among them those whose bars in a break are left out, as their reviews read them (ADR-0022);
 * none until every review of a file not skipped is read and each file that does not import has
 * a decision, a correction that lets it import or a skip (D-105), and none where no file
 * imports. A skipped file is never sent, even once a later choice lets it import, and its read
 * holds nothing back. */
export function filesRequest(
  asks: readonly FileImportAsked[],
  states: readonly FileState[],
  skipped: readonly string[]
): FilesImportAsked | null {
  requireOnePerFile(asks.length, states)
  const [first] = asks
  if (first === undefined) {
    return null
  }
  const kept = asks.flatMap((ask, index) =>
    skipped.includes(fileOf(ask.source)) ? [] : [{ ask, state: states[index] }]
  )
  if (kept.some(({ state }) => state.kind === "reading")) {
    return null
  }
  if (kept.some(({ state }) => waitsForDecision(outcomeOf(state)))) {
    return null
  }
  const sent = kept
    .filter(({ state }) => imports(outcomeOf(state)))
    .map(({ ask }) => ask)
  if (sent.length === 0) {
    return null
  }
  return {
    kind: "files",
    sources: sent.map((ask) => ask.source),
    profile: first.profile,
    root: first.root,
    time_zone: first.time_zone,
    differing: first.differing,
    leaving_out_bars_in_breaks: sent
      .filter((ask) => ask.bars_in_breaks === "leave-out")
      .map((ask) => ask.source),
  }
}

/** The files a round left: those its import left out, and those not sent that hold records
 * to import, refused, differing, or not read, the skipped among them, rather than imported
 * before or empty. */
export function filesLeft(
  files: readonly ReviewedFile[],
  sent: readonly ImportSource[],
  notImported: readonly Readonly<{ upload_id: string | null }>[]
): UploadedFile[] {
  const sentIds = new Set(sent.map(uploadIdOf))
  const leftIds = new Set(notImported.map((each) => each.upload_id))
  return files
    .filter(({ upload, state }) =>
      sentIds.has(upload.id) ? leftIds.has(upload.id) : !doneWith(state)
    )
    .map(({ upload }) => upload)
}

function doneWith(state: FileState): boolean {
  const outcome = outcomeOf(state)
  return outcome === "imported_before" || outcome === "nothing"
}

/** Why `count` files are too many for one import, before any is copied; none where they are
 * not. */
export function tooManyFiles(count: number): string | null {
  return count > FILES_AT_MOST
    ? `Expected ${FILES_AT_MOST} files at most in one import, got ${count}: choose fewer, and import the others next.`
    : null
}

function uploadIdOf(source: ImportSource): string | null {
  return source.kind === "upload" ? source.upload_id : null
}
