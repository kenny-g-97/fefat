import { useEffect } from "react"
import { barsSpanQuery, type Series } from "@/api/bars"
import { queryClient } from "@/api/client"
import {
  type DatasetWritten,
  type ImportAsked,
  importResult,
  type UploadedFile,
} from "@/api/imports"
import { isActive, type Job } from "@/api/jobs"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { PercentBar } from "@/ui/percent-bar"
import { TextLink } from "@/ui/text-link"
import { datasetName } from "../datasets"
import type { ChosenUploads } from "./import-draft"
import { filesLeft } from "./import-reviews"
import { type ImportRun, keptLine } from "./import-run"
import { RoundAccount } from "./RoundAccount"

/** The draft's files, of which a round leaves some, and the way to review those left. */
type RoundFilesLeft = Readonly<{
  uploads: readonly UploadedFile[]
  onReviewLeft: (files: ChosenUploads) => void
}>

type RunProps = Readonly<{
  run: ImportRun
  reading: boolean
  files: RoundFilesLeft
}>

/** Import and its job, in the review's card (web/DESIGN.md, Patterns, Job in its card): Import
 * sends the latest draft's request once its own answer says it imports as it is, or for
 * several files once each is read, the reading line beside it while a change is read; the
 * job's bar and message follow from the jobs drawer's own reads, then what it wrote and kept,
 * with the way to the dataset and its chart, and for a round what it did with each file
 * (`RoundAccount`); or why it failed. */
export function Run({ run, reading, files }: RunProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <Button
          data-testid="import-run"
          disabled={!run.importable}
          onClick={run.importNow}
        >
          Import
        </Button>
        {reading && (
          <p className="text-xs text-muted-foreground">
            Reading your latest change
          </p>
        )}
        {run.refusal !== null && (
          <p role="alert" className="text-negative">
            {run.refusal.message}
          </p>
        )}
      </div>
      {run.job !== undefined && (
        <ImportJob job={run.job} sent={run.sent} files={files} />
      )}
    </div>
  )
}

type ImportJobProps = Readonly<{
  job: Job
  sent: ImportAsked | undefined
  files: RoundFilesLeft
}>

function ImportJob({ job, sent, files }: ImportJobProps) {
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
        left={filesLeft(
          files.uploads,
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
          {sent?.kind === "files"
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
