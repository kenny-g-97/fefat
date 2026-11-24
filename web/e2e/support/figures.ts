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
