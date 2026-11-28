import type { Page } from "@playwright/test"
import { z } from "zod"

const listed = z.object({ runs: z.array(z.object({ run_key: z.string() })) })

/** The run key of the seed's saved run of the strategy `demo`, the run the specs call
 * `demo-run-01`: the last that `GET /v1/runs` lists of it, newest first, so the oldest, since
 * other specs launch runs of it in the same seeded home. */
export async function theSeededKey(page: Page): Promise<string> {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const seeded = listed.parse(await answer.json()).runs.at(-1)
  if (seeded === undefined) {
    throw new Error("Expected the seed's saved run of demo, got none.")
  }
  return seeded.run_key
}

const versioned = z.object({
  runs: z.array(
    z.looseObject({
      run_key: z.string(),
      strategy: z.looseObject({ version: z.number() }).nullable(),
    })
  ),
})

/** The seed's run of each version of demo, the oldest of each, which other specs leave as they
 * are: version 1's is `demo-run-01`, and version 2's, its wider stop, one no spec reproduces. */
export async function theSeededRuns(
  page: Page
): Promise<readonly [string, string]> {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const { runs } = versioned.parse(await answer.json())
  const oldestOf = (version: number) => {
    const found = runs.filter((run) => run.strategy?.version === version).at(-1)
    if (found === undefined) {
      throw new Error(
        `Expected the seed's run of demo version ${version}, got none.`
      )
    }
    return found.run_key
  }
  return [oldestOf(1), oldestOf(2)]
}
