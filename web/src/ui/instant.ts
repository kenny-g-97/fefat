/** An instant the API gives as ISO 8601, in the one format web/DESIGN.md sets for dates and
 * times, `2026-11-07 14:32`, in this browser's time zone. */
export function formatInstant(iso: string): string {
  const instant = new Date(iso)
  if (Number.isNaN(instant.getTime())) {
    throw new Error(`Expected an ISO 8601 instant, got ${JSON.stringify(iso)}.`)
  }
  const two = (value: number) => String(value).padStart(2, "0")
  const date = `${instant.getFullYear()}-${two(instant.getMonth() + 1)}-${two(instant.getDate())}`
  return `${date} ${two(instant.getHours())}:${two(instant.getMinutes())}`
}
