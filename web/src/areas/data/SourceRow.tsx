import type { ReactNode } from "react"
import type { Source } from "@/api/catalog"
import { ExternalLink, TextLink } from "@/ui/text-link"
import { DisclosureRow } from "./DisclosureRow"
import { SOURCE_KINDS } from "./imported-sources"

const DESKTOP_USE: Readonly<Record<Source["desktop_use"], string>> = {
  confirmed: "Confirmed by the source in writing",
  "check-the-terms": "Check the terms yourself",
  forbidden: "Forbidden by its terms",
}

/** A source of the guide behind a disclosure (web/DESIGN.md, Patterns, Disclosure row): its name,
 * its kind, and how many of its file layouts FEAT imports; open, what it offers and costs, its
 * terms with their page, whether a desktop app may use your account or files, the licence it
 * gives you, and its presets, each with an Import where FEAT reads its files. */
export function SourceRow({ source }: Readonly<{ source: Source }>) {
  const available = source.presets.filter(
    (preset) => preset.status === "available"
  )
  return (
    <DisclosureRow
      testId="source-row"
      name={source.name}
      note={SOURCE_KINDS[source.kind]}
      aside={presetCount(available.length)}
    >
      <dl className="grid max-w-4xl grid-cols-[10rem_1fr] gap-x-6 gap-y-3 pt-2 pb-5 pl-7">
        <Term label="Offers">{source.offers}</Term>
        <Term label="Cost">{source.cost}</Term>
        <Term label="Terms">
          {source.terms}
          {source.terms_page !== null && (
            <>
              {" "}
              <ExternalLink href={source.terms_page}>Terms page</ExternalLink>
            </>
          )}
        </Term>
        <Term label="Desktop use">
          {DESKTOP_USE[source.desktop_use]}. {source.desktop_use_note}
        </Term>
        <Term label="Your licence">{source.licence_scope}</Term>
        {source.presets.length > 0 && (
          <Term label="Presets">
            <ul className="flex flex-col gap-3">
              {source.presets.map((preset) => (
                <li key={preset.id} className="flex flex-col items-start gap-1">
                  <span className="font-medium text-foreground">
                    {preset.name}
                    {preset.status === "planned" && (
                      <span className="pl-2 text-xs text-muted-foreground">
                        planned
                      </span>
                    )}
                  </span>
                  <span>{preset.reads}</span>
                  {preset.status === "available" && (
                    <TextLink to="/data/import" search={{ preset: preset.id }}>
                      Import with {preset.name}
                    </TextLink>
                  )}
                </li>
              ))}
            </ul>
          </Term>
        )}
      </dl>
    </DisclosureRow>
  )
}

/** How many of a source's file layouts FEAT imports, in words, or nothing where it reads none. */
function presetCount(available: number): string | undefined {
  if (available === 0) {
    return undefined
  }
  return available === 1 ? "1 preset" : `${available} presets`
}

function Term({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <>
      <dt className="font-medium text-foreground">{label}</dt>
      <dd className="text-foreground-secondary">{children}</dd>
    </>
  )
}
