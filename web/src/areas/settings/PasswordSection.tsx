import { zodResolver } from "@hookform/resolvers/zod"
import type { ComponentProps } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { isRefusal } from "@/api/problems"
import { usePasswordChange } from "@/api/session"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { Input } from "@/ui/input"
import { Panel } from "@/ui/panel"

const passwordForm = z
  .object({
    current: z.string().min(1, "Type the current password"),
    next: z
      .string()
      .min(8, "Use at least 8 characters")
      .max(1024, "Use at most 1,024 characters"),
    again: z.string(),
  })
  .refine((form) => form.next === form.again, {
    message: "Type the same new password twice",
    path: ["again"],
  })

/** The password, changed with the current one; this browser stays logged in, and every other
 * session ends. */
export function PasswordSection() {
  const change = usePasswordChange()
  const form = useForm({
    resolver: zodResolver(passwordForm),
    defaultValues: { current: "", next: "", again: "" },
    mode: "onTouched",
  })
  const errors = form.formState.errors
  const submit = form.handleSubmit(({ current, next }) =>
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => form.reset(),
        onError: (error) => {
          const refusal = currentPasswordRefusal(error)
          if (refusal !== undefined) {
            form.setError("current", { message: refusal })
            form.setFocus("current", { shouldSelect: true })
          }
        },
      }
    )
  )
  const otherFailure =
    change.error !== null && currentPasswordRefusal(change.error) === undefined
      ? change.error.message
      : undefined

  return (
    <Panel
      title="Password"
      description="Changing it ends every other login session"
    >
      <form
        onSubmit={submit}
        noValidate
        className="flex max-w-sm flex-col gap-5"
      >
        <PasswordField
          id="current-password"
          label="Current password"
          autoComplete="current-password"
          error={errors.current?.message}
          {...form.register("current")}
        />
        <PasswordField
          id="new-password"
          label="New password"
          autoComplete="new-password"
          error={errors.next?.message}
          {...form.register("next")}
        />
        <PasswordField
          id="new-password-again"
          label="New password again"
          autoComplete="new-password"
          error={errors.again?.message}
          {...form.register("again")}
        />
        <div className="flex items-center gap-4">
          <Button type="submit" disabled={change.isPending}>
            Change password
          </Button>
          {change.isSuccess && (
            <p role="status" className="text-foreground-secondary">
              Password changed
            </p>
          )}
        </div>
        <FieldError>{otherFailure}</FieldError>
      </form>
    </Panel>
  )
}

type PasswordFieldProps = ComponentProps<"input"> &
  Readonly<{ id: string; label: string; error: string | undefined }>

function PasswordField({ id, label, error, ...input }: PasswordFieldProps) {
  return (
    <Field data-invalid={error !== undefined} className="gap-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="password"
        aria-invalid={error !== undefined}
        {...input}
      />
      <FieldError>{error}</FieldError>
    </Field>
  )
}

/** What a refusal of the current password says, under that field, or undefined for another
 * failure. */
function currentPasswordRefusal(error: Error): string | undefined {
  if (isRefusal(error, 403)) {
    return "That is not the current password. Type it again."
  }
  if (isRefusal(error, 429)) {
    return "Five attempts in a minute: wait a minute, then try again."
  }
  return undefined
}
