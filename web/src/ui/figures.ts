/** The decimals a figure may need: an instrument's lot step goes to 0.00001. */
const DECIMALS: readonly number[] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

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

/** A price with its instrument's decimals, as the chart's axis writes it: 5012.25. */
export function formatPrice(price: number, decimals: number): string {
  return price.toFixed(decimals)
}

/** Money as the API sends it, decimal text such as `-2721.560000`, with its thousands apart and
 * the zeros past its second decimal dropped, read as text so that no float rounds a digit:
 * `-2,721.56`. */
export function formatMoney(text: string): string {
  const found = MONEY.exec(text)
  if (found === null) {
    throw new Error(
      `Expected money as decimal text, got ${JSON.stringify(text)}.`
    )
  }
  const [, sign, whole, fraction = ""] = found
  const decimals = fraction.replace(/0+$/, "").padEnd(2, "0")
  return `${sign}${whole.replace(THOUSANDS, ",")}.${decimals}`
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

/** A count with its thousands apart: 12,345. */
export function formatCount(count: number): string {
  return count.toLocaleString("en-US")
}

/** Whether `scaled` is a whole number but for a float's noise, which a decimal of the API, a
 * tick or a lot step, keeps far under a millionth when scaled to its places. */
function isWhole(scaled: number): boolean {
  return Math.abs(scaled - Math.round(scaled)) < 1e-6
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
