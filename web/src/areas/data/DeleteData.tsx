import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { deletionQuery, useStoredDataDeletion } from "@/api/catalog"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { Panel } from "@/ui/panel"
import type { ImportedDataset } from "./datasets"
import { deletionWords } from "./deletion-words"
import { QueryBody } from "./QueryBody"

/** The last card of a dataset's page (step 5.18, ADR-0023; web/DESIGN.md, Patterns, Dataset
 * page): what a delete of the instrument's data from the provider removes and what stays, then
 * Delete, asked once in place (Inline confirmation), which leads back to the Data page once the
 * data is gone; a refusal says why under it, and Delete now pressed again finishes a delete that
 * a file held open stopped. */
export function DeleteData({
  dataset,
}: Readonly<{ dataset: ImportedDataset }>) {
  const preview = useQuery(deletionQuery(dataset.provider, dataset.root))
  const deletion = useStoredDataDeletion(dataset.provider, dataset.root)
  const navigate = useNavigate()
  return (
    <Panel title="Delete this data">
      <QueryBody query={preview}>
        {(shown) => (
          <div data-testid="delete-data" className="flex flex-col gap-4">
            <div className="flex max-w-prose flex-col gap-2 text-foreground-secondary">
              {deletionWords(dataset, shown).map((sentence) => (
                <p key={sentence}>{sentence}</p>
              ))}
            </div>
            <div className="flex flex-col items-end gap-2">
              <InlineConfirmation
                trigger="Delete"
                confirm="Delete now"
                pending={deletion.isPending}
                onConfirm={() =>
                  deletion.mutate(undefined, {
                    onSuccess: () => void navigate({ to: "/data" }),
                  })
                }
              />
              {deletion.error !== null && (
                <p
                  role="alert"
                  className="max-w-prose text-right text-negative"
                >
                  {deletion.error.message}
                </p>
              )}
            </div>
          </div>
        )}
      </QueryBody>
    </Panel>
  )
}
