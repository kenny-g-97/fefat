import { lazyRouteComponent } from "@tanstack/react-router"
import { cn } from "cn"
import { Suspense, useId } from "react"

/** A note on a line of the code, which the editor underlines: an error in the negative, a
 * warning dotted in body text. */
export type CodeNote = Readonly<{
  line: number
  severity: "error" | "warning"
  message: string
}>

export type CodeEditorProps = Readonly<{
  label: string
  code: string
  onChange?: (code: string) => void
  notes?: readonly CodeNote[]
  waiting?: boolean
}>

/** CodeMirror's chunk, loaded with the first editor a page shows; a chunk a rebuild of the web
 * app has replaced reloads the page once, where React's `lazy` would keep its first failure. */
const CodeMirrorEditor = lazyRouteComponent(
  () => import("./code-editor-codemirror")
)

/** Python code in CodeMirror 6 (web/DESIGN.md, Patterns, Code editor), named for a screen reader
 * by `label`: editable where the page takes its `onChange`, else read-only, with its `notes`
 * underlined at their lines; an editable one `waiting`, as while its page saves the code, takes
 * no change and keeps its look. An editable editor says under it how to leave it by the keys,
 * which its text names as its description. CodeMirror's code loads with the first page that shows an editor, the code
 * standing as plain text in the editor's own box meanwhile; the strategy page uses it (step
 * 5.5), and the feature lab and the builder of Phase 6 after it. */
export function CodeEditor(props: CodeEditorProps) {
  const hint = useId()
  const editable = props.onChange !== undefined
  return (
    <div data-slot="code-editor" className="flex flex-col gap-3">
      <Suspense
        fallback={
          <CodeText label={props.label} code={props.code} editable={editable} />
        }
      >
        <CodeMirrorEditor {...props} describedBy={editable ? hint : null} />
      </Suspense>
      {editable && (
        <p id={hint} className="text-xs text-muted-foreground">
          Tab indents. Press Escape, then Tab, to leave the editor.
        </p>
      )}
    </div>
  )
}

/** The code as the editor shows it, in the editor's box with its gutter of line numbers, while
 * CodeMirror loads, so that nothing moves once it has. */
function CodeText({
  label,
  code,
  editable,
}: Readonly<{ label: string; code: string; editable: boolean }>) {
  const lines = code.split("\n")
  return (
    <div
      role="region"
      aria-label={label}
      className={cn(
        "flex overflow-x-auto rounded-xl border bg-muted text-sm leading-5",
        editable && "border-input"
      )}
    >
      <div
        aria-hidden="true"
        className="box-content min-w-12 shrink-0 border-r py-2 text-right text-muted-foreground select-none"
      >
        {lines.map((_, index) => (
          <div key={index} className="pr-3 pl-4">
            {index + 1}
          </div>
        ))}
      </div>
      <div className="py-2">
        {lines.map((line, index) => (
          <div key={index} className="h-5 px-4 whitespace-pre">
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}
