import { useQuery } from "@tanstack/react-query"
import { type MonteCarlo, runMonteCarloQuery } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { currencyApart, formatMoney, formatShare } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { Stat } from "@/ui/stat"
import { MonteCarloCharts } from "./MonteCarloCharts"
import { ResultBody } from "./ResultBody"
import { toneOf } from "./result-words"

/** How a run's outcome could have varied (web/DESIGN.md, Patterns, Monte Carlo card): its trades
 * drawn again with replacement, as the server draws them, its paths' figures beside the run's own
 * and their charts, money in `currency`; a run of fewer than two trades says why it has none.
 * While the paths are drawn, which a long run's take seconds, the card says so and keeps the room
 * its figures take, so that the cards under it do not jump. */
export function MonteCarloCard({
  runKey,
  currency,
}: Readonly<{ runKey: string; currency: Currency }>) {
  const monteCarlo = useQuery(runMonteCarloQuery(runKey))
  if (monteCarlo.status === "pending") {
    return (
      <Panel title="Monte Carlo">
        <p
          role="status"
          data-testid="monte-carlo-drawing"
          className="min-h-176 text-xs text-muted-foreground"
        >
          Drawing paths
        </p>
      </Panel>
    )
  }
  return (
    <Panel title="Monte Carlo">
      <ResultBody query={monteCarlo}>
        {(answered) =>
          answered.kind === "too_few_trades" ? (
            <p
              data-testid="monte-carlo-too-few"
              className="text-foreground-secondary"
            >
              {answered.reason}
            </p>
          ) : (
            <div className="flex flex-col gap-6">
              <MonteCarloFigures report={answered} currency={currency} />
              <MonteCarloCharts report={answered} currency={currency} />
            </div>
          )
        }
      </ResultBody>
    </Panel>
  )
}

/** The paths' figures as stat cards inside the card: the median net P&L, the chance of a net
 * loss, and the median and 95th percentile of the maximum drawdown, beside the run's own. */
function MonteCarloFigures({
  report,
  currency,
}: Readonly<{ report: MonteCarlo; currency: Currency }>) {
  const { net_pnl: net, max_drawdown: drawdown } = report
  const apart = currencyApart(currency)
  const figure = (money: string) => formatMoney(money, apart.figure)
  const written = (money: string) => formatMoney(money, currency)
  return (
    <dl
      data-testid="monte-carlo-figures"
      className="grid grid-cols-2 gap-4 min-[75rem]:grid-cols-4"
    >
      <Stat
        inset
        testId="monte-carlo-net"
        label="Median net P&L"
        value={figure(net.median)}
        unit={apart.code}
        tone={toneOf(net.median)}
        detail={`5th to 95th percentile: ${written(net.p5)} to ${written(net.p95)}`}
      />
      <Stat
        inset
        testId="monte-carlo-loss"
        label="Chance of a net loss"
        value={formatShare(report.net_loss_share)}
        detail="Paths that ended below the capital"
      />
      <Stat
        inset
        testId="monte-carlo-drawdown"
        label="Median max drawdown"
        value={figure(drawdown.median)}
        unit={apart.code}
        detail={`The run's own, of closed trades: ${written(report.own_max_drawdown)}`}
      />
      <Stat
        inset
        testId="monte-carlo-drawdown-95"
        label="95th percentile max drawdown"
        value={figure(drawdown.p95)}
        unit={apart.code}
        detail={`${formatShare(report.deeper_drawdown_share)} of paths fell deeper than the run's own`}
      />
    </dl>
  )
}
