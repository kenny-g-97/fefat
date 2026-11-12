type SegmentedOption<Option extends string> = Readonly<{
  value: Option
  label: string
}>

type SegmentedProps<Option extends string> = Readonly<{
  label: string
  options: readonly SegmentedOption<Option>[]
  value: Option
  onChange: (value: Option) => void
  disabled?: boolean
  testId?: string
}>

/** A choice among a few short options in a toolbar or a drawer (web/DESIGN.md, Patterns,
 * Segmented control): the Contemporary skill's buttons in a box on the control surface, the
 * chosen one pressed on the accent's fill. */
export function Segmented<Option extends string>({
  label,
  options,
  value,
  onChange,
  disabled = false,
  testId,
}: SegmentedProps<Option>) {
  return (
    <div
      role="group"
      aria-label={label}
      data-slot="segmented"
      data-testid={testId}
      className="inline-flex shrink-0 gap-1 rounded-xl border bg-muted p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={disabled}
          data-slot="segmented-option"
          onClick={() => onChange(option.value)}
          className="h-8 rounded-xl border border-transparent px-3 font-semibold text-foreground-secondary hover:text-foreground disabled:opacity-50 aria-pressed:bg-primary aria-pressed:text-primary-foreground"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
