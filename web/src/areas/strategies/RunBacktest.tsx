import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { useState } from "react"
import type { RunEstimated } from "@/api/runs"
import { type IndexedStrategy, strategyVersionQuery } from "@/api/strategies"
import { Button } from "@/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/ui/dialog"
import { type RunDraft, UNTOUCHED } from "./run-draft"
import { RunForm } from "./RunForm"

/** Run backtest, the strategy page's primary action, and its dialog (web/DESIGN.md, Patterns, Run
 * backtest dialog), for the version the page shows: what the trader chose, and the last estimate
 * it was read against, stay while the page does, so that closing the dialog to read the code
 * loses nothing, and a dialog opened on a refused choice can still change it. */
export function RunBacktest({
  strategy,
  number,
}: Readonly<{ strategy: IndexedStrategy; number: number }>) {
  const version = useQuery(strategyVersionQuery(strategy.id, number))
  const [draft, setDraft] = useState<RunDraft>(UNTOUCHED)
  const [lastEstimate, setLastEstimate] = useState<RunEstimated | null>(null)
  return (
    <Dialog>
      {/* A trigger's asChild gives the Button the trigger's own data-slot; this Button keeps the
          button's, which the stylesheet's rules key on. */}
      <DialogTrigger asChild>
        <Button
          data-slot="button"
          data-testid="run-backtest"
          disabled={version.status !== "success"}
        >
          Run backtest
        </Button>
      </DialogTrigger>
      {version.status === "success" && (
        <DialogContent
          showCloseButton={false}
          data-testid="run-dialog"
          onOpenAutoFocus={(event) => {
            // The form takes the focus once it is drawn; until then the dialog holds it.
            event.preventDefault()
            if (event.currentTarget instanceof HTMLElement) {
              event.currentTarget.focus()
            }
          }}
        >
          <header className="flex flex-col gap-1 pr-12">
            <DialogTitle className="text-base font-semibold">
              Run backtest
            </DialogTitle>
            <DialogDescription className="text-foreground-secondary">
              {`Version ${version.data.version} of ${version.data.name}: ${version.data.instrument} in ${version.data.timeframe} bars`}
            </DialogDescription>
          </header>
          <RunForm
            version={version.data}
            draft={draft}
            lastEstimate={lastEstimate}
            onEstimated={setLastEstimate}
            onChange={setDraft}
          />
          <DialogClose asChild>
            <Button
              data-slot="button"
              variant="ghost"
              size="icon-lg"
              className="absolute top-4 right-4"
              aria-label="Close"
            >
              <X className="size-5" />
            </Button>
          </DialogClose>
        </DialogContent>
      )}
    </Dialog>
  )
}
