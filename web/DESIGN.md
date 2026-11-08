# FEFAT design system

The one design system of the web app (D-28). It applies the Contemporary skill (`.claude/skills/contemporary-typeui/`), the reference the design brief follows exactly (D-88), to FEFAT, and records each place where FEFAT departs from the skill, with its reason. Every step that touches `web/` reads it, builds from its tokens, and adds the patterns it introduces under "Patterns", so the app stays one system. Precedence: the design brief's own words (`docs/masterplan/phases/P04-local-app.md`, "Design brief"), then this file, then the skill's values, then unslop's, then the `frontend-design` skill's defaults; the `apple-design` skill is the design reviewer's lens (D-34, D-77, D-88). Step 4.3 wrote it.

## Direction

- **Product.** FEFAT is a research terminal where a futures or crypto trader builds features, backtests them through an exact fill engine, and checks whether an edge survives, read for hours at a desk beside a charting platform.
- **Character.** Exact, dense, tech-forward: a terminal, not a desk.
- **World.** Monospaced readouts on near-black panels at night, the skill's world: pure greys with no tint, hairlines in place of shadows, and one hot-pink indicator that marks where you are, what to do next, and the data that matters.
- **Moments.** The chart, an equity or price curve in the pink with its fills marked by their sign, and the one figure that matters on a page, a bold tabular number. The home page's cards keep their place until the steps that build runs, features, and jobs fill them.
- **Signature.** The skill's, kept whole: Geist Mono for every text, one 12 px radius on everything, and bold tabular figures on a four-step grey ramp with hairlines; and FEFAT's identity chip, a version, hash, run key, or token name in a 12 px tag, the mark of a deterministic, pinned, hashed run (D-11).

## Palette

Six named values carry the dark theme, the default and the one tuned first; they are the skill's:

| Name | Hex | Role |
| --- | --- | --- |
| Night | `#050505` | the page |
| Panel | `#0a0a0a` | cards |
| Control | `#111111` | the sidebar, fields, and the boxes inside cards |
| Hairline | `#1a1a1a` | borders, and the hover step |
| Heading | `#ededed` | headings, labels, names, and figures |
| Pink | `#f44174` | the accent: the primary action, the active item, focus, links, and the data |

The tokens, as `web/src/index.css` defines them under shadcn's names, so that its components and FEFAT's code share one vocabulary; a test holds the two files equal. The light theme is FEFAT's, since the skill is dark only: the same steps in grey and white, the pink fills unchanged, and the pink, green, and red darkened where they are text. The contrast column gives the lowest WCAG ratio of a colour on the surfaces it sits on.

| Role | Token | Dark | Light | Lowest contrast, dark / light |
| --- | --- | --- | --- | --- |
| Page | `--background` | `#050505` | `#f5f5f5` | |
| Card | `--card` | `#0a0a0a` | `#ffffff` | |
| Sidebar | `--sidebar` | `#111111` | `#ececec` | |
| Control surface: a field, a box in a card | `--muted` | `#111111` | `#ececec` | |
| Hover step, identity chip | `--accent` | `#1a1a1a` | `#e0e0e0` | |
| Hairline | `--border` | `#1a1a1a` | `#e0e0e0` | |
| A field's border | `--input` | `#666666` | `#868686` | 3.29 / 3.08, a boundary |
| Heading text | `--foreground` | `#ededed` | `#121212` | 14.87 / 14.19 |
| Body text | `--foreground-secondary` | `#888888` | `#555555` | 4.91 / 5.65 |
| Subtle text | `--muted-foreground` | `#7c7c7c` | `#6b6b6b` | 4.52 / 4.51 |
| Accent fill | `--primary` | `#f44174` | `#f44174` | |
| Accent fill under the pointer | `--primary-hover` | `#ff5a89` | `#ff5a89` | |
| Text on the accent | `--primary-foreground` | `#050505` | `#050505` | 5.68 / 5.68 |
| Accent as text and icons | `--brand` | `#f44174` | `#c8175a` | 5.26 / 4.77 |
| The active item's fill | `--brand-soft` | `#1a0810` | `#fde8ef` | |
| The active item's border | `--brand-soft-border` | `#3d0e1f` | `#f5c2d3` | |
| The active item's label and icon | `--brand-soft-foreground` | `#ffb0c7` | `#c8175a` | 11.31 / 4.82 |
| Positive sign | `--positive` | `#10b981` | `#0a7a4c` | 7.44 / 4.56 |
| Negative sign, errors | `--negative` | `#ff6677` | `#cc2244` | 6.67 / 4.58 |
| The danger action's fill under the pointer | `--negative-soft` | `#1a0508` | `#fdeaed` | |

- **Colour means something.** The chrome is grey. The pink marks the primary action, the active item, keyboard focus, links, and the data that matters; positive and negative mark the sign of a profit or loss, an alert or error, and the confirm of an action that cannot be undone, nothing else: no red or green decoration. Log out is a neutral row, not the skill's red text, for that reason.
- **Lifted for contrast.** The skill's values that fail WCAG on these surfaces are lifted to the first that passes: subtle text from `#666` (3.45 : 1 on a card) to `#7c7c7c`; a field's border from `#222` (1.24 : 1) to `#666`, 3 : 1 against the card and the field (1.4.11); text on the pink in ink, `#050505`, at 5.68 : 1, where the skill's white gives 3.59 : 1; and focus as a 2 px outline in the pink, 2 px outside the control, where the skill's 4 px rings in `#3d0e1f` and `#111` give 1.24 : 1 on the page. Lifted so, subtle text sits close to body text, so meta also takes the smaller size.
- **Hairlines and depth.** Borders are the hairline, a grey rather than an alpha. Depth comes from the surface steps and the hairlines; cards, fields, and tiles take one small neutral shadow, `0 1px 2px` in black at 45 % on dark and 6 % on light. The border colour of every element is set in the base layer, so that a transparent or a semantic border still shows (a tell of the skill's reference).
- **Steps that read.** A thing that must read on a surface takes the next step, never the same grey: a hovered sidebar row takes the hairline step, since the control step is the sidebar's own, and the identity chip takes the hairline step on the sidebar and on a card alike. Light pink text never sits on the light hover step, where it would fall to 4.27 : 1.
- **Contrast themes.** Where Windows forces colours, a field's focus ring disappears with every box-shadow, so focus takes a 2 px outline in the system's highlight colour there (`src/index.css`).
- **Charts** (from Phase 5) take their colours from these tokens: the lead series in the pink, the others in neutral steps (`#252525`, `#1a1a1a`), the sign colours for fills and P&L only; several hues only where a chart tells series apart.

## Type

- **Geist Mono** at 400, 500, 600, and 700 for every text, the skill's one family. It ships with the app from `@fontsource/geist-mono`, Latin subset, under the SIL Open Font License, since the content security policy allows no remote font. A monospace everywhere sets every identity and figure exactly, so the identity chip is told apart by its tag, not by its face.
- **Figures are tabular** everywhere (`font-variant-numeric: tabular-nums` on the body), in one format per column, aligned right in tables; a figure that matters takes 700 with -0.025em of tracking. Dates and times read `2026-11-07 14:32`, in the trader's time zone.
- **Hierarchy comes from size, colour, and weight together**, as the skill has it: the interface at 14 px, meta at 12 px, and only titles and figures above 16 px. Sentence case everywhere, except the two places the skill allows uppercase with open tracking, table headers and a sidebar group label. No italic, and no underline at rest.

| Use | Size / line height | Weight | Colour |
| --- | --- | --- | --- |
| Meta, hints, times, the tagline, "Not built yet" | 12 / 16 | 400 | subtle |
| A table's headers | 12 / 16, uppercase, 0.125 rem of tracking | 600 | body |
| Identity chip | 12 / 16 | 400 | body |
| Body, descriptions, table cells, errors | 14 / 20 | 400 | body, or negative |
| Navigation rows, labels, names, a field's text | 14 / 20 | 500 | heading |
| Text links | 14 / 20 | 600 | accent |
| Card titles, the wordmark | 16 / 24 | 600 | heading |
| A stat's value (from Phase 5) | 24 / 32, -0.025em | 700 | heading |
| The figure that matters (from Phase 5) | 30 / 36, -0.025em | 700 | heading |
| Page title | 26 to 36, as the window widens / 1.2, -0.02em | 600 | heading |

## Layout

The shell is the skill's: a sidebar on the control surface beside a fluid page, where cards sit 24 px apart; nothing floats.

```text
+----------------+--------------------------------------------------------+
| [F] FEFAT      |                                                        |
+----------------+  Home                                                  |
| Home           |                                                        |
| Lab            |  +--------------------------------+ +---------------+  |
| Strategies     |  | Recent runs        All runs -> | | Running jobs  |  |
| Runs           |  |                                | |               |  |
| Prop           |  +--------------------------------+ +---------------+  |
| Agent          |  +--------------------------------+ +---------------+  |
| Data           |  | Feature library All features ->| | Start         |  |
|                |  |                                | |               |  |
+----------------+  +--------------------------------+ +---------------+  |
| Settings       |                                                        |
| Log out        |                                                        |
| [FEFAT 0.0.0]  |                                                        |
+----------------+--------------------------------------------------------+
      256 px          fluid, padded 32 px, at most 1600 px wide
```

- **Measures.** Sidebar 256 px with a hairline on its right; its brand row 72 px over a hairline; navigation rows 40 px, 4 px apart, in blocks padded 16 by 12 px; the page padded 32 px, its header 32 px above the content; cards 24 px apart and padded 24 px; fields and buttons 40 px; a table's rows 40 px with 32 px controls; the content at most 1600 px wide.
- **Spacing** sits on a 4 px scale in `rem` (0.25 rem a step), so that the layout survives a larger text size: 4 between rows, 8 inside controls, 12 between an icon or a tile and its text, 16 inside the sidebar's blocks, 20 under a card's header, 24 for a card's padding and between cards, 32 for the page's padding.
- **Alignment.** Text aligns left and numbers right; icons sit in one column, labels start on one line. Only the login card is centred.
- **Radius.** One, 12 px, on everything from a card to a chip, the skill's signature: small things read as pills, large ones as rounded cards, and no second radius is added for variety.
- **Targets.** Rows and fields of 32 to 40 px suit dense tables and navigation at a desk, which the brief asks for; the 44 px targets of the design reviewer's note wait for the phone pass (D-54).
- **Width.** Every page works at 1280 px without horizontal scroll; the phone layout, the skill's "Phones" section, waits for the backlog's phone item (D-54).

## Motion

- The skill's timing: 150 ms on `cubic-bezier(0.4, 0, 0.2, 1)` for hover, press, and toggles, and 200 ms for the theme's cross-fade.
- Only colour, background, border, shadow, and transform move, each named (`transition-colors`, never `transition-all`).
- A press answers on pointer-down on every control (the design brief): buttons, rows, and links scale to 0.98, and a text link turns to heading text; a radio, too small for a scale to show, takes the accent on its border, its label's press included. A hover is one surface step, never a scale.
- The theme cross-fades on background and text colour, and only when the trader switches it; a theme painted on load switches with every transition off (`src/ui/theme.ts`), since 73 colour transitions would otherwise run at once.
- At most one deliberate motion per screen that the app starts by itself (an entrance, an automatic transition, a pulsing mark); feedback to the trader's own input does not count. The shell starts none: nothing loops, pulses, or enters on load.
- `prefers-reduced-motion: reduce` sets every duration to zero, the theme's cross-fade included.

## Copy

- Plain verbs, sentence case, no exclamation marks, and one spelling for one action ("Log out"). No trailing period on a label, a button, a title, or a description or hint of one sentence, as the skill writes them; a message of two sentences, such as an error, keeps its periods.
- An action keeps its name from the button to its result: "Change password" gives "Password changed", "Revoke" gives the token gone from the list.
- Errors say what happened and what to do: "That is not FEFAT's password. Type it again.", "The server did not answer: is fefat up still running?".
- A page names its place, never greets. A page not built yet says what it will do under its title, in one line, and that it is not built yet; it never shows invented data.
- Each tab names the page, then FEFAT: `Lab – FEFAT`. The login page shows FEFAT with "feature engineering for algorithmic trading" small beneath it.

## Principles

1. **Figures first.** The page exists for its numbers and charts; the chrome stays grey so that they read at once.
2. **Colour means sign.** Red and green say whether money was made or lost, or that something failed; the pink says where you are, what to do next, and which figure matters.
3. **Dense, never crowded.** Many rows on one screen, each at a readable size and contrast, grouped by space and by hairline cards.
4. **No interruptions.** Inline edits and undo for routine actions; a confirmation only where an action cannot be undone, inline rather than in a dialog; settings one level deep.
5. **Exactness shows.** Identities appear whole in the chip, numbers come from the API unchanged, and nothing is rounded for looks.
6. **Dark first.** The dark theme is the skill's and paints first; the light theme follows the same steps in grey and white.

## Patterns

- **Shell.** The sidebar's brand row, the 40 px monogram tile 12 px from FEFAT at 16 px and 600; then Home, Lab, Strategies, Runs, Prop, Agent, and Data; then, under a hairline, Settings, Log out, and the version's identity chip. A row is 40 px, padded 12 px, with a 20 px lucide icon (stroke 2) 12 px from its label, both in heading text at 500; the active row takes the brand's soft fill and border, the skill's intended border that its reference lost, with its label and icon in the brand's soft foreground, and a hovered row the hairline step. The sidebar spans the window's height, and its contents stay in view. A group label, 12 px uppercase with 0.2em of tracking in subtle text, arrives with a second group of rows; the skill's user row and quick actions wait for something to hold.
- **Top bar.** None yet: the skill's 64 px sticky top bar arrives with step 4.4's running-jobs indicator (D-88), solid or blurred rather than the reference's unblurred glass.
- **Page header.** The page title, then its one-line description 4 px below in body text, 32 px above the content; any page actions on the right.
- **Card.** The card surface with a hairline and the small shadow, radius 12 px, padding 24 px: its title at 16 px and 600, an optional one-line description 4 px below in body text, a text link or a badge on the right, and its content 20 px below. Cards in one row differ in width when their content does. An icon tile only where the icon identifies the item, never one per card.
- **Text link.** 14 px at 600 in the accent, no underline at rest and one under the pointer, with a 16 px arrow 6 px after it when it leads to another page; a pressed link turns to heading text.
- **List row in a card.** A link padded 8 px with a transparent hairline, its 16 px icon in body text 12 px from its label in heading text, since the brief keeps the accent rare; under the pointer, the control surface and the hairline, its label in the accent.
- **Login card.** 384 px wide, anchored at 30 % of the window's height rather than centred, so that a refusal grows it downward: the monogram tile, the wordmark, the tagline, the password field, and "Log in" across the card.
- **Forms.** react-hook-form with zod. A label in heading text at 500 sits 8 px above its field, and fields sit 20 px apart; a field is 40 px on the control surface with the field border, its text in heading text and its placeholder in subtle text, and its focus the accent's border with a 1 px ring of the accent. A field's rules are checked when it is left (the login's on submit); an error sits under its field in the negative colour, and a refusal of one field by the server sits there too, the field taking the focus with its text selected, until the field changes; a control whose request is in flight is disabled; the primary button closes the form; a success shows as one line of body text beside the button.
- **Buttons.** The primary action, one to a form or a card, fills with the accent in ink text and lightens under the pointer; a quieter action is a ghost button in body text that takes the hover step; the confirm of an action that cannot be undone is the skill's danger action, the negative colour as text, on its soft fill under the pointer. Buttons are 40 px in forms and 32 px in a table's rows.
- **Settings.** Each section is a card, its title and its one-line description, then its controls; settings stay one level deep.
- **Read-only value.** A path or an identity the trader cannot change here, in heading text in a box on the control surface with a hairline, and the way to change it said in the card's description.
- **Secret shown once.** A box on the control surface with a hairline: its warning, the secret, and Copy, the box's one action and so the primary, which says when the copy is refused; it leaves with the page or once the secret is revoked.
- **Inline confirmation.** For an action that cannot be undone: the trigger gives way to Keep, in its place and focused, with the confirm beside it as the danger action, so that a double click keeps. The column keeps one width, 12 rem, so that the confirm moves nothing, and the confirm's refusal wraps under it.
- **Tables.** Rows of 40 px divided by hairlines, a row's own controls 32 px tall inside them, 4 px under the last row for its focus outline; headers at 12 px and 600, uppercase with 0.125 rem of tracking in body text, over a hairline; cells in body text, names in heading text, numbers and dates aligned right in one format.
- **Identity chip.** 12 px in body text on the hairline step, radius 12 px, padding 2 by 8 px; it reads on the sidebar and on a card alike.
- **Badges** (from step 4.4). The skill's: 12 px on a soft semantic fill with its strong text, radius 12 px, and a count in ink on the accent.
- **Placeholder.** A page not built yet: its description says what it will hold, and "Not built yet" sits under the header in subtle text at 12 px; a home card says what it will hold in body text and leads to its page from its title row.
- **Error and not-found pages.** The page title says what happened ("Something broke on this page", "This page does not exist"), the error's message follows in body text, and one button leads on. An unknown address, wherever it was typed, and a failure of the shell itself show their page alone, without the sidebar, in its own main landmark under the monogram and the wordmark; a page that fails keeps the shell around its error.
- **Charts** (from Phase 5). The skill's: horizontal grid lines in the hairline and no vertical grid, axis line, or tick mark; tick labels at 12 px in subtle text, the Y axis at least 40 px wide; the legend in HTML under the figure; the lead series in the accent.
- **Overlays.** None yet: Radix's dialogs, menus, and selects lock scrolling with a style element that the content security policy refuses (`BACKLOG.md`), so inline confirmations and radio groups take their place; a later overlay takes the skill's panel, the control surface with a hairline and its middle shadow.
- **shadcn/ui.** `src/ui/` keeps the components as the shadcn CLI writes them, formatted by oxfmt in their own style, so that `shadcn add --diff` shows upstream changes alone. They are themed through these tokens and a few unlayered rules of `src/index.css`: on `a` and `button`, which name their transitions and give every control its press; on `:focus-visible`, the outline; and on a few `data-slot`s, which give a field its surface, height, and focus, a button its 40 px, the primary its hover, the destructive variant the danger action, a radio its press, and a table room under its last row for the focus.

## Review against the generic defaults

The first direction, Cobalt on an ink ramp with IBM Plex, was checked against the defaults the `frontend-design` skill lists and unslop's signs at step 4.3's plan; the builder then chose the Contemporary skill as the reference to follow exactly (D-88), and the brief's words let a reference pin a look the skills would otherwise call a default. What follows the skill, what departs from it, and why:

- **The near-black page with one bright accent** is the second default `frontend-design` names, and the skill's look. The reference pins it, so it stays with the skill's own character: pure greys with no tint, a pink that sits on the data and the active item as much as on the primary button, and bold monospaced figures. The skill's template check holds: with blue for the pink and Inter for Geist Mono this would be any dark dashboard, so those, and the one radius, never change.
- **A monospace for small labels** is a tell `frontend-design` names; here the reference sets every text in one monospace, so it is the system rather than a decoration.
- **Arrows after links** are another; the skill's text links carry a 16 px arrow icon only where the link leads to another page, never a `→` in the text.
- **The pink beside the sign colours.** Cobalt was chosen at the plan for its distance from red and green; the hot pink sits nearer the red, so the pink never marks a figure's sign, a negative figure keeps its minus sign beside its colour, and an action that cannot be undone shows the negative colour as text, never a pink fill.
- **Contrast.** The skill's values were measured on every surface they sit on, and four were lifted (Palette, "Lifted for contrast"); the light theme, which the skill does not have, was built from the same steps and measured the same way, and the quality floor's contrast specs hold both themes.
- **The skill's own tells**, avoided: no greeting under the page title; no decorative icon tile on every card; one fill for every card and one weight for every card title; the border colour in the base layer; no surface on a surface of the same grey; one number format and one spelling per action; and no top bar until it has something to hold, then never glass without blur.
- **The brief over the skill.** Log out stays a neutral row rather than the skill's red text; every control answers a press on pointer-down, where the skill only steps the surface under the pointer; tables keep 40 px rows rather than the reference's 57 px; and the page stops at 1600 px rather than running fluid.
- **The page title** is the skill's 26 to 36 px rather than the first direction's 20 px: the reference sets the title alone above the cards, not in a toolbar's row.

The audit of every UI step follows unslop by Damir Sokolovsky ([@heydamir](https://x.com/heydamir)), CC BY 4.0. The Contemporary skill reads its values from TypeUI's Contemporary preview (`.claude/skills/contemporary-typeui/SKILL.md`, "Provenance").
