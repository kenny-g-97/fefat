import type {
  ImportAsked,
  ImportProfile,
  ListedProfile,
  PreviewAsked,
  TablePreview,
} from "@/api/imports"
import type { components } from "@/api/schema"
import type { Draft, Missing, Source } from "./import-draft"
import { profileOf } from "./import-profile"

type FileImportAsked = components["schemas"]["FileImportAsked"]
type AskedSource = FileImportAsked["source"]

/** What can be asked of the server now: the file's table, once a file is chosen, and the
 * review, the preview of what its import would do, which is also the import's request, once
 * nothing is missing. */
export type Asks = Readonly<{
  table: PreviewAsked | null
  review: ImportAsked | null
  missing: readonly Missing[]
}>

/** What `draft` can ask, with the listed profiles it names and the file's table once read. */
export function asksOf(
  draft: Draft,
  profiles: readonly ListedProfile[],
  table: TablePreview | null
): Asks {
  const source = sourceOf(draft.source)
  if (source === null) {
    const text =
      draft.reading === "batch"
        ? "Type the path of the batch's folder"
        : "Choose a file, or type its path"
    return { table: null, review: null, missing: [{ card: "file", text }] }
  }
  if (draft.reading === "batch") {
    if (source.kind !== "path") {
      throw new Error("Expected a batch named by its path, got an upload.")
    }
    const review: ImportAsked = {
      kind: "databento",
      source,
      differing: draft.differing,
    }
    return { table: null, review, missing: [] }
  }
  return fileAsks(draft, source, profiles, table)
}

function fileAsks(
  draft: Draft,
  source: AskedSource,
  profiles: readonly ListedProfile[],
  table: TablePreview | null
): Asks {
  const profile = draft.profile
  if (profile.kind === "none") {
    return {
      table: { kind: "table", source },
      review: null,
      missing: [{ card: "layout", text: "Choose a profile, or make one" }],
    }
  }
  if (profile.kind === "listed") {
    return listedAsks(draft, source, listedProfile(profiles, profile.name))
  }
  const base = listedProfile(profiles, profile.base)
  const { delimiter, header } = profile.fields
  const tableAsked: PreviewAsked = {
    kind: "table",
    source,
    layout: { delimiter, header },
  }
  const built = profileOf(base, profile.fields, draft.instrument, table)
  if (built.kind === "missing") {
    return { table: tableAsked, review: null, missing: built.missing }
  }
  const review: FileImportAsked = {
    ...fileFields(draft, source),
    profile: { kind: "given", profile: built.profile },
  }
  return { table: tableAsked, review, missing: [] }
}

/** A listed profile's asks: the time zone the trader typed where the profile leaves it to
 * the import, and none otherwise. */
function listedAsks(
  draft: Draft,
  source: AskedSource,
  listed: ImportProfile
): Asks {
  const tableAsked: PreviewAsked = {
    kind: "table",
    source,
    layout: listed.layout,
  }
  const asksZone = listed.timestamp.time_zone === null
  const zone = draft.timeZone.trim()
  if (asksZone && zone === "") {
    const missing: Missing = {
      card: "layout",
      text: "Type the time zone of the file's times",
    }
    return { table: tableAsked, review: null, missing: [missing] }
  }
  const review: FileImportAsked = {
    ...fileFields(draft, source),
    profile: { kind: "named", name: listed.name },
    time_zone: asksZone ? zone : null,
  }
  return { table: tableAsked, review, missing: [] }
}

/** What every file's ask holds beside its profile: the file, the contract and the root typed,
 * and what to do with records that differ from the store's. */
function fileFields(
  draft: Draft,
  source: AskedSource
): Pick<
  FileImportAsked,
  "kind" | "source" | "contract" | "root" | "differing"
> {
  return {
    kind: "file",
    source,
    contract: blankAsNull(draft.contract),
    root: blankAsNull(draft.root),
    differing: draft.differing,
  }
}

function sourceOf(source: Source): AskedSource | null {
  switch (source.kind) {
    case "none":
      return null
    case "upload":
      return { kind: "upload", upload_id: source.upload.id }
    case "path": {
      const path = source.path.trim()
      return path === "" ? null : { kind: "path", path }
    }
  }
}

/** The time zone the draft reads the file's times in: a new profile's, a listed profile's own,
 * or the one typed where it leaves it to the import; none before a profile. */
export function zoneOf(
  draft: Draft,
  profiles: readonly ListedProfile[]
): string | null {
  const profile = draft.profile
  switch (profile.kind) {
    case "none":
      return null
    case "new":
      return blankAsNull(profile.fields.timeZone)
    case "listed": {
      const own = listedProfile(profiles, profile.name).timestamp.time_zone
      return own === null ? blankAsNull(draft.timeZone) : own
    }
  }
}

/** The profile named `name` among `profiles`; a draft names only a listed one. */
export function listedProfile(
  profiles: readonly ListedProfile[],
  name: string
): ImportProfile {
  const found = profiles.find((listed) => listed.profile.name === name)
  if (found === undefined) {
    throw new Error(`Expected a listed profile named ${name}, got none.`)
  }
  return found.profile
}

function blankAsNull(text: string): string | null {
  const trimmed = text.trim()
  return trimmed === "" ? null : trimmed
}
