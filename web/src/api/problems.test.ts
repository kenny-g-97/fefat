import { describe, expect, it } from "vitest"
import { answer, ApiProblem } from "./problems"

/** The problem `answer` throws for a refusal of `status` whose body is `error`. */
function problemOf(status: number, error: unknown): ApiProblem {
  try {
    answer({ error, response: new Response(null, { status }) })
  } catch (thrown) {
    if (thrown instanceof ApiProblem) {
      return thrown
    }
    throw thrown
  }
  throw new Error(`Expected a refusal of ${status} to throw, got none.`)
}

describe("answer", () => {
  it("keeps the line of the code a refusal of it is at, for the editor to underline", () => {
    const refused = problemOf(400, {
      detail: "SyntaxError: invalid syntax",
      line: 7,
    })

    expect([refused.status, refused.message, refused.line]).toEqual([
      400,
      "SyntaxError: invalid syntax",
      7,
    ])
  })

  it("keeps no line for a refusal of code without one, or for another problem", () => {
    const lineless = problemOf(400, {
      detail: "Expected the hypothesis.",
      line: null,
    })
    const taken = problemOf(409, { detail: "A saved strategy has the name." })

    expect([lineless.line, taken.line]).toEqual([null, null])
  })
})
