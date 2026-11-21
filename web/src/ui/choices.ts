/** The value of `options` that `chosen` is, a control's own text read back as its type. */
export function picked<Value extends string>(
  options: readonly { value: Value }[],
  chosen: string
): Value {
  const found = options.find((option) => option.value === chosen)
  if (found === undefined) {
    const known = options.map((option) => option.value).join(", ")
    throw new Error(`Expected one of ${known}, got ${chosen}.`)
  }
  return found.value
}
