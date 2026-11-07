import { Link, type LinkProps } from "@tanstack/react-router"
import {
  ChartLine,
  Database,
  FlaskConical,
  Workflow,
  type LucideIcon,
} from "lucide-react"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"

type Start = Readonly<{ label: string; to: LinkProps["to"]; icon: LucideIcon }>

// Each start takes its area's icon in the sidebar.
const STARTS: readonly Start[] = [
  { label: "Build a strategy", to: "/strategies", icon: Workflow },
  { label: "Open the feature lab", to: "/lab", icon: FlaskConical },
  { label: "Run a backtest", to: "/runs", icon: ChartLine },
  { label: "Import data", to: "/data", icon: Database },
]

const QUIET_LINK =
  "rounded-sm text-caption text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"

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
              All features
            </Link>
          }
        >
          <WidgetSlot>
            Saved features will appear here with their versions.
          </WidgetSlot>
        </Panel>
        <Panel title="Start">
          <ul className="-mx-2 flex flex-col gap-1">
            {STARTS.map(({ label, to, icon: Icon }) => (
              <li key={label}>
                <Link
                  to={to}
                  className="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-foreground-secondary outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Icon
                    strokeWidth={1.5}
                    className="size-4 shrink-0 text-muted-foreground"
                  />
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
