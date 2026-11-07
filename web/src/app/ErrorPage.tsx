import { useRouter, type ErrorComponentProps } from "@tanstack/react-router"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"

/** What a route shows when it fails (the router's error boundary): what broke, in the
 * error's own words, and a way to try again. */
export function ErrorPage({ error, reset }: Readonly<ErrorComponentProps>) {
  const router = useRouter()
  const tryAgain = () => {
    reset()
    void router.invalidate()
  }
  return (
    <Page title="Something broke on this page">
      <p className="max-w-2xl font-mono text-sm text-foreground-secondary">
        {error instanceof Error ? error.message : String(error)}
      </p>
      <Button className="mt-6" onClick={tryAgain}>
        Try again
      </Button>
    </Page>
  )
}
