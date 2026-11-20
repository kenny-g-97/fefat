import { HighlightStyle } from "@codemirror/language"
import { EditorView } from "@codemirror/view"
import { tags } from "@lezer/highlight"

/** The editor drawn from web/DESIGN.md's tokens, so that it follows the theme the page shows:
 * every colour CodeMirror's own theme sets for a light page is set here, its caret, gutter,
 * bracket match, selection, underlines, and focus. A read-only editor is a box of code on the
 * control surface with a hairline; an editable one is a field, in the field border, its focus the
 * accent's border with a 1 px ring of the accent. A bracket and its match beside the cursor take
 * the hover step with a hairline, and a bracket that closes nothing the negative's text and
 * outline, a mark and not a fill. Errors take a wavy underline in the negative and warnings a
 * dotted one in body text, as text decorations, where CodeMirror draws a red and an orange
 * squiggle as images. */
export const codeTheme = EditorView.theme({
  "&": {
    color: "var(--foreground)",
    backgroundColor: "var(--muted)",
    border: "1px solid var(--border)",
    borderRadius: "0.75rem",
    fontSize: "0.875rem",
  },
  "&[data-editable=true]": { borderColor: "var(--input)" },
  "&.cm-focused": {
    outline: "none",
    borderColor: "var(--ring)",
    boxShadow: "0 0 0 1px var(--ring)",
  },
  ".cm-scroller": {
    fontFamily: "inherit",
    lineHeight: "1.25rem",
    borderRadius: "inherit",
  },
  ".cm-content": { padding: "0.5rem 0", caretColor: "var(--foreground)" },
  ".cm-content ::selection": {
    backgroundColor: "var(--primary)",
    color: "var(--primary-foreground)",
  },
  ".cm-line": { padding: "0 1rem" },
  ".cm-gutters": {
    backgroundColor: "var(--muted)",
    color: "var(--muted-foreground)",
    borderRight: "1px solid var(--border)",
    borderRadius: "0.75rem 0 0 0.75rem",
  },
  ".cm-lineNumbers .cm-gutterElement": {
    minWidth: "3rem",
    padding: "0 0.75rem 0 1rem",
  },
  ".cm-matchingBracket, &.cm-focused .cm-matchingBracket": {
    backgroundColor: "var(--accent)",
    outline: "1px solid var(--input)",
  },
  ".cm-nonmatchingBracket, &.cm-focused .cm-nonmatchingBracket": {
    backgroundColor: "transparent",
    color: "var(--negative)",
    outline: "1px solid var(--negative)",
  },
  ".cm-lintRange": { backgroundImage: "none", paddingBottom: "0" },
  ".cm-lintRange-error": {
    textDecoration: "underline wavy var(--negative)",
    textUnderlineOffset: "4px",
  },
  ".cm-lintRange-warning": {
    textDecoration: "underline dotted var(--foreground-secondary)",
    textUnderlineOffset: "4px",
  },
  ".cm-lintPoint:after": { borderBottomColor: "var(--negative)" },
  ".cm-lintPoint-warning:after": {
    borderBottomColor: "var(--foreground-secondary)",
  },
})

/** Python's syntax in the system's few roles: keywords at 600 in heading text, comments in
 * subtle text, strings in body text, and the numbers and the flags a trader tunes in the brand
 * colour, the one bright thing of a strategy's code. */
export const codeHighlight = HighlightStyle.define([
  { tag: tags.keyword, fontWeight: "600" },
  { tag: tags.comment, color: "var(--muted-foreground)" },
  { tag: tags.string, color: "var(--foreground-secondary)" },
  { tag: [tags.number, tags.bool], color: "var(--brand)" },
])
