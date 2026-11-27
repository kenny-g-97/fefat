/** What a key does on a focused chart: pan by a share of the bars in view, zoom by a factor,
 * go to the earliest or the latest bar loaded, or step the crosshair a bar at a time. */
export type KeyAction =
  | Readonly<{ kind: "pan"; screens: number }>
  | Readonly<{ kind: "zoom"; factor: number }>
  | Readonly<{ kind: "earliest" }>
  | Readonly<{ kind: "latest" }>
  | Readonly<{ kind: "step"; bars: -1 | 1 }>

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

/** The arrows with Shift, which read the bars one at a time. */
const STEPS: ReadonlyMap<string, KeyAction> = new Map<string, KeyAction>([
  ["ArrowLeft", { kind: "step", bars: -1 }],
  ["ArrowRight", { kind: "step", bars: 1 }],
])

/** The action of `key` on a focused chart, with Shift held where `shift` is true, none for a
 * key it leaves to the page: the arrows pan a tenth of the bars in view, and with Shift step the
 * crosshair a bar, PageUp and PageDown pan a screen, Home and End go to the earliest and the
 * latest bar loaded, and plus and minus zoom, a plus typed with Shift among them. */
export function keyAction(key: string, shift = false): KeyAction | undefined {
  const step = shift ? STEPS.get(key) : undefined
  return step === undefined ? ACTIONS.get(key) : step
}
