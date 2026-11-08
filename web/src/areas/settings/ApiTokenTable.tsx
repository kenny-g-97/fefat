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

const HEAD =
  "h-10 px-3 text-xs font-semibold tracking-[0.125rem] text-foreground-secondary uppercase"

/** The live API tokens, one 40 px row each: the name, when it was made and last used, and
 * its revocation, which asks once inline, since it cannot be undone. */
export function ApiTokenTable({
  tokens,
}: Readonly<{ tokens: readonly ApiToken[] }>) {
  if (tokens.length === 0) {
    return (
      <p className="text-foreground-secondary">
        No tokens yet. Create one for each notebook or script that calls the
        API.
      </p>
    )
  }
  // The table runs to the card's inner edges, its outer cells padded as the card is, so that a
  // row's hover spans the card while its text keeps the card's line.
  return (
    <div className="-mx-6">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={`${HEAD} pl-6`}>Name</TableHead>
            <TableHead className={`${HEAD} text-right`}>Created</TableHead>
            <TableHead className={`${HEAD} text-right`}>Last used</TableHead>
            <TableHead className="h-10 w-52 pr-6">
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
    </div>
  )
}

type Revoking = "not asked" | "confirming" | "kept"

function ApiTokenRow({ token }: Readonly<{ token: ApiToken }>) {
  const [revoking, setRevoking] = useState<Revoking>("not asked")
  const revocation = useTokenRevocation()
  return (
    <TableRow className="h-10 hover:bg-muted">
      <TableCell className="py-0 pr-3 pl-6">
        <IdentityChip>{token.name}</IdentityChip>
      </TableCell>
      <TableCell className="px-3 py-0 text-right text-foreground-secondary">
        {formatInstant(token.created_at)}
      </TableCell>
      <TableCell className="px-3 py-0 text-right text-foreground-secondary">
        {token.last_used_at === null
          ? "Never"
          : formatInstant(token.last_used_at)}
      </TableCell>
      <TableCell className="py-0 pr-6 text-right">
        {revoking === "confirming" ? (
          // Keep takes the trigger's place and the focus, so a double click keeps the token,
          // and the trigger takes the focus back when Keep is pressed.
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
              className="text-foreground-secondary"
              autoFocus
              onClick={() => setRevoking("kept")}
            >
              Keep
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="text-foreground-secondary"
            autoFocus={revoking === "kept"}
            onClick={() => setRevoking("confirming")}
          >
            Revoke
          </Button>
        )}
        {revocation.error !== null && (
          <p
            role="alert"
            className="pb-1 text-xs whitespace-normal text-negative"
          >
            {revocation.error.message}
          </p>
        )}
      </TableCell>
    </TableRow>
  )
}
