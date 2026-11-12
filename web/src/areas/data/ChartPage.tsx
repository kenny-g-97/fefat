import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { cn } from "cn"
import { useState } from "react"
import type { Series } from "@/api/bars"
import {
  type CatalogStatus,
  catalogQuery,
  type InstrumentVersion,
  instrumentsQuery,
} from "@/api/catalog"
import { type ChartStyle, settingsQuery } from "@/api/settings"
import { Page } from "@/ui/page"
import { Sheet } from "@/ui/sheet"
import { ChartStyleDrawer } from "./ChartStyleDrawer"
import { ChartToolbar } from "./ChartToolbar"
import { ChartView } from "./ChartView"
import { chartRoots, latestVersion, rootProviders } from "./chart-panes"
import type { ChartSearch } from "./chart-search"
import { fidelityLabel } from "./datasets"
import { QueryBody } from "./QueryBody"

/** The chart viewer (step 5.4): a series of the store's bars, chosen in the toolbar and kept in
 * the address, drawn by `PriceChart` a window at a time as the trader scrolls back, with the
 * chart style drawer beside it, the chart narrowing so that it redraws in view. */
export function ChartPage() {
  const catalog = useQuery(catalogQuery)
  const instruments = useQuery(instrumentsQuery)
  const { data: settings } = useSuspenseQuery(settingsQuery)
  const [styling, setStyling] = useState(false)
  // The drawer's sheet holds the toolbar's Chart style as its trigger, which the focus goes back
  // to when the drawer closes.
  return (
    <Sheet modal={false} open={styling} onOpenChange={setStyling}>
      <Page
        title="Chart"
        description="Your data's bars, a window at a time as you scroll back"
        fill
      >
        <div
          className={cn(
            "flex min-h-0 flex-1 flex-col gap-5",
            styling && "pr-96"
          )}
        >
          <QueryBody query={catalog}>
            {(status) => (
              <QueryBody query={instruments}>
                {(versions) => (
                  <ChartWorkspace
                    catalog={status}
                    versions={versions}
                    style={settings.chart_style}
                  />
                )}
              </QueryBody>
            )}
          </QueryBody>
        </div>
        <ChartStyleDrawer style={settings.chart_style} />
      </Page>
    </Sheet>
  )
}

type ChartWorkspaceProps = Readonly<{
  catalog: CatalogStatus
  versions: readonly InstrumentVersion[]
  style: ChartStyle
}>

function ChartWorkspace({ catalog, versions, style }: ChartWorkspaceProps) {
  const shown = useSearch({ from: "/_shell/data/chart" })
  const navigate = useNavigate({ from: "/data/chart" })
  const roots = chartRoots(catalog)
  const root = shown.instrument === undefined ? roots.at(0) : shown.instrument
  if (root === undefined) {
    return (
      <p className="text-foreground-secondary">
        No data to chart yet. Import your files on the Data page.
      </p>
    )
  }
  const version = latestVersion(versions, root)
  if (version === undefined) {
    return (
      <p role="alert" className="text-negative">
        FEAT knows no instrument {root}. Choose another on the Data page.
      </p>
    )
  }
  const futures = version.kind === "futures"
  const series: Series = {
    instrument: shown.contract === undefined ? root : shown.contract,
    timeframe: shown.timeframe,
    prices: futures && shown.contract === undefined ? shown.prices : "adjusted",
    provider: shown.provider === undefined ? null : shown.provider,
  }
  const choose = (change: Partial<ChartSearch>) =>
    void navigate({ search: (previous) => ({ ...previous, ...change }) })
  return (
    <>
      <ChartToolbar
        roots={roots.includes(root) ? roots : [root, ...roots]}
        root={root}
        futures={futures}
        providers={rootProviders(catalog, root)}
        shown={shown}
        onChoose={choose}
      />
      <ChartView
        key={[
          series.instrument,
          series.timeframe,
          series.prices,
          series.provider,
        ].join(" ")}
        series={series}
        style={style}
        tickSize={version.tick_size}
        label={`${series.instrument}, ${fidelityLabel(series.timeframe)}`}
      />
    </>
  )
}
