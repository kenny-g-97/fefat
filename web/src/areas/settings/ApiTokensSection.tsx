import { zodResolver } from "@hookform/resolvers/zod"
import { useSuspenseQuery } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { apiTokensQuery, useTokenCreation } from "@/api/api-tokens"
import { isRefusal } from "@/api/problems"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { Input } from "@/ui/input"
import { Panel } from "@/ui/panel"
import { ApiTokenTable } from "./ApiTokenTable"
import { IssuedToken } from "./IssuedToken"

// The server's own rule for a token's name (fefat_app.services.api_tokens.TOKEN_NAME).
const tokenForm = z.object({
  name: z
    .string()
    .regex(
      /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/,
      "Use 1 to 64 letters, digits, dots, dashes, or underscores, starting with a letter or a digit"
    ),
})

/** The API tokens of notebooks and scripts: made here and shown once, listed by name, and
 * revoked from their row. */
export function ApiTokensSection() {
  const { data: tokens, dataUpdatedAt } = useSuspenseQuery(apiTokensQuery)
  const creation = useTokenCreation()
  const form = useForm({
    resolver: zodResolver(tokenForm),
    defaultValues: { name: "" },
    mode: "onTouched",
  })
  const submit = form.handleSubmit(({ name }) =>
    creation.mutate(name, {
      onSuccess: () => form.reset(),
      onError: (error) => {
        // A name in use is the field's own refusal: under the field, which takes the focus
        // with the name selected, until the name changes.
        if (isRefusal(error, 409)) {
          form.setError("name", {
            message: `A token is already called ${name}, revoked or not. Choose another name.`,
          })
          form.setFocus("name", { shouldSelect: true })
        }
      },
    })
  )
  const refusal =
    form.formState.errors.name?.message ??
    (creation.error === null || isRefusal(creation.error, 409)
      ? undefined
      : creation.error.message)
  const issued = creation.data
  // A token is shown once, so it leaves only when a list asked after its creation lacks it,
  // revoked here or elsewhere; a list that failed to come back leaves it in view.
  const stillLive =
    issued !== undefined &&
    (dataUpdatedAt <= creation.submittedAt ||
      tokens.some((token) => token.name === issued.name))

  return (
    <Panel
      title="API tokens"
      description={
        <>
          A notebook or a script sends one as <code>Authorization: Bearer</code>
        </>
      }
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-2">
        <div className="flex items-end gap-2">
          <Field
            data-invalid={refusal !== undefined}
            className="max-w-xs gap-2"
          >
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
      {stillLive && <IssuedToken issued={issued} />}
      <ApiTokenTable tokens={tokens} />
    </Panel>
  )
}
