import { useQuery } from "@tanstack/react-query"
import { datasetQualityQuery } from "@/api/catalog"
import { Panel } from "@/ui/panel"
import { SectionFailure } from "@/ui/section-failure"
import { CoverageLegend, CoverageStrip } from "./CoverageStrip"
import type { ImportedDataset } from "./datasets"
import { Findings } from "./Findings"
import { QualityBadge } from "./QualityBadge"

type QualityPanelProps = Readonly<{
  dataset: ImportedDataset
  syncing: boolean
}>

/** A dataset's quality (web/DESIGN.md, Patterns, Dataset page): its badge, Checking while a
 * check covers its instrument, how far its report checked, the report's coverage by month with
 * its legend, and its findings; one report of the instrument covers every kind of its data from
 * the provider. */
export function QualityPanel({ dataset, syncing }: QualityPanelProps) {
  const [first] = dataset.stored
  const quality = useQuery(datasetQualityQuery(first.id))
  // The legend comes with the strip it explains: before a report its keys would explain nothing.
  const drawn = quality.data !== undefined && quality.data.months.length > 0
  return (
    <Panel title="Quality" action={drawn ? <CoverageLegend /> : undefined}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <QualityBadge standing={syncing ? "checking" : dataset.quality} />
          {first.checked_through !== null && (
            <span className="text-xs text-muted-foreground">
              Checked through {first.checked_through}
            </span>
          )}
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
        {quality.status === "success" && <Findings quality={quality.data} />}
      </div>
    </Panel>
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
        No quality report yet. Check quality, above, writes one and shows the
        coverage by month.
      </p>
    )
  }
  return <CoverageStrip months={months} />
}
