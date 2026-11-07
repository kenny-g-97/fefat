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

const HEAD = "h-8 text-caption text-muted-foreground"

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
          <TableHead className={HEAD}>Name</TableHead>
          <TableHead className={`${HEAD} text-right`}>Created</TableHead>
          <TableHead className={`${HEAD} text-right`}>Last used</TableHead>
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
      <TableCell className="py-0">
        <IdentityChip>{token.name}</IdentityChip>
      </TableCell>
      <TableCell className="py-0 text-right">
        {formatInstant(token.created_at)}
      </TableCell>
      <TableCell className="py-0 text-right">
        {token.last_used_at === null
          ? "Never"
          : formatInstant(token.last_used_at)}
      </TableCell>
      <TableCell className="py-0 text-right">
        {confirming ? (
          // Keep takes the trigger's place and the focus, so a double click keeps the token.
          <div className="flex justify-end gap-2">
            <Button
              variant="destructive"
              size="sm"
              disabled={revocation.isPending}
              onClick={() => revocation.mutate(token.name)}
            >
              Revoke now
            </Button>
            <Button
              variant="ghost"
              size="sm"
              autoFocus
              onClick={() => setConfirming(false)}
            >
              Keep
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            Revoke
          </Button>
        )}
        {revocation.error !== null && (
          <p role="alert" className="pb-1 text-caption text-negative">
            {revocation.error.message}
          </p>
        )}
      </TableCell>
    </TableRow>
  )
}
