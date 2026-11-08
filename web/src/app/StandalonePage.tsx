import type { ReactNode } from "react"

/** A page shown without the shell, for an unknown address or the shell's own failure: its own
 * main landmark, under FEAT's logo, so that it still says it is FEAT. */
export function StandalonePage({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <main>
      <div className="mx-auto flex h-18 w-full max-w-400 items-center px-8">
        <img src="/logo-full.svg" alt="FEAT" className="h-10" />
      </div>
      {children}
    </main>
  )
}
