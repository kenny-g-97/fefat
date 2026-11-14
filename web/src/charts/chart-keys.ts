/** What a key does on a focused chart: pan by a share of the bars in view, zoom by a factor,
 * or go to the earliest or the latest bar loaded. */
export type KeyAction =
  | Readonly<{ kind: "pan"; screens: number }>
  | Readonly<{ kind: "zoom"; factor: number }>
  | Readonly<{ kind: "earliest" }>
  | Readonly<{ kind: "latest" }>

const ACTIONS: ReadonlyMap<string, KeyAction> = new Map<string, KeyAction>([
  ["ArrowLeft", { kind: "pan", screens: -0.1 }],
  ["ArrowRight", { kind: "pan", screens: 0.1 }],
  ["PageUp", { kind: "pan", screens: -1 }],
  ["PageDown", { kind: "pan", screens: 1 }],
  ["Home", { kind: "earliest" }],
  ["End", { kind: "latest" }],
  ["+", { kind: "zoom", factor: 1.25 }],
  ["=", { kind: "zoom", factor: 1.25 }],
  ["-", { kind: "zoom", factor: 0.8 }],
])

/** The action of `key` on a focused chart, none for a key it leaves to the page: the arrows pan
 * a tenth of the bars in view, PageUp and PageDown a screen, Home and End go to the earliest and
 * the latest bar loaded, and plus and minus zoom. */
export function keyAction(key: string): KeyAction | undefined {
  return ACTIONS.get(key)
}
