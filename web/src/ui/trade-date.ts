const DATE_TEXT = /^(\d{4})-(\d{2})-(\d{2})$/

/** The days of `month` of `year`, from the calendar's rule rather than the browser's clock,
 * which would move a date near midnight. */
function daysIn(year: number, month: number): number {
  if (month === 2) {
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
    return leap ? 29 : 28
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31
}

/** Whether `text` is a date as the app writes one, `2026-03-06`, that the calendar holds; the
 * Run backtest dialog's and the trade table's dates are typed so (steps 5.6 and 5.8). */
export function isTradeDate(text: string): boolean {
  const found = DATE_TEXT.exec(text)
  if (found === null) {
    return false
  }
  const [year, month, day] = [found[1], found[2], found[3]].map(Number)
  return month >= 1 && month <= 12 && day >= 1 && day <= daysIn(year, month)
}
