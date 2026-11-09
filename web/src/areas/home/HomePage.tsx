import { Link, type LinkProps } from "@tanstack/react-router"
import {
  ArrowRight,
  ChartLine,
  Database,
  FlaskConical,
  Workflow,
  type LucideIcon,
} from "lucide-react"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { RunningJobsWidget } from "./RunningJobsWidget"

type Start = Readonly<{ label: string; to: LinkProps["to"]; icon: LucideIcon }>

// Each start takes its area's icon in the sidebar.
const STARTS: readonly Start[] = [
  { label: "Build a strategy", to: "/strategies", icon: Workflow },
  { label: "Open the feature lab", to: "/lab", icon: FlaskConical },
  { label: "Run a backtest", to: "/runs", icon: ChartLine },
  { label: "Import data", to: "/data", icon: Database },
]

/** The page the app opens on (the design brief's home): a card for each kind of work, each
 * leading to its page, a placeholder until the steps that fill them (`BACKLOG.md`); the running
 * jobs are live since step 4.4. */
export function HomePage() {
  return (
    <Page title="Home">
      <div className="grid grid-cols-3 gap-6">
        <Panel
          title="Recent runs"
          className="col-span-2"
          action={<TextLink to="/runs">All runs</TextLink>}
        >
          <PanelSlot>
            Your latest backtests will appear here with their robustness verdict
          </PanelSlot>
        </Panel>
        <RunningJobsWidget />
        <Panel
          title="Feature library"
          className="col-span-2"
          action={<TextLink to="/lab">All features</TextLink>}
        >
          <PanelSlot>
            Saved features will appear here with their versions
          </PanelSlot>
        </Panel>
        <Panel title="Start">
          <ul className="-mx-2 flex flex-col gap-1">
            {STARTS.map(({ label, to, icon: Icon }) => (
              <li key={label}>
                <Link
                  to={to}
                  className="group flex items-center gap-3 rounded-xl border border-transparent p-2 font-medium hover:border-border hover:bg-muted"
                >
                  <Icon className="size-4 shrink-0 text-foreground-secondary" />
                  <span className="group-hover:text-brand">{label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </Page>
  )
}

/** The skill's text link to another page, in the second accent with its arrow (D-89). */
function TextLink({
  to,
  children,
}: Readonly<{ to: LinkProps["to"]; children: string }>) {
  return (
    <Link
      to={to}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-xl font-semibold text-brand-secondary underline-offset-4 hover:underline"
    >
      {children}
      <ArrowRight className="size-4" />
    </Link>
  )
}

function PanelSlot({ children }: Readonly<{ children: string }>) {
  return (
    <p className="flex min-h-24 items-center text-foreground-secondary">
      {children}
    </p>
  )
}
