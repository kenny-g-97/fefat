import { useQuery } from "@tanstack/react-query"
import { datasetQualityQuery, type StoredDataset } from "@/api/catalog"
import { IdentityChip } from "@/ui/identity-chip"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import { CoverageStrip } from "./CoverageStrip"
import { chartTimeframe } from "./datasets"
import { DatasetTable } from "./DatasetTable"
import { Findings } from "./Findings"
import { QualityBadge } from "./QualityBadge"

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
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <IdentityChip testId="provider-chip">{provider}</IdentityChip>
        <QualityBadge standing={syncing ? "checking" : first.quality} />
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
