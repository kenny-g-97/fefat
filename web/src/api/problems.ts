import { z } from "zod"

/** A part of a request the API's schema refused, by where it is in the request, and why. */
export type FieldRefusal = Readonly<{
  location: readonly (string | number)[]
  message: string
}>

/** A request the server refused: its status, the detail of its problem as the message, and,
 * for a request its schema refused (422), each part refused, such as a profile's field. */
export class ApiProblem extends Error {
  readonly status: number
  readonly refusedFields: readonly FieldRefusal[]

  constructor(
    status: number,
    detail: string,
    refusedFields: readonly FieldRefusal[] = []
  ) {
    super(detail)
    this.name = "ApiProblem"
    this.status = status
    this.refusedFields = refusedFields
  }
}

/** A validation problem's errors (`fefat_app.http.problems.ValidationProblem`). */
const validationErrors = z.object({
  errors: z.array(
    z.object({
      location: z.array(z.union([z.string(), z.number()])),
      message: z.string(),
    })
  ),
})

type ApiResult<T> = {
  readonly data?: T
  readonly error?: unknown
  readonly response: Response
}

/** The data of a request the server answered with success; a refusal throws its problem. */
export function answer<T>(result: ApiResult<T>): T {
  if (!result.response.ok) {
    throw problemOf(result)
  }
  if (result.data === undefined) {
    throw new ApiProblem(
      result.response.status,
      `Expected data in the answer to ${result.response.url}, got none.`
    )
  }
  return result.data
}

/** A request the server answered with success and no content; a refusal throws its problem. */
export function succeeded(result: ApiResult<unknown>): void {
  if (!result.response.ok) {
    throw problemOf(result)
  }
}

/** Whether `error` is the server's refusal with `status`. */
export function isRefusal(error: unknown, status: number): boolean {
  return error instanceof ApiProblem && error.status === status
}

function problemOf({ error, response }: ApiResult<unknown>): ApiProblem {
  const detail =
    typeof error === "object" &&
    error !== null &&
    "detail" in error &&
    typeof error.detail === "string"
      ? error.detail
      : `The server answered ${response.status} ${response.statusText}.`
  const refused = validationErrors.safeParse(error)
  return new ApiProblem(
    response.status,
    detail,
    refused.success ? refused.data.errors : []
  )
}
