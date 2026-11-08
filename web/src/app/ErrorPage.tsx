import { useRouter, type ErrorComponentProps } from "@tanstack/react-router"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"

/** What a route shows when it fails (the router's error boundary): what broke, in the
 * error's own words under the title, and a way to try again. */
export function ErrorPage({ error, reset }: Readonly<ErrorComponentProps>) {
  const router = useRouter()
  const tryAgain = () => {
    reset()
    void router.invalidate()
  }
  return (
    <Page
      title="Something broke on this page"
      description={error instanceof Error ? error.message : String(error)}
    >
      <Button onClick={tryAgain}>Try again</Button>
    </Page>
  )
}
