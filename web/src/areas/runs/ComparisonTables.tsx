import { cn } from "cn"
import type { ReactNode } from "react"
import type { ComparedRun, RunComparison } from "@/api/comparisons"
import { formatCount, sentenceCase } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import { TextLink } from "@/ui/text-link"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import {
  COMPARED_ROWS,
  comparedLabel,
  countChange,
  moneyChange,
  SERIES_MARKS,
} from "./compare-words"
import { LOOKS, made, type Written } from "./side-figures"

const KEY_DIGITS = 12

/** The figures of the compared runs side by side (web/DESIGN.md, Patterns, Comparison tables): a
 * row a figure, a column a run, each figure the API's, and under each but the reference's what
 * it differs by from the reference's, the first run's. */
export function ComparisonFiguresCard({
  runs,
}: Readonly<{ runs: readonly ComparedRun[] }>) {
  return (
    <Panel
      title="Figures"
      description="Each run's figures, and under them what each differs by from the reference's"
    >
      <ComparedTable runs={runs} label="Figure">
        {COMPARED_ROWS.map((row) => (
          <TableRow
            key={row.id}
            data-testid={`compared-${row.id}`}
            className="hover:bg-muted"
          >
            <RowHead label={row.label} />
            {runs.map((run, at) => (
              <ComparedCell
                key={run.run_key}
                written={row.figure(run.figures, run.currency)}
                change={
                  run.deltas === null
                    ? null
                    : row.change(run.deltas, run.currency)
                }
                last={at === runs.length - 1}
              />
            ))}
          </TableRow>
        ))}
      </ComparedTable>
    </Panel>
  )
}

/** The compared runs' trades by the exit reason that left them flat, every reason any of them
 * closed a trade by, two rows a reason, its trades and their net P&L, with each change beside the
 * reference's under them; none where no run closed a trade. */
export function ExitReasonsCard({
  comparison,
}: Readonly<{ comparison: RunComparison }>) {
  const { runs, exit_reasons: reasons } = comparison
  return (
    <Panel
      title="Trades by exit reason"
      description="What left each run's trades flat, and under it what each differs by from the reference's"
    >
      {reasons.length === 0 ? (
        <p className="text-foreground-secondary">
          None of these runs closed a trade.
        </p>
      ) : (
        <ComparedTable runs={runs} label="Exit reason">
          {reasons.flatMap((reason) => [
            <TableRow
              key={`${reason}-trades`}
              data-testid={`compared-${reason}-trades`}
              className="hover:bg-muted"
            >
              <RowHead label={`${sentenceCase(reason)}, trades`} />
              {runs.map((run, at) => (
                <ComparedCell
                  key={run.run_key}
                  written={{
                    text: formatCount(outcomeOf(run, reason).trades),
                    look: "figure",
                  }}
                  change={
                    run.exit_reason_deltas === null
                      ? null
                      : countChange(changeOf(run, reason).trades)
                  }
                  last={at === runs.length - 1}
                />
              ))}
            </TableRow>,
            <TableRow
              key={`${reason}-pnl`}
              data-testid={`compared-${reason}-pnl`}
              className="hover:bg-muted"
            >
              <RowHead label={`${sentenceCase(reason)}, net P&L`} />
              {runs.map((run, at) => (
                <ComparedCell
                  key={run.run_key}
                  written={made(outcomeOf(run, reason).pnl, run.currency)}
                  change={
                    run.exit_reason_deltas === null
                      ? null
                      : moneyChange(changeOf(run, reason).pnl, run.currency)
                  }
                  last={at === runs.length - 1}
                />
              ))}
            </TableRow>,
          ])}
        </ComparedTable>
      )}
    </Panel>
  )
}

function outcomeOf(run: ComparedRun, reason: string) {
  const outcome = run.exit_reasons[reason]
  if (outcome === undefined) {
    throw new Error(
      `Expected run ${run.run_key.slice(0, KEY_DIGITS)}'s trades by ${reason}, which every run of a comparison holds, got none.`
    )
  }
  return outcome
}

function changeOf(run: ComparedRun, reason: string) {
  const change = run.exit_reason_deltas?.[reason]
  if (change === undefined) {
    throw new Error(
      `Expected what run ${run.run_key.slice(0, KEY_DIGITS)}'s trades by ${reason} differ by, got none.`
    )
  }
  return change
}

/** A table in a card of the compared runs' figures: the rows' names under `label`, then a column
 * a run, headed by its mark, its strategy and version, and its key. */
function ComparedTable({
  runs,
  label,
  children,
}: Readonly<{
  runs: readonly ComparedRun[]
  label: string
  children: ReactNode
}>) {
  return (
    <div className="-mx-6 -mb-2">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pr-3 pl-6">{label}</TableHead>
            {runs.map((run, at) => (
              <RunHead
                key={run.run_key}
                run={run}
                at={at}
                last={at === runs.length - 1}
              />
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>{children}</TableBody>
      </Table>
    </div>
  )
}

/** A run's column head: its mark in its curve's colour, its strategy and version as a text link
 * to the run's page, which keeps the way back to the list, and its key's first twelve digits in
 * its identity chip, with Reference beside the first's. */
function RunHead({
  run,
  at,
  last,
}: Readonly<{ run: ComparedRun; at: number; last: boolean }>) {
  return (
    <th
      scope="col"
      data-testid="compared-run"
      className={cn(
        "w-40 py-2 text-right align-bottom font-normal",
        last ? "pr-6 pl-3" : "px-3"
      )}
    >
      <span className="flex items-center justify-end gap-2 font-medium text-foreground">
        <span
          data-slot="chart-mark"
          className={cn("size-2.5 shrink-0 rounded-xl", SERIES_MARKS[at])}
        />
        <TextLink
          to="/runs/run"
          search={{ key: run.run_key }}
          state={(kept) => kept}
          data-testid="compared-run-link"
        >
          {comparedLabel(run)}
        </TextLink>
      </span>
      <span className="mt-1 flex items-center justify-end gap-2 text-xs text-muted-foreground">
        {at === 0 && "Reference"}
        <IdentityChip>{run.run_key.slice(0, KEY_DIGITS)}</IdentityChip>
      </span>
    </th>
  )
}

function RowHead({ label }: Readonly<{ label: string }>) {
  return (
    <th
      scope="row"
      className="py-2 pr-3 pl-6 text-left align-top font-normal whitespace-nowrap text-foreground-secondary"
    >
      {label}
    </th>
  )
}

/** A run's figure in its look's colour, and under it, but for the reference, what it differs by
 * from the reference's, at 12 px in body text. */
function ComparedCell({
  written,
  change,
  last,
}: Readonly<{ written: Written; change: string | null; last: boolean }>) {
  return (
    <TableCell
      className={cn("py-2 text-right align-top", last ? "pr-6 pl-3" : "px-3")}
    >
      <span className={cn("block", LOOKS[written.look])}>{written.text}</span>
      {change !== null && (
        <span
          data-testid="compared-change"
          className="block text-xs text-foreground-secondary"
        >
          <span className="sr-only">Differs from the reference's by </span>
          {change}
        </span>
      )}
    </TableCell>
  )
}
