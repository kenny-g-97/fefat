import type { RoundFiles, UploadedFile } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import type { ChosenUploads } from "./import-draft"

type RoundAccountProps = Readonly<{
  round: RoundFiles | undefined
  chosen: number
  sent: number
  left: readonly UploadedFile[]
  onReviewLeft: (files: ChosenUploads) => void
}>

/** What a round of several files did with them (web/DESIGN.md, Patterns, Job in its card;
 * D-102): of the files `chosen`, how many it imported, found imported before, and left out,
 * and how many were not `sent`, each file left out with why; then Review the files left, those
 * it left out and those not sent that hold records to import, which the wizard reads anew as
 * its files. */
export function RoundAccount({
  round,
  chosen,
  sent,
  left,
  onReviewLeft,
}: RoundAccountProps) {
  const [first, ...others] = left
  return (
    <div
      className="flex flex-col items-start gap-3"
      data-testid="round-account"
    >
      {round !== undefined && (
        <p className="text-foreground-secondary">
          {roundLine(round, chosen, chosen - sent)}
        </p>
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

function roundLine(round: RoundFiles, chosen: number, notSent: number): string {
  const before =
    round.files_imported_before > 0
      ? `, ${counted(round.files_imported_before, "file")} imported before`
      : ""
  const leftOut =
    round.not_imported.length > 0
      ? `, ${counted(round.not_imported.length, "file")} not imported`
      : ""
  const held =
    notSent > 0
      ? `, ${formatCount(notSent)} not sent, as ${notSent === 1 ? "its review" : "their reviews"} said`
      : ""
  return `${formatCount(round.files_imported)} of ${counted(chosen, "file")} imported${before}${leftOut}${held}.`
}
