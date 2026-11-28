import type { IndexedStrategy, IndexedStrategyVersion } from "@/api/strategies"
import type { components } from "@/api/schema"

type StrategyKind = components["schemas"]["StrategyKind"]

/** How each kind of strategy reads in a list. */
export const KIND_LABELS: Readonly<Record<StrategyKind, string>> = {
  signal: "Signal",
}

/** The latest version of `strategy`, its highest number, which a saved strategy always has. */
export function latestVersion(
  strategy: IndexedStrategy
): IndexedStrategyVersion {
  const latest = strategy.versions.at(-1)
  if (latest === undefined) {
    throw new Error(
      `Expected a saved strategy with a version, got ${strategy.name} with none.`
    )
  }
  return latest
}

/** Version `number` of `strategy`, or none where it has no such version. */
export function versionNumbered(
  strategy: IndexedStrategy,
  number: number
): IndexedStrategyVersion | undefined {
  return strategy.versions.find((version) => version.version === number)
}

/** The version the Changes card sets beside version `shown` among `numbers` (step 5.10): `asked`
 * where it is another of them, else the one before `shown`, else the one after it; none where
 * `shown` is the only one. */
export function comparedVersion(
  numbers: readonly number[],
  shown: number,
  asked: number | undefined
): number | undefined {
  if (asked !== undefined && asked !== shown && numbers.includes(asked)) {
    return asked
  }
  const before = numbers.filter((number) => number < shown)
  if (before.length > 0) {
    return Math.max(...before)
  }
  const after = numbers.filter((number) => number > shown)
  return after.length > 0 ? Math.min(...after) : undefined
}
