import type { Dispatch } from "react"
import type {
  FileSeen,
  ImportProfile,
  ListedProfile,
  TablePreview,
} from "@/api/imports"
import { KeptField } from "@/ui/kept-field"
import { Panel } from "@/ui/panel"
import { Choice } from "../Picker"
import { TableState } from "./FileCard"
import type { Draft, DraftChange, ProfileDraft } from "./import-draft"
import type { LatestPreview } from "./import-preview"
import { columnKeys, shownRoles } from "./import-profile"
import { listedProfile, offsetRefusal } from "./import-request"
import { rolesOf, withRole } from "./import-roles"
import { MadeFrom, ProfileChoice } from "./ProfileChoice"
import { ProfileForm } from "./ProfileForm"
import { type ColumnHeads, Rows } from "./Rows"

type LayoutCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  profiles: readonly ListedProfile[]
  table: TablePreview | null
  preview: LatestPreview
  offsets: Readonly<FileSeen["offsets"]>
}>

/** The wizard's second step: the profile the file reads with, a preset, one the trader saved,
 * or a new one made from either, whose base stays fixed while it is drafted, and the file's
 * first rows under the columns' roles, with the table's read as File shows it, since a
 * profile's layout reads the table again (D-105). */
export function LayoutCard({
  draft,
  change,
  profiles,
  table,
  preview,
  offsets,
}: LayoutCardProps) {
  const profile = draft.profile
  return (
    <Panel
      title="Layout"
      description="How the file's fields read: a preset, a profile you saved, or a new one made from either"
    >
      <div className="flex flex-col gap-5" data-testid="import-layout">
        {profile.kind === "new" ? (
          <MadeFrom base={profile.base} change={change} />
        ) : (
          <ProfileChoice
            profile={profile}
            profiles={profiles}
            change={change}
          />
        )}
        {profile.kind === "listed" && (
          <ListedLayout
            profile={listedProfile(profiles, profile.name)}
            timeZone={draft.timeZone}
            change={change}
            refusal={offsetRefusal(offsets, "time zone")}
          />
        )}
        {profile.kind === "new" && (
          <ProfileForm
            fields={profile.fields}
            change={change}
            offsets={offsets}
          />
        )}
        <TableState table={preview} />
        {table !== null && (
          <Rows
            table={table}
            heads={headsOf(profile, profiles, table, change)}
          />
        )}
      </div>
    </Panel>
  )
}

/** What stands over the table's columns: a new profile's role selects, a listed profile's roles,
 * or, before a profile, the file's own names. */
function headsOf(
  profile: ProfileDraft,
  profiles: readonly ListedProfile[],
  table: TablePreview,
  change: Dispatch<DraftChange>
): ColumnHeads {
  switch (profile.kind) {
    case "none":
      return { kind: "names" }
    case "listed": {
      const listed = listedProfile(profiles, profile.name)
      const keys = columnKeys(table, listed.layout.header)
      return { kind: "roles", roles: rolesOf(listed.columns, keys) }
    }
    case "new": {
      const roles = shownRoles(
        listedProfile(profiles, profile.base),
        profile.fields,
        table
      )
      return {
        kind: "selects",
        roles,
        ticks: profile.fields.timeframe === "ticks",
        onRole: (index, role) =>
          change({
            kind: "profile fields",
            fields: {
              roles: { kind: "chosen", roles: withRole(roles, index, role) },
            },
          }),
      }
    }
  }
}

type ListedLayoutProps = Readonly<{
  profile: ImportProfile
  timeZone: string
  change: Dispatch<DraftChange>
  refusal: string | null
}>

/** A listed profile's description, and its time zone's field where it leaves the time zone to
 * the import, as the IBKR and TradeStation presets do, with the latest review's offset under it
 * where one points at the time zone. */
function ListedLayout({
  profile,
  timeZone,
  change,
  refusal,
}: ListedLayoutProps) {
  return (
    <div className="flex flex-col gap-5">
      <p className="text-foreground-secondary">{profile.description}</p>
      {profile.timestamp.time_zone === null && (
        <Choice
          id="import-time-zone"
          label="Time zone of the file's times"
          refusal={refusal}
          className="w-72"
        >
          <KeptField
            id="import-time-zone"
            value={timeZone}
            placeholder="America/New_York"
            className="w-72"
            invalid={refusal !== null}
            describedBy={
              refusal === null ? undefined : "import-time-zone-refusal"
            }
            onKeep={(typed) => change({ kind: "time zone", timeZone: typed })}
          />
        </Choice>
      )}
    </div>
  )
}
