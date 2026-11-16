import type { Dispatch } from "react"
import type { ListedProfile } from "@/api/imports"
import { Button } from "@/ui/button"
import { Choice, Picker } from "../Picker"
import type { DraftChange, ProfileDraft } from "./import-draft"
import { listedProfile } from "./import-request"

type ProfileChoiceProps = Readonly<{
  profile: Exclude<ProfileDraft, { kind: "new" }>
  profiles: readonly ListedProfile[]
  change: Dispatch<DraftChange>
}>

/** The Layout card's choice of a listed profile, a preset or one the trader saved, named
 * "yours", and Make a new profile from it once one is chosen. */
export function ProfileChoice({
  profile,
  profiles,
  change,
}: ProfileChoiceProps) {
  const options = profiles.map((listed) => ({
    value: listed.profile.name,
    label:
      listed.origin === "saved"
        ? `${listed.profile.name}, yours`
        : listed.profile.name,
  }))
  return (
    <div className="flex flex-wrap items-end gap-4">
      <Choice id="import-profile" label="Profile">
        <Picker
          id="import-profile"
          value={profile.kind === "listed" ? profile.name : ""}
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
  )
}

/** A new profile's base, fixed while it is drafted, since another base would start the draft
 * anew; Use it as it is, in the place of Make a new profile from it, leaves the new profile. */
export function MadeFrom({
  base,
  change,
}: Readonly<{ base: string; change: Dispatch<DraftChange> }>) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <p className="text-foreground-secondary" data-testid="made-from">
        Made from <span className="font-medium text-foreground">{base}</span>
      </p>
      <Button
        variant="ghost"
        data-testid="use-base"
        onClick={() => change({ kind: "listed profile", name: base })}
      >
        {`Use ${base} as it is`}
      </Button>
    </div>
  )
}
