import { Link } from "@tanstack/react-router"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { StandalonePage } from "./StandalonePage"

/** What a path no route has shows: that the page does not exist, and the way home. */
export function NotFoundPage() {
  return (
    <StandalonePage>
      <Page
        title="This page does not exist"
        description="Check the address, or go on from the home page"
      >
        <Button asChild>
          <Link to="/">Go to the home page</Link>
        </Button>
      </Page>
    </StandalonePage>
  )
}
