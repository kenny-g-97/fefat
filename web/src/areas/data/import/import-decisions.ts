import type { FileSeen } from "@/api/imports"
import { counted, formatCount } from "@/ui/figures"
import type { DecisionOption } from "./Decision"
import type { Answer, Correctable, Draft } from "./import-draft"
import { type Outcome, outcomeOf, shownState } from "./import-reviews"
import { filesToDecide, type ReviewedFile } from "./import-round"

/** A kind of problem a round's files share, each asked in a box of its own under the round's
 * rows (D-106): bars in a break, which leaving them out corrects, records that differ, which
 * taking them corrects, and the files no correction fits, refused or not read. */
export type Problem = Correctable | "not correctable"

/** A box under a round's rows: its kind, its files by their uploads' ids, skipped or not, how
 * many of them are skipped, and its answer, none until one is given, a skip alone for the files
 * no correction fits. */
export type RoundDecision =
  | Readonly<{
      problem: Correctable
      files: readonly string[]
      skipped: number
      answer: Answer | null
    }>
  | Readonly<{
      problem: "not correctable"
      files: readonly string[]
      skipped: number
      answer: "skipped" | null
    }>

/** Whether leaving out a file's bars in a break lets it import, or left them out already
 * (ADR-0022). */
export function correctsBars(seen: FileSeen): boolean {
  const breaks = seen.breaks_with_bars
  return (
    breaks !== null && (breaks.left_out || seen.verdict === "bars_in_breaks")
  )
}

/** Whether a file's records differ from the stored ones, refused or taken (ADR-0021). */
export function differs(seen: FileSeen): boolean {
  return seen.merge !== null && seen.merge.records_differing > 0
}

/** The boxes a round asks once every file is read, in their order, each kind by its files'
 * reviews or, while they are read again, their last ones (D-106). A file read without its bars
 * that then differs stands in both of the first two boxes; a file its box's correction leaves
 * refused stands in the box of the files no correction fits as well, so that its skip is
 * offered; a skipped file stays in its box. A box is answered skipped where each of its files is
 * skipped, corrected where each of the others carries the correction, its bars left out or its
 * records taken as the draft holds them for that file, and not at all otherwise. */
export function roundDecisions(
  files: readonly ReviewedFile[],
  draft: Draft
): readonly RoundDecision[] {
  if (files.some(({ state }) => shownState(state).kind === "reading")) {
    return []
  }
  const fitting = (fits: (seen: FileSeen) => boolean) =>
    files.flatMap(({ upload, state }) => {
      const shown = shownState(state)
      return shown.kind === "answered" &&
        shown.answer.kind === "file" &&
        fits(shown.answer)
        ? [upload.id]
        : []
    })
  const bars = fitting(correctsBars)
  const differing = fitting(differs)
  const explained = (file: string, outcome: Outcome | null) =>
    (outcome === "bars_in_breaks" && bars.includes(file)) ||
    (outcome === "differing" && differing.includes(file))
  const others = filesToDecide(files, []).flatMap(({ upload, state }) =>
    explained(upload.id, outcomeOf(shownState(state))) ? [] : [upload.id]
  )
  return [
    decisionOf("bars in breaks", bars, draft.skipped, draft.breaksLeftOut),
    decisionOf("differing", differing, draft.skipped, draft.recordsTaken),
    decisionOf("not correctable", others, draft.skipped, []),
  ].filter((decision) => decision.files.length > 0)
}

function decisionOf(
  problem: Problem,
  files: readonly string[],
  skipped: readonly string[],
  corrected: readonly string[]
): RoundDecision {
  const kept = files.filter((file) => !skipped.includes(file))
  const count = files.length - kept.length
  if (kept.length === 0) {
    return { problem, files, skipped: count, answer: "skipped" }
  }
  if (problem === "not correctable" || !allCorrected(kept, corrected)) {
    return { problem, files, skipped: count, answer: null }
  }
  return { problem, files, skipped: count, answer: "corrected" }
}

/** Whether each of `files`, one or more, carries the correction `corrected` holds: its bars left
 * out, or its records taken. */
export function allCorrected(
  files: readonly string[],
  corrected: readonly string[]
): boolean {
  return files.length > 0 && files.every((file) => corrected.includes(file))
}

/** What a box says (web/DESIGN.md, Patterns, Decision): its title, what its files share and
 * what to check, its options, each its answer named by what happens to the files, then what it
 * does, none for the files no correction fits, and its notes: how many of its files are skipped,
 * where some are and some not, or that they are, where no option shows it, and, once the bars
 * are left out, what the calendar check lists. */
export type DecisionWords = Readonly<{
  title: string
  message: string
  options: readonly DecisionOption<Answer>[]
  notes: readonly string[]
}>

export function decisionWords(decision: RoundDecision): DecisionWords {
  const files = decision.files.length
  const asked = {
    "bars in breaks": barsWords,
    differing: differingWords,
    "not correctable": notCorrectableWords,
  }[decision.problem](files)
  return { ...asked, notes: notesOf(decision) }
}

function notesOf(decision: RoundDecision): string[] {
  const files = decision.files.length
  const skipped = decision.skipped
  const skips =
    skipped > 0 && skipped < files
      ? [
          `${formatCount(skipped)} of these ${counted(files, "file")} ${skipped === 1 ? "is" : "are"} skipped.`,
        ]
      : decision.problem === "not correctable" && skipped === files
        ? [
            files === 1
              ? "The file is skipped."
              : `These ${counted(files, "file")} are skipped.`,
          ]
        : []
  const leftOut =
    decision.problem === "bars in breaks" && decision.answer === "corrected"
      ? [
          `${files === 1 ? "The file's" : "Each file's"} calendar check may list the sessions left out as having no prints.`,
        ]
      : []
  return [...skips, ...leftOut]
}

type AskedWords = Omit<DecisionWords, "notes">

function barsWords(files: number): AskedWords {
  const one = files === 1
  return {
    title: `${counted(files, "file")} ${one ? "holds" : "hold"} bars in a break`,
    message: `${one ? "This file holds" : "These files hold"} bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check the sessions ${one ? "its row lists" : "each file's row lists"} against another source if you can.`,
    options: [
      {
        value: "corrected",
        label: `Import ${one ? "it" : "them"} without those bars`,
        description: `FEAT leaves out those bars and the sessions that go with them, and imports the rest of ${one ? "the file. Its row lists what goes." : "each file. Each file's row lists what goes."}`,
      },
      {
        value: "skipped",
        label: one ? "Skip it" : "Skip them",
        description: one
          ? "The file is not imported."
          : `None of these ${counted(files, "file")} is imported.`,
      },
    ],
  }
}

function differingWords(files: number): AskedWords {
  const one = files === 1
  return {
    title: `${counted(files, "file")} ${one ? "holds" : "hold"} records that differ from the ones FEAT holds`,
    message: one
      ? RECORDS_MESSAGE.file
      : "Where the files are exports, check their profile's time zone and bar stamping under Layout first. Where they hold a vendor's correction, their records should replace the stored ones.",
    options: [
      {
        value: "corrected",
        label: `Import ${one ? "it" : "them"} and replace the stored records`,
        description: `${one ? "The file's" : "The files'"} records take the place of the stored ones they differ from. Once imported, this cannot be undone.`,
      },
      {
        value: "skipped",
        label: one ? "Skip it" : "Skip them",
        description: one
          ? "The file is not imported, and the stored records stay."
          : `None of these ${counted(files, "file")} is imported, and the stored records stay.`,
      },
    ],
  }
}

function notCorrectableWords(files: number): AskedWords {
  const one = files === 1
  return {
    title: one
      ? "1 file does not import as it is read"
      : `${counted(files, "file")} do not import as they are read`,
    message: one
      ? "Its row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip the file."
      : "Each file's row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip these files.",
    options: [],
  }
}

/** The button of the box of the files no correction fits: Skip for those not skipped yet, the
 * others where some are, and once each is, the way back for them all. */
export function skipAction(decision: RoundDecision): string {
  const files = decision.files.length
  const left = files - decision.skipped
  if (left === 0) {
    return files === 1 ? "Do not skip it" : "Do not skip them"
  }
  const other = decision.skipped > 0 ? "other " : ""
  return left === 1
    ? `Skip the ${other}file`
    : `Skip the ${other}${formatCount(left)} files`
}

/** What bars in a break mean and what to check, where the review shows one file, whose box
 * lists the sessions beside them (ADR-0022). */
export const BARS_MESSAGE =
  "These bars are stamped at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check these sessions against another source if you can."

/** What to check first where records differ from the stored ones, for one file or a batch. */
export const RECORDS_MESSAGE = {
  file: "Where the file is an export, check its profile's time zone and bar stamping under Layout first. Where it holds a vendor's correction, its records should replace the stored ones.",
  batch:
    "Where the batch holds a vendor's correction, its records should replace the stored ones.",
} as const
