import { CHART_NOTICE, EQUITY_CHART_NOTICE } from "@/charts/attribution"
import { Panel } from "@/ui/panel"
import { ExternalLink } from "@/ui/text-link"

/** What FEAT is built with and must credit (web/DESIGN.md, Patterns, Settings): the notices of
 * the libraries that draw its charts, word for word, each address a link: Lightweight Charts',
 * whose licence asks for it beside the logo on a price chart, and ECharts', which Apache 2.0 asks
 * a distribution to carry. */
export function AboutSection() {
  return (
    <Panel
      title="About"
      description="The libraries that draw FEAT's charts, credited here and by the logo on a price chart"
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
      <div
        data-testid="equity-chart-notice"
        className="flex flex-col gap-1 text-foreground-secondary"
      >
        <p className="font-medium text-foreground">
          {EQUITY_CHART_NOTICE.product}
        </p>
        <p>{EQUITY_CHART_NOTICE.copyright}</p>
        <p>
          {EQUITY_CHART_NOTICE.credit}{" "}
          <ExternalLink href={EQUITY_CHART_NOTICE.page}>
            {EQUITY_CHART_NOTICE.page}
          </ExternalLink>
        </p>
      </div>
    </Panel>
  )
}
