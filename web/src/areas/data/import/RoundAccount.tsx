import type { RoundFiles, UploadedFile } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import type { ChosenUploads } from "./import-draft"

type RoundAccountProps = Readonly<{
  round: RoundFiles | undefined
  left: readonly UploadedFile[]
  onReviewLeft: (files: ChosenUploads) => void
}>

/** What a round of several files did with them (web/DESIGN.md, Patterns, Job in its card;
 * D-102): how many it imported, found imported before, and left out, each file left out with
 * why; then Review the files left, those it left out and those not sent, which the wizard reads
 * anew as its files. */
export function RoundAccount({ round, left, onReviewLeft }: RoundAccountProps) {
  const [first, ...others] = left
  return (
    <div
      className="flex flex-col items-start gap-3"
      data-testid="round-account"
    >
      {round !== undefined && (
        <p className="text-foreground-secondary">{roundLine(round)}</p>
      )}
      {round !== undefined && round.not_imported.length > 0 && (
        <ul
          className="flex flex-col gap-1 text-negative"
          data-testid="round-not-imported"
        >
          {round.not_imported.map((file, index) => (
            <li key={`${index} ${file.file_name}`}>
              {`${file.file_name}: ${file.message}`}
            </li>
          ))}
        </ul>
      )}
      {first !== undefined && (
        <Button
          variant="ghost"
          data-testid="review-left"
          onClick={() => onReviewLeft([first, ...others])}
        >
          {`Review the ${counted(left.length, "file")} left`}
        </Button>
      )}
    </div>
  )
}

function roundLine(round: RoundFiles): string {
  const before =
    round.files_imported_before > 0
      ? `, ${counted(round.files_imported_before, "file")} imported before`
      : ""
  const leftOut =
    round.not_imported.length > 0
      ? `, ${counted(round.not_imported.length, "file")} not imported`
      : ""
  return `${counted(round.files_imported, "file")} imported${before}${leftOut}.`
}
