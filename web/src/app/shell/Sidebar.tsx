import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate, type LinkProps } from "@tanstack/react-router"
import {
  ChartLine,
  Database,
  FlaskConical,
  House,
  LogOut,
  MessageSquareText,
  Settings,
  ShieldCheck,
  Workflow,
  type LucideIcon,
} from "lucide-react"
import { isRefusal } from "@/api/problems"
import { useLogout } from "@/api/session"
import { versionsQuery } from "@/api/versions"
import { IdentityChip } from "@/ui/identity-chip"

type Destination = Readonly<{
  label: string
  to: LinkProps["to"]
  icon: LucideIcon
}>

const AREAS: readonly Destination[] = [
  { label: "Home", to: "/", icon: House },
  { label: "Lab", to: "/lab", icon: FlaskConical },
  { label: "Strategies", to: "/strategies", icon: Workflow },
  { label: "Runs", to: "/runs", icon: ChartLine },
  { label: "Prop", to: "/prop", icon: ShieldCheck },
  { label: "Agent", to: "/agent", icon: MessageSquareText },
  { label: "Data", to: "/data", icon: Database },
]
const SETTINGS: Destination = {
  label: "Settings",
  to: "/settings",
  icon: Settings,
}

const ROW = "flex h-10 items-center gap-3 rounded-xl border px-3 font-medium"
const ICON = "size-5 shrink-0"

/** The shell's sidebar (web/DESIGN.md, Patterns): the mark, the areas, then Settings, Log
 * out, and the app's version. */
export function Sidebar() {
  const versions = useQuery(versionsQuery)
  return (
    <aside className="w-64 shrink-0 border-r bg-sidebar">
      <div className="sticky top-0 flex h-screen flex-col">
        <div className="flex h-18 shrink-0 items-center border-b px-4">
          <Link to="/" aria-label="FEAT, the home page" className="rounded-xl">
            <img src="/logo-full.svg" alt="" className="h-10" />
          </Link>
        </div>
        <nav aria-label="Main" className="flex flex-1 flex-col overflow-y-auto">
          <ul className="flex flex-col gap-1 px-3 py-4">
            {AREAS.map((area) => (
              <SidebarLink key={area.label} destination={area} />
            ))}
          </ul>
          <ul className="mt-auto flex flex-col gap-1 border-t px-3 pt-4 pb-1">
            <SidebarLink destination={SETTINGS} />
            <li>
              <LogOutRow />
            </li>
          </ul>
        </nav>
        <div className="px-6 pt-3 pb-4">
          <IdentityChip testId="version">
            {versions.data === undefined
              ? "FEAT"
              : `FEAT ${versions.data.fefat_app}`}
          </IdentityChip>
        </div>
      </div>
    </aside>
  )
}

function SidebarLink({ destination }: Readonly<{ destination: Destination }>) {
  const { label, to, icon: Icon } = destination
  return (
    <li>
      <Link
        to={to}
        activeOptions={{ exact: to === "/" }}
        className={ROW}
        activeProps={{
          className:
            "border-brand-soft-border bg-brand-soft text-brand-soft-foreground",
        }}
        inactiveProps={{ className: "border-transparent hover:bg-accent" }}
      >
        <Icon className={ICON} />
        {label}
      </Link>
    </li>
  )
}

function LogOutRow() {
  const logout = useLogout()
  const navigate = useNavigate()
  const leave = () => void navigate({ to: "/login", search: {} })
  const logOut = () =>
    logout.mutate(undefined, {
      onSuccess: leave,
      onError: (error) => {
        if (isRefusal(error, 401)) {
          leave()
        }
      },
    })
  const error = logout.error
  return (
    <>
      <button
        type="button"
        onClick={logOut}
        className={`${ROW} w-full border-transparent hover:bg-accent`}
      >
        <LogOut className={ICON} />
        Log out
      </button>
      {error !== null && !isRefusal(error, 401) && (
        <p role="alert" className="px-3 pt-1 text-xs text-negative">
          Still logged in. {error.message}
        </p>
      )}
    </>
  )
}
