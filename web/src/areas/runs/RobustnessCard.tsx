import { cn } from "cn"
import type { Robustness } from "@/api/run-results"
import { VERDICT_LABELS } from "@/api/runs"
import { formatMoney, moneySign } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { sampleSizeWords, sentenceCase } from "./result-words"

const BADGE =
  "rounded-xl border border-transparent bg-accent px-2 py-0.5 text-xs font-semibold text-foreground"

type RobustnessCardProps = Readonly<{
  robustness: Robustness
  trades: number
}>

/** The robustness summary (web/DESIGN.md, Patterns, Robustness summary): the five scores of 20
 * and their total, the verdict with `fragile_to_slippage` beside it, which of 30, 100, and 200
 * trades the run reaches, its net P&L at one more tick of slippage, and the red flags that fired. */
export function RobustnessCard({ robustness, trades }: RobustnessCardProps) {
  const atOneMoreTick = robustness.pnl_at_plus_one_tick
  const sign = moneySign(atOneMoreTick)
  return (
    <Panel
      title="Robustness"
      action={
        <div className="flex shrink-0 items-center gap-2">
          {robustness.fragile_to_slippage && (
            <span data-testid="robustness-fragile" className={BADGE}>
              Fragile to slippage
            </span>
          )}
          <span data-testid="robustness-verdict" className={BADGE}>
            {`Verdict: ${VERDICT_LABELS[robustness.verdict]}`}
          </span>
        </div>
      }
    >
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-12 gap-y-4">
        <div className="flex flex-col gap-3">
          <p
            data-testid="robustness-total"
            className="text-2xl font-bold tracking-tight text-foreground"
          >
            {`${robustness.total_score} of 100`}
          </p>
          <p
            data-testid="robustness-sample"
            className="text-foreground-secondary"
          >
            {sampleSizeWords(robustness.sample_size, trades)}
          </p>
          <p
            data-testid="robustness-plus-tick"
            className="flex justify-between gap-4 text-foreground-secondary"
          >
            Net P&L at one more tick of slippage
            <span
              className={cn(
                "shrink-0 font-semibold text-foreground",
                sign === "positive" && "text-positive",
                sign === "negative" && "text-negative"
              )}
            >
              {formatMoney(atOneMoreTick)}
            </span>
          </p>
        </div>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2">
          {robustness.dimensions.map((dimension) => (
            <div key={dimension.name} className="contents">
              <dt className="text-foreground-secondary">
                {sentenceCase(dimension.name)}
              </dt>
              <dd
                role="meter"
                aria-label={sentenceCase(dimension.name)}
                aria-valuemin={0}
                aria-valuemax={dimension.max_score}
                aria-valuenow={dimension.score}
                className="h-2 overflow-hidden rounded-xl bg-accent"
              >
                <div
                  className="h-full rounded-xl bg-brand"
                  style={{
                    width: `${(dimension.score / dimension.max_score) * 100}%`,
                  }}
                />
              </dd>
              <dd
                data-testid="robustness-score"
                className="text-right font-semibold text-foreground"
              >
                {`${dimension.score} of ${dimension.max_score}`}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      {robustness.red_flags.length > 0 && (
        <ul className="flex flex-col gap-1 border-t pt-4">
          {robustness.red_flags.map((flag) => (
            <li
              key={flag.id}
              data-testid="robustness-flag"
              className="flex gap-4 text-foreground-secondary"
            >
              <span
                className={cn(
                  "w-16 shrink-0 font-semibold",
                  flag.severity === "high" ? "text-negative" : "text-foreground"
                )}
              >
                {sentenceCase(flag.severity)}
              </span>
              <span>{flag.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
