import type { Page } from "@playwright/test"
import { z } from "zod"

const listed = z.object({ runs: z.array(z.object({ run_key: z.string() })) })

/** The run key of the seed's saved run of the strategy `demo`, the run the specs call
 * `demo-run-01`: the first that `GET /v1/runs` lists of it, newest first. */
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
