import type { Dispatch } from "react"
import { KeptField } from "@/ui/kept-field"
import { Panel } from "@/ui/panel"
import { Segmented } from "@/ui/segmented"
import { Choice } from "../Picker"
import { type Draft, type DraftChange, NEW_INSTRUMENT } from "./import-draft"
import { InstrumentForm } from "./InstrumentForm"

const INSTRUMENTS = [
  { value: "profile's", label: "As the profile and the file name" },
  { value: "new", label: "A new instrument" },
] satisfies readonly { value: Draft["instrument"]["kind"]; label: string }[]

type InstrumentCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** The wizard's third card: the contract and the root, where the file's name does not say
 * them, and the instrument, the one the profile and the file name give, or, for a new profile,
 * a new one, which the profile carries and the import saves for later imports and loads. */
export function InstrumentCard({ draft, change }: InstrumentCardProps) {
  const made = draft.profile.kind === "new"
  return (
    <Panel
      title="Instrument"
      description="Which contract the records are of, where the file's name does not say, and a new instrument's specification"
    >
      <div className="flex flex-col gap-5" data-testid="import-instrument">
        <div className="flex flex-wrap gap-4">
          <Choice id="import-contract" label="Contract">
            <KeptField
              id="import-contract"
              value={draft.contract}
              placeholder="From the file's name"
              className="w-48"
              onKeep={(contract) =>
                change({ kind: "contract", contract: contract.toUpperCase() })
              }
            />
          </Choice>
          <Choice id="import-root" label="Root of a continuous series">
            <KeptField
              id="import-root"
              value={draft.root}
              placeholder="None"
              className="w-48"
              onKeep={(root) =>
                change({ kind: "root", root: root.toUpperCase() })
              }
            />
          </Choice>
        </div>
        {made ? (
          <Segmented
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
        ) : (
          <p className="text-foreground-secondary">
            A new instrument goes into a profile of your own: make one under
            Layout.
          </p>
        )}
        {draft.instrument.kind === "new" && (
          <InstrumentForm fields={draft.instrument.fields} change={change} />
        )}
      </div>
    </Panel>
  )
}
