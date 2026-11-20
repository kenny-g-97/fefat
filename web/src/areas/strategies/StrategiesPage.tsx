import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { strategiesQuery } from "@/api/strategies"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { QueryBody } from "@/ui/query-body"
import { StrategyHead, StrategyRow } from "./StrategyRow"

/** The Strategies page (step 5.5; web/DESIGN.md, Patterns, Strategies list): each saved strategy
 * as a row that opens its page, abandoned ones among them, since the library keeps its failures
 * too (D-29); New strategy copies a template into a strategy's version 1. */
export function StrategiesPage() {
  const strategies = useQuery(strategiesQuery)
  return (
    <Page
      title="Strategies"
      description="Your strategies, each a line of versions that never change once saved"
      action={
        <Button asChild>
          <Link to="/strategies/new">New strategy</Link>
        </Button>
      }
    >
      <Panel
        title="Saved strategies"
        description="A strategy in each row, with its latest version and when it last ran"
      >
        <QueryBody query={strategies}>
          {(listed) =>
            listed.length === 0 ? (
              <p className="text-foreground-secondary">
                No strategies yet. New strategy, above, starts one from a
                template.
              </p>
            ) : (
              <div className="-mx-2 flex flex-col gap-1">
                <StrategyHead />
                <ul className="flex flex-col gap-1">
                  {listed.map((strategy) => (
                    <li key={strategy.id}>
                      <StrategyRow strategy={strategy} />
                    </li>
                  ))}
                </ul>
              </div>
            )
          }
        </QueryBody>
      </Panel>
    </Page>
  )
}
