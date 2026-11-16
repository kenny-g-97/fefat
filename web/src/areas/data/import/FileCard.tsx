import { useQuery } from "@tanstack/react-query"
import { type Dispatch, useState } from "react"
import { type FilesCopied, useUploads } from "@/api/imports"
import type { components } from "@/api/schema"
import { settingsQuery } from "@/api/settings"
import { Button } from "@/ui/button"
import { FileDrop } from "@/ui/file-drop"
import { counted } from "@/ui/figures"
import { KeptField } from "@/ui/kept-field"
import { Label } from "@/ui/label"
import { Panel } from "@/ui/panel"
import { SectionFailure } from "@/ui/section-failure"
import { Segmented } from "@/ui/segmented"
import type { Draft, DraftChange, Reading } from "./import-draft"
import type { LatestPreview } from "./import-preview"
import { FILES_AT_MOST } from "./import-reviews"

type AppSettings = components["schemas"]["AppSettings"]

const READINGS = [
  { value: "file", label: "A file of your own" },
  { value: "batch", label: "A Databento batch" },
] satisfies readonly { value: Reading; label: string }[]

type FileCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  table: LatestPreview
}>

/** The wizard's first card: a file of the trader's own, chosen and copied into FEAT's folder,
 * or named by its path under the import roots, or a Databento batch by its folder's path; and
 * whether the file reads as a table. */
export function FileCard({ draft, change, table }: FileCardProps) {
  const [typing, setTyping] = useState(draft.source.kind === "path")
  const typed = typing || draft.reading === "batch"
  return (
    <Panel
      title="File"
      description="What to import, copied into FEAT's folder on this PC and sent nowhere else"
    >
      <div className="flex flex-col gap-5" data-testid="import-file">
        <div>
          <Segmented
            label="What to import"
            options={READINGS}
            value={draft.reading}
            onChange={(reading) => change({ kind: "reading", reading })}
          />
        </div>
        {typed ? (
          <TypedPath draft={draft} change={change} />
        ) : (
          <ChosenFile draft={draft} change={change} />
        )}
        {draft.reading === "file" && (
          <Button
            variant="ghost"
            className="self-start"
            onClick={() => {
              setTyping(!typing)
              change({ kind: "source", source: { kind: "none" } })
            }}
          >
            {typing ? "Choose files instead" : "Type a path instead"}
          </Button>
        )}
        <TableState table={table} />
      </div>
    </Panel>
  )
}

/** The files chosen, copied into FEAT's folder one after another (D-102): how far the copy
 * has come, the files kept, and each file the server refused, with why; more than
 * `FILES_AT_MOST` are refused before any is copied. */
function ChosenFile({
  draft,
  change,
}: Readonly<{ draft: Draft; change: Dispatch<DraftChange> }>) {
  const uploads = useUploads()
  const [chosen, setChosen] = useState(0)
  const kept = draft.source.kind === "uploads" ? draft.source.uploads : null
  const tooMany = chosen > FILES_AT_MOST
  return (
    <div className="flex flex-col gap-2">
      <FileDrop
        id="import-file-input"
        disabled={uploads.isPending}
        onFiles={(files) => {
          setChosen(files.length)
          if (files.length <= FILES_AT_MOST) {
            uploads.mutate(files, {
              onSuccess: (copied) => keep(copied, change),
            })
          }
        }}
      />
      {uploads.isPending && (
        <p className="text-xs text-muted-foreground">
          {chosen === 1
            ? "Copying the file into FEAT's folder"
            : `Copying file ${Math.min(uploads.copied + 1, chosen)} of ${chosen} into FEAT's folder`}
        </p>
      )}
      {tooMany && (
        <p role="alert" className="text-negative">
          {`Expected ${FILES_AT_MOST} files at most in one import, got ${chosen}: choose fewer, and import the others next.`}
        </p>
      )}
      {uploads.error !== null && !tooMany && (
        <p role="alert" className="text-negative">
          {uploads.error.message}
        </p>
      )}
      {uploads.data !== undefined && !uploads.isPending && !tooMany && (
        <ul className="flex flex-col gap-1 text-negative" role="alert">
          {uploads.data.refused.map((refused) => (
            <li key={refused.name}>{`${refused.name}: ${refused.message}`}</li>
          ))}
        </ul>
      )}
      {kept !== null && !uploads.isPending && (
        <p data-testid="import-chosen" className="text-foreground-secondary">
          <span className="font-medium text-foreground">{kept[0].name}</span>
          {kept.length > 1 &&
            ` and ${counted(kept.length - 1, "more file")}`},{" "}
          {sizeText(kept.reduce((total, each) => total + each.size, 0))}, copied
          into FEAT's folder on this PC
        </p>
      )}
    </div>
  )
}

/** The files `copied` as the draft's source, where any was. */
function keep(copied: FilesCopied, change: Dispatch<DraftChange>) {
  const [first, ...others] = copied.uploads
  if (first !== undefined) {
    change({
      kind: "source",
      source: { kind: "uploads", uploads: [first, ...others] },
    })
  }
}

function TypedPath({
  draft,
  change,
}: Readonly<{ draft: Draft; change: Dispatch<DraftChange> }>) {
  const settings = useQuery(settingsQuery)
  const path = draft.source.kind === "path" ? draft.source.path : ""
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="import-path">
        {draft.reading === "batch" ? "Batch folder" : "Path"}
      </Label>
      <KeptField
        id="import-path"
        value={path}
        placeholder={
          draft.reading === "batch"
            ? "The folder Databento's download unpacked to"
            : "The file's full path"
        }
        describedBy="import-roots"
        onKeep={(typed) =>
          change({ kind: "source", source: { kind: "path", path: typed } })
        }
      />
      <p
        id="import-roots"
        data-testid="import-roots"
        className="text-xs text-muted-foreground"
      >
        {rootsNote(settings.data)}
      </p>
    </div>
  )
}

/** Where FEAT reads a typed path, and the file that says so, which the trader edits by hand,
 * since the app never widens what it may read (plan call 2). */
function rootsNote(settings: AppSettings | undefined): string {
  if (settings === undefined) {
    return "FEAT reads a path under one of the import roots of its config.toml."
  }
  const roots = settings.server.import_roots
  if (roots.length === 0) {
    return `FEAT reads a path under one of its import roots, and has none yet: add a folder to import_roots in ${settings.config_file}, then start FEAT again.`
  }
  return `FEAT reads a path under one of its import roots, ${roots.join(", ")}, which import_roots in ${settings.config_file} lists.`
}

function TableState({ table }: Readonly<{ table: LatestPreview }>) {
  if (table.error !== null) {
    return <SectionFailure error={table.error} onRetry={table.readAgain} />
  }
  if (table.answer?.kind === "refused" && table.current) {
    return (
      <p role="alert" className="text-negative">
        {table.answer.message}
      </p>
    )
  }
  if (table.reading) {
    return <p className="text-xs text-muted-foreground">Reading the file</p>
  }
  return null
}

/** A file's size in the unit that keeps its figure short. */
function sizeText(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} bytes`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}
