import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { barsSpanQuery, type Series } from "@/api/bars"
import { queryClient } from "@/api/client"
import {
  type DatasetWritten,
  type ImportAsked,
  importResult,
  useImportStart,
} from "@/api/imports"
import { isActive, type Job, jobsQuery } from "@/api/jobs"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { PercentBar } from "@/ui/percent-bar"
import { TextLink } from "@/ui/text-link"
import { datasetFolder } from "../datasets"
import type { LatestPreview } from "./import-preview"
import type { Asks } from "./import-request"

type RunProps = Readonly<{ asks: Asks; review: LatestPreview }>

/** Import and its job, in the review's card (web/DESIGN.md, Patterns, Job in its card): Import
 * reads the latest draft's answer alone and sends that answer's request, once it imports as it
 * is; the job's bar and message follow from the jobs drawer's own reads, then what it wrote,
 * with the way to the dataset and its chart, or why it failed. */
export function Run({ asks, review }: RunProps) {
  const start = useImportStart()
  const [started, setStarted] = useState<Readonly<{
    ask: string
    id: string
  }> | null>(null)
  const jobs = useQuery(jobsQuery)
  const job =
    started === null
      ? undefined
      : jobs.data?.find((each) => each.id === started.id)
  const ask = asks.review === null ? null : JSON.stringify(asks.review)
  const imports =
    review.current &&
    review.answer !== null &&
    verdictOf(review.answer) === "imports"
  const ran =
    started !== null &&
    started.ask === ask &&
    (job === undefined || job.status !== "failed")
  const request: ImportAsked | null = imports ? asks.review : null
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <Button
          data-testid="import-run"
          disabled={request === null || ran || start.isPending}
          onClick={() => {
            if (request !== null && ask !== null) {
              start.mutate(request, {
                onSuccess: (queued) => setStarted({ ask, id: queued.id }),
              })
            }
          }}
        >
          Import
        </Button>
        {start.error !== null && (
          <p role="alert" className="text-negative">
            {start.error.message}
          </p>
        )}
      </div>
      {job !== undefined && <ImportJob job={job} />}
    </div>
  )
}

function ImportJob({ job }: Readonly<{ job: Job }>) {
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
  return <Imported job={job} />
}

function Imported({ job }: Readonly<{ job: Job }>) {
  const result = importResult.parse(job.result)
  if (result.kind === "imported_before") {
    return (
      <p data-testid="import-done" className="text-foreground-secondary">
        The file was imported before: nothing changed.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3" data-testid="import-done">
      {result.datasets.map((written) => (
        <Written key={datasetFolder(written.dataset)} written={written} />
      ))}
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
  return (
    <div className="flex flex-col gap-2">
      <p className="text-foreground-secondary">
        {`Imported ${counted(written.records_added, "record")} into ${datasetFolder(written.dataset)}, ${formatCount(written.records_held)} held already.`}
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

function verdictOf(
  answer: NonNullable<LatestPreview["answer"]>
): string | null {
  return answer.kind === "file" || answer.kind === "databento"
    ? answer.verdict
    : null
}
