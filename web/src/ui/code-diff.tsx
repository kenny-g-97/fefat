import { lazyRouteComponent } from "@tanstack/react-router"
import { Suspense } from "react"
import { CodeText } from "./code-editor"

/** A version's code as a side of the diff shows it, named for a screen reader by `label`. */
export type DiffSide = Readonly<{ label: string; code: string }>

export type CodeDiffProps = Readonly<{ earlier: DiffSide; later: DiffSide }>

/** CodeMirror's merge view, in a chunk of its own loaded with the first diff a page shows, beside
 * the editor's; a chunk a rebuild of the web app has replaced reloads the page once. */
const MergeEditors = lazyRouteComponent(() => import("./code-diff-codemirror"))

/** Two versions' Python code side by side (web/DESIGN.md, Patterns, Changes card), read only, the
 * earlier on the left and the later on the right, every line shown, each change marked in the
 * accent: its lines on the hover step, its characters underlined, and a bar in the gutter. While
 * CodeMirror loads, both codes stand as plain text in the editor's boxes, so that nothing moves
 * once it has. */
export function CodeDiff({ earlier, later }: CodeDiffProps) {
  return (
    <div data-slot="code-diff" data-testid="code-diff">
      <Suspense
        fallback={
          <div className="grid grid-cols-2 gap-3">
            <CodeText
              label={earlier.label}
              code={earlier.code}
              editable={false}
            />
            <CodeText label={later.label} code={later.code} editable={false} />
          </div>
        }
      >
        <MergeEditors earlier={earlier} later={later} />
      </Suspense>
    </div>
  )
}
