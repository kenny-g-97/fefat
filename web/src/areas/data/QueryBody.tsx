import type { UseQueryResult } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { SectionFailure } from "@/ui/section-failure"

type QueryBodyProps<Answer> = Readonly<{
  query: UseQueryResult<Answer>
  children: (answer: Answer) => ReactNode
}>

/** A section's content once its query answers: room for it while it loads, and its own failure
 * with Try again where it cannot load (web/DESIGN.md, Patterns, Section failure). */
export function QueryBody<Answer>({ query, children }: QueryBodyProps<Answer>) {
  if (query.status === "pending") {
    return <div className="min-h-24" />
  }
  if (query.status === "error") {
    return (
      <SectionFailure
        error={query.error}
        onRetry={() => void query.refetch()}
        className="min-h-24 justify-center"
      />
    )
  }
  return children(query.data)
}
