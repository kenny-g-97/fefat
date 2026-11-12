import { useQuery } from "@tanstack/react-query"
import { catalogQuery, isSyncing, type SyncCover } from "@/api/catalog"
import { Panel } from "@/ui/panel"
import { CoverageLegend } from "./CoverageStrip"
import { byRoot } from "./datasets"
import { QueryBody } from "./QueryBody"
import { RootBlock } from "./RootBlock"

/** The catalog's products, each with the data the trader imported of it, and the data of the
 * roots the catalog does not list, both from `GET /v1/catalog`. */
export function CatalogPanels({ syncs }: Readonly<{ syncs: SyncCover }>) {
  const catalog = useQuery(catalogQuery)
  return (
    <>
      <Panel
        title="Catalog products"
        description="The products FEAT knows, each with the data you imported and how clean it is"
        action={<CoverageLegend />}
      >
        <QueryBody query={catalog}>
          {(status) => (
            <div className="flex flex-col gap-4">
              {status.products.map((product) => (
                <RootBlock
                  key={product.root}
                  root={product.root}
                  product={{
                    historyFrom: product.history_from,
                    recommendedSource: product.recommended_source,
                  }}
                  datasets={product.datasets}
                  syncing={isSyncing(syncs, product.root)}
                />
              ))}
            </div>
          )}
        </QueryBody>
      </Panel>
      <Panel
        title="Your data"
        description="The data of products outside the catalog, from your own imports"
      >
        <QueryBody query={catalog}>
          {(status) =>
            status.unlisted.length === 0 ? (
              <p className="text-foreground-secondary">
                No data outside the catalog yet.
              </p>
            ) : (
              <div className="flex flex-col gap-4">
                {byRoot(status.unlisted).map(({ name, datasets }) => (
                  <RootBlock
                    key={name}
                    root={name}
                    product={null}
                    datasets={datasets}
                    syncing={isSyncing(syncs, name)}
                  />
                ))}
              </div>
            )
          }
        </QueryBody>
      </Panel>
    </>
  )
}
