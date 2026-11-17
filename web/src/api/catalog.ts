import { queryOptions, useMutation, useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { z } from "zod"
import { api, queryClient } from "./client"
import { isActive, type Job, jobsQuery } from "./jobs"
import { answer } from "./problems"
import type { components } from "./schema"

export type CatalogStatus = components["schemas"]["CatalogStatus"]
export type StoredDataset = components["schemas"]["StoredDataset"]
export type InstrumentVersion = components["schemas"]["InstrumentVersion"]
export type Source = components["schemas"]["Source"]
export type MonthCoverage = components["schemas"]["MonthCoverage"]

/** The catalog's products with the datasets that cover them, then the datasets of the roots it
 * does not list, the trader's own. */
export const catalogQuery = queryOptions({
  queryKey: ["catalog"],
  queryFn: async () => answer(await api.GET("/v1/catalog")),
})

/** The source guide FEAT ships, which no session changes. */
export const sourcesQuery = queryOptions({
  queryKey: ["sources"],
  queryFn: async () => answer(await api.GET("/v1/sources")),
  staleTime: Infinity,
})

/** Every version of every instrument's specification, FEAT's and those imports saved. */
export const instrumentsQuery = queryOptions({
  queryKey: ["instruments"],
  queryFn: async () => answer(await api.GET("/v1/instruments")),
})

/** A dataset's quality: its root's report from its provider, with its findings and its
 * coverage by month, the same for every dataset of the root and the provider. */
export function datasetQualityQuery(datasetId: string) {
  return queryOptions({
    queryKey: ["datasets", datasetId, "quality"],
    queryFn: async () =>
      answer(
        await api.GET("/v1/datasets/{dataset_id}/quality", {
          params: { path: { dataset_id: datasetId } },
        })
      ),
  })
}

/** Start the catalog sync of a root, its quality report as a job, which the jobs drawer
 * follows; the server gives the sync already under way where one covers the root. */
export function useCatalogSync() {
  return useMutation({
    mutationFn: async (root: string) =>
      answer(await api.POST("/v1/catalog/sync", { body: { root } })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  })
}

/** A catalog sync's payload, which the OpenAPI document does not type: its root, or none for
 * every product. */
const syncPayload = z.object({ root: z.string().nullable() })

/** What the queued and running catalog syncs cover: every root, or the roots named. */
export type SyncCover = Readonly<{ every: boolean; roots: ReadonlySet<string> }>

/** What the queued and running catalog syncs among `jobs` cover. */
export function syncsUnderWay(jobs: readonly Job[]): SyncCover {
  const roots = activeSyncs(jobs).map(
    (job) => syncPayload.parse(job.payload).root
  )
  return {
    every: roots.includes(null),
    roots: new Set(roots.filter((root): root is string => root !== null)),
  }
}

/** Whether a sync under way covers `root`. */
export function isSyncing(cover: SyncCover, root: string): boolean {
  return cover.every || cover.roots.has(root)
}

/** What the catalog syncs under way cover, for a page that shows quality; the shell reads the
 * catalog and the datasets' quality again once a sync ends (`useStoreReadAfterWrites`). */
export function useSyncCover(): SyncCover {
  const jobs = useQuery(jobsQuery)
  return syncsUnderWay(jobs.data === undefined ? [] : jobs.data)
}

/** The kinds of job that write what the data pages read: a catalog sync its reports, and an
 * import its datasets, its instrument, its reports, and its profile (step 5.12). */
const STORE_WRITERS: ReadonlySet<Job["kind"]> = new Set([
  "catalog_sync",
  "import",
])

/** What a job that writes the store makes stale: the catalog, the datasets' quality, the
 * instruments, the chart's spans and bars, and the import profiles. */
const STORE_READS = [
  catalogQuery.queryKey,
  ["datasets"],
  instrumentsQuery.queryKey,
  ["market"],
  ["import-profiles"],
]

/** Read again, on every page, what a catalog sync or an import among `jobs` wrote, once it
 * ends: a job another read of the jobs lists as ended for the first time, so that one which
 * ended before any read saw it running counts too. The shell's top bar calls it once. */
export function useStoreReadAfterWrites(
  jobs: readonly Job[] | undefined
): void {
  const ended = jobs === undefined ? undefined : endedStoreWrites(jobs)
  const before = useRef(ended)
  useEffect(() => {
    if (ended === undefined) {
      return
    }
    const earlier = before.current
    before.current = ended
    if (earlier !== undefined && writeEndedSince(earlier, ended)) {
      for (const queryKey of STORE_READS) {
        void queryClient.invalidateQueries({ queryKey })
      }
    }
  }, [ended])
}

/** The ids of the catalog syncs and the imports among `jobs` that ended, as one text a hook's
 * dependency can compare from one read of the jobs to the next. */
export function endedStoreWrites(jobs: readonly Job[]): string {
  return jobs
    .filter((job) => STORE_WRITERS.has(job.kind) && !isActive(job))
    .map((job) => job.id)
    .join(" ")
}

/** Whether `later`, a read of the ended writes, lists one that `earlier` does not, which ended
 * between the two reads. */
export function writeEndedSince(earlier: string, later: string): boolean {
  const known = new Set(earlier.split(" "))
  return later.split(" ").some((id) => id !== "" && !known.has(id))
}

function activeSyncs(jobs: readonly Job[]): readonly Job[] {
  return jobs.filter((job) => job.kind === "catalog_sync" && isActive(job))
}
