/** A page or panel not built yet (web/DESIGN.md, Patterns): what it will hold, in one line,
 * and that it is not built yet; never invented data. */
export function Placeholder({ purpose }: Readonly<{ purpose: string }>) {
  return (
    <div className="max-w-2xl">
      <p className="text-foreground-secondary">{purpose}</p>
      <p className="mt-1 text-caption text-muted-foreground">Not built yet</p>
    </div>
  )
}
