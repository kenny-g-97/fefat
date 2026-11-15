import type { Dispatch } from "react"
import type { ImportProfile, ListedProfile, TablePreview } from "@/api/imports"
import { Button } from "@/ui/button"
import { KeptField } from "@/ui/kept-field"
import { Panel } from "@/ui/panel"
import { Choice, Picker } from "../Picker"
import type { Draft, DraftChange } from "./import-draft"
import { shownRoles } from "./import-profile"
import { listedProfile } from "./import-request"
import { withRole } from "./import-roles"
import { ProfileForm } from "./ProfileForm"
import { Rows } from "./Rows"

type LayoutCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  profiles: readonly ListedProfile[]
  table: TablePreview | null
}>

/** The wizard's second card: the profile the file reads with, a preset, one the trader saved,
 * or a new one made from either, and the file's first rows under the columns' roles. */
export function LayoutCard({
  draft,
  change,
  profiles,
  table,
}: LayoutCardProps) {
  const profile = draft.profile
  const chosen =
    profile.kind === "listed"
      ? profile.name
      : profile.kind === "new"
        ? profile.base
        : ""
  const options = profiles.map((listed) => ({
    value: listed.profile.name,
    label:
      listed.origin === "saved"
        ? `${listed.profile.name}, yours`
        : listed.profile.name,
  }))
  return (
    <Panel
      title="Layout"
      description="How the file's fields read: a preset, a profile you saved, or a new one made from either"
    >
      <div className="flex flex-col gap-5" data-testid="import-layout">
        <div className="flex flex-wrap items-end gap-4">
          <Choice
            id="import-profile"
            label={profile.kind === "new" ? "Made from" : "Profile"}
          >
            <Picker
              id="import-profile"
              value={chosen}
              options={options}
              placeholder="Choose a profile"
              className="w-72"
              onChange={(name) => change({ kind: "listed profile", name })}
            />
          </Choice>
          {profile.kind === "listed" && (
            <Button
              variant="ghost"
              data-testid="new-profile"
              onClick={() =>
                change({
                  kind: "new profile",
                  base: listedProfile(profiles, profile.name),
                })
              }
            >
              Make a new profile from it
            </Button>
          )}
        </div>
        {profile.kind === "listed" && (
          <ListedLayout
            profile={listedProfile(profiles, profile.name)}
            timeZone={draft.timeZone}
            change={change}
          />
        )}
        {profile.kind === "new" && (
          <ProfileForm fields={profile.fields} change={change} />
        )}
        {table !== null && (
          <Rows
            table={table}
            roles={
              profile.kind === "new"
                ? shownRoles(
                    listedProfile(profiles, profile.base),
                    profile.fields,
                    table
                  )
                : null
            }
            ticks={
              profile.kind === "new" && profile.fields.timeframe === "ticks"
            }
            onRole={(index, role, shown) =>
              change({
                kind: "profile fields",
                fields: {
                  roles: {
                    kind: "chosen",
                    roles: withRole(shown, index, role),
                  },
                },
              })
            }
          />
        )}
      </div>
    </Panel>
  )
}

type ListedLayoutProps = Readonly<{
  profile: ImportProfile
  timeZone: string
  change: Dispatch<DraftChange>
}>

/** A listed profile's description, and its time zone's field where it leaves the time zone to
 * the import, as the IBKR and TradeStation presets do. */
function ListedLayout({ profile, timeZone, change }: ListedLayoutProps) {
  return (
    <div className="flex flex-col gap-5">
      <p className="text-foreground-secondary">{profile.description}</p>
      {profile.timestamp.time_zone === null && (
        <Choice id="import-time-zone" label="Time zone of the file's times">
          <KeptField
            id="import-time-zone"
            value={timeZone}
            placeholder="America/New_York"
            className="w-72"
            onKeep={(typed) => change({ kind: "time zone", timeZone: typed })}
          />
        </Choice>
      )}
    </div>
  )
}
