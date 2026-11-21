import type { components } from "@/api/schema"
import type { CodeLine } from "./code-notes"

type ValidStrategy = components["schemas"]["ValidStrategy"]

type CodeVerdictProps = Readonly<{
  lines: readonly CodeLine[]
  valid: ValidStrategy | null
  validating: boolean
  failure: Error | null
}>

/** What the server's executor said of the code in the editor, under it, in a status region that
 * stands from the start, so that a screen reader hears each verdict arrive: while it validates,
 * that it does; valid, with what the strategy trades; and each refusal and warning, a refusal in
 * the negative, with its line where it has one; or why Validate could not ask. */
export function CodeVerdict({
  lines,
  valid,
  validating,
  failure,
}: CodeVerdictProps) {
  return (
    <div
      role="status"
      data-testid="code-verdict"
      className="flex min-w-0 flex-col gap-1"
    >
      {validating && (
        <p className="text-xs text-muted-foreground">Validating</p>
      )}
      {failure !== null && <p className="text-negative">{failure.message}</p>}
      {valid !== null && (
        <p className="text-foreground">{`Valid: ${valid.instrument}, ${valid.timeframe} bars`}</p>
      )}
      {lines.length > 0 && (
        <ul className="flex flex-col gap-1">
          {lines.map((line, index) => (
            <li
              key={`${index} ${line.message}`}
              data-testid="code-line"
              className={
                line.severity === "error"
                  ? "wrap-anywhere text-negative"
                  : "wrap-anywhere text-foreground-secondary"
              }
            >
              {line.line === null
                ? line.message
                : `Line ${line.line}: ${line.message}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
