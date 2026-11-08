import { useState } from "react"
import type { components } from "@/api/schema"
import { Button } from "@/ui/button"

type IssuedApiToken = components["schemas"]["IssuedApiToken"]
type Copying = "not yet" | "copied" | "refused"

/** A token just made, shown this once: the server keeps its hash alone, so leaving the page
 * loses it. */
export function IssuedToken({ issued }: Readonly<{ issued: IssuedApiToken }>) {
  const [copying, setCopying] = useState<Copying>("not yet")
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issued.token)
      setCopying("copied")
    } catch {
      setCopying("refused")
    }
  }
  return (
    <div
      data-testid="new-token"
      className="flex flex-col gap-3 rounded-xl border bg-muted p-4"
    >
      <p>Copy the token of {issued.name} now: it is not shown again</p>
      <div className="flex items-center gap-2">
        <code data-testid="new-token-value" className="min-w-0 flex-1 truncate">
          {issued.token}
        </code>
        <Button size="sm" onClick={() => void copy()}>
          {copying === "copied" ? "Copied" : "Copy"}
        </Button>
      </div>
      {copying === "refused" && (
        <p role="alert" className="text-xs text-negative">
          Copy failed: select the token and press Ctrl+C.
        </p>
      )}
    </div>
  )
}
