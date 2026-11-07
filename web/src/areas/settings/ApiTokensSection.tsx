import { zodResolver } from "@hookform/resolvers/zod"
import { useSuspenseQuery } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { apiTokensQuery, useTokenCreation } from "@/api/api-tokens"
import { isRefusal } from "@/api/problems"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { Input } from "@/ui/input"
import { ApiTokenTable } from "./ApiTokenTable"
import { IssuedToken } from "./IssuedToken"
import { SettingsSection } from "./SettingsSection"

// The server's own rule for a token's name (fefat_app.services.api_tokens.TOKEN_NAME).
const tokenForm = z.object({
  name: z
    .string()
    .regex(
      /^[A-Za-z0-9._-]{1,64}$/,
      "Use 1 to 64 letters, digits, dots, dashes, or underscores"
    ),
})

/** The API tokens of notebooks and scripts: made here and shown once, listed by name, and
 * revoked from their row. */
export function ApiTokensSection() {
  const { data: tokens } = useSuspenseQuery(apiTokensQuery)
  const creation = useTokenCreation()
  const form = useForm({
    resolver: zodResolver(tokenForm),
    defaultValues: { name: "" },
  })
  const submit = form.handleSubmit(({ name }) =>
    creation.mutate(name, { onSuccess: () => form.reset() })
  )
  const refusal =
    form.formState.errors.name?.message ??
    (creation.error === null
      ? undefined
      : refusalOf(creation.error, creation.variables))

  return (
    <SettingsSection
      title="API tokens"
      description={
        <>
          A notebook or a script sends one as{" "}
          <code className="font-mono">Authorization: Bearer</code>.
        </>
      }
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-2">
        <div className="flex items-end gap-2">
          <Field data-invalid={refusal !== undefined} className="max-w-xs">
            <FieldLabel htmlFor="token-name">Token name</FieldLabel>
            <Input
              id="token-name"
              placeholder="notebook"
              autoComplete="off"
              aria-invalid={refusal !== undefined}
              {...form.register("name")}
            />
          </Field>
          <Button type="submit" disabled={creation.isPending}>
            Create token
          </Button>
        </div>
        <FieldError>{refusal}</FieldError>
      </form>
      {creation.data !== undefined && <IssuedToken issued={creation.data} />}
      <ApiTokenTable tokens={tokens} />
    </SettingsSection>
  )
}

function refusalOf(error: Error, name: string | undefined): string {
  if (isRefusal(error, 409) && name !== undefined) {
    return `A token is already called ${name}, revoked or not. Choose another name.`
  }
  return error.message
}
