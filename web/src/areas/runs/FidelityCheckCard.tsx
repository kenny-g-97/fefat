import { cn } from "cn"
import type {
  FidelityCheck,
  FidelityRerun,
  RefusedCheck,
} from "@/api/run-results"
import {
  fidelityLabel,
  formatCount,
  formatMoney,
  moneySign,
} from "@/ui/figures"
import { Panel } from "@/ui/panel"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { signed } from "./result-words"

const FIGURE = "px-3 py-0 text-right text-foreground-secondary"

function moneyChange(change: string): string {
  return signed(formatMoney(change), moneySign(change))
}

/** A net P&L in its sign's colour, as every P&L of the page. */
function pnlCell(pnl: string): string {
  const sign = moneySign(pnl)
  return cn(
    "px-3 py-0 text-right font-semibold text-foreground",
    sign === "positive" && "text-positive",
    sign === "negative" && "text-negative"
  )
}

function countChange(change: number): string {
  const written = formatCount(change)
  return change > 0 ? `+${written}` : written
}

/** The fidelity check's deltas where the run has one (`02` section 1.6): the days finer than a
 * minute run from flat at the run's own fidelity, the baseline, and again coarser, each with its
 * change against the baseline, as the API gives it; or why the engine refused the check. */
export function FidelityCheckCard({
  check,
}: Readonly<{ check: FidelityCheck | RefusedCheck }>) {
  const period = `From ${check.first} to ${check.last}, each run from flat`
  if (check.kind === "refused") {
    return (
      <Panel title="Fidelity check" description={period}>
        <p data-testid="fidelity-check" className="text-foreground-secondary">
          {`Refused at ${fidelityLabel(check.fidelity)}: ${check.refused}`}
        </p>
      </Panel>
    )
  }
  const { baseline } = check
  const reruns = [check.at_one_second, check.at_one_minute].filter(
    (rerun): rerun is FidelityRerun => rerun !== null
  )
  return (
    <Panel title="Fidelity check" description={period}>
      <div data-testid="fidelity-check" className="-mx-6 -mb-2">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pr-3 pl-6">Run</TableHead>
              <TableHead className="px-3 text-right">Trades</TableHead>
              <TableHead className="px-3 text-right">Change</TableHead>
              <TableHead className="px-3 text-right">Net P&L</TableHead>
              <TableHead className="px-3 text-right">Change</TableHead>
              <TableHead className="px-3 text-right">Max drawdown</TableHead>
              <TableHead className="pr-6 pl-3 text-right">Change</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow className="h-10 hover:bg-muted">
              <TableCell className="py-0 pr-3 pl-6 font-medium text-foreground">
                {`Baseline, ${fidelityLabel(baseline.fidelity)}`}
              </TableCell>
              <TableCell className={FIGURE}>
                {formatCount(baseline.trades)}
              </TableCell>
              <TableCell className={FIGURE} />
              <TableCell className={pnlCell(baseline.pnl)}>
                {formatMoney(baseline.pnl)}
              </TableCell>
              <TableCell className={FIGURE} />
              <TableCell className={FIGURE}>
                {formatMoney(baseline.max_drawdown)}
              </TableCell>
              <TableCell className="py-0 pr-6 pl-3" />
            </TableRow>
            {reruns.map((rerun) => (
              <TableRow
                key={rerun.outcome.fidelity}
                className="h-10 hover:bg-muted"
              >
                <TableCell className="py-0 pr-3 pl-6 font-medium text-foreground">
                  {`At ${fidelityLabel(rerun.outcome.fidelity)}`}
                </TableCell>
                <TableCell className={FIGURE}>
                  {formatCount(rerun.outcome.trades)}
                </TableCell>
                <TableCell className={FIGURE}>
                  {countChange(rerun.trades_delta)}
                </TableCell>
                <TableCell className={pnlCell(rerun.outcome.pnl)}>
                  {formatMoney(rerun.outcome.pnl)}
                </TableCell>
                <TableCell className={FIGURE}>
                  {moneyChange(rerun.pnl_delta)}
                </TableCell>
                <TableCell className={FIGURE}>
                  {formatMoney(rerun.outcome.max_drawdown)}
                </TableCell>
                <TableCell className="py-0 pr-6 pl-3 text-right text-foreground-secondary">
                  {moneyChange(rerun.max_drawdown_delta)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Panel>
  )
}
