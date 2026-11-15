import type { Dispatch } from "react"
import type { DatasetMerge } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { datasetFolder } from "../datasets"
import type { Draft, DraftChange } from "./import-draft"

type MergeProps = Readonly<{
  merge: DatasetMerge
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** What the file adds to a dataset FEAT holds (ADR-0021), in a box in the card: its new
 * sessions, the sessions it extends, its records new, held, and differing, and the partitions
 * that change; where its records differ from the stored ones, Take the file's records behind an
 * inline confirmation that says how many stored records give way (plan call 8), and once taken,
 * the way back. */
export function Merge({ merge, draft, change }: MergeProps) {
  const differing = merge.records_differing > 0
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border bg-muted p-4"
      data-testid="merge-account"
    >
      <p className="font-medium text-foreground">
        {datasetFolder(merge.dataset)}
      </p>
      <ul className="flex flex-col gap-1 text-foreground-secondary">
        <li>
          {`Sessions: ${formatCount(merge.new_sessions.length)} new, ${formatCount(merge.extended_sessions.length)} extended, those FEAT holds part of`}
        </li>
        <li>
          {`Records: ${formatCount(merge.records_added)} new, ${formatCount(merge.records_held)} held already, ${formatCount(merge.records_differing)} differing`}
        </li>
        <li>
          {`Partitions: ${formatCount(merge.partitions_changed)} to change, ${formatCount(merge.partitions_unchanged)} unchanged`}
        </li>
        {merge.differing_sessions.length > 0 && (
          <li>
            {`Differing on ${merge.differing_sessions.map((day) => day.trade_date).join(", ")}`}
          </li>
        )}
      </ul>
      {differing && draft.differing === "refuse" && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-foreground-secondary">
            Where the file is an export, check its profile's time zone and bar
            stamping first; where it holds a vendor's correction, take its
            records.
          </p>
          <InlineConfirmation
            trigger="Take the file's records"
            confirm={`Replace ${counted(merge.stored_records_disputed, "stored record")}`}
            onConfirm={() =>
              change({ kind: "differing", differing: "take-file" })
            }
          />
        </div>
      )}
      {differing && draft.differing === "take-file" && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-foreground-secondary">
            {`The file's records stand in place of ${counted(merge.stored_records_disputed, "stored record")}.`}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => change({ kind: "differing", differing: "refuse" })}
          >
            Keep the stored records
          </Button>
        </div>
      )}
    </div>
  )
}
