import type { ReactNode } from "react"
import { Monogram } from "@/ui/monogram"

/** A page shown without the shell, for an unknown address or the shell's own failure: its own
 * main landmark, under the monogram and the wordmark, so that it still says it is FEFAT. */
export function StandalonePage({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <main>
      <div className="mx-auto flex h-18 w-full max-w-400 items-center gap-3 px-8">
        <Monogram className="size-10" />
        <span className="text-base font-semibold">FEFAT</span>
      </div>
      {children}
    </main>
  )
}
