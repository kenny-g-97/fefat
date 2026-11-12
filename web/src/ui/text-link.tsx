import { createLink } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowRight } from "lucide-react"
import type { ComponentProps } from "react"

function TextLinkAnchor({
  children,
  className,
  ...anchor
}: ComponentProps<"a">) {
  return (
    <a
      {...anchor}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-xl font-semibold text-brand-secondary underline-offset-4 hover:underline",
        className
      )}
    >
      {children}
      <ArrowRight className="size-4" />
    </a>
  )
}

/** The skill's text link to another page (web/DESIGN.md, Patterns, Text link): in the second
 * accent with its arrow (D-89), typed as the router's Link, its path and search included. */
export const TextLink = createLink(TextLinkAnchor)
