import { useState } from "react"
import { useTokenRevocation } from "@/api/api-tokens"
import type { components } from "@/api/schema"
import { Button } from "@/ui/button"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"

type ApiToken = components["schemas"]["ApiToken"]

/** The live API tokens, one 32 px row each: the name, when it was made and last used, and
 * its revocation, which asks once inline, since it cannot be undone. */
export function ApiTokenTable({
  tokens,
}: Readonly<{ tokens: readonly ApiToken[] }>) {
  if (tokens.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No tokens yet. Create one for each notebook or script that calls the
        API.
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="h-8 text-caption text-muted-foreground">
            Name
          </TableHead>
          <TableHead className="h-8 text-right text-caption text-muted-foreground">
            Created
          </TableHead>
          <TableHead className="h-8 text-right text-caption text-muted-foreground">
            Last used
          </TableHead>
          <TableHead className="h-8">
            <span className="sr-only">Revocation</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {tokens.map((token) => (
          <ApiTokenRow key={token.name} token={token} />
        ))}
      </TableBody>
    </Table>
  )
}

function ApiTokenRow({ token }: Readonly<{ token: ApiToken }>) {
  const [confirming, setConfirming] = useState(false)
  const revocation = useTokenRevocation()
  return (
    <TableRow>
      <TableCell className="py-1.5">
        <IdentityChip>{token.name}</IdentityChip>
      </TableCell>
      <TableCell className="py-1.5 text-right">
        {formatInstant(token.created_at)}
      </TableCell>
      <TableCell className="py-1.5 text-right">
        {token.last_used_at === null
          ? "Never"
          : formatInstant(token.last_used_at)}
      </TableCell>
      <TableCell className="py-1.5 text-right">
        {confirming ? (
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(false)}
            >
              Keep
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={revocation.isPending}
              onClick={() => revocation.mutate(token.name)}
            >
              Revoke now
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            Revoke
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}
