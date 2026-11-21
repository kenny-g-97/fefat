import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
  isolateHistory,
} from "@codemirror/commands"
import { python } from "@codemirror/lang-python"
import {
  bracketMatching,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language"
import { linter, setDiagnostics } from "@codemirror/lint"
import { Annotation, Compartment, EditorState } from "@codemirror/state"
import { EditorView, keymap, lineNumbers } from "@codemirror/view"
import { useEffect, useEffectEvent, useRef } from "react"
import { lineSpan } from "./code-diagnostics"
import type { CodeEditorProps } from "./code-editor"
import { codeHighlight, codeTheme } from "./code-editor-look"

type CodeMirrorEditorProps = CodeEditorProps &
  Readonly<{ describedBy: string | null }>

/** A change of the code the page made, such as a draft discarded, which it knows already. */
const fromThePage = Annotation.define<boolean>()
const named = new Compartment()
const editing = new Compartment()

/** `CodeEditor`'s CodeMirror, in a module of its own, which the page loads on demand: line
 * numbers, undo, bracket matching, and Python's syntax, Tab indenting, where Escape then Tab
 * leaves the editor, CodeMirror's own way out; no search, completion, or folding, and the
 * browser's own caret, which no animation of the app's makes blink. The notes the page gives
 * stand on their lines, without CodeMirror's tooltip, since the page lists them; a change the
 * page makes, such as a draft discarded, is an undo step of its own, so that Ctrl+Z takes back
 * that change alone. */
export default function CodeMirrorEditor({
  label,
  code,
  onChange,
  notes = [],
  waiting = false,
  describedBy,
}: CodeMirrorEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const shownNotes = useRef<string | null>(null)
  const editable = onChange !== undefined
  const typed = useEffectEvent((text: string) => onChange?.(text))
  const firstState = useEffectEvent(() =>
    EditorState.create({
      doc: code,
      extensions: [
        ...codeEditing,
        editing.of(editingMode(editable, waiting)),
        named.of(naming(label, describedBy)),
        EditorView.updateListener.of((update) => {
          const byHand = update.transactions.some(
            (each) => each.docChanged && each.annotation(fromThePage) !== true
          )
          if (byHand) {
            typed(update.state.doc.toString())
          }
        }),
      ],
    })
  )

  // Built once: the effects below carry the mode, the names, the code, and the notes to it.
  useEffect(() => {
    const parent = host.current
    if (parent === null) {
      return
    }
    const created = new EditorView({ parent, state: firstState() })
    view.current = created
    return () => {
      created.destroy()
      view.current = null
      shownNotes.current = null
    }
  }, [])

  useEffect(() => {
    view.current?.dispatch({
      effects: [
        editing.reconfigure(editingMode(editable, waiting)),
        named.reconfigure(naming(label, describedBy)),
      ],
    })
  }, [editable, waiting, label, describedBy])

  useEffect(() => {
    const current = view.current
    if (current === null || current.state.doc.toString() === code) {
      return
    }
    current.dispatch({
      changes: { from: 0, to: current.state.doc.length, insert: code },
      annotations: [fromThePage.of(true), isolateHistory.of("full")],
    })
  }, [code])

  useEffect(() => {
    const current = view.current
    // A page draws its notes anew at each render: the same notes on the same code stay put.
    const shown = `${JSON.stringify(notes)}\n${code}`
    if (current === null || shownNotes.current === shown) {
      return
    }
    shownNotes.current = shown
    const doc = current.state.doc
    const marked = notes.map((note) => ({
      ...lineSpan(doc, note.line),
      severity: note.severity,
      message: note.message,
    }))
    current.dispatch(setDiagnostics(current.state, marked))
  }, [notes, code])

  return <div ref={host} />
}

const codeEditing = [
  lineNumbers(),
  history(),
  bracketMatching(),
  indentUnit.of("    "),
  python(),
  syntaxHighlighting(codeHighlight),
  codeTheme,
  keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
  linter(null, { tooltipFilter: () => [] }),
]

function editingMode(editable: boolean, waiting: boolean) {
  return [
    EditorView.editable.of(editable),
    EditorState.readOnly.of(!editable || waiting),
    EditorView.editorAttributes.of({ "data-editable": String(editable) }),
  ]
}

function naming(label: string, describedBy: string | null) {
  return EditorView.contentAttributes.of(
    describedBy === null
      ? { "aria-label": label }
      : { "aria-label": label, "aria-describedby": describedBy }
  )
}
