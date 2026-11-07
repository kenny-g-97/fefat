import { Link } from "@tanstack/react-router"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { StandalonePage } from "./StandalonePage"

/** What a path no route has shows: that the page does not exist, and the way home. */
export function NotFoundPage() {
  return (
    <StandalonePage>
      <Page title="This page does not exist">
        <p className="text-foreground-secondary">
          Check the address, or go on from the home page.
        </p>
        <Button asChild className="mt-6">
          <Link to="/">Go to the home page</Link>
        </Button>
      </Page>
    </StandalonePage>
  )
}
