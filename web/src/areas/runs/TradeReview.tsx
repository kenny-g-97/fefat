import { useQuery } from "@tanstack/react-query"
import type { Currency } from "@/api/runs"
import { settingsQuery } from "@/api/settings"
import type { Trade, TradesShown } from "@/api/trades"
import { ChartFrame } from "@/ui/chart-frame"
import { ExplanationPanel } from "./ExplanationPanel"
import { useExplanation } from "./explanation-run"
import { TRADE_CHART_FRAME } from "./trade-chart-frame"
import { TradeChart } from "./TradeChart"
import { TradeLine } from "./TradeLine"
import { useSelectedTrade } from "./use-selected-trade"

type TradeReviewProps = Readonly<{
  runKey: string
  dates: Readonly<{ first: string; last: string }>
  timeframe: string
  currency: Currency | null
  shown: TradesShown
  row: number | undefined
  onSelect: (trade: Trade) => void
}>

/** The trade review at the head of the Trades tab (web/DESIGN.md, Patterns, Trade review chart):
 * the line of the trade the address names, with Previous, Next, and Explain, over the chart of
 * the run's bars, which shows that trade's, and beside it, once asked, the trade's explanation,
 * the chart narrowing to the column left. */
export function TradeReview({
  runKey,
  dates,
  timeframe,
  currency,
  shown,
  row,
  onSelect,
}: TradeReviewProps) {
  const selection = useSelectedTrade(runKey, shown, row, onSelect)
  const explanation = useExplanation(runKey)
  const settings = useQuery(settingsQuery)
  const selected = selection.trade
  const explained = explanation.trade
  return (
    <section
      aria-label="Trade review"
      data-testid="trade-review"
      className="flex flex-col gap-4"
    >
      <TradeLine
        trade={selected}
        place={selection.place}
        currency={currency}
        onPrevious={selection.previous}
        onNext={selection.next}
        onExplain={
          selected === null ? null : () => explanation.explain(selected)
        }
      />
      <div className="flex items-stretch gap-6">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {settings.data === undefined ? (
            <ChartFrame {...TRADE_CHART_FRAME} />
          ) : (
            <TradeChart
              runKey={runKey}
              dates={dates}
              timeframe={timeframe}
              style={settings.data.chart_style}
              selected={selected}
            />
          )}
        </div>
        {explained !== null && (
          <ExplanationPanel
            trade={explained}
            state={explanation.state}
            onClose={explanation.close}
            onExplainAgain={() => explanation.explain(explained)}
          />
        )}
      </div>
    </section>
  )
}
