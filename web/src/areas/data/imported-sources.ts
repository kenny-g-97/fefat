import type { Source } from "@/api/catalog"

/** A source's kind in words. */
export const SOURCE_KINDS: Readonly<Record<Source["kind"], string>> = {
  vendor: "Vendor",
  "exchange-archive": "Exchange archive",
  platform: "Platform",
}

/** What stands for its kind beside a provider the guide lists under no source. */
const UNLISTED = "Not in the source guide"

/** Where rows of the imported data came from, as the Data page's Sources card names it: a
 * source of the guide, or a provider the guide lists under none. */
type Named = Readonly<{ key: string; name: string; note: string }>

/** A source the trader imported from, with the rows held from it. */
export type ImportedSource<Row> = Named & Readonly<{ rows: readonly Row[] }>

/** The sources `rows` came from, each once in the order the list first shows it, with its rows.
 * A row's source is the one whose presets name its provider, since a preset's id is the
 * provider its datasets are stored under; a provider no preset names, a trader's own import
 * profile, stands for itself, apart from any source, whatever it is called. */
export function importedSources<Row extends Readonly<{ provider: string }>>(
  rows: readonly Row[],
  sources: readonly Source[]
): readonly ImportedSource<Row>[] {
  const named = rows.map((row) => ({
    row,
    source: sourceOf(row.provider, sources),
  }))
  const once = new Map(named.map(({ source }) => [source.key, source]))
  return [...once.values()].map((source) => ({
    ...source,
    rows: named
      .filter((each) => each.source.key === source.key)
      .map((each) => each.row),
  }))
}

function sourceOf(provider: string, sources: readonly Source[]): Named {
  const source = sources.find((each) =>
    each.presets.some((preset) => preset.id === provider)
  )
  // A folder name holds no space, so a source's key and a provider's never meet.
  return source === undefined
    ? { key: `provider ${provider}`, name: provider, note: UNLISTED }
    : {
        key: `source ${source.id}`,
        name: source.name,
        note: SOURCE_KINDS[source.kind],
      }
}
