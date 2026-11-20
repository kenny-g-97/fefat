import { useQuery } from "@tanstack/react-query"
import { useSearch } from "@tanstack/react-router"
import {
  type IndexedStrategy,
  strategiesQuery,
  strategyVersionQuery,
} from "@/api/strategies"
import { Page } from "@/ui/page"
import { QueryBody } from "@/ui/query-body"
import { BackLink } from "@/ui/text-link"
import { AbandonCard, AbandonedPanel } from "./AbandonedMark"
import { CodeCard } from "./CodeCard"
import { ParametersCard } from "./ParametersCard"
import type { StrategySearch } from "./strategy-names"
import { latestVersion, versionNumbered } from "./strategy-versions"
import { VersionsCard } from "./VersionsCard"

/** A strategy's page (step 5.5; web/DESIGN.md, Patterns, Strategy page), its name and a version
 * in the address, the latest where none is: the version's hypothesis above its code, the code in
 * the editor with Validate and Save as new version, the versions, the version's parameters, and
 * the abandoned mark, or the way to make one. */
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

function ShownVersion({
  strategy,
  number,
}: Readonly<{ strategy: IndexedStrategy; number: number }>) {
  const version = useQuery(strategyVersionQuery(strategy.id, number))
  return (
    <div className="flex flex-col gap-6">
      {strategy.abandoned !== null && (
        <AbandonedPanel strategy={strategy} mark={strategy.abandoned} />
      )}
      <QueryBody query={version}>
        {(saved) => <CodeCard strategy={strategy} version={saved} />}
      </QueryBody>
      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-6">
        <VersionsCard strategy={strategy} shown={number} />
        <QueryBody query={version}>
          {(saved) => <ParametersCard version={saved} />}
        </QueryBody>
      </div>
      {strategy.abandoned === null && <AbandonCard strategy={strategy} />}
    </div>
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
