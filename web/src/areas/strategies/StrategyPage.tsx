import { useQuery } from "@tanstack/react-query"
import { useSearch } from "@tanstack/react-router"
import { useRef, useState } from "react"
import {
  type IndexedStrategy,
  strategiesQuery,
  strategyVersionQuery,
  useAbandonment,
  useReopening,
} from "@/api/strategies"
import { Page } from "@/ui/page"
import { QueryBody } from "@/ui/query-body"
import { BackLink } from "@/ui/text-link"
import { AbandonCard, AbandonedPanel } from "./AbandonedMark"
import { ChangesCard } from "./ChangesCard"
import { CodeCard } from "./CodeCard"
import { ParametersCard } from "./ParametersCard"
import { RunBacktest } from "./RunBacktest"
import type { StrategySearch } from "./strategy-names"
import {
  comparedVersion,
  latestVersion,
  versionNumbered,
} from "./strategy-versions"
import { VersionsCard } from "./VersionsCard"

/** A strategy's page (step 5.5; web/DESIGN.md, Patterns, Strategy page), its name and a version
 * in the address, the latest where none is: Run backtest in its header (step 5.6), the version's
 * hypothesis above its code, the code in the editor with Validate and Save as new version, the
 * versions, the version's parameters, and the abandoned mark, or the way to make one. */
export function StrategyPage() {
  const shown = useSearch({ from: "/_shell/strategies/strategy" })
  const strategies = useQuery(strategiesQuery)
  const strategy =
    strategies.status === "success"
      ? strategies.data.find((each) => each.name === shown.name)
      : undefined
  const version =
    strategy === undefined
      ? undefined
      : shown.version === undefined
        ? latestVersion(strategy)
        : versionNumbered(strategy, shown.version)
  return (
    <Page
      title={shown.name === undefined ? "Strategy" : shown.name}
      description={version === undefined ? undefined : version.hypothesis}
      back={<BackLink to="/strategies">Back to Strategies</BackLink>}
      action={
        strategy === undefined || version === undefined ? undefined : (
          <RunBacktest
            key={`${strategy.name} ${version.version}`}
            strategy={strategy}
            number={version.version}
          />
        )
      }
    >
      <QueryBody query={strategies}>
        {() =>
          strategy === undefined || version === undefined ? (
            <NotFound shown={shown} found={strategy} />
          ) : (
            <ShownVersion
              key={`${strategy.name} ${version.version}`}
              strategy={strategy}
              number={version.version}
            />
          )
        }
      </QueryBody>
    </Page>
  )
}

/** The cards of one version, drawn together once the version is read, the Changes card after
 * its code where the strategy has another version (step 5.10). The focus follows the mark: a mark
 * just made takes it, where the page shows it first, and a reopen gives it to the Code card,
 * which stands where the mark stood, rather than to the editor, where the next Tab would indent
 * the code. */
function ShownVersion({
  strategy,
  number,
}: Readonly<{ strategy: IndexedStrategy; number: number }>) {
  const version = useQuery(strategyVersionQuery(strategy.id, number))
  const abandonment = useAbandonment(strategy.id)
  const reopening = useReopening(strategy.id)
  const [marked, setMarked] = useState(false)
  const codeCard = useRef<HTMLElement>(null)
  const asked = useSearch({
    from: "/_shell/strategies/strategy",
    select: (search) => search.diff,
  })
  const other = comparedVersion(
    strategy.versions.map((each) => each.version),
    number,
    asked
  )
  return (
    <QueryBody query={version}>
      {(saved) => (
        <div className="flex flex-col gap-6">
          {strategy.abandoned !== null && (
            <AbandonedPanel
              mark={strategy.abandoned}
              arrived={marked}
              reopening={reopening.isPending}
              refusal={reopening.error}
              onReopen={() =>
                reopening.mutate(undefined, {
                  onSuccess: () => {
                    setMarked(false)
                    codeCard.current?.focus()
                  },
                })
              }
            />
          )}
          <CodeCard ref={codeCard} strategy={strategy} version={saved} />
          {other !== undefined && (
            <ChangesCard strategy={strategy} shown={saved} other={other} />
          )}
          <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-6">
            <VersionsCard strategy={strategy} shown={number} />
            <ParametersCard version={saved} />
          </div>
          {strategy.abandoned === null && (
            <AbandonCard
              marking={abandonment.isPending}
              refusal={abandonment.error}
              onMark={(mark) =>
                abandonment.mutate(mark, { onSuccess: () => setMarked(true) })
              }
            />
          )}
        </div>
      )}
    </QueryBody>
  )
}

function NotFound({
  shown,
  found,
}: Readonly<{ shown: StrategySearch; found: IndexedStrategy | undefined }>) {
  const said =
    shown.name === undefined
      ? "This address needs a strategy's name."
      : found === undefined
        ? `FEAT holds no strategy called ${shown.name}.`
        : `${shown.name} has no version ${shown.version}.`
  return (
    <p role="alert" className="text-negative">
      {said} Choose one on the Strategies page.
    </p>
  )
}
