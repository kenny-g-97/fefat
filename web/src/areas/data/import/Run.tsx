import { useEffect } from "react"
import { barsSpanQuery, type Series } from "@/api/bars"
import { queryClient } from "@/api/client"
import {
  type DatasetWritten,
  type ImportAsked,
  importResult,
} from "@/api/imports"
import { isActive, type Job } from "@/api/jobs"
import { counted, formatCount } from "@/ui/figures"
import { PercentBar } from "@/ui/percent-bar"
import { TextLink } from "@/ui/text-link"
import { datasetName } from "../datasets"
import type { ChosenUploads } from "./import-draft"
import { filesLeft, type ReviewedFile } from "./import-round"
import { keptLine } from "./import-run"
import { RoundAccount } from "./RoundAccount"

/** The draft's files with their reviews, of which a round leaves some, how many the trader
 * skipped (D-105), and the way to review those left. */
type RoundFilesLeft = Readonly<{
  reviewed: readonly ReviewedFile[]
  skipped: number
  onReviewLeft: (files: ChosenUploads) => void
}>

type ImportJobProps = Readonly<{
  job: Job
  sent: ImportAsked | undefined
  files: RoundFilesLeft
}>

/** An import's job, in the review's card (web/DESIGN.md, Patterns, Job in its card), Import
 * standing under the card (D-105): the job's bar and message, which follow from the jobs
 * drawer's own reads, then what it wrote and kept, with the way to the dataset and its chart,
 * and for a round what it did with each file (`RoundAccount`); or why it failed. */
export function ImportJob({ job, sent, files }: ImportJobProps) {
  if (isActive(job)) {
    return (
      <div className="flex flex-col gap-2" data-testid="import-job">
        <PercentBar value={job.progress} label="Import progress" />
        <p className="text-xs text-muted-foreground">
          {job.status === "queued" ? "Queued" : job.message}
        </p>
      </div>
    )
  }
  if (job.status !== "succeeded") {
    return (
      <p role="alert" data-testid="import-job" className="text-negative">
        {job.status === "cancelled"
          ? "The import was cancelled before it wrote."
          : job.error}
      </p>
    )
  }
  return <Imported job={job} sent={sent} files={files} />
}

function Imported({ job, sent, files }: ImportJobProps) {
  const result = importResult.parse(job.result)
  const round =
    sent?.kind === "files" ? (
      <RoundAccount
        round={result.round}
        chosen={files.reviewed.length}
        sent={sent.sources.length}
        skipped={files.skipped}
        left={filesLeft(
          files.reviewed,
          sent.sources,
          result.round === undefined ? [] : result.round.not_imported
        )}
        onReviewLeft={files.onReviewLeft}
      />
    ) : null
  if (result.kind === "imported_before") {
    return (
      <div className="flex flex-col gap-3" data-testid="import-done">
        <p className="text-foreground-secondary">
          {sent?.kind === "files" && sent.sources.length > 1
            ? "The files were imported before: nothing changed."
            : "The file was imported before: nothing changed."}
        </p>
        {round}
      </div>
    )
  }
  const kept = keptLine(result)
  return (
    <div className="flex flex-col gap-3" data-testid="import-done">
      {result.datasets.length === 0 && (
        <p className="text-foreground-secondary">
          Nothing was written: the batch held no record FEAT stores.
        </p>
      )}
      {result.datasets.map((written) => (
        <Written key={datasetName(written.dataset)} written={written} />
      ))}
      {kept !== null && (
        <p
          className={
            kept.refused ? "text-negative" : "text-foreground-secondary"
          }
        >
          {kept.text}
        </p>
      )}
      {round}
    </div>
  )
}

/** What an import wrote into one dataset, with the way to the dataset and its chart; the
 * chart's span is asked at once, which builds the product's roll calendar on the server before
 * the chart opens (from `BACKLOG.md`). */
function Written({ written }: Readonly<{ written: DatasetWritten }>) {
  const { root, provider } = written.dataset
  useEffect(() => {
    const series: Series = {
      instrument: root,
      timeframe: "5m",
      prices: "adjusted",
      provider,
    }
    void queryClient.prefetchQuery(barsSpanQuery(series))
  }, [root, provider])
  const taken =
    written.records_taken > 0
      ? ` and ${formatCount(written.records_taken)} taken from the file in place of stored ones`
      : ""
  return (
    <div className="flex flex-col gap-2">
      <p className="text-foreground-secondary">
        {`Imported ${counted(written.records_added, "record")} into ${datasetName(written.dataset)}, ${formatCount(written.records_held)} held already${taken}.`}
      </p>
      {written.records_left_out > 0 && (
        <p className="text-foreground-secondary" data-testid="import-left-out">
          {`Left out ${counted(written.records_left_out, "record")}, the bars in a break and the sessions the review listed, as you approved.`}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <TextLink
          to="/data/dataset"
          search={{ instrument: root, provider }}
          data-testid="open-dataset"
        >
          Open the dataset
        </TextLink>
        <TextLink
          to="/data/chart"
          search={{ instrument: root, provider }}
          data-testid="open-chart"
        >
          Open its chart
        </TextLink>
      </div>
    </div>
  )
}
