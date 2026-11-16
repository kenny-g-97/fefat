import type { Dispatch } from "react"
import type { ImportProfile, ListedProfile } from "@/api/imports"
import { KeptField } from "@/ui/kept-field"
import { Panel } from "@/ui/panel"
import { Choice } from "../Picker"
import { type Draft, type DraftChange, NEW_INSTRUMENT } from "./import-draft"
import { listedProfile } from "./import-request"
import { InstrumentForm } from "./InstrumentForm"
import { type Choice as Option, RadioChoice } from "./RadioChoice"

const INSTRUMENTS: readonly Option<Draft["instrument"]["kind"]>[] = [
  { value: "profile's", label: "As the profile and the file name" },
  { value: "new", label: "A new instrument" },
]

type InstrumentCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  profiles: readonly ListedProfile[]
}>

/** The wizard's third card: the contract and the root, where the file's name does not say
 * them, the contract hidden where several files are chosen, each file's name giving its own
 * (D-102); and the instrument: under a listed profile, the one it reads its records as; for a
 * new profile, that one or a new one, which the profile carries and the import saves for later
 * imports and loads. */
export function InstrumentCard({
  draft,
  change,
  profiles,
}: InstrumentCardProps) {
  const profile = draft.profile
  const several =
    draft.source.kind === "uploads" && draft.source.uploads.length > 1
  return (
    <Panel
      title="Instrument"
      description="Which contract the records are of, where the file's name does not say, and a new instrument's specification"
    >
      <div className="flex flex-col gap-5" data-testid="import-instrument">
        <div className="flex flex-wrap gap-5">
          {!several && (
            <Choice id="import-contract" label="Contract">
              <KeptField
                id="import-contract"
                value={draft.contract}
                placeholder="From the file's name"
                className="w-56"
                onKeep={(contract) =>
                  change({ kind: "contract", contract: contract.toUpperCase() })
                }
              />
            </Choice>
          )}
          <Choice id="import-root" label="Root of a continuous series">
            <KeptField
              id="import-root"
              value={draft.root}
              placeholder="None"
              className="w-56"
              onKeep={(root) =>
                change({ kind: "root", root: root.toUpperCase() })
              }
            />
          </Choice>
        </div>
        {several && (
          <p
            className="text-foreground-secondary"
            data-testid="several-contracts"
          >
            Each file's name gives its contract.
          </p>
        )}
        {profile.kind === "new" && (
          <RadioChoice
            id="import-instrument"
            label="Instrument"
            options={INSTRUMENTS}
            value={draft.instrument.kind}
            onChange={(kind) =>
              change({
                kind: "instrument",
                instrument:
                  kind === "new"
                    ? { kind: "new", fields: NEW_INSTRUMENT }
                    : { kind: "profile's" },
              })
            }
          />
        )}
        {profile.kind === "listed" && (
          <p
            className="text-foreground-secondary"
            data-testid="profile-instrument"
          >
            {`${readsAs(listedProfile(profiles, profile.name))} Another instrument needs a new profile, under Layout.`}
          </p>
        )}
        {draft.instrument.kind === "new" && (
          <InstrumentForm fields={draft.instrument.fields} change={change} />
        )}
      </div>
    </Panel>
  )
}

/** What instrument a listed profile reads its records as, in one sentence. */
function readsAs(profile: ImportProfile): string {
  const instrument = profile.instrument
  if (typeof instrument === "string") {
    return `${profile.name} reads its records as ${instrument}.`
  }
  if (instrument === null || instrument === undefined) {
    return `${profile.name} reads the instrument from the file's name or the contract typed.`
  }
  return `${profile.name} reads its records as ${instrument.root}, an instrument it carries.`
}
