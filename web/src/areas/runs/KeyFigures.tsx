import type { Outcome, RunStatistics } from "@/api/run-results"
import {
  counted,
  currencyApart,
  fidelityLabel,
  formatCount,
  formatFigure,
  formatMoney,
  formatShare,
  moneyFigure,
} from "@/ui/figures"
import { Stat } from "@/ui/stat"
import { figureOrNone, toneOf } from "./result-words"

const NONE = "None"

/** The eight KPI cards of a finished run (web/DESIGN.md, Patterns, Stat card), each figure the
 * API's, money with its currency's sign, and where the engine could count nothing, None with the
 * reason. */
export function KeyFigures({
  statistics,
}: Readonly<{ statistics: RunStatistics }>) {
  const { metrics, currency, pnl_share: pnlShare } = statistics
  const { trades, drawdown, daily } = metrics
  const none = trades.trades === 0 ? "No trades" : null
  const apart = currencyApart(currency)
  return (
    <dl
      data-testid="key-figures"
      className="grid grid-cols-2 gap-4 min-[75rem]:grid-cols-4"
    >
      <Stat
        testId="kpi-pnl"
        label="Net P&L"
        value={formatMoney(metrics.pnl, apart.figure)}
        unit={apart.code}
        tone={toneOf(metrics.pnl)}
        detail={`${formatShare(pnlShare)} of the capital`}
      />
      <Stat
        testId="kpi-profit-factor"
        label="Profit factor"
        value={figureOrNone(trades.profit_factor)}
        detail={
          trades.profit_factor === null
            ? (none ?? "No losing trade")
            : "Profit over loss"
        }
      />
      <Stat
        testId="kpi-expectancy"
        label="Expectancy"
        value={
          trades.expectancy_r === null
            ? NONE
            : `${formatFigure(trades.expectancy_r)} R`
        }
        detail={
          trades.expectancy_r === null
            ? (none ?? "No trade with a stop")
            : `${trades.expectancy === null ? NONE : moneyFigure(trades.expectancy, currency)} a trade`
        }
      />
      <Stat
        testId="kpi-win-rate"
        label="Win rate"
        value={trades.win_rate === null ? NONE : formatShare(trades.win_rate)}
        detail={
          none ??
          `${formatCount(trades.wins)} of ${counted(trades.trades, "trade")}`
        }
      />
      <Stat
        testId="kpi-drawdown"
        label="Max drawdown"
        value={formatMoney(drawdown.max_drawdown, apart.figure)}
        unit={apart.code}
        detail={`${formatShare(drawdown.max_drawdown_share)} of the capital`}
      />
      <Stat
        testId="kpi-sharpe"
        label="Sharpe"
        value={figureOrNone(daily.sharpe)}
        detail={
          daily.sharpe === null
            ? "Needs 2 days that differ"
            : `Over ${counted(daily.days, "day")}`
        }
      />
      <Stat
        testId="kpi-trades"
        label="Trades"
        value={formatCount(trades.trades)}
        detail={`${counted(trades.wins, "win")}, ${counted(trades.losses, "loss", "losses")}`}
      />
      <FidelitySplit groups={metrics.breakdowns.fidelity} />
    </dl>
  )
}

/** The fidelity split: the run's trades by the fidelity their entry filled on. */
function FidelitySplit({
  groups,
}: Readonly<{ groups: Readonly<Record<string, Outcome>> }>) {
  const levels = Object.entries(groups)
  if (levels.length === 0) {
    return (
      <Stat
        testId="kpi-fidelity"
        label="Fidelity split"
        value={NONE}
        detail="No trades"
      />
    )
  }
  return (
    <Stat
      testId="kpi-fidelity"
      label="Fidelity split"
      detail="Entries by fidelity"
      value={
        <span className="flex flex-col gap-0.5 text-sm font-semibold tracking-normal">
          {levels.map(([level, group]) => (
            <span
              key={level}
              data-testid={`kpi-fidelity-${level}`}
              className="flex justify-between gap-3"
            >
              <span>{fidelityLabel(level)}</span>
              <span>{formatCount(group.trades)}</span>
            </span>
          ))}
        </span>
      }
    />
  )
}
