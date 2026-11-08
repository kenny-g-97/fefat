import { zodResolver } from "@hookform/resolvers/zod"
import { useRouter } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { isRefusal } from "@/api/problems"
import { useLogin } from "@/api/session"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { Input } from "@/ui/input"

const loginForm = z.object({ password: z.string().min(1, "Type the password") })

/** The login panel (web/DESIGN.md, Patterns): the password, then the page that asked for
 * it, `returnTo`. */
export function LoginPage({ returnTo }: Readonly<{ returnTo: string }>) {
  const router = useRouter()
  const login = useLogin()
  const form = useForm({
    resolver: zodResolver(loginForm),
    defaultValues: { password: "" },
  })
  const submit = form.handleSubmit(({ password }) =>
    login.mutate(password, {
      onSuccess: () => router.history.push(returnTo),
      onError: (error) => {
        form.setError("password", { message: refusalOf(error) })
        form.setFocus("password", { shouldSelect: true })
      },
    })
  )
  const refusal = form.formState.errors.password?.message

  return (
    // Anchored near the top rather than centred, so that a refusal grows the panel downward.
    <main className="flex min-h-screen justify-center px-6 pt-[30vh]">
      <title>Log in – FEAT</title>
      <div className="h-fit w-full max-w-96 rounded-xl border bg-card p-6 shadow-raised">
        <h1>
          <img src="/logo-full.svg" alt="FEAT" className="h-12" />
        </h1>
        <p className="mt-3 text-xs text-muted-foreground">
          feature engineering for algorithmic trading
        </p>
        <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-5">
          <Field data-invalid={refusal !== undefined} className="gap-2">
            <FieldLabel htmlFor="password">Password</FieldLabel>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              aria-invalid={refusal !== undefined}
              {...form.register("password")}
            />
            <FieldError>{refusal}</FieldError>
          </Field>
          <Button type="submit" disabled={login.isPending}>
            Log in
          </Button>
        </form>
      </div>
    </main>
  )
}

function refusalOf(error: Error): string {
  if (isRefusal(error, 401)) {
    return "That is not FEAT's password. Type it again."
  }
  if (isRefusal(error, 429)) {
    return "Five attempts in a minute: wait a minute, then try again."
  }
  return error.message
}
