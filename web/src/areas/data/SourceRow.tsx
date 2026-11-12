import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"
import type { Source } from "@/api/catalog"
import { TextLink } from "@/ui/text-link"

const KINDS: Readonly<Record<Source["kind"], string>> = {
  vendor: "Vendor",
  "exchange-archive": "Exchange archive",
  platform: "Platform",
}
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
    <details
      data-testid="source-row"
      className="group border-b last:border-b-0"
    >
      <summary className="flex h-10 cursor-pointer list-none items-center gap-3 rounded-xl">
        <ChevronRight className="size-4 shrink-0 text-foreground-secondary transition-transform group-open:rotate-90" />
        <span className="font-medium text-foreground">{source.name}</span>
        <span className="text-xs text-muted-foreground">
          {KINDS[source.kind]}
        </span>
        {available.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {available.length === 1
              ? "1 preset"
              : `${available.length} presets`}
          </span>
        )}
      </summary>
      <dl className="grid max-w-4xl grid-cols-[10rem_1fr] gap-x-6 gap-y-3 pt-2 pb-5 pl-7">
        <Term label="Offers">{source.offers}</Term>
        <Term label="Cost">{source.cost}</Term>
        <Term label="Terms">
          {source.terms}
          {source.terms_page !== null && (
            <>
              {" "}
              <a
                href={source.terms_page}
                target="_blank"
                rel="noreferrer"
                className="font-semibold text-brand-secondary underline-offset-4 hover:underline"
              >
                Terms page
              </a>
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
    </details>
  )
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
