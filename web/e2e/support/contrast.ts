import type { Page } from "@playwright/test"

/** What `lowContrast` measures: the text, placeholders, and field borders of the whole page,
 * or the ring of the control that has the keyboard focus. */
export type Measured = "text" | "focus ring"

/** What falls below WCAG's contrast on the page as the browser paints it, one line each: text
 * and placeholders under 4.5 : 1 (3 : 1 when large) against what lies beneath them (1.4.3),
 * and field borders and the focused control's ring under 3 : 1 against the surface around
 * them (1.4.11). Each colour is painted on a canvas over the backgrounds beneath it, so that a
 * token with transparency counts as it looks. */
export function lowContrast(page: Page, measured: Measured): Promise<string[]> {
  return page.evaluate(contrastProblems, measured)
}

/** `lowContrast` in the dark theme, then in the light one, each line led by its theme. The
 * page switches as the shell paints the server's setting, at once; a spec reduces motion
 * first, so that no colour is measured halfway through its transition. */
export async function lowContrastInEachTheme(
  page: Page,
  measured: Measured = "text"
): Promise<string[]> {
  const problems: string[] = []
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (dark) => document.documentElement.classList.toggle("dark", dark),
      theme === "dark"
    )
    for (const problem of await lowContrast(page, measured)) {
      problems.push(`${theme}: ${problem}`)
    }
  }
  return problems
}

/** Runs in the page, so it carries its own helpers. */
function contrastProblems(measured: Measured): string[] {
  const canvas = document.createElement("canvas")
  canvas.width = 1
  canvas.height = 1
  const context = canvas.getContext("2d", { willReadFrequently: true })
  if (context === null) {
    throw new Error("Expected a 2D canvas to paint colours on, got none.")
  }
  const unpaintable = "#010203"
  const paint = (colour: string) => {
    context.fillStyle = unpaintable
    context.fillStyle = colour
    if (context.fillStyle === unpaintable && colour !== unpaintable) {
      throw new Error(`Expected a colour the canvas can paint, got ${colour}.`)
    }
    context.fillRect(0, 0, 1, 1)
    return [...context.getImageData(0, 0, 1, 1).data.slice(0, 3)]
  }
  // The opaque colour beneath `element`: white, then each background from the root down.
  const ground = (element: Element) => {
    const layers: string[] = []
    for (
      let node: Element | null = element;
      node !== null;
      node = node.parentElement
    ) {
      layers.unshift(getComputedStyle(node).backgroundColor)
    }
    let colour = paint("#ffffff")
    for (const layer of layers) {
      colour = paint(layer)
    }
    return colour
  }
  const luminance = (colour: number[]) => {
    const [red, green, blue] = colour.map((channel) => {
      const value = channel / 255
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
  }
  const problems: string[] = []
  const check = (
    what: string,
    colour: string,
    beneath: Element,
    needed: number
  ) => {
    const background = luminance(ground(beneath))
    const painted = luminance(paint(colour))
    const ratio =
      (Math.max(background, painted) + 0.05) /
      (Math.min(background, painted) + 0.05)
    if (ratio < needed) {
      problems.push(`${what}: ${ratio.toFixed(2)} : 1, under ${needed} : 1`)
    }
  }
  const name = (element: Element) =>
    `${element.tagName.toLowerCase()} "${(element.textContent ?? "").trim().slice(0, 40)}"`
  const shown = (element: Element) =>
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility === "visible" &&
    getComputedStyle(element).opacity !== "0" &&
    element.closest('[aria-hidden="true"]') === null
  // The colour of the shadow with the widest spread, which is how Tailwind draws a ring.
  const ringColour = (shadows: string) => {
    const parts: string[] = []
    let depth = 0
    let start = 0
    for (let index = 0; index < shadows.length; index += 1) {
      depth += shadows[index] === "(" ? 1 : shadows[index] === ")" ? -1 : 0
      if (shadows[index] === "," && depth === 0) {
        parts.push(shadows.slice(start, index))
        start = index + 1
      }
    }
    parts.push(shadows.slice(start))
    let widest = { colour: "", spread: 0 }
    for (const part of parts) {
      const shadow =
        /^\s*([a-z-]+\([^)]*\)|#[0-9a-f]+|[a-z]+)\s+([-\d.px\s]+)$/i.exec(part)
      const spread = parseFloat(shadow?.[2].trim().split(/\s+/)[3] ?? "0")
      if (shadow !== null && spread > widest.spread) {
        widest = { colour: shadow[1], spread }
      }
    }
    return widest.spread > 0 ? widest.colour : null
  }

  if (measured === "focus ring") {
    const focused = document.activeElement
    if (focused === null || focused === document.body) {
      return ["Expected a control with the keyboard focus, got none"]
    }
    const style = getComputedStyle(focused)
    const outlined =
      style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0
    const ring = outlined ? style.outlineColor : ringColour(style.boxShadow)
    if (ring === null) {
      return [`Expected a ring around ${name(focused)}, got none`]
    }
    // A ring that touches the control has its fill on the inside as well.
    if (!outlined || parseFloat(style.outlineOffset) <= 0) {
      check(`the ring of ${name(focused)} on its fill`, ring, focused, 3)
    }
    check(
      `the ring of ${name(focused)}`,
      ring,
      focused.parentElement ?? focused,
      3
    )
    return problems
  }
  for (const element of document.querySelectorAll("body *")) {
    const ownText = [...element.childNodes].some(
      (node) =>
        node.nodeType === Node.TEXT_NODE &&
        (node.textContent ?? "").trim() !== ""
    )
    if (ownText && shown(element) && element.closest(":disabled") === null) {
      const style = getComputedStyle(element)
      const size = parseFloat(style.fontSize)
      const large =
        size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700)
      check(name(element), style.color, element, large ? 3 : 4.5)
    }
  }
  for (const field of document.querySelectorAll("input, [role='radio']")) {
    const style = getComputedStyle(field)
    if (!shown(field) || parseFloat(style.borderTopWidth) === 0) {
      continue
    }
    const label = field.id || field.getAttribute("value") || name(field)
    check(
      `the border of ${label}`,
      style.borderTopColor,
      field.parentElement ?? field,
      3
    )
    if (
      field instanceof HTMLInputElement &&
      field.placeholder !== "" &&
      field.value === ""
    ) {
      const placeholder = getComputedStyle(field, "::placeholder").color
      check(`the placeholder of ${label}`, placeholder, field, 4.5)
    }
  }
  return problems
}
