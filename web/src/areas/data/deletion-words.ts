import type { DeletionPreview } from "@/api/catalog"
import { counted, formatCount } from "@/ui/figures"
import type { ImportedDataset } from "./datasets"

const LISTED = new Intl.ListFormat("en", { style: "long", type: "conjunction" })

/** How many of the files FEAT keeps a sentence names before it only counts them. */
const NAMED_AT_MOST = 3

/** What stays of the trader's own, whatever the delete removes. */
const OWN_FILES_STAY =
  "Your own files stay where you keep them, and can be imported again afterwards."

/** The sentences of a dataset's Delete card (step 5.18, ADR-0023; web/DESIGN.md, Patterns,
 * Dataset page): what Delete removes, what stays, the files FEAT keeps since they also hold
 * another instrument, the saved runs that read the data, and that it cannot be undone. */
export function deletionWords(
  dataset: ImportedDataset,
  preview: DeletionPreview
): readonly string[] {
  return [
    whatGoes(dataset, preview),
    OWN_FILES_STAY,
    ...keptFiles(preview.kept_files),
    savedRuns(preview.saved_runs),
    "This cannot be undone.",
  ]
}

function whatGoes(dataset: ImportedDataset, preview: DeletionPreview): string {
  const kinds = LISTED.format(dataset.kinds.map(inSentence))
  const records = `Delete removes ${kinds} from ${dataset.from} to ${dataset.to}`
  const besides = [
    ...(preview.imported_files === 0
      ? []
      : [importedFiles(preview.imported_files)]),
    ...(preview.quality_report ? ["the quality report"] : []),
  ]
  return besides.length === 0
    ? `${records}.`
    : `${records}, with ${LISTED.format(besides)}.`
}

/** A kind of data as a sentence names it: Trades as trades, while TBBO and 1-minute bars stay
 * as they are. */
function inSentence(kind: string): string {
  return kind === kind.toUpperCase()
    ? kind
    : `${kind.charAt(0).toLowerCase()}${kind.slice(1)}`
}

function importedFiles(files: number): string {
  return files === 1
    ? "FEAT's copy of the file they were imported from"
    : `FEAT's copies of the ${formatCount(files)} files they were imported from`
}

function keptFiles(names: readonly string[]): readonly string[] {
  if (names.length === 0) {
    return []
  }
  if (names.length === 1) {
    return [
      `FEAT keeps its copy of ${names[0]}, which also holds another instrument still stored: importing it again adds nothing until that instrument is deleted too.`,
    ]
  }
  const named = LISTED.format(names.slice(0, NAMED_AT_MOST))
  const which =
    names.length <= NAMED_AT_MOST
      ? `its copies of ${named}, which also hold`
      : `its copies of ${formatCount(names.length)} files, ${named} among them, which also hold`
  return [
    `FEAT keeps ${which} another instrument still stored: importing them again adds nothing until those instruments are deleted too.`,
  ]
}

function savedRuns(runs: number): string {
  if (runs === 0) {
    return "No saved run read this data."
  }
  const keeps =
    runs === 1
      ? "it keeps its results, but FEAT can no longer explain its trades or check it again"
      : "they keep their results, but FEAT can no longer explain their trades or check them again"
  return `${counted(runs, "saved run")} read this data: ${keeps}.`
}
