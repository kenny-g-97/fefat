import type { SavedStrategyVersion } from "@/api/strategies"
import { Panel } from "@/ui/panel"
import { type ParameterField, parameterFields } from "@/ui/schema-fields"

const KIND_WORDS: Readonly<Record<ParameterField["kind"], string>> = {
  integer: "Whole number",
  number: "Number",
  string: "Word",
  boolean: "Flag",
  choice: "Choice",
}

/** A version's parameters as its JSON schema declares them, each with its type and its default
 * (web/DESIGN.md, Patterns, Strategy page), read-only: Run backtest is where a run changes them,
 * so that the page and the dialog never hold two copies. */
export function ParametersCard({
  version,
}: Readonly<{ version: SavedStrategyVersion }>) {
  const reading = parameterFields(version.parameter_schema)
  return (
    <Panel
      title="Parameters"
      description="What a backtest runs with by default. Change them in Run backtest"
    >
      {reading.kind === "unreadable" ? (
        <p role="alert" className="text-negative">
          {reading.reason}
        </p>
      ) : reading.fields.length === 0 ? (
        <p className="text-foreground-secondary">It takes no parameters.</p>
      ) : (
        <dl className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-4 gap-y-2">
          {reading.fields.map((field) => (
            <div
              key={field.name}
              data-testid="parameter-row"
              className="contents"
            >
              <dt className="font-medium wrap-anywhere text-foreground">
                {field.name}
              </dt>
              <dd className="text-foreground-secondary">
                {KIND_WORDS[field.kind]}
              </dd>
              <dd className="text-right text-foreground">
                {String(field.initial)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  )
}
