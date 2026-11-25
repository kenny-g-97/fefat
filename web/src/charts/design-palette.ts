import designSystem from "../../DESIGN.md?raw"

/** The token `name`'s colour in `theme` as web/DESIGN.md's palette writes it, which
 * python/tests/test_web_design_system.py holds equal to index.css, for the tests that measure a
 * chart's colours, since vitest reads no stylesheet. */
export function tokenColour(name: string, theme: "dark" | "light"): string {
  const row = new RegExp(
    `^\\| [^|]+ \\| \`${name}\` \\| \`(#[0-9a-f]{6})\` \\| \`(#[0-9a-f]{6})\` \\|`,
    "m"
  ).exec(designSystem)
  if (row === null) {
    throw new Error(
      `Expected the token ${name} in web/DESIGN.md's palette, got none.`
    )
  }
  return theme === "dark" ? row[1] : row[2]
}

/** `top` over `bottom` at `alpha`, as a canvas paints a fill, in whole channels. */
export function painted(top: string, bottom: string, alpha: number): string {
  const channels = (colour: string) =>
    [1, 3, 5].map((at) => parseInt(colour.slice(at, at + 2), 16))
  const under = channels(bottom)
  const mixed = channels(top).map((over, at) =>
    Math.round(over * alpha + under[at] * (1 - alpha))
  )
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`
}
