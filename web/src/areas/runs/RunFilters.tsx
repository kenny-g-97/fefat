import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { STATUS_LABELS } from "@/api/jobs"
import { strategiesQuery } from "@/api/strategies"
import { Choice, Picker } from "@/ui/picker"
import { RUN_STATUSES, type RunsSearch } from "./run-search"

/** The selects' first choice, which asks nothing of their column; no strategy's name and no
 * status holds parentheses. */
const ALL = "(all)"
/** The strategy select's choice of the runs that name no saved version. */
const NOT_SAVED = "(no saved version)"

/** The list's two filters (web/DESIGN.md, Patterns, Runs list), by strategy and by status, each
 * kept in the page's address; a change keeps what the page was told on arrival, so that the
 * list does not move under the pointer. */
export function RunFilters({ filters }: Readonly<{ filters: RunsSearch }>) {
  const navigate = useNavigate({ from: "/runs/" })
  const strategies = useQuery(strategiesQuery)
  const names =
    strategies.status === "success"
      ? strategies.data.map((each) => each.name)
      : []
  const held =
    filters.strategy === undefined || names.includes(filters.strategy)
      ? names
      : [filters.strategy, ...names]
  const strategy =
    filters.versioned === false
      ? NOT_SAVED
      : filters.strategy === undefined
        ? ALL
        : filters.strategy
  return (
    <div
      role="group"
      aria-label="Filter runs"
      className="flex flex-wrap items-end gap-4"
    >
      <Choice id="runs-strategy" label="Strategy">
        <Picker
          id="runs-strategy"
          className="w-56"
          value={strategy}
          options={[
            { value: ALL, label: "All" },
            ...held.map((name) => ({ value: name, label: name })),
            { value: NOT_SAVED, label: "No saved version" },
          ]}
          onChange={(chosen) =>
            void navigate({
              search: (before) => ({
                ...before,
                strategy:
                  chosen === ALL || chosen === NOT_SAVED ? undefined : chosen,
                versioned: chosen === NOT_SAVED ? false : undefined,
              }),
              state: true,
            })
          }
        />
      </Choice>
      <Choice id="runs-status" label="Status">
        <Picker
          id="runs-status"
          className="w-42"
          value={filters.status === undefined ? ALL : filters.status}
          options={[
            { value: ALL, label: "All" },
            ...RUN_STATUSES.map((status) => ({
              value: status,
              label: STATUS_LABELS[status],
            })),
          ]}
          onChange={(chosen) =>
            void navigate({
              search: (before) => ({
                ...before,
                status: RUN_STATUSES.find((status) => status === chosen),
              }),
              state: true,
            })
          }
        />
      </Choice>
    </div>
  )
}
