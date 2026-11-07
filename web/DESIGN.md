# FEFAT design system

The one design system of the web app (D-28). Every step that touches `web/` reads it, builds from its tokens, and adds the patterns it introduces under "Patterns", so the app stays one system. Precedence: the design brief's own words (`docs/masterplan/phases/P04-local-app.md`, "Design brief"), then this file, then unslop's values, then the `frontend-design` skill's defaults; the `apple-design` skill is the design reviewer's lens (D-34, D-77). Step 4.3 wrote it.

## Direction

- **Product.** FEFAT is a research terminal where a futures or crypto trader builds features, backtests them through an exact fill engine, and checks whether an edge survives, read for hours at a desk beside a charting platform.
- **Character.** Exact, quiet, unhurried.
- **World.** The research desk after the close: dark instrument panels, graph-paper grids, a notebook of hypotheses, figures under one lamp. It sets the ink tint of the neutrals, the hairline grids of the charts, and a monospace for whatever identifies a thing exactly.
- **Moments.** The chart, an equity or price curve in the accent with its fills marked by their sign, and the one figure that matters on a page, a large tabular number with a small unit. The home page's widgets keep their place until the steps that build runs, features, and jobs fill them.
- **Signature.** The identity chip: a version, hash, run key, or token name in the monospace, muted, in a 4 px tag, the mark of a deterministic, pinned, hashed run (D-11). The shell shows the app's version in one; later pages show every pinned identity the same way.

## Palette

Six named values carry the dark theme, the default and the one tuned first:

| Name | Hex | Role |
| --- | --- | --- |
| Desk | `#07080d` | the deepest surface: the sidebar |
| Ink | `#0b0d14` | the page |
| Panel | `#11141c` | raised surfaces: panels, widgets, forms |
| Chalk | `#eef0f5` | primary text |
| Graphite | `#a3a9b8` | secondary text |
| Cobalt | `#5aa2ff` | the accent: the primary action, the selection, focus, the figure that matters |

The tokens, as `web/src/index.css` defines them (shadcn's names, so that its components and FEFAT's code share one vocabulary; a test holds the two files equal). The contrast column gives the lowest WCAG ratio of a text colour on the surfaces it sits on.

| Role | Token | Dark | Light | Lowest contrast, dark / light |
| --- | --- | --- | --- | --- |
| Deepest surface (sidebar) | `--sidebar` | `#07080d` | `#eceff4` | |
| Page | `--background` | `#0b0d14` | `#f5f7fa` | |
| Raised surface (panel, card) | `--card` | `#11141c` | `#ffffff` | |
| Active surface (hover, selected row, field) | `--muted` | `#1a1e28` | `#eceff4` | |
| Active row in the sidebar | `--sidebar-accent` | `#1a1e28` | `#ffffff` | |
| Primary text | `--foreground` | `#eef0f5` | `#111827` | 14.61 / 15.39 |
| Secondary text | `--foreground-secondary` | `#a3a9b8` | `#4b5565` | 7.08 / 6.54 |
| Muted text and icons | `--muted-foreground` | `#808898` | `#5f6878` | 4.68 / 4.87 |
| Accent | `--primary` | `#5aa2ff` | `#1a5fd0` | 6.39 / 5.07 |
| Text on the accent | `--primary-foreground` | `#0b0d14` | `#ffffff` | 7.44 / 5.85 |
| Positive sign | `--positive` | `#4cc38a` | `#14773a` | 7.52 / 4.89 |
| Negative sign, errors | `--negative` | `#ef5a5f` | `#c42121` | 5.00 / 5.08 |

- **Colour means something.** The chrome is neutral. Cobalt marks the primary action, the selection, keyboard focus, and the one figure that matters, a few percent of a screen at most. Positive and negative mark the sign of a profit or loss, an alert or error, and the confirm of an action that cannot be undone, nothing else: no red or green decoration.
- **Hairlines.** Borders are primary text at 8 % (`--border`); a form field's border is primary text at 38 % on dark and 48 % on light (`--input`), which gives a field's edge 3 : 1 against the page and the panels (WCAG 1.4.11).
- **Contrast themes.** Where Windows forces colours, the box-shadow rings disappear, so focus takes a 2 px outline in the system's highlight colour (`src/index.css`).
- **Depth** comes from the surface steps and the hairlines. The dark theme has no shadows; the light theme gives small raised things `0 1px 2px rgba(0, 0, 0, 0.05)`.
- **Charts** (from Phase 5) take their colours from these tokens: the main series in the accent, the others in neutral steps, the sign colours for fills and P&L only.

## Type

- **IBM Plex Sans** at 400, 500, and 600 for the interface; **IBM Plex Mono** at 400 and 500 for code, hashes, versions, run keys, token values, and file paths, and never for ordinary figures. Both are under the SIL Open Font License and ship with the app from `@fontsource`, Latin subset, since the content security policy allows no remote font.
- **Figures are tabular** everywhere (`font-variant-numeric: tabular-nums` on the body), in one format per column, aligned right in tables. Dates and times read `2026-11-07 14:32`, in the trader's time zone.
- **Hierarchy comes from size and colour**, weights stay at 400 and 500, with 600 for the wordmark alone. Sentence case everywhere; no uppercase labels, no italic for emphasis; letter-spacing 0 below 16 px.

| Use | Size / line height | Weight |
| --- | --- | --- |
| Meta, counts, identity chips | 12 / 16 | 400 (mono for identities) |
| Captions, help text | 13 / 20 | 400 |
| Body, navigation, table cells, fields | 14 / 20 | 400 (500 for an active row) |
| Section titles, panel titles | 16 / 24 | 500 |
| Wordmark | 16 / 24 | 600 |
| Page title | 20 / 28 | 500 |
| The figure that matters | 28 / 32 | 500 |

## Layout

The shell is a terminal: a fixed sidebar on the deepest surface and a fluid work area on the page, where panels sit on the raised surface; nothing floats.

```text
+--------------+-----------------------------------------------------------+
| [F] FEFAT    | Home                                               56 px  |
|              +-----------------------------------------------------------+
| Home         |  +-------------------------------------+ +--------------+ |
| Lab          |  | Recent runs                    Runs | | Running jobs | |
| Strategies   |  |                                     | |              | |
| Runs         |  +-------------------------------------+ +--------------+ |
| Prop         |  +-------------------------------------+ +--------------+ |
| Agent        |  | Feature library                 Lab | | Start        | |
| Data         |  |                                     | |              | |
|              |  +-------------------------------------+ +--------------+ |
| Settings     |                                                           |
| Log out      |                                                           |
| [v0.0.0]     |                                                           |
+--------------+-----------------------------------------------------------+
     240 px              fluid, at most 1600 px, gutters of 24 px
```

- **Measures.** Sidebar 240 px; page header 56 px; content padded 24 px, so that no text touches the window's edge, and at most 1600 px wide; navigation rows 32 px with 2 px between them; table rows 32 px; form fields and their buttons 36 px; toolbar controls 32 px.
- **Spacing** sits on a 4 px scale (4, 8, 12, 16, 20, 24, 32, 40, 48, 64), in `rem` (0.25 rem a step), so that the layout survives a larger text size. Space inside a group is smaller than space between groups.
- **Alignment.** Text aligns left and numbers right; icons sit in one column, labels start on one line. A long title aligns left; only the login panel is centred.
- **Radii.** Tags and identity chips 4 px, fields, buttons, and rows 8 px, panels 12 px; an inner radius is the outer one less the padding between them, never below 4 px.
- **Targets.** Rows and fields of 32 to 36 px suit dense tables and navigation at a desk, which the brief asks for; the 44 px targets of the design reviewer's note wait for the phone pass (D-54).
- **Width.** Every page works at 1280 px without horizontal scroll; the phone layout is the backlog's phone item (D-54).

## Motion

- One easing curve, `cubic-bezier(0.22, 1, 0.36, 1)`, and three durations: 150 ms for hover, press, and toggles; 200 ms for the theme's cross-fade; 300 ms for anything that enters, when a later step needs it.
- Only colour, background, border, opacity, and transform move, each named (`transition-colors`, never `transition-all`).
- A press answers on pointer-down on every control (the design brief): buttons, rows, and links scale to 0.98, and a text link turns to primary text.
- The theme cross-fades on background and text colour, and only when the trader switches it; a theme painted on load switches with every transition off (`src/ui/theme.ts`), since 73 colour transitions would otherwise run at once.
- At most one deliberate motion per screen that the app starts by itself (an entrance, an automatic transition, a pulsing mark); feedback to the trader's own input does not count. The shell starts none.
- `prefers-reduced-motion: reduce` sets every duration to zero, the theme's cross-fade included.

## Copy

- Plain verbs, sentence case, no exclamation marks, no trailing period on a label, a button, or a title.
- An action keeps its name from the button to its result: "Change password" gives "Password changed", "Revoke" gives the token gone from the list.
- Errors say what happened and what to do: "That is not FEFAT's password. Type it again.", "The server did not answer: is fefat up still running?".
- A page not built yet says what it will do, in one line, and that it is not built yet; it never shows invented data.
- Each tab names the page, then FEFAT: `Lab – FEFAT`. The login page shows FEFAT with "feature engineering for algorithmic trading" small beneath it.

## Principles

1. **Figures first.** The page exists for its numbers and charts; the chrome stays quiet so that they read at once.
2. **Colour means sign.** Red and green say whether money was made or lost, or that something failed; Cobalt says where you are and what to do next.
3. **Dense, never crowded.** Many rows on one screen, each at a readable size and contrast, grouped by space rather than boxes.
4. **No interruptions.** Inline edits and undo for routine actions; a confirmation only where an action cannot be undone, inline rather than in a dialog; settings one level deep.
5. **Exactness shows.** Identities appear whole in the monospace chip, numbers come from the API unchanged, and nothing is rounded for looks.
6. **Dark first.** The dark theme is tuned first and paints first; the light theme follows the same ramp.

## Patterns

- **Shell.** The sidebar lists Home, Lab, Strategies, Runs, Prop, Agent, and Data, then Settings and Log out at its foot with the version's identity chip. An active row takes the active surface, primary text, and a Cobalt icon; the others take secondary text and muted icons. Lucide icons at 16 px, stroke 1.5, in an icon box 24 px wide, centred under the mark, and 8 px from the label, so that every label starts on the line of the wordmark. The sidebar spans the page's height, and its contents stay in view.
- **Page header.** 56 px tall, the page title at 20 px left-aligned, any page actions on the right.
- **Panel.** The raised surface with a hairline, radius 12 px, padding 20 px, its title at 16 px with an optional quiet link on the right. Panels in one row differ in width when their content does.
- **Login panel.** 360 px wide, anchored at 30 % of the window's height rather than centred, so that a refusal grows it downward: the F monogram, the wordmark, the tagline, the password field, and "Log in".
- **Forms.** react-hook-form with zod. The label sits 8 px above its field, and fields sit 20 px apart; a field's rules are checked when it is left (the login's on submit); an error sits under its field in the negative colour, and a refusal of one field by the server sits there too, the field taking the focus with its text selected; a control whose request is in flight is disabled; the primary button closes the form; a success shows as one line of secondary text beside the button.
- **Settings section.** Its title at 16 px, what it changes in one line of secondary text at 13 px, then its controls; sections are divided by a hairline, 24 px apart, and settings stay one level deep.
- **Read-only value.** A path or an identity the trader cannot change here, in the monospace on the active surface with a hairline, and the way to change it said in the section's line.
- **Secret shown once.** A box on the active surface with its warning, the secret in the monospace, and Copy, which says when the copy is refused; it leaves with the page, or once the secret is revoked.
- **Inline confirmation.** For an action that cannot be undone: the trigger gives way to Keep, in its place and focused, with the confirm beside it in the negative colour, so that a double click keeps; the confirm's refusal shows under the row.
- **Tables.** 32 px rows divided by hairlines, a row's own controls fitting inside them, a header in muted text at 13 px, numbers and dates aligned right in one format.
- **Identity chip.** IBM Plex Mono at 12 px, muted text on the active surface with a hairline, which keeps it visible on the light sidebar, whose surface is the active one; radius 4 px, padding 2 by 6 px.
- **Placeholder.** A panel or page not built yet: one line of secondary text on what it will hold, and, on a page, "Not built yet" in muted text; a home widget leads to its page from its title row.
- **Error and not-found pages.** The page title says what happened ("Something broke on this page", "This page does not exist"), the error's message follows in the monospace, and one button leads on.
- **Overlays.** None yet: Radix's dialogs, menus, and selects lock scrolling with a style element that the content security policy refuses (`BACKLOG.md`), so inline confirmations and radio groups take their place.
- **shadcn/ui.** `src/ui/` keeps the components as the shadcn CLI writes them, formatted by oxfmt in their own style, so that `shadcn add --diff` shows upstream changes alone; they are themed through these tokens and a few unlayered rules of `src/index.css` keyed on their `data-slot`, which name their transitions and give buttons their press.

## Review against the generic defaults

The plan was checked against the defaults the `frontend-design` skill lists and unslop's signs before any code; what changed, and why:

- **The near-black page with one bright accent** is the second default the skill names. The brief asks for dark first and quiet chrome, so the dark page stays, but the neutrals take unslop's ink ramp, tinted toward the night desk, with three text roles, rather than a flat `#111`; and the accent sits on the selection and focus as much as on buttons, so it is a working colour, not a sticker.
- **The accent.** Cobalt rather than amber, which the builder chose at the plan: it sits farthest in hue from the red and green that mean sign, so a selected row or a primary button never reads as a profit, a loss, or a warning in a dense table. It is a drafting blue, `#5aa2ff`, not a framework's stock blue, and darkens to `#1a5fd0` on light surfaces for contrast.
- **A monospace for small data labels** is a tell the skill names. The mono here is confined to identities that must be read exactly (versions, hashes, keys, paths), and every ordinary figure uses Plex Sans' tabular figures.
- **Template chrome.** No eyebrow labels, uppercase tracked labels, middle-dot meta strings, arrows after links, or numbered markers; the sidebar has no section labels, since its eight items need none.
- **The SaaS card kit.** The home widgets are hairline panels of different widths over the content they will hold, not a grid of identical shadowed cards.
- **The page title** is 20 px rather than unslop's 28 to 36: a terminal's title shares its row with controls and should not outweigh the figures beneath it.
- **The primary button** on dark is Cobalt with ink text, rather than unslop's off-white fill, so that the one accent is also the one bright control.
- **Contrast.** Unslop's ink values were measured on every surface they sit on: dark muted text moved from `#7a8296` to `#808898`, dark negative from `#e5484d` to `#ef5a5f`, and the light theme's muted, positive, and negative from `#6b7487`, `#16a34a`, and `#dc2626` to `#5f6878`, `#14773a`, and `#c42121`, which each failed 4.5 : 1 on the sidebar or a selected row.
- **Targets.** 32 to 36 px rows rather than 44 px targets, recorded under "Layout", since the brief asks for dense tables and the 44 px note concerns the phone, deferred by D-54.
- **Field borders**, after the design review: a hairline at 14 % gave a field's edge 1.5 : 1, under WCAG 1.4.11's 3 : 1 for the boundary that identifies a control, so `--input` takes 38 % on dark and 48 % on light, while every other border stays a hairline.

The neutral ramp starts from unslop's ink ramp: unslop by Damir Sokolovsky ([@heydamir](https://x.com/heydamir)), CC BY 4.0.
