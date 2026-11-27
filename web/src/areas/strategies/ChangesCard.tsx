import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import {
  type IndexedStrategy,
  type SavedStrategyVersion,
  strategyVersionQuery,
} from "@/api/strategies"
import { type DiffSide, CodeDiff } from "@/ui/code-diff"
import { Panel } from "@/ui/panel"
import { Picker } from "@/ui/picker"
import { QueryBody } from "@/ui/query-body"

type ChangesCardProps = Readonly<{
  strategy: IndexedStrategy
  shown: SavedStrategyVersion
  other: number
}>

/** What changed between the version shown and version `other` of `strategy` (web/DESIGN.md,
 * Patterns, Changes card): the two codes side by side, the earlier on the left, each change in
 * the accent; where the strategy has more than two versions, Compare with chooses the other,
 * kept in the page's address. A version's builder spec and its structured diff wait for the rule
 * builder (step 6.8, BACKLOG.md). */
export function ChangesCard({ strategy, shown, other }: ChangesCardProps) {
  const read = useQuery(strategyVersionQuery(strategy.id, other))
  const navigate = useNavigate({ from: "/strategies/strategy" })
  const [earlier, later] =
    other < shown.version ? [other, shown.version] : [shown.version, other]
  const others = strategy.versions.filter(
    (each) => each.version !== shown.version
  )
  return (
    <Panel
      title="Changes"
      description={`Version ${earlier} on the left, version ${later} on the right`}
      action={
        others.length > 1 ? (
          <Picker
            id="changes-compared"
            label="Compare with"
            value={String(other)}
            options={others.map((each) => ({
              value: String(each.version),
              label: `Version ${each.version}`,
            }))}
            onChange={(chosen) =>
              void navigate({
                search: (now) => ({ ...now, diff: Number(chosen) }),
                replace: true,
              })
            }
            className="-my-2 w-36"
          />
        ) : undefined
      }
    >
      <QueryBody query={read}>
        {(otherVersion) =>
          otherVersion.version < shown.version ? (
            <CodeDiff earlier={sideOf(otherVersion)} later={sideOf(shown)} />
          ) : (
            <CodeDiff earlier={sideOf(shown)} later={sideOf(otherVersion)} />
          )
        }
      </QueryBody>
    </Panel>
  )
}

function sideOf(version: SavedStrategyVersion): DiffSide {
  return { label: `Version ${version.version}`, code: version.code }
}
