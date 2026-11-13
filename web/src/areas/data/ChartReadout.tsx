import type { BarColumns } from "@/api/bar-windows"
import { crosshairTime } from "@/charts/chart-time"
import { formatCount, formatPrice } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"

type ChartReadoutProps = Readonly<{
  bars: BarColumns
  index: number | null
  decimals: number
  daily: boolean
  loading: boolean
}>

/** The bar under the crosshair, or else the last that traded, as the API gave it
 * (web/DESIGN.md, Patterns, Price chart): its contract and its open in the browser's zone or its
 * trade date, then its open, high, low, close, and volume, its prices at its instrument's
 * decimals, the two groups wrapping apart, and the second between its figures only in a card too
 * narrow for it, a label never from its figure; and, while a window of bars loads, a word that
 * it does. */
export function ChartReadout({
  bars,
  index,
  decimals,
  daily,
  loading,
}: ChartReadoutProps) {
  const last = bars.time.length - 1
  const at = index === null || index < 0 || index > last ? last : index
  return (
    <div className="flex min-h-12 shrink-0 items-center gap-6 border-b px-4 py-2 text-xs">
      {at >= 0 && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <dl className="flex items-center gap-6 whitespace-nowrap">
            <div className="flex items-center gap-2">
              <dt className="sr-only">Contract</dt>
              <dd>
                <IdentityChip testId="readout-contract">
                  {bars.contract[at]}
                </IdentityChip>
              </dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="text-muted-foreground">
                {daily ? "Trade date" : "Open at"}
              </dt>
              <dd
                data-testid="readout-time"
                className="font-medium text-foreground"
              >
                {daily ? bars.trade_date[at] : crosshairTime(bars.time[at])}
              </dd>
            </div>
          </dl>
          <Prices bars={bars} at={at} decimals={decimals} />
        </div>
      )}
      {loading && (
        <span className="ml-auto text-muted-foreground">Loading bars</span>
      )}
    </div>
  )
}

function Prices({
  bars,
  at,
  decimals,
}: Readonly<{ bars: BarColumns; at: number; decimals: number }>) {
  const fields: readonly Readonly<{
    label: string
    id: string
    value: string
  }>[] = [
    { label: "Open", id: "open", value: formatPrice(bars.open[at], decimals) },
    { label: "High", id: "high", value: formatPrice(bars.high[at], decimals) },
    { label: "Low", id: "low", value: formatPrice(bars.low[at], decimals) },
    {
      label: "Close",
      id: "close",
      value: formatPrice(bars.close[at], decimals),
    },
    { label: "Volume", id: "volume", value: formatCount(bars.volume[at]) },
  ]
  // A card too narrow for the five on one line, such as MNQ's at the frame's least width, wraps
  // between figures rather than cut the last.
  return (
    <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 whitespace-nowrap">
      {fields.map(({ label, id, value }) => (
        <div key={id} className="flex items-center gap-2">
          <dt className="text-muted-foreground">{label}</dt>
          <dd
            data-testid={`readout-${id}`}
            className="font-semibold text-foreground"
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
