import type { SavedStrategyVersion } from "@/api/strategies"
import { Panel } from "@/ui/panel"
import { SchemaForm } from "@/ui/schema-form"

/** A version's parameters as its JSON schema declares them, drawn by the schema form at their
 * defaults and checked as they are typed (web/DESIGN.md, Patterns, Schema form); Run backtest
 * sends them once it is built. */
export function ParametersCard({
  version,
}: Readonly<{ version: SavedStrategyVersion }>) {
  return (
    <Panel
      title="Parameters"
      description="What a backtest of this version runs with, its defaults until you change them"
    >
      <SchemaForm
        schema={version.parameter_schema}
        idPrefix={`parameter-v${version.version}`}
      />
      <p className="text-xs text-muted-foreground">
        Run backtest, which sends these values, is not built yet.
      </p>
    </Panel>
  )
}
