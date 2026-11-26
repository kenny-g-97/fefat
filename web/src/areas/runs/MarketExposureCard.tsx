import { useQuery } from "@tanstack/react-query"
import {
  type MarketExposure,
  type RunStatistics,
  runMarketQuery,
} from "@/api/run-results"
import type { Currency } from "@/api/runs"
import {
  currencyApart,
  formatFigure,
  formatShare,
  moneyFigure,
} from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { Stat } from "@/ui/stat"
import { BuyAndHoldTable } from "./BuyAndHoldTable"
import { exposureDetail, sidesWords } from "./market-words"
import { ResultBody } from "./ResultBody"

const NONE = "None"
const CENTS = 100

type MarketExposureCardProps = Readonly<{
  runKey: string
  statistics: RunStatistics
}>

/** How a run's days moved with one lot of its instrument held long, each roll's gap taken off,
 * beside buy and hold (web/DESIGN.md, Patterns, Market exposure card): every figure the API's
 * (step 5.23), each naming its days or why it reads None. While it is read, the card keeps the
 * room its figures take, so that the cards under it do not jump. */
export function MarketExposureCard({
  runKey,
  statistics,
}: MarketExposureCardProps) {
  const market = useQuery(runMarketQuery(runKey))
  return (
    <Panel
      title="Market exposure"
      description="This run's days against one lot of the instrument it trades, held long, each roll's gap taken off"
    >
      {market.status === "pending" ? (
        <div data-testid="market-reading" className="min-h-[30.375rem]" />
      ) : (
        <ResultBody query={market}>
          {(exposure) => (
            <div className="flex flex-col gap-6">
              <div className="flex flex-col gap-4">
                <ExposureFigures
                  exposure={exposure}
                  currency={statistics.currency}
                />
                <p
                  data-testid="market-sides"
                  className="whitespace-pre-line text-foreground-secondary"
                >
                  {sidesWords(exposure.falling_days, exposure.rising_days)}
                </p>
              </div>
              <BuyAndHoldTable
                held={exposure.buy_and_hold}
                metrics={statistics.metrics}
                currency={statistics.currency}
              />
            </div>
          )}
        </ResultBody>
      )}
    </Panel>
  )
}

/** The four stat cards over every day: the correlation, the beta in lots, the alpha in the
 * currency, and the share of the run's variance the market explains. */
function ExposureFigures({
  exposure,
  currency,
}: Readonly<{ exposure: MarketExposure; currency: Currency }>) {
  const every = exposure.all_days
  const apart = currencyApart(currency)
  return (
    <dl
      data-testid="market-figures"
      className="grid grid-cols-2 gap-4 min-[75rem]:grid-cols-4"
    >
      <Stat
        inset
        testId="market-correlation"
        label="Correlation"
        value={figureOrNone(every.correlation)}
        detail={exposureDetail(every.correlation, every)}
      />
      <Stat
        inset
        testId="market-beta"
        label="Beta"
        value={figureOrNone(every.beta_lots)}
        unit={every.beta_lots === null ? null : "lots"}
        detail={exposureDetail(every.beta_lots, every)}
      />
      <Stat
        inset
        testId="market-alpha"
        label="Alpha"
        value={
          every.alpha === null ? NONE : moneyFigure(every.alpha, apart.figure)
        }
        unit={every.alpha === null ? null : apart.code}
        tone={toneOfAmount(every.alpha)}
        detail={exposureDetail(every.alpha, every)}
      />
      <Stat
        inset
        testId="market-explained"
        label="Variance explained"
        value={
          every.explained_share === null
            ? NONE
            : formatShare(every.explained_share)
        }
        detail={exposureDetail(every.explained_share, every)}
      />
    </dl>
  )
}

function figureOrNone(value: number | null): string {
  return value === null ? NONE : formatFigure(value)
}

/** The sign's colour of money the API sends as a float, as it reads at two decimals: none for an
 * amount that rounds to zero, which carries no sign. */
function toneOfAmount(
  amount: number | null
): "positive" | "negative" | undefined {
  const cents = amount === null ? 0 : Math.round(amount * CENTS)
  if (cents === 0) {
    return undefined
  }
  return cents > 0 ? "positive" : "negative"
}
