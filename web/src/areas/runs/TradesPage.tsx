import { useQuery } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { Download } from "lucide-react"
import { useState } from "react"
import { runStatisticsQuery } from "@/api/run-results"
import { runQuery } from "@/api/runs"
import {
  executionsFileAddress,
  tradesFileAddress,
  type TradesShown,
} from "@/api/trades"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui/tabs"
import { BackLink } from "@/ui/text-link"
import { ColumnChooser } from "./ColumnChooser"
import { keepColumns, keptColumns } from "./kept-columns"
import type { TradesSearch } from "./run-search"
import { RunKey } from "./RunStatusLine"
import { resultsLine } from "./run-words"
import { SqlTab } from "./SqlTab"
import { TradesTable } from "./TradesTable"
import { type TradesAsked, TradesToolbar } from "./TradesToolbar"

const TITLE = "Trades"

/** A saved run's trades (web/DESIGN.md, Patterns, Trades page), addressed by its run key, with
 * what its table asks: the table, or the SQL tab, under Back to the run. */
export function TradesPage() {
  const search = useSearch({ from: "/_shell/runs/run_/trades" })
  if (search.key === undefined) {
    return (
      <Page title={TITLE} back={<BackLink to="/runs">Back to Runs</BackLink>}>
        <p role="alert" className="text-negative">
          This address names no run. Choose one on the Runs page.
        </p>
      </Page>
    )
  }
  return <TradesOfRun key={search.key} runKey={search.key} search={search} />
}

/** What the table shows of `search`: its filters and its order, without the run and the tab. */
function shownOf(search: TradesSearch): TradesShown {
  const { key: _key, tab: _tab, ...shown } = search
  return shown
}

function TradesOfRun({
  runKey,
  search,
}: Readonly<{ runKey: string; search: TradesSearch }>) {
  const run = useQuery(runQuery(runKey))
  const statistics = useQuery(runStatisticsQuery(runKey))
  const navigate = useNavigate({ from: "/runs/run/trades" })
  const [visibility, setVisibility] = useState(keptColumns)
  const shown = shownOf(search)
  const filtered = FILTERS.some((filter) => search[filter] !== undefined)
  const saved = run.data?.state === "saved" ? run.data : null
  const breakdowns =
    statistics.status === "success" ? statistics.data.metrics.breakdowns : null
  const ask = (change: TradesAsked) =>
    void navigate({
      search: (before) => ({ ...before, ...change }),
      replace: true,
    })
  const choose = (chosen: Readonly<Record<string, boolean>>) => {
    setVisibility(chosen)
    keepColumns(chosen)
  }
  return (
    <Page
      title={TITLE}
      description={run.data === undefined ? undefined : resultsLine(run.data)}
      back={
        <BackLink
          to="/runs/run"
          search={{ key: runKey }}
          state={(kept) => kept}
        >
          Back to the run
        </BackLink>
      }
      action={<Exports runKey={runKey} shown={shown} />}
      fill
    >
      <div className="flex min-h-0 flex-1 flex-col gap-6">
        <RunKey runKey={runKey} />
        <Tabs
          value={search.tab ?? "trades"}
          onValueChange={(tab) =>
            void navigate({
              search: (before) => ({
                ...before,
                tab: tab === "sql" ? "sql" : undefined,
              }),
            })
          }
          className="min-h-0 flex-1 gap-6"
        >
          <TabsList variant="line" aria-label="Trades or SQL">
            <TabsTrigger value="trades" data-testid="tab-trades">
              Trades
            </TabsTrigger>
            <TabsTrigger value="sql" data-testid="tab-sql">
              SQL
            </TabsTrigger>
          </TabsList>
          <TabsContent
            value="trades"
            forceMount
            className="flex min-h-0 flex-col gap-5 data-[state=inactive]:hidden"
          >
            <TradesToolbar
              search={search}
              exitReasons={
                breakdowns === null ? [] : Object.keys(breakdowns.exit_reason)
              }
              fidelities={
                breakdowns === null ? [] : Object.keys(breakdowns.fidelity)
              }
              onAsk={ask}
              chooser={
                <ColumnChooser visibility={visibility} onChange={choose} />
              }
            />
            <TradesTable
              runKey={runKey}
              shown={shown}
              filtered={filtered}
              everyTrade={saved === null ? null : saved.key_metrics.trades}
              currency={saved === null ? null : saved.currency}
              visibility={visibility}
              onOrder={(sort, order) =>
                ask({
                  sort: sort === "entry_ts" ? undefined : sort,
                  order: order === "asc" ? undefined : order,
                })
              }
              onClear={() => ask(CLEARED)}
            />
          </TabsContent>
          <TabsContent
            value="sql"
            forceMount
            className="flex min-h-0 flex-col data-[state=inactive]:hidden"
          >
            <SqlTab runKey={runKey} />
          </TabsContent>
        </Tabs>
      </div>
    </Page>
  )
}

/** The table's filters, which a count of the trades it keeps says it is out of. */
const FILTERS = [
  "side",
  "exit_reason",
  "start",
  "end",
  "pnl_sign",
  "fidelity",
  "ambiguous",
] as const

/** Every filter asking nothing, the table's order kept. */
const CLEARED: TradesAsked = Object.fromEntries(
  FILTERS.map((filter) => [filter, undefined])
)

/** The page's two downloads (D-119): the trades the table's filters keep, in its order, and the
 * run's executions, each a CSV the server names. */
function Exports({
  runKey,
  shown,
}: Readonly<{ runKey: string; shown: TradesShown }>) {
  return (
    <>
      <Button variant="ghost" asChild>
        <a
          href={tradesFileAddress(runKey, shown)}
          download
          data-testid="export-trades"
        >
          <Download className="size-4" aria-hidden="true" />
          Export trades
        </a>
      </Button>
      <Button variant="ghost" asChild>
        <a
          href={executionsFileAddress(runKey)}
          download
          data-testid="export-executions"
        >
          <Download className="size-4" aria-hidden="true" />
          Export executions
        </a>
      </Button>
    </>
  )
}
