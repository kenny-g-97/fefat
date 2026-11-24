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
