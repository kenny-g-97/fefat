import type { UseQueryResult } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { isRefusal } from "@/api/problems"
import { QueryBody } from "@/ui/query-body"

type ResultBodyProps<Answer> = Readonly<{
  query: UseQueryResult<Answer>
  afterRefusal?: ReactNode
  children: (answer: Answer) => ReactNode
}>

/** A section of a run's results once its query answers. Where the server refuses it for good, as
 * for a run another engine saved or a folder that is gone, its sentence says why and what to do,
 * with `afterRefusal` under it and no Try again, since another read would answer the same; else
 * what `QueryBody` shows. */
export function ResultBody<Answer>({
  query,
  afterRefusal,
  children,
}: ResultBodyProps<Answer>) {
  if (
    query.status === "error" &&
    (isRefusal(query.error, 404) || isRefusal(query.error, 409))
  ) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p
          role="alert"
          data-testid="run-results-refused"
          className="text-negative wrap-anywhere"
        >
          {query.error.message}
        </p>
        {afterRefusal}
      </div>
    )
  }
  return <QueryBody query={query}>{children}</QueryBody>
}
