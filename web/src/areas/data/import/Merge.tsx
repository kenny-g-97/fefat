import type { Dispatch, ReactNode } from "react"
import type { MergeSeen } from "@/api/imports"
import { counted, formatCount } from "@/ui/figures"
import { datasetName } from "../datasets"
import { Options } from "./Decision"
import type { Draft, DraftChange } from "./import-draft"

type MergeProps = Readonly<{ merge: MergeSeen; children?: ReactNode }>

/** What the file adds to a dataset FEAT holds (ADR-0021), in a box in the card: its sessions
 * new to the store and those it held in part, its records new, held, and differing, the
 * partitions that change, and the first trade dates whose records differ; at its foot, where
 * the review shows one file, what to do with records that differ (`RecordsChoice`). */
export function Merge({ merge, children }: MergeProps) {
  const more = merge.differing_sessions_total - merge.differing_sessions.length
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border bg-muted p-4"
      data-testid="merge-account"
    >
      <p className="font-medium text-foreground">
        {datasetName(merge.dataset)}
      </p>
      <ul className="flex flex-col gap-1 text-foreground-secondary">
        <li>
          {`Sessions: ${formatCount(merge.new_sessions)} new, ${formatCount(merge.extended_sessions)} already held in part`}
        </li>
        <li>
          {`Records: ${formatCount(merge.records_added)} new, ${formatCount(merge.records_held)} held already, ${formatCount(merge.records_differing)} differing`}
        </li>
        <li>
          {`Partitions: ${formatCount(merge.partitions_changed)} to change, ${formatCount(merge.partitions_unchanged)} unchanged`}
        </li>
        {merge.differing_sessions.length > 0 && (
          <li>
            {`Differing on ${merge.differing_sessions.join(", ")}${more > 0 ? `, and ${formatCount(more)} more` : ""}`}
          </li>
        )}
      </ul>
      {children}
    </div>
  )
}

type RecordsChoiceProps = Readonly<{
  subject: "file" | "batch"
  disputed: number
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Where the records of the one file or batch the review shows differ from the stored ones
 * (plan call 8; D-106): the choice, imported with its records in place of the `disputed`
 * stored ones, over every dataset the import writes, which cannot be undone once imported, or
 * not imported, chosen at the start, since it is what happens if nothing is chosen. A round asks
 * it under its rows instead (`RoundDecisions`). */
export function RecordsChoice({
  subject,
  disputed,
  draft,
  change,
}: RecordsChoiceProps) {
  return (
    <Options
      label="Records that differ"
      options={[
        {
          value: "take-file",
          label: `Import the ${subject} and replace the stored records`,
          description: `The ${subject}'s records take the place of the ${counted(disputed, "stored record")} they differ from. Once imported, this cannot be undone.`,
        },
        {
          value: "refuse",
          label: `Do not import the ${subject}`,
          description:
            "It stays refused for these records, and nothing is written.",
        },
      ]}
      value={draft.differing}
      onChange={(differing) => change({ kind: "differing", differing })}
      testId="records-choice"
    />
  )
}
