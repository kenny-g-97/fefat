import { useQuery } from "@tanstack/react-query"
import { useNavigate, useRouter } from "@tanstack/react-router"
import { deletionQuery, useStoredDataDeletion } from "@/api/catalog"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { Panel } from "@/ui/panel"
import type { ImportedDataset } from "./datasets"
import { deletionWords } from "./deletion-words"
import { QueryBody } from "@/ui/query-body"

/** The last card of a dataset's page (step 5.18, ADR-0023; web/DESIGN.md, Patterns, Dataset
 * page): what Delete removes and what stays, then Delete, asked once in place (Inline
 * confirmation), Deleting beside it while the request runs; once the data is gone, the Data page,
 * which says what was deleted, with the focus on that line, unless the trader went elsewhere
 * meanwhile. A refusal says why under it, and Delete now pressed again finishes a delete that a
 * file held open stopped. */
export function DeleteData({
  dataset,
}: Readonly<{ dataset: ImportedDataset }>) {
  const preview = useQuery(deletionQuery(dataset.provider, dataset.root))
  const router = useRouter()
  const deletion = useStoredDataDeletion(
    dataset.provider,
    dataset.root,
    useLeaving(dataset)
  )
  return (
    <Panel title="Delete this data">
      <QueryBody query={preview}>
        {(shown) => (
          <div data-testid="delete-data" className="flex flex-col gap-4">
            <div className="flex max-w-prose flex-col gap-2 text-foreground-secondary">
              {deletionWords(dataset, shown).map((sentence) => (
                <Sentence key={sentence} words={sentence} />
              ))}
            </div>
            <div className="flex flex-col items-end gap-2">
              <InlineConfirmation
                trigger="Delete"
                confirm="Delete now"
                pending={deletion.isPending}
                size="default"
                onConfirm={() => deletion.mutate(router.state.location.href)}
              />
              {/* On the page from the start, so that a screen reader hears Deleting arrive. */}
              <p
                role="status"
                className={
                  deletion.isPending
                    ? "text-xs text-muted-foreground"
                    : "sr-only"
                }
              >
                {deletion.isPending && "Deleting"}
              </p>
              {deletion.error !== null && (
                <p
                  role="alert"
                  className="max-w-prose wrap-anywhere text-negative"
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

/** How the card leaves once its data is gone, from the address its delete was asked at: to the
 * Data page, which says what was deleted and takes the focus to that line; unless the trader
 * left that address while the delete ran, who stays where they went. The address comes with
 * the delete, since the page re-renders at the next one as it leaves. */
function useLeaving(
  dataset: ImportedDataset
): (askedFrom: string) => Promise<void> {
  const router = useRouter()
  const navigate = useNavigate()
  return async (askedFrom) => {
    if (router.state.location.href !== askedFrom) {
      return
    }
    await navigate({
      to: "/data",
      state: { deleted: `${dataset.root} from ${dataset.provider}` },
    })
  }
}

/** A trade date, which a line never breaks inside, at the hyphens it would break at otherwise. */
const TRADE_DATE = /(\d{4}-\d{2}-\d{2})/

/** A sentence of the card, each trade date in it kept whole. */
function Sentence({ words }: Readonly<{ words: string }>) {
  return (
    <p>
      {words.split(TRADE_DATE).map((part, index) =>
        index % 2 === 1 ? (
          <span key={index} className="whitespace-nowrap">
            {part}
          </span>
        ) : (
          part
        )
      )}
    </p>
  )
}
