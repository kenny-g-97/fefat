import { useTokenRevocation } from "@/api/api-tokens"
import type { components } from "@/api/schema"
import { IdentityChip } from "@/ui/identity-chip"
import { InlineConfirmation } from "@/ui/inline-confirmation"
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
            <TableHead className="px-3 pl-6">Name</TableHead>
            <TableHead className="px-3 text-right">Created</TableHead>
            <TableHead className="px-3 text-right">Last used</TableHead>
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

function ApiTokenRow({ token }: Readonly<{ token: ApiToken }>) {
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
        <InlineConfirmation
          trigger="Revoke"
          confirm="Revoke now"
          pending={revocation.isPending}
          onConfirm={() => revocation.mutate(token.name)}
        />
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
