import { useMutation } from "@tanstack/react-query"
import { z } from "zod"
import { api, queryClient } from "./client"
import { type Job, jobsQuery } from "./jobs"
import { answer } from "./problems"

/** How a reproduction ended (`fefat_app.reproductions.ReproductionVerdict`): its trades the
 * saved run's, other trades, or refused before the engine ran. */
const VERDICTS = ["matched", "differed", "refused"] as const

/** A `reproduce` job's result, which the OpenAPI document does not type
 * (`fefat_app.reproductions`, step 5.10): the hash of the trades that matched, both hashes where
 * they differ, or why the reproduction was refused, in words. */
export const reproduction = z.discriminatedUnion("verdict", [
  z.object({ verdict: z.literal(VERDICTS[0]), trades_hash: z.string() }),
  z.object({
    verdict: z.literal(VERDICTS[1]),
    saved_trades_hash: z.string(),
    reproduced_trades_hash: z.string(),
  }),
  z.object({ verdict: z.literal(VERDICTS[2]), reason: z.string() }),
])

export type Reproduction = z.infer<typeof reproduction>

/** What a `reproduce` job's payload names, the run it makes again. */
const reproducing = z.object({ reproduces: z.string() })

/** The newest `reproduce` job of the saved run `runKey` among `jobs`, newest first, as the jobs
 * drawer lists them; none where the list holds none. */
export function newestReproductionOf(
  runKey: string,
  jobs: readonly Job[]
): Job | undefined {
  return jobs.find(
    (job) =>
      job.kind === "reproduce" &&
      reproducing.safeParse(job.payload).data?.reproduces === runKey
  )
}

/** Queue the reproduction of the saved run `runKey` as a `reproduce` job, which the jobs drawer
 * follows; the run's reproduction already under way where there is one. A page of a run not saved
 * yet, `null`, has no Reproduce to press. */
export function useReproduceStart(runKey: string | null) {
  return useMutation({
    mutationFn: async () => {
      if (runKey === null) {
        throw new Error(
          "Expected a saved run to reproduce, got a run not saved yet."
        )
      }
      return answer(
        await api.POST("/v1/runs/{run}/reproduce", {
          params: { path: { run: runKey } },
        })
      )
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  })
}
