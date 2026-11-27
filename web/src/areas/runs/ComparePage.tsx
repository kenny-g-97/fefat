import { useQuery } from "@tanstack/react-query"
import { useSearch } from "@tanstack/react-router"
import { comparisonQuery } from "@/api/comparisons"
import { Page } from "@/ui/page"
import { ComparisonEquityCard } from "./ComparisonEquityCard"
import { ComparisonFiguresCard, ExitReasonsCard } from "./ComparisonTables"
import { ResultBody } from "./ResultBody"
import { BackToRuns } from "./RunPage"

const TITLE = "Comparison"

/** Two to four saved runs side by side (web/DESIGN.md, Patterns, Comparison page), addressed by
 * their keys, the first the reference: their equity over their capital on one chart, their
 * figures with what each differs by from the reference's, and their trades by exit reason, led
 * back to the list as it was filtered. */
export function ComparePage() {
  const { runs } = useSearch({ from: "/_shell/runs/compare" })
  if (runs === undefined) {
    return (
      <Page title={TITLE} back={<BackToRuns />}>
        <p role="alert" className="text-negative">
          This address names no runs to compare. Tick two to four on the Runs
          page.
        </p>
      </Page>
    )
  }
  return <ComparedRuns key={runs} runKeys={runs.split(",")} />
}

function ComparedRuns({ runKeys }: Readonly<{ runKeys: readonly string[] }>) {
  const comparison = useQuery(comparisonQuery(runKeys))
  return (
    <Page
      title={TITLE}
      description={`${runKeys.length} runs side by side, the first the reference`}
      back={<BackToRuns />}
    >
      <ResultBody query={comparison}>
        {(answer) => (
          <div className="flex flex-col gap-6">
            <ComparisonEquityCard runs={answer.runs} />
            <ComparisonFiguresCard runs={answer.runs} />
            <ExitReasonsCard comparison={answer} />
          </div>
        )}
      </ResultBody>
    </Page>
  )
}
