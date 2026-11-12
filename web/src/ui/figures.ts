/** The decimals a figure may need: an instrument's lot step goes to 0.00001. */
const DECIMALS: readonly number[] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

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

/** A count with its thousands apart: 12,345. */
export function formatCount(count: number): string {
  return count.toLocaleString("en-US")
}

/** Whether `scaled` is a whole number but for a float's noise, which a decimal of the API, a
 * tick or a lot step, keeps far under a millionth when scaled to its places. */
function isWhole(scaled: number): boolean {
  return Math.abs(scaled - Math.round(scaled)) < 1e-6
}
