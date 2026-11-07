import { Link, type LinkProps } from "@tanstack/react-router"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"

type Start = Readonly<{ label: string; to: LinkProps["to"] }>

const STARTS: readonly Start[] = [
  { label: "Build a strategy", to: "/strategies" },
  { label: "Open the feature lab", to: "/lab" },
  { label: "Run a backtest", to: "/runs" },
  { label: "Import data", to: "/data" },
]

const QUIET_LINK =
  "rounded-sm text-caption text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"

/** The page the app opens on (the design brief's home): a widget for each kind of work, each
 * leading to its page, a placeholder until the steps that fill them (`BACKLOG.md`). */
export function HomePage() {
  return (
    <Page title="Home">
      <div className="grid grid-cols-3 gap-4">
        <Panel
          title="Recent runs"
          className="col-span-2"
          action={
            <Link to="/runs" className={QUIET_LINK}>
              All runs
            </Link>
          }
        >
          <WidgetSlot>
            Your latest backtests will appear here with their robustness
            verdict.
          </WidgetSlot>
        </Panel>
        <Panel title="Running jobs">
          <WidgetSlot>
            Imports, backtests, and studies will show their progress here while
            they run.
          </WidgetSlot>
        </Panel>
        <Panel
          title="Feature library"
          className="col-span-2"
          action={
            <Link to="/lab" className={QUIET_LINK}>
              The lab
            </Link>
          }
        >
          <WidgetSlot>
            Saved features will appear here with their versions.
          </WidgetSlot>
        </Panel>
        <Panel title="Start">
          <ul className="-mx-2 flex flex-col gap-1">
            {STARTS.map(({ label, to }) => (
              <li key={label}>
                <Link
                  to={to}
                  className="flex h-8 items-center rounded-md px-2 text-sm text-foreground-secondary transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </Page>
  )
}

function WidgetSlot({ children }: Readonly<{ children: string }>) {
  return (
    <p className="flex min-h-24 items-center text-sm text-foreground-secondary">
      {children}
    </p>
  )
}
