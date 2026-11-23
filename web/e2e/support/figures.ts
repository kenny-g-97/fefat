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

/** Money the API sends as decimal text: its thousands apart, the zeros past a cent dropped. */
export function moneyText(text: string): string {
  const [whole, fraction = ""] = text.split(".")
  const sign = whole.startsWith("-") ? "-" : ""
  const digits = whole.replace("-", "").replace(/\B(?=(\d{3})+$)/g, ",")
  return `${sign}${digits}.${fraction.replace(/0+$/, "").padEnd(2, "0")}`
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
