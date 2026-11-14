import { cn } from "cn"
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
 * decimals, on one line, two, or three by the row's width alone, a label never apart from its
 * figure; and, while a window of bars loads, a word that it does, which moves nothing. */
export function ChartReadout({
  bars,
  index,
  decimals,
  daily,
  loading,
}: ChartReadoutProps) {
  const last = bars.time.length - 1
  const at = index === null || index < 0 || index > last ? last : index
  // The row holds two lines at the least, 40 px under its padding, so that a second line, the
  // prices' under 56 rem or the loading word's where the figures leave it no room, never moves
  // the chart under the pointer. Under 56 rem the word stands on the first line, after the
  // time, where there is always room for it.
  return (
    <div className="@container box-content flex min-h-10 shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-b px-4 py-2 text-xs">
      {at >= 0 && (
        <>
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
        </>
      )}
      {loading && (
        <span className="ml-auto whitespace-nowrap text-muted-foreground">
          Loading bars
        </span>
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
  // The lines follow the row's width, never the figures under the crosshair, which would move
  // the chart under the pointer from one bar to the next: under 56 rem the prices start a line
  // of their own, and under 40 rem, where five-digit prices leave it no room, the volume does.
  return (
    <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 whitespace-nowrap @max-[56rem]:order-last @max-[56rem]:basis-full">
      {fields.map(({ label, id, value }) => (
        <div
          key={id}
          className={cn(
            "flex items-center gap-2",
            id === "volume" && "@max-[40rem]:basis-full"
          )}
        >
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
