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
type FileLayout = components["schemas"]["FileLayout"]
/** A review's ask, which is also its import's request: a file's or a batch's. */
export type ReviewAsked = Exclude<ImportAsked, Readonly<{ kind: "files" }>>

/** What can be asked of the server now: the file's table, the first file's where several are
 * chosen, once a file is chosen; and once nothing is missing, the review, the preview of what
 * its import would do, which is also the import's request, or where several files are chosen,
 * each file's review instead, its contract the one its name gives (D-102); and what every card
 * still misses, each step of the wizard saying its own (D-105). */
export type Asks = Readonly<{
  table: PreviewAsked | null
  review: ReviewAsked | null
  several: readonly FileImportAsked[]
  missing: readonly Missing[]
}>

/** What `draft` can ask, with the listed profiles it names and the file's table once read. */
export function asksOf(
  draft: Draft,
  profiles: readonly ListedProfile[],
  table: TablePreview | null
): Asks {
  const [source, ...others] = sourcesOf(draft.source)
  if (draft.reading === "batch") {
    return batchAsks(draft, source)
  }
  const profile = profileAsks(draft, profiles, table)
  if (source === undefined) {
    const file: Missing = { card: "file", text: "Choose files, or type a path" }
    return {
      table: null,
      review: null,
      several: [],
      missing: [file, ...profile.missing],
    }
  }
  const asks = fileAsks(draft, source, profile)
  if (others.length === 0 || asks.review === null) {
    return { ...asks, several: [] }
  }
  const first = asks.review
  const several = [source, ...others].map((each): FileImportAsked => ({
    ...first,
    source: each,
    contract: null,
    bars_in_breaks: barsInBreaksOf(draft, each),
  }))
  return { ...asks, review: null, several }
}

/** A Databento batch's asks: its review once its folder's path is typed. */
function batchAsks(draft: Draft, source: AskedSource | undefined): Asks {
  if (source === undefined) {
    const missing: Missing = {
      card: "file",
      text: "Type the path of the batch's folder",
    }
    return { table: null, review: null, several: [], missing: [missing] }
  }
  if (source.kind !== "path") {
    throw new Error("Expected a batch named by its path, got an upload.")
  }
  const review: ReviewAsked = {
    kind: "databento",
    source,
    differing: draft.differing,
  }
  return { table: null, review, several: [], missing: [] }
}

/** What the draft's profile gives the asks of every file, whichever is chosen: the layout the
 * file's table is read with, once a profile sets one; its part of a file's review, once it
 * misses nothing; and what it misses. */
type ProfileAsks = Readonly<{
  layout: FileLayout | null
  review: Pick<FileImportAsked, "profile" | "time_zone"> | null
  missing: readonly Missing[]
}>

function profileAsks(
  draft: Draft,
  profiles: readonly ListedProfile[],
  table: TablePreview | null
): ProfileAsks {
  const profile = draft.profile
  if (profile.kind === "none") {
    const missing: Missing = {
      card: "layout",
      text: "Choose a profile, or make one",
    }
    return { layout: null, review: null, missing: [missing] }
  }
  if (profile.kind === "listed") {
    return listedAsks(draft, listedProfile(profiles, profile.name))
  }
  const base = listedProfile(profiles, profile.base)
  const { delimiter, header } = profile.fields
  const built = profileOf(base, profile.fields, draft.instrument, table)
  if (built.kind === "missing") {
    return {
      layout: { delimiter, header },
      review: null,
      missing: built.missing,
    }
  }
  return {
    layout: { delimiter, header },
    review: { profile: { kind: "given", profile: built.profile } },
    missing: [],
  }
}

/** A listed profile's asks: the time zone the trader typed where the profile leaves it to
 * the import, and none otherwise. */
function listedAsks(draft: Draft, listed: ImportProfile): ProfileAsks {
  const asksZone = listed.timestamp.time_zone === null
  const zone = draft.timeZone.trim()
  if (asksZone && zone === "") {
    const missing: Missing = {
      card: "layout",
      text: "Type the time zone of the file's times",
    }
    return { layout: listed.layout, review: null, missing: [missing] }
  }
  return {
    layout: listed.layout,
    review: {
      profile: { kind: "named", name: listed.name },
      time_zone: asksZone ? zone : null,
    },
    missing: [],
  }
}

/** The asks of the file `source` through the draft's profile: its table, read with the
 * profile's layout once there is one, and its review once the profile misses nothing. */
function fileAsks(
  draft: Draft,
  source: AskedSource,
  profile: ProfileAsks
): Readonly<{
  table: PreviewAsked
  review: FileImportAsked | null
  missing: readonly Missing[]
}> {
  const table: PreviewAsked =
    profile.layout === null
      ? { kind: "table", source }
      : { kind: "table", source, layout: profile.layout }
  const review =
    profile.review === null
      ? null
      : { ...fileFields(draft, source), ...profile.review }
  return { table, review, missing: profile.missing }
}

/** What every file's ask holds beside its profile: the file, the contract and the root typed,
 * what to do with records that differ from the store's, and with the file's bars in a break. */
function fileFields(
  draft: Draft,
  source: AskedSource
): Pick<
  FileImportAsked,
  "kind" | "source" | "contract" | "root" | "differing" | "bars_in_breaks"
> {
  return {
    kind: "file",
    source,
    contract: blankAsNull(draft.contract),
    root: blankAsNull(draft.root),
    differing: draft.differing,
    bars_in_breaks: barsInBreaksOf(draft, source),
  }
}

/** Whether the import leaves out the bars in a break of the file `source` and the sessions
 * beside them, as the trader approved for that file (ADR-0022). */
function barsInBreaksOf(
  draft: Draft,
  source: AskedSource
): FileImportAsked["bars_in_breaks"] {
  return draft.breaksLeftOut.includes(fileOf(source)) ? "leave-out" : "refuse"
}

/** The file `source` names, by its upload's id or its path. */
export function fileOf(source: AskedSource): string {
  return source.kind === "upload" ? source.upload_id : source.path
}

/** The files `source` names, each by its upload's id or its path, as the draft names the
 * files whose bars in a break are left out. */
export function filesOf(source: Source): readonly string[] {
  return sourcesOf(source).map(fileOf)
}

function sourcesOf(source: Source): readonly AskedSource[] {
  switch (source.kind) {
    case "none":
      return []
    case "uploads":
      return source.uploads.map((upload) => ({
        kind: "upload",
        upload_id: upload.id,
      }))
    case "path": {
      const path = source.path.trim()
      return path === "" ? [] : [{ kind: "path", path }]
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

type OffsetSeen = components["schemas"]["OffsetSeen"]

const POINTS_AT: Readonly<
  Record<"time zone" | "bar stamp", readonly OffsetSeen["cause"][]>
> = {
  "time zone": ["time-zone", "time-zone-or-bar-stamping"],
  "bar stamp": ["bar-stamping", "time-zone-or-bar-stamping"],
}

/** What the latest review's offset says under the field it points at (web/DESIGN.md, Forms):
 * the time zone's, or the bar's timestamp's; none where no offset points there. */
export function offsetRefusal(
  offsets: readonly OffsetSeen[],
  field: "time zone" | "bar stamp"
): string | null {
  const offset = offsets.find((each) => POINTS_AT[field].includes(each.cause))
  return offset === undefined
    ? null
    : `The records run ${offset.duration} ${offset.direction} against their calendar`
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
