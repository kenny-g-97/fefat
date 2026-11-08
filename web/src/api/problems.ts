/** A request the server refused: its status, and the detail of its problem as the message. */
export class ApiProblem extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiProblem"
    this.status = status
  }
}

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
  return new ApiProblem(response.status, detail)
}
