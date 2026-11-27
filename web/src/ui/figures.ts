import type { Currency, Fee } from "@/api/runs"

/** The decimals a figure may need: an instrument's lot step goes to 0.00001. */
const DECIMALS: readonly number[] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

/** The sign each currency is written with before its figure, or null for one written as its
 * code after it (web/DESIGN.md, Type, D-117); a currency the API adds fails the build here. */
const CURRENCY_SIGNS: Readonly<Record<Currency, string | null>> = {
  USD: "$",
  USDT: null,
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CHF: null,
  AUD: "A$",
  CAD: "CA$",
}

/** The space no line breaks at, which joins a currency's code to its figure (D-117), named
 * since a formatter writes the character itself, which reads as a plain space. */
export const NO_BREAK_SPACE = String.fromCharCode(0xa0)

const MONEY = /^(-?)(\d+)(?:\.(\d+))?$/
const THOUSANDS = /\B(?=(\d{3})+$)/g

const TWO_DECIMALS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "negative",
})
const PERCENT = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "negative",
})
const EDGE = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  signDisplay: "negative",
})

const DECIMAL_TEXT = /^-?[0-9]+(?:[.][0-9]+)?$/

const UNITS: Readonly<Record<string, string>> = {
  s: "second",
  m: "minute",
  h: "hour",
  d: "day",
}

/** The decimals a decimal of the API is written with, without a float's noise: a tick of 0.25
 * gives 2, a lot step of 0.00001 gives 5, a point value of 50 gives 0. */
export function decimalsOf(value: number): number {
  const decimals = DECIMALS.find((each) => isWhole(value * 10 ** each))
  if (decimals === undefined) {
    throw new Error(
      `Expected a decimal of at most ${DECIMALS.length - 1} places, got ${value}.`
    )
  }
  return decimals
}

/** A decimal of the API as it is written: 0.00001, 50, 1.25. */
export function formatDecimal(value: number): string {
  return value.toFixed(decimalsOf(value))
}

/** A decimal of the API written to line its point up in a column of `places` decimals, set in a
 * monospace and kept with its spaces: its own digits, then a space for each place and for the
 * point it lacks, so that no digit is added. */
export function formatAligned(value: number, places: number): string {
  const own = decimalsOf(value)
  if (own > places) {
    throw new Error(
      `Expected a decimal of at most ${places} places, got ${value}.`
    )
  }
  const point = own === 0 && places > 0 ? 1 : 0
  return formatDecimal(value) + " ".repeat(places - own + point)
}

/** The places a decimal the API sends as text holds, as a price is sent: `5000.25` holds 2,
 * `5000` none. */
export function placesOfText(text: string): number {
  if (!DECIMAL_TEXT.test(text)) {
    throw new Error(`Expected a decimal as text, got ${JSON.stringify(text)}.`)
  }
  const point = text.indexOf(".")
  return point === -1 ? 0 : text.length - point - 1
}

/** A decimal the API sends as text, written to line its point up in a column of `places`
 * decimals, as `formatAligned` writes a number: its own digits, then a space for each place and
 * for the point it lacks, so that no digit is added (step 5.8). */
export function alignedText(text: string, places: number): string {
  const own = placesOfText(text)
  if (own > places) {
    throw new Error(
      `Expected a decimal of at most ${places} places, got ${text}.`
    )
  }
  const point = own === 0 && places > 0 ? 1 : 0
  return text + " ".repeat(places - own + point)
}

/** A price with its instrument's decimals, as the chart's axis writes it: 5012.25. */
export function formatPrice(price: number, decimals: number): string {
  return price.toFixed(decimals)
}

/** Money as the API sends it, decimal text such as `-2721.560000`, in `currency`: its thousands
 * apart and the zeros past its second decimal dropped, read as text so that no float rounds a
 * digit, after the currency's sign and the minus before both, `-$2,721.56` (`withCurrency`). */
export function formatMoney(text: string, currency: Currency | null): string {
  const found = MONEY.exec(text)
  if (found === null) {
    throw new Error(
      `Expected money as decimal text, got ${JSON.stringify(text)}.`
    )
  }
  const [, , whole, fraction = ""] = found
  const decimals = fraction.replace(/0+$/, "").padEnd(2, "0")
  const digits = `${whole.replace(THOUSANDS, ",")}.${decimals}`
  return withCurrency(moneySign(text) === "negative", digits, currency)
}

/** An amount of `currency` the API sends as a float, at two decimals: `$51,250.50`. */
export function moneyFigure(value: number, currency: Currency | null): string {
  return signedInCurrency(TWO_DECIMALS.format(value), currency)
}

/** An axis's or a histogram's edge in `currency`, with the decimals it holds: `-$150`. */
export function moneyEdge(edge: number, currency: Currency | null): string {
  return signedInCurrency(EDGE.format(edge), currency)
}

/** What a fee table charges, as the run pays it: per contract per side in the instrument's
 * currency, or a crypto fee in basis points of the trade's value, as its record writes it. */
export function feeWords(fee: Fee, currency: Currency | null): string {
  if (fee.kind === "futures") {
    return `${formatMoney(fee.per_contract_side, currency)} per contract per side`
  }
  return `maker ${fee.maker_bps} bps, taker ${fee.taker_bps} bps`
}

/** A figure Intl wrote, its minus moved before `currency`'s sign. */
function signedInCurrency(written: string, currency: Currency | null): string {
  const negative = written.startsWith("-")
  return withCurrency(negative, negative ? written.slice(1) : written, currency)
}

/** A currency's sign and code apart, for a figure set large beside its code in small (web/DESIGN.md,
 * Stat card): the currency to write the figure in, none where its code follows it, and that code. */
export function currencyApart(
  currency: Currency
): Readonly<{ figure: Currency | null; code: Currency | null }> {
  return CURRENCY_SIGNS[currency] === null
    ? { figure: null, code: currency }
    : { figure: currency, code: null }
}

/** `digits` in `currency`: after its sign, or before its code where it has no sign, joined by a
 * space no line breaks at, the minus first; plain where no currency is known, as for a run
 * indexed before D-114. */
function withCurrency(
  negative: boolean,
  digits: string,
  currency: Currency | null
): string {
  const minus = negative ? "-" : ""
  if (currency === null) {
    return `${minus}${digits}`
  }
  const sign = CURRENCY_SIGNS[currency]
  return sign === null
    ? `${minus}${digits}${NO_BREAK_SPACE}${currency}`
    : `${minus}${sign}${digits}`
}

/** A ratio or an amount the API sends as a float, at two decimals with its thousands apart:
 * `1.84`, `-0.31`, `51,250.50`; a value that rounds to zero carries no sign. */
export function formatFigure(value: number): string {
  return TWO_DECIMALS.format(value)
}

/** A share the API sends as a fraction, in percent at two decimals: 0.025 is `2.50%`. */
export function formatShare(share: number): string {
  return PERCENT.format(share)
}

/** A histogram's edge, with the decimals it holds and its thousands apart: `-1.5`, `12,500`. */
export function formatEdge(edge: number): string {
  return EDGE.format(edge)
}

/** The sign of money as the API sends it, read from its text. */
export function moneySign(text: string): "positive" | "negative" | "zero" {
  if (/^-?0*(\.0*)?$/.test(text)) {
    return "zero"
  }
  return text.startsWith("-") ? "negative" : "positive"
}

/** What a dataset's fidelity holds, in words: Trades, TBBO, or 1-minute bars. */
export function fidelityLabel(fidelity: string): string {
  if (fidelity === "trades") {
    return "Trades"
  }
  if (fidelity === "tbbo") {
    return "TBBO"
  }
  const parts = /^(\d+)([smhd])$/.exec(fidelity)
  if (parts === null) {
    throw new Error(
      `Expected a fidelity such as trades or 1m, got ${JSON.stringify(fidelity)}.`
    )
  }
  return `${parts[1]}-${UNITS[parts[2]]} bars`
}

/** A word of the API in sentence case, such as an exit reason, a weekday, or a template's name:
 * `target_1` reads `Target 1`, `mean_reversion` `Mean reversion`. */
export function sentenceCase(word: string): string {
  const spaced = word.replaceAll("_", " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A count with its thousands apart: 12,345. */
export function formatCount(count: number): string {
  return count.toLocaleString("en-US")
}

/** Whether `scaled` is a whole number but for a float's noise, which a decimal of the API, a
 * tick or a lot step, keeps far under a millionth when scaled to its places. */
function isWhole(scaled: number): boolean {
  return Math.abs(scaled - Math.round(scaled)) < 1e-6
}

const MINUTES_AN_HOUR = 60
const MINUTES_A_DAY = 1440

/** A time the API sends in minutes, in its two largest units, in words, rounded to the smaller:
 * `45 minutes`, `1 hour 30 minutes`, `3 days 4 hours`, and `Under a minute` short of half of one
 * (web/DESIGN.md, Figures). */
export function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes < 0) {
    throw new Error(
      `Expected a count of minutes at or above zero, got ${minutes}.`
    )
  }
  const whole = Math.round(minutes)
  if (whole === 0) {
    return "Under a minute"
  }
  if (whole < MINUTES_AN_HOUR) {
    return counted(whole, "minute")
  }
  if (whole < MINUTES_A_DAY) {
    return inTwoUnits(whole, MINUTES_AN_HOUR, "hour", "minute")
  }
  const hours = Math.round(minutes / MINUTES_AN_HOUR)
  return inTwoUnits(hours, MINUTES_A_DAY / MINUTES_AN_HOUR, "day", "hour")
}

/** `count` of a smaller unit as whole larger units of `per` and the rest, the rest left out at
 * none: `1 hour 30 minutes`, `2 days`. */
function inTwoUnits(
  count: number,
  per: number,
  larger: string,
  smaller: string
): string {
  const rest = count % per
  const whole = counted(Math.floor(count / per), larger)
  return rest === 0 ? whole : `${whole} ${counted(rest, smaller)}`
}

/** A count of `noun`, with its thousands apart and the noun's `plural` where it is not one:
 * `1 session`, `2,760 records`, `3 mismatches`. */
export function counted(
  count: number,
  noun: string,
  plural = `${noun}s`
): string {
  return `${formatCount(count)} ${count === 1 ? noun : plural}`
}
