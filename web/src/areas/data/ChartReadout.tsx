import type { BarColumns } from "@/api/bar-windows"
import { crosshairTime } from "@/charts/chart-time"
import { formatCount, formatPrice } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"

type ChartReadoutProps = Readonly<{
  bars: BarColumns
  index: number | null
  decimals: number
  daily: boolean
}>

/** The bar under the crosshair, or else the last, as the API gave it (web/DESIGN.md, Patterns,
 * Price chart): its contract, its open in the browser's zone or its trade date, and its open,
 * high, low, close, and volume, its prices at its instrument's decimals. */
export function ChartReadout({
  bars,
  index,
  decimals,
  daily,
}: ChartReadoutProps) {
  const last = bars.time.length - 1
  const at = index === null || index < 0 || index > last ? last : index
  if (at < 0) {
    return <p className="h-12 px-4 text-foreground-secondary" />
  }
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
  return (
    <dl className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-b px-4 py-2 text-xs whitespace-nowrap">
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
        <dd data-testid="readout-time" className="font-medium text-foreground">
          {daily ? bars.trade_date[at] : crosshairTime(bars.time[at])}
        </dd>
      </div>
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
