import { createLink, type LinkComponent } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowLeft, ArrowRight } from "lucide-react"
import type { ComponentProps, ReactNode } from "react"

const LINK_LOOK =
  "rounded-xl font-semibold text-brand-secondary underline-offset-4 hover:underline"
const TEXT_LINK = `inline-flex shrink-0 items-center gap-1.5 ${LINK_LOOK}`

function TextLinkAnchor({
  children,
  className,
  ...anchor
}: ComponentProps<"a">) {
  return (
    <a {...anchor} className={cn(TEXT_LINK, className)}>
      {children}
      <ArrowRight className="size-4" />
    </a>
  )
}

function BackLinkAnchor({
  children,
  className,
  ...anchor
}: ComponentProps<"a">) {
  return (
    <a {...anchor} className={cn(TEXT_LINK, className)}>
      <ArrowLeft className="size-4" />
      {children}
    </a>
  )
}

/** The skill's text link to another page (web/DESIGN.md, Patterns, Text link): in the second
 * accent with its arrow (D-89), typed as the router's Link, its path and search included. */
export const TextLink = createLink(TextLinkAnchor)

const BackLinkTo = createLink(BackLinkAnchor)

/** A link out of FEAT within a sentence (web/DESIGN.md, Patterns, Text link): the text link's
 * colour and underline without its arrow, opened in a new tab that gets no hold on this one. */
export function ExternalLink({
  href,
  children,
}: Readonly<{ href: string; children: ReactNode }>) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={LINK_LOOK}>
      {children}
    </a>
  )
}

/** The text link above a page's title back to its area's page (web/DESIGN.md, Patterns, Page
 * header), its arrow before its label; matched exactly, so that it is never marked as the
 * current page on a page whose path starts with its own. */
export const BackLink: LinkComponent<typeof BackLinkAnchor> = (props) => (
  <BackLinkTo activeOptions={{ exact: true }} {...props} />
)
