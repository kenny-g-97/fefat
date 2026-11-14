import { cn } from "cn"
import { Button } from "./button"

type SectionFailureProps = Readonly<{
  error: Error
  onRetry: () => void
  className?: string
}>

/** A card or a drawer that could not load its own data (web/DESIGN.md, Patterns, Section
 * failure): its reason in the negative colour, as a sentence, and Try again, while the rest of
 * the page keeps working. */
export function SectionFailure({
  error,
  onRetry,
  className,
}: SectionFailureProps) {
  return (
    <div className={cn("flex flex-col items-start gap-3", className)}>
      <p role="alert" className="text-negative">
        {error.message}
      </p>
      <Button variant="ghost" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
