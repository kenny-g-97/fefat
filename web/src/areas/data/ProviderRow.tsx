import { useQuery } from "@tanstack/react-query"
import { cn } from "cn"
import { datasetQualityQuery, type StoredDataset } from "@/api/catalog"
import { IdentityChip } from "@/ui/identity-chip"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import { CoverageStrip } from "./CoverageStrip"
import { chartTimeframe } from "./datasets"
import { DatasetTable } from "./DatasetTable"
import { Findings } from "./Findings"

type Standing = StoredDataset["quality"] | "checking"

/** A quality's badge (web/DESIGN.md, Patterns, Badges): Checking while a sync runs, on the
 * active item's soft fill; Flagged in the negative on its soft fill, an alert; the others on
 * the hover step in heading text, since green marks a profit alone. */
const BADGES: Readonly<
  Record<Standing, Readonly<{ label: string; tone: string }>>
> = {
  checking: {
    label: "Checking",
    tone: "border-brand-soft-border bg-brand-soft text-brand-soft-foreground",
  },
  flagged: {
    label: "Flagged",
    tone: "border-transparent bg-negative-soft text-negative",
  },
  clean: {
    label: "Clean",
    tone: "border-transparent bg-accent text-foreground",
  },
  unchecked: {
    label: "Unchecked",
    tone: "border-transparent bg-accent text-foreground",
  },
  stale: {
    label: "Stale",
    tone: "border-transparent bg-accent text-foreground",
  },
}

type ProviderRowProps = Readonly<{
  root: string
  provider: string
  datasets: readonly [StoredDataset, ...StoredDataset[]]
  syncing: boolean
}>

/** A provider's data of a root: its name, where it came from, its quality, which one report of
 * the root covers for every dataset, the report's coverage by month and its findings, its
 * datasets, and its chart. */
export function ProviderRow({
  root,
  provider,
  datasets,
  syncing,
}: ProviderRowProps) {
  const [first] = datasets
  const quality = useQuery(datasetQualityQuery(first.id))
  const badge = BADGES[syncing ? "checking" : first.quality]
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <IdentityChip testId="provider-chip">{provider}</IdentityChip>
        <span
          data-testid="quality-badge"
          className={cn(
            "rounded-xl border px-2 py-0.5 text-xs font-semibold",
            badge.tone
          )}
        >
          {badge.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {provenance(first)}
        </span>
        {first.checked_through !== null && (
          <span className="text-xs text-muted-foreground">
            Checked through {first.checked_through}
          </span>
        )}
        <TextLink
          to="/data/chart"
          search={{
            instrument: root,
            provider,
            timeframe: chartTimeframe(datasets),
          }}
          className="ml-auto"
        >
          Chart
        </TextLink>
      </div>
      {quality.status === "error" ? (
        <SectionFailure
          error={quality.error}
          onRetry={() => void quality.refetch()}
        />
      ) : (
        <Coverage
          months={
            quality.status === "success" ? quality.data.months : undefined
          }
        />
      )}
      <DatasetTable datasets={datasets} />
      {quality.status === "success" && <Findings quality={quality.data} />}
    </div>
  )
}

function Coverage({
  months,
}: Readonly<{
  months: Parameters<typeof CoverageStrip>[0]["months"] | undefined
}>) {
  if (months === undefined) {
    return <div className="h-9" />
  }
  if (months.length === 0) {
    return (
      <p className="flex h-9 items-center text-foreground-secondary">
        No quality report yet. Update checks the data and shows its coverage by
        month.
      </p>
    )
  }
  return <CoverageStrip months={months} />
}

/** Where a dataset came from: imported or synced, and the last day a file of it came in. */
function provenance(dataset: StoredDataset): string {
  const origin = dataset.origin === "import" ? "Imported" : "Synced"
  return dataset.last_import === null
    ? origin
    : `${origin}, last on ${dataset.last_import}`
}
