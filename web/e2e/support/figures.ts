/** The API's figures as a page writes them, formatted here on their own, so that a spec comparing
 * the page with the API does not read the app's formatters. */

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

/** The space no line breaks at, which the page joins a currency's code to its figure with. */
const NO_BREAK_SPACE = String.fromCharCode(0xa0)

/** The sign a currency's money is written after; a currency without one follows its figure as its
 * code (D-117). */
const CURRENCY_SIGNS = new Map([
  ["USD", "$"],
  ["EUR", "€"],
  ["GBP", "£"],
  ["JPY", "¥"],
  ["AUD", "A$"],
  ["CAD", "CA$"],
])

/** A figure, with its minus or none, as money in `currency`: `-$2,721.56`, `12.50 USDT`, the code
 * joined by a space no line breaks at; plain where the API names no currency. */
function inCurrency(figure: string, currency: string | null): string {
  if (currency === null) {
    return figure
  }
  const minus = figure.startsWith("-") ? "-" : ""
  const digits = figure.replace("-", "")
  const sign = CURRENCY_SIGNS.get(currency)
  return sign === undefined
    ? `${minus}${digits}${NO_BREAK_SPACE}${currency}`
    : `${minus}${sign}${digits}`
}

/** Money the API sends as decimal text, in `currency`: its thousands apart, the zeros past a cent
 * dropped, and no minus on a zero. */
export function moneyText(text: string, currency: string | null): string {
  const [whole, fraction = ""] = text.split(".")
  const zero = /^-?0*(\.0*)?$/.test(text)
  const sign = whole.startsWith("-") && !zero ? "-" : ""
  const digits = whole.replace("-", "").replace(/\B(?=(\d{3})+$)/g, ",")
  const cents = fraction.replace(/0+$/, "").padEnd(2, "0")
  return inCurrency(`${sign}${digits}.${cents}`, currency)
}

/** An amount the API sends as a float, at two decimals, in `currency`. */
export function figureMoney(value: number, currency: string | null): string {
  return inCurrency(TWO_DECIMALS.format(value), currency)
}

/** A histogram's edge of money, with the decimals it holds, in `currency`. */
export function edgeMoney(edge: number, currency: string | null): string {
  return inCurrency(EDGE.format(edge), currency)
}

/** A ratio or an amount the API sends as a float, at two decimals. */
export function figureText(value: number): string {
  return TWO_DECIMALS.format(value)
}

/** A share the API sends as a fraction, in percent at two decimals. */
export function shareText(share: number): string {
  return PERCENT.format(share)
}

/** A histogram's edge, with the decimals it holds. */
export function edgeText(edge: number): string {
  return EDGE.format(edge)
}

/** A count with its unit, the unit in the plural where the count is not one: `3 days`. */
export function countText(count: number, unit: string): string {
  return `${count.toLocaleString("en-US")} ${unit}${count === 1 ? "" : "s"}`
}

/** A time the API sends in minutes, in its two largest units, rounded to the smaller: `45
 * minutes`, `1 hour 30 minutes`, `3 days 4 hours`, and `Under a minute` short of half of one. */
export function durationText(minutes: number): string {
  const whole = Math.round(minutes)
  if (whole === 0) {
    return "Under a minute"
  }
  if (whole < 60) {
    return countText(whole, "minute")
  }
  if (whole < 1440) {
    const rest = whole % 60
    const hours = countText(Math.floor(whole / 60), "hour")
    return rest === 0 ? hours : `${hours} ${countText(rest, "minute")}`
  }
  const inHours = Math.round(minutes / 60)
  const days = countText(Math.floor(inHours / 24), "day")
  return inHours % 24 === 0
    ? days
    : `${days} ${countText(inHours % 24, "hour")}`
}
