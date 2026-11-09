import { Progress } from "./progress"

type PercentBarProps = Readonly<{
  value: number
  label: string
}>

/** How far a piece of work has come (web/DESIGN.md, Patterns): the 8 px bar, then the percent
 * as an integer in a slot of its own at the right, so that bars in a list end on one line. */
export function PercentBar({ value, label }: PercentBarProps) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <Progress value={value} aria-label={label} className="flex-1" />
      <span className="w-12 shrink-0 text-right font-semibold text-foreground">
        {Math.round(value)}%
      </span>
    </div>
  )
}
