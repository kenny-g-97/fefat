import { lazy, Suspense } from "react"

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
}>

const CodeMirrorEditor = lazy(() => import("./code-editor-codemirror"))

/** Python code in CodeMirror 6 (web/DESIGN.md, Patterns, Code editor), named for a screen reader
 * by `label`: editable where the page takes its `onChange`, else read-only, with its `notes`
 * underlined at their lines. CodeMirror's code loads with the first page that shows an editor,
 * the code standing as plain text meanwhile; the strategy page uses it (step 5.5), and the
 * feature lab and the builder of Phase 6 after it. */
export function CodeEditor(props: CodeEditorProps) {
  return (
    <div data-slot="code-editor">
      <Suspense fallback={<CodeText label={props.label} code={props.code} />}>
        <CodeMirrorEditor {...props} />
      </Suspense>
    </div>
  )
}

/** The code as the editor shows it, with its line numbers, while CodeMirror loads. */
function CodeText({ label, code }: Readonly<{ label: string; code: string }>) {
  return (
    <div
      role="region"
      aria-label={label}
      className="overflow-x-auto rounded-xl border bg-muted py-2 text-sm leading-5"
    >
      {code.split("\n").map((line, index) => (
        <div key={index} className="flex">
          <span className="w-12 shrink-0 pr-3 text-right text-muted-foreground select-none">
            {index + 1}
          </span>
          <span className="px-4 whitespace-pre">{line}</span>
        </div>
      ))}
    </div>
  )
}
