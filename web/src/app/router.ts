import { createRouter } from "@tanstack/react-router"
import { queryClient } from "@/api/client"
import { ErrorPage } from "./ErrorPage"
import { NotFoundPage } from "./NotFoundPage"
import { routeTree } from "./routeTree.gen"

/** The app's router over the file routes of `src/app/routes`, with the query cache in its
 * context for the routes' loaders; a route that fails shows the error page in its place. */
export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultErrorComponent: ErrorPage,
  defaultNotFoundComponent: NotFoundPage,
  // An unknown path inside the shell shows the page alone too, with its one main landmark.
  notFoundMode: "root",
})

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
