import { python } from "@codemirror/lang-python"
import { syntaxHighlighting } from "@codemirror/language"
import { MergeView } from "@codemirror/merge"
import { EditorState } from "@codemirror/state"
import { EditorView, lineNumbers } from "@codemirror/view"
import { useEffect, useRef } from "react"
import type { CodeDiffProps } from "./code-diff"
import { codeHighlight, codeTheme } from "./code-editor-look"

/** `CodeDiff`'s CodeMirror, in a module of its own, which the page loads on demand: a merge view
 * of the two codes, read only, with the editor's line numbers, Python's syntax, and its look, and
 * the changes marked as `src/index.css` draws them; its long lines wrap, so that a change at a
 * line's end shows in a side half the card's width, and every unchanged line stays shown, since
 * the merge view's collapsed lines open by a click alone and a version's code is tens of lines. */
export default function CodeMirrorDiff({ earlier, later }: CodeDiffProps) {
  const host = useRef<HTMLDivElement>(null)
  const { label: earlierLabel, code: earlierCode } = earlier
  const { label: laterLabel, code: laterCode } = later

  useEffect(() => {
    const parent = host.current
    if (parent === null) {
      return
    }
    const view = new MergeView({
      a: { doc: earlierCode, extensions: readOnlySide(earlierLabel) },
      b: { doc: laterCode, extensions: readOnlySide(laterLabel) },
      parent,
      highlightChanges: true,
      gutter: true,
    })
    return () => view.destroy()
  }, [earlierLabel, earlierCode, laterLabel, laterCode])

  return <div ref={host} />
}

function readOnlySide(label: string) {
  return [
    lineNumbers(),
    python(),
    syntaxHighlighting(codeHighlight),
    codeTheme,
    EditorView.lineWrapping,
    EditorView.editable.of(false),
    EditorState.readOnly.of(true),
    EditorView.contentAttributes.of({ "aria-label": label }),
  ]
}
