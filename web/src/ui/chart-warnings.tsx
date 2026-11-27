/** What a chart's bars warn of, under its card (web/DESIGN.md, Patterns, Price chart): each
 * warning a line at 12 px in body text, the list gone where there are none. */
export function ChartWarnings({
  warnings,
}: Readonly<{ warnings: readonly string[] }>) {
  if (warnings.length === 0) {
    return null
  }
  return (
    <ul
      data-testid="chart-warnings"
      className="flex shrink-0 flex-col gap-1 text-xs text-foreground-secondary"
    >
      {warnings.map((warning) => (
        <li key={warning}>{warning}</li>
      ))}
    </ul>
  )
}
