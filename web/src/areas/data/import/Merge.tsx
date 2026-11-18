import type { Dispatch, ReactNode } from "react"
import type { MergeSeen } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { datasetName } from "../datasets"
import type { Draft, DraftChange } from "./import-draft"

type MergeProps = Readonly<{ merge: MergeSeen; children?: ReactNode }>

/** What the file adds to a dataset FEAT holds (ADR-0021), in a box in the card: its sessions
 * new to the store and those it held in part, its records new, held, and differing, the
 * partitions that change, and the first trade dates whose records differ; at its foot, where
 * the review shows one file, what to do with records that differ (`TakeRecords`). */
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

type TakeRecordsProps = Readonly<{
  disputed: number | null
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Where the file's records differ from the stored ones (plan call 8): what to check first, and
 * Take the file's records behind an inline confirmation that counts the stored records that
 * give way, `disputed`, over every dataset the import writes, or for several files (D-102),
 * none, since two files of one contract dispute the same ones; once taken, the way back. The
 * trigger starts its own line, so that Keep takes its place. */
export function TakeRecords({ disputed, draft, change }: TakeRecordsProps) {
  const stored =
    disputed === null
      ? "the stored records they differ from"
      : counted(disputed, "stored record")
  const records =
    disputed === null ? "The files' records" : "The file's records"
  if (draft.differing === "take-file") {
    return (
      <div
        className="flex flex-col items-start gap-3"
        data-testid="take-records"
      >
        <p className="text-foreground-secondary">
          {`${records} stand in place of ${stored}.`}
        </p>
        <Button
          variant="ghost"
          size="sm"
          autoFocus
          onClick={() => change({ kind: "differing", differing: "refuse" })}
        >
          Keep the stored records
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-col items-start gap-3" data-testid="take-records">
      <p className="text-foreground-secondary">
        {disputed === null
          ? "Where the files are exports, check the profile's time zone and bar stamping first; where they hold a vendor's correction, take their records."
          : "Where the file is an export, check its profile's time zone and bar stamping first; where it holds a vendor's correction, take its records."}
      </p>
      <InlineConfirmation
        trigger={`Take ${records.toLowerCase()}`}
        confirm={
          disputed === null ? "Replace the stored records" : `Replace ${stored}`
        }
        align="start"
        onConfirm={() => change({ kind: "differing", differing: "take-file" })}
      />
    </div>
  )
}
