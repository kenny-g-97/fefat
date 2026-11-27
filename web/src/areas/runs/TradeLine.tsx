import { cn } from "cn"
import { ChevronLeft, ChevronRight } from "lucide-react"
import type { Currency } from "@/api/runs"
import type { Trade } from "@/api/trades"
import { Button } from "@/ui/button"
import { counted, formatMoney, moneySign, sentenceCase } from "@/ui/figures"
import { formatInstantToTheSecond } from "@/ui/instant"

type TradeLineProps = Readonly<{
  trade: Trade | null
  position: Readonly<{ at: number; of: number }> | null
  currency: Currency | null
  onPrevious: (() => void) | null
  onNext: (() => void) | null
  onExplain: (() => void) | null
}>

const SIGN_COLOUR = {
  positive: "text-positive",
  negative: "text-negative",
  zero: "text-foreground",
} as const

/** The line over the trade review chart (web/DESIGN.md, Patterns, Trade line): the selected trade,
 * where it stands among the trades the table keeps, its entry to the second, its side and lots,
 * and its net P&L in its sign's colour, then Previous and Next, which step through the table's
 * trades, and Explain, the card's one primary action; with no trade selected, the way to one. */
export function TradeLine({
  trade,
  position,
  currency,
  onPrevious,
  onNext,
  onExplain,
}: TradeLineProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      {trade === null ? (
        <p className="text-foreground-secondary">
          Choose a trade in the table, or Next, to see it on the chart.
        </p>
      ) : (
        <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 whitespace-nowrap">
          <Figure label="Trade" testId="trade-position">
            {position === null
              ? "Not in the table"
              : `${position.at} of ${position.of}`}
          </Figure>
          <Figure label="Entry" testId="trade-entry">
            {formatInstantToTheSecond(trade.entry_ts)}
          </Figure>
          <Figure label="Side" testId="trade-side" labelHidden>
            {`${sentenceCase(trade.side)} ${counted(trade.lots, "lot")}`}
          </Figure>
          <Figure
            label="Net P&L"
            testId="trade-pnl"
            className={SIGN_COLOUR[moneySign(trade.pnl)]}
          >
            {formatMoney(trade.pnl, currency)}
          </Figure>
        </dl>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          aria-label="Previous trade"
          data-testid="previous-trade"
          disabled={onPrevious === null}
          onClick={onPrevious === null ? undefined : onPrevious}
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
          Previous
        </Button>
        <Button
          variant="ghost"
          aria-label="Next trade"
          data-testid="next-trade"
          disabled={onNext === null}
          onClick={onNext === null ? undefined : onNext}
        >
          Next
          <ChevronRight className="size-4" aria-hidden="true" />
        </Button>
        <Button
          data-testid="explain-trade"
          disabled={onExplain === null}
          onClick={onExplain === null ? undefined : onExplain}
        >
          Explain
        </Button>
      </div>
    </div>
  )
}

/** A figure of the line and its label, the label read by a screen reader alone where
 * `labelHidden`, as a side's words say what they are. */
function Figure({
  label,
  testId,
  className,
  labelHidden = false,
  children,
}: Readonly<{
  label: string
  testId: string
  className?: string
  labelHidden?: boolean
  children: string
}>) {
  return (
    <div className="flex items-center gap-2">
      <dt className={labelHidden ? "sr-only" : "text-muted-foreground"}>
        {label}
      </dt>
      <dd
        data-testid={testId}
        className={cn("font-medium text-foreground", className)}
      >
        {children}
      </dd>
    </div>
  )
}
