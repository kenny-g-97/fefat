import { useState } from "react"
import type { components } from "@/api/schema"
import { Button } from "@/ui/button"

type IssuedApiToken = components["schemas"]["IssuedApiToken"]

/** A token just made, shown this once: the server keeps its hash alone, so leaving the page
 * loses it. */
export function IssuedToken({ issued }: Readonly<{ issued: IssuedApiToken }>) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(issued.token)
    setCopied(true)
  }
  return (
    <div
      data-testid="new-token"
      className="flex flex-col gap-2 rounded-lg border bg-muted p-4"
    >
      <p className="text-sm">
        Copy the token of {issued.name} now: it is not shown again.
      </p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-sm">
          {issued.token}
        </code>
        <Button variant="secondary" size="sm" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  )
}
