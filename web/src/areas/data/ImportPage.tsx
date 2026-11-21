import { useQuery } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { importProfilesQuery } from "@/api/imports"
import { Page } from "@/ui/page"
import { BackLink } from "@/ui/text-link"
import { type Back, backOf, type Step } from "./import/import-search"
import { ImportWizard } from "./import/ImportWizard"
import { QueryBody } from "@/ui/query-body"

/** The import page (step 5.12; web/DESIGN.md, Patterns, Import wizard): the wizard's four steps,
 * the file, its layout, its instrument, and the review with Import, one at a time beside their
 * list (D-105), which leads back to the page it was opened from. The profiles load first; a
 * preset in the address starts the draft, and a new one starts it anew, while the step shown is
 * the address's too, so that the browser's Back moves between steps and the draft stays. */
export function ImportPage() {
  const search = useSearch({ from: "/_shell/data/import" })
  const navigate = useNavigate({ from: "/data/import" })
  const profiles = useQuery(importProfilesQuery)
  const onStep = (step: Step) =>
    void navigate({
      search: (previous) => ({
        ...previous,
        step: step === "file" ? undefined : step,
      }),
    })
  return (
    <Page
      title="Import"
      description="Bring your own files in through a source's preset or a profile of your own"
      back={<BackTo back={backOf(search)} />}
    >
      <QueryBody query={profiles}>
        {(listed) => (
          <ImportWizard
            key={search.preset ?? ""}
            profiles={listed}
            preset={search.preset}
            step={search.step}
            onStep={onStep}
          />
        )}
      </QueryBody>
    </Page>
  )
}

function BackTo({ back }: Readonly<{ back: Back }>) {
  switch (back.kind) {
    case "data":
      return <BackLink to="/data">Back to Data</BackLink>
    case "sources":
      return <BackLink to="/data/sources">Back to Sources</BackLink>
    case "dataset":
      return (
        <BackLink
          to="/data/dataset"
          search={{ instrument: back.instrument, provider: back.provider }}
        >
          {`Back to ${back.instrument} from ${back.provider}`}
        </BackLink>
      )
  }
}
