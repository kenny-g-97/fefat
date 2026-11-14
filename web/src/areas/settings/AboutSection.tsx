import { CHART_NOTICE } from "@/charts/attribution"
import { Panel } from "@/ui/panel"
import { ExternalLink } from "@/ui/text-link"

/** What FEAT is built with and must credit (web/DESIGN.md, Patterns, Settings): the notice of
 * the library that draws its charts, word for word, its address a link, which that library's
 * licence asks for beside the logo on each chart. */
export function AboutSection() {
  return (
    <Panel
      title="About"
      description="The library that draws FEAT's charts, credited here and by the logo on each chart"
    >
      <div
        data-testid="chart-notice"
        className="flex flex-col gap-1 text-foreground-secondary"
      >
        <p className="font-medium text-foreground">{CHART_NOTICE.product}</p>
        <p>
          {CHART_NOTICE.copyright}{" "}
          <ExternalLink href={CHART_NOTICE.page}>
            {CHART_NOTICE.page}
          </ExternalLink>
        </p>
      </div>
    </Panel>
  )
}
