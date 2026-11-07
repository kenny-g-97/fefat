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
import { Monogram } from "@/ui/monogram"

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

const ROW =
  "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-foreground-secondary outline-none hover:bg-sidebar-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring"
const ICON = "mx-1 size-4 shrink-0 text-muted-foreground"

/** The shell's sidebar (web/DESIGN.md, Patterns): the mark, the areas, then Settings, Log
 * out, and the app's version. */
export function Sidebar() {
  const versions = useQuery(versionsQuery)
  return (
    <aside className="w-60 shrink-0 border-r border-sidebar-border bg-sidebar">
      <div className="sticky top-0 flex h-screen flex-col px-3 pb-4">
        <Link
          to="/"
          aria-label="FEFAT, the home page"
          className="flex h-14 items-center gap-2 rounded-md px-2 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          <Monogram className="size-6" />
          <span className="text-base font-semibold">FEFAT</span>
        </Link>
        <nav aria-label="Main" className="flex flex-1 flex-col">
          <ul className="flex flex-col gap-0.5">
            {AREAS.map((area) => (
              <SidebarLink key={area.label} destination={area} />
            ))}
          </ul>
          <ul className="mt-auto flex flex-col gap-0.5">
            <SidebarLink destination={SETTINGS} />
            <li>
              <LogOutRow />
            </li>
          </ul>
        </nav>
        <div className="mt-4 px-2">
          <IdentityChip testId="version">
            {versions.data === undefined
              ? "FEFAT"
              : `FEFAT ${versions.data.fefat_app}`}
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
        className={`${ROW} group data-[status=active]:bg-sidebar-accent data-[status=active]:font-medium data-[status=active]:text-foreground`}
      >
        <Icon
          strokeWidth={1.5}
          className={`${ICON} group-data-[status=active]:text-primary`}
        />
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
      <button type="button" onClick={logOut} className={`${ROW} w-full`}>
        <LogOut strokeWidth={1.5} className={ICON} />
        Log out
      </button>
      {error !== null && !isRefusal(error, 401) && (
        <p role="alert" className="px-2 pt-1 text-caption text-negative">
          Still logged in: {error.message}
        </p>
      )}
    </>
  )
}
