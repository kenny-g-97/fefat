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
  /** What a page leaves the next one in the browser's history: the data a delete removed,
   * "MES from synthetic", which the Data page says it deleted (step 5.18); the strategy version
   * a save opened, which its page says it saved (step 5.5); and, from the Run backtest dialog
   * (step 5.6), the run key of a run found saved, which its page marks Cached, and the strategy
   * a stress ran, which the Runs page says. */
  interface HistoryState {
    deleted?: string
    saved?: Readonly<{ strategy: string; version: number }>
    cachedRun?: string
    stressed?: string
  }
}
