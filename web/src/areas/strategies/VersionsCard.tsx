import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import type { IndexedStrategy } from "@/api/strategies"
import { formatInstant } from "@/ui/instant"
import { Panel } from "@/ui/panel"

type VersionsCardProps = Readonly<{
  strategy: IndexedStrategy
  shown: number
}>

/** A strategy's versions, newest first (web/DESIGN.md, Patterns, Strategy page), each a row that
 * opens it, with when it was saved and its changelog; the version shown is marked as the
 * sidebar marks the page shown. */
export function VersionsCard({ strategy, shown }: VersionsCardProps) {
  const newestFirst = [...strategy.versions].reverse()
  return (
    <Panel
      title="Versions"
      description="Newest first, each saved once and never changed"
    >
      <ul className="-mx-2 flex flex-col gap-1">
        {newestFirst.map((version) => {
          const current = version.version === shown
          return (
            <li key={version.id}>
              <Link
                to="/strategies/strategy"
                search={{ name: strategy.name, version: version.version }}
                aria-current={current ? "page" : undefined}
                data-slot="row-link"
                data-testid="version-row"
                className={cn(
                  "grid grid-cols-[3rem_9rem_minmax(0,1fr)] items-baseline gap-x-4 rounded-xl border px-2 py-2",
                  current
                    ? "border-brand-soft-border bg-brand-soft"
                    : "border-transparent hover:border-border hover:bg-muted"
                )}
              >
                <span
                  className={
                    current
                      ? "font-medium text-brand-soft-foreground"
                      : "font-medium text-foreground"
                  }
                >
                  {`v${version.version}`}
                </span>
                <span className="text-foreground-secondary">
                  {formatInstant(version.created_at)}
                </span>
                <span className="wrap-anywhere text-foreground-secondary">
                  {version.changelog === ""
                    ? "No changelog"
                    : version.changelog}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
