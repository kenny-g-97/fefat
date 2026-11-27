/** An instant the API gives as ISO 8601, in the one format web/DESIGN.md sets for dates and
 * times, `2026-11-07 14:32`, in this browser's time zone. */
export function formatInstant(iso: string): string {
  return wallClock(iso).slice(0, MINUTES)
}

/** An instant the API gives as ISO 8601 to the second, `2026-11-07 14:32:05`, in this browser's
 * time zone, as a table of trades writes it, where two fills of one minute stand apart (step
 * 5.8); a fraction of the second is dropped, as a clock drops it. */
export function formatInstantToTheSecond(iso: string): string {
  return wallClock(iso)
}

const MINUTES = "2026-11-07 14:32".length

function wallClock(iso: string): string {
  const instant = new Date(iso)
  if (Number.isNaN(instant.getTime())) {
    throw new Error(`Expected an ISO 8601 instant, got ${JSON.stringify(iso)}.`)
  }
  const two = (value: number) => String(value).padStart(2, "0")
  const date = `${instant.getFullYear()}-${two(instant.getMonth() + 1)}-${two(instant.getDate())}`
  return `${date} ${two(instant.getHours())}:${two(instant.getMinutes())}:${two(instant.getSeconds())}`
}
