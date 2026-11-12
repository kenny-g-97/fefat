import { useId } from "react"
import { type StoredDataset, useCatalogSync } from "@/api/catalog"
import { Button } from "@/ui/button"
import { byProvider } from "./datasets"
import { ProviderRow } from "./ProviderRow"

/** What the catalog says of a product: the first trade date of its history and its first
 * recommended source. */
export type Product = Readonly<{
  historyFrom: string
  recommendedSource: string
}>

type RootBlockProps = Readonly<{
  root: string
  product: Product | null
  datasets: readonly StoredDataset[]
  syncing: boolean
}>

/** A root's data (web/DESIGN.md, Patterns, Root block): a box on the control surface with its
 * root and, for a catalog product, its history and recommended source; Update, which checks the
 * root's quality as a job, a catalog sync; then each provider's data, or, for a product without
 * any, a sentence saying so. */
export function RootBlock({
  root,
  product,
  datasets,
  syncing,
}: RootBlockProps) {
  const heading = useId()
  const sync = useCatalogSync()
  const providers = byProvider(datasets)
  return (
    <article
      aria-labelledby={heading}
      data-testid="root-block"
      className="flex flex-col gap-4 rounded-xl border bg-muted p-4"
    >
      <header className="flex items-center gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 id={heading} className="text-base font-semibold">
            {root}
          </h3>
          {product !== null && (
            <p className="text-xs text-muted-foreground">
              History from {product.historyFrom}, {product.recommendedSource}{" "}
              recommended
            </p>
          )}
        </div>
        {providers.length > 0 && (
          <Button
            variant="ghost"
            aria-label={`Update ${root}`}
            disabled={syncing || sync.isPending}
            onClick={() => sync.mutate(root)}
          >
            Update
          </Button>
        )}
      </header>
      {sync.error !== null && (
        <p role="alert" className="text-negative">
          {sync.error.message}
        </p>
      )}
      {providers.length === 0 && (
        <p className="text-foreground-secondary">No data yet</p>
      )}
      {providers.map(({ name, datasets: provided }) => {
        const [first, ...rest] = provided
        return first === undefined ? null : (
          <ProviderRow
            key={name}
            root={root}
            provider={name}
            datasets={[first, ...rest]}
            syncing={syncing}
          />
        )
      })}
    </article>
  )
}
