---
name: contemporary-typeui
description: Reproduce the "Contemporary" application style from TypeUI, a dark-only, tech-forward dashboard on a pure-grey ink ramp (#050505 page, #0a0a0a cards, #111 controls) with #ededed headings, Geist Mono for every piece of text, one 12px radius on everything from cards to badges, 1px #1a1a1a hairlines, and a single hot-pink accent (#f44174, #ff5a89). Use when the user asks for the Contemporary or TypeUI look, "the pink mono dashboard", a bento dashboard on near-black, or to match https://contemporary-typeui-99b07032.vercel.app/application while building or restyling an app shell, sidebar, top bar, stat cards, progress lists, Recharts widgets, activity feeds, data tables, forms, badges or buttons. Gives the exact tokens, type scale, spacing, component recipes, states, chart rules, motion, copy conventions, and the tells to avoid when extending the style.
---

# Contemporary (TypeUI) application style

A reverse-engineered style guide for the application route of the Contemporary TypeUI
preview, captured on 2026-11-08 from the shipped page (REA passive inspection, bundle
analysis and screenshot over the Chrome DevTools Protocol, a Playwright computed-style
probe, and unslop's snapshot and audit). Every value below was read from the live CSS or
computed styles; inferences are marked as such.

Look at [reference-application-1440.png](reference-application-1440.png) before you build:
it is the full page at 1440 wide. The site describes the system as "a dark, glass-forward
Contemporary system: Geist Mono, hot-pink brand, and bento layouts", and the application
route as a "dashboard shell with sidebar, charts, widgets, and activity table".

## Direction

- **Product.** A workspace dashboard for a small software team: revenue, users, orders,
  conversion, sales by channel, quarterly goals, top content, traffic sources, activity,
  and a transactions table. Apply the style to any dense, data-first app.
- **Character.** Tech-forward, dense, bold. Hot rather than warm; a terminal, not a desk.
- **World.** Neon on black glass at night: monospaced readouts on near-black panels, one
  hot-pink indicator. The greys are pure, with no tint; the pink is the only hue the chrome
  knows.
- **Moments.** The pink data: bars, progress fills, deltas, the active item, the one primary
  button. Series charts may add purple and cyan, nothing else.
- **Signature.** One 12px radius on everything, from a 540px card to an 8px progress bar,
  carrying Geist Mono figures in weight 700 on a four-step grey ramp with 1px #1a1a1a
  hairlines.

## Tokens

Dark only. The preview ships no light theme (its sun button is inert). Copy this block as
`:root`; names follow the source so Tailwind v4 users can register them under `@theme`.

```css
:root {
  color-scheme: dark;

  /* Surfaces: a pure-grey ramp, four steps */
  --neutral-primary: #050505;         /* page */
  --neutral-primary-soft: #0a0a0a;    /* cards, stat icon tiles, quick-action buttons, table head band */
  --neutral-secondary-soft: #0a0a0a;
  --neutral-tertiary-soft: #0e0e0e;   /* alternate stat cards, rank tiles */
  --neutral-primary-medium: #111;     /* sidebar, inner panels, dropdown fills */
  --neutral-secondary-medium: #111;   /* inputs, icon buttons, segmented container, activity tiles, hover rows */
  --neutral-tertiary: #111;           /* progress tracks, focus ring on icon buttons */
  --neutral-primary-strong: #1a1a1a;
  --neutral-secondary-strong: #1a1a1a;
  --neutral-tertiary-medium: #1a1a1a; /* hover fill for icon buttons */
  --neutral-quaternary: #1a1a1a;
  --quaternary-medium: #252525;
  --gray: #252525;
  --disabled: #111;
  --glass-bg: #0a0a0ab8;              /* top bar: 72% of the card grey, no blur in the app */

  /* Text: three roles */
  --heading: #ededed;     /* headings, figures, labels, names, icons in buttons */
  --body: #888;           /* copy, table cells, table headers, legend, idle controls */
  --body-subtle: #666;    /* hints, times, emails, group labels, axis ticks, placeholders */
  --fg-disabled: #444;

  /* Brand: the one accent */
  --brand: #f44174;           /* fills: primary button, pressed segment, progress, chart-1, count badge */
  --brand-strong: #ff5a89;    /* primary button hover */
  --brand-medium: #3d0e1f;    /* focus ring on primary buttons */
  --brand-soft: #3d0e1f;
  --brand-softer: #1a0810;    /* active nav row, sidebar avatar, card-header icon tiles */
  --fg-brand: #f44174;        /* pink text, icons, links */
  --fg-brand-strong: #ffb0c7; /* active nav label, sidebar avatar initials */
  --fg-brand-subtle: #3d0e1f;

  /* Semantic: soft fill + strong text, toned into the ink */
  --success: #0c8;  --success-strong: #096;  --success-soft: #061a14;  --success-medium: #0a2e22;
  --fg-success-strong: #10b981;  --fg-success: #065f46;  --border-success-subtle: #0a2e22;
  --warning: #f83;  --warning-strong: #d51;  --warning-soft: #1a0e04;  --warning-medium: #331a08;
  --fg-warning: #fb3;  --fg-warning-subtle: #f83;  --border-warning-subtle: #331a08;
  --danger: #f35;   --danger-strong: #c24;   --danger-soft: #1a0508;   --danger-medium: #3d0a14;
  --fg-danger: #f46;  --fg-danger-strong: #f67;  --border-danger-subtle: #3d0a14;
  --fg-info: #93c5fd;

  /* Series hues: only inside charts and multi-series progress lists */
  --purple: #a855f7;  --cyan: #06b6d4;  --teal: #0d9488;

  /* Borders: greys, never alpha */
  --border-default: #1a1a1a;        /* cards, dividers, inputs, tiles: the only border that renders in the preview */
  --border-default-subtle: #0e0e0e;
  --border-default-medium: #222;    /* intended on inputs and icon buttons */
  --border-default-strong: #333;    /* intended on hover */
  --border-brand: #f44174;          /* input focus */
  --border-brand-subtle: #3d0e1f;   /* intended on the active nav row and the avatar */

  /* Shadows: neutral black only, all small */
  --shadow-2xs: 0 1px #0006;
  --shadow-xs: 0 1px 2px 0 #00000073;                             /* cards, inputs, icon buttons, tiles */
  --shadow-sm: 0 1px 3px 0 #00000080, 0 1px 2px -1px #0006;
  --shadow-md: 0 4px 6px -1px #00000080, 0 2px 4px -2px #0006;   /* menus, skip link, card hover */
  --shadow-lg: 0 10px 15px -3px #0000008c, 0 4px 6px -4px #00000073;
  --shadow-xl: 0 20px 25px -5px #0009, 0 8px 10px -6px #00000080;
  --shadow-2xl: 0 25px 50px -12px #000000b3;

  /* Radius: one value */
  --radius-base: 12px;   /* cards, buttons, inputs, badges, tiles, nav rows, dots, bars */
  --radius-sm: 12px;     /* focus outline, skip link */
  --radius-full: 9999px; /* the goals card's progress bars only */

  /* Type: one family, in the mono slot */
  --font-mono: "Geist Mono", "Geist Mono Fallback", ui-monospace, monospace;
  --font-weight-medium: 500; --font-weight-semibold: 600; --font-weight-bold: 700;
  --text-xs: 0.75rem;  --text-xs--line-height: calc(1 / 0.75);
  --text-sm: 0.875rem; --text-sm--line-height: calc(1.25 / 0.875);
  --text-base: 1rem;   --text-base--line-height: calc(1.5 / 1);
  --text-2xl: 1.5rem;  --text-2xl--line-height: calc(2 / 1.5);
  --text-3xl: 1.875rem; --text-3xl--line-height: calc(2.25 / 1.875);
  --text-4xl: 2.25rem; --text-4xl--line-height: calc(2.5 / 2.25);
  --tracking-tight: -0.025em;
  --leading-tight: 1.25; --leading-relaxed: 1.625;

  /* Sizing */
  --spacing: 0.25rem;      /* 4px grid */
  --content-max: 1280px;   /* marketing pages; the app shell is fluid */

  /* Motion */
  --ease-out: cubic-bezier(0, 0, 0.2, 1);
  --default-transition-duration: 0.15s;
  --default-transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
}

@layer base {
  /* Keep this inside a layer. The preview declares it unlayered, so it beats every
     border-color utility and every border on the page renders as #1a1a1a. */
  * { border-color: var(--border-default); }
}
html { color-scheme: dark; scroll-behavior: smooth; scroll-padding-top: 88px; }
body {
  min-height: 100vh; background: var(--neutral-primary); color: var(--body);
  font-family: var(--font-mono); -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
.heading-display { font-size: clamp(2.25rem, 5vw, 3.75rem); font-weight: 600; line-height: 1.05; letter-spacing: -0.04em; color: var(--heading); text-wrap: balance; }
.heading-section { font-size: clamp(1.875rem, 4vw, 2.75rem); font-weight: 600; line-height: 1.15; letter-spacing: -0.03em; color: var(--heading); text-wrap: balance; }
.heading-sub     { font-size: clamp(1.625rem, 3vw, 2.25rem); font-weight: 600; line-height: 1.2;  letter-spacing: -0.02em; color: var(--heading); text-wrap: balance; } /* the app's page title */
.lead { font-size: 1.125rem; line-height: 1.75; color: var(--body); text-wrap: pretty; }
.glass-panel { background: var(--glass-bg); }
:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; border-radius: var(--radius-sm); }
.skip-link { position: absolute; top: -100px; left: 1rem; z-index: 100; padding: 0.75rem 1.25rem; background: var(--neutral-primary-medium); color: var(--heading); border: 1px solid var(--border-default); border-radius: var(--radius-sm); box-shadow: var(--shadow-md); transition: top 0.15s; }
.skip-link:focus { top: 1rem; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
```

The source also defines unused hues (indigo, orange, fuchsia, sky, lime, yellow, pink as an
alias of brand) and two radial glows (`--hero-glow`, pink at 14%; `--hero-glow-secondary`,
indigo at 8%) for its marketing hero. The application route uses none of them: leave them
out. Geist Mono ships as a variable font (weights 100 to 900) in six woff2 subsets through
next/font, with an Arial fallback size-adjusted to 134.59%; Google Fonts or Fontsource
serve the same family.

## Type

One family, Geist Mono, and nothing in the app renders at the browser's 16px default:
the interface size is 14, meta is 12, figures are 24 to 36. Hierarchy comes from size,
color, and weight together; this style leans on 600 and 700 more than most.

| Role | Size / line | Weight | Tracking | Case | Color |
| --- | --- | --- | --- | --- | --- |
| Sidebar group label | 12 / 16 | 500 | +0.20em | uppercase | body-subtle |
| Table header | 12 / 16 | 600 | +2px | uppercase | body |
| Hint, time, email, note, legend, axis tick | 12 / 16 | 400 | 0 | sentence | body-subtle (legend in body) |
| Quick-action label, tag badge | 12 / 16 | 500 | 0 | sentence | body, or semantic |
| Delta, status badge, rank number | 12 / 16 | 700 | 0 | sentence | semantic, or heading |
| Count badge, primary button (size xs) | 12 / 16 | 600, 500 | 0 | sentence | white |
| Nav row, goal label, user name, list title, table name | 14 / 20 | 500 to 600 | 0 | sentence | heading |
| Sub-nav row, input, table cell, copy, card subtitle | 14 / 20 | 400 | 0 | sentence | body (input text in heading) |
| Segmented button, date button, text link, top-bar link | 14 / 20 | 600 | 0 | sentence | body; links in fg-brand |
| Card title h2 | 16 / 24 | 600 or 700 (pick one) | 0 | sentence | heading |
| Stat value | 24 / 32 | 700 | -0.025em, tabular | | heading |
| Chart headline figure | 30 / 36 | 700 | -0.025em, tabular | | heading |
| Goal headline figure | 36 / 40 | 600 | -0.025em, tabular | | heading |
| Page title h1 (`heading-sub`) | 36 / 43 at 1440, 26 on phones | 600 | -0.02em | sentence | heading |

- Every number is `font-variant-numeric: tabular-nums`.
- Uppercase appears in exactly two places: the sidebar group label and table headers, both
  with open tracking. Never on body copy, buttons, badges, or headings inside the app.
- Links carry no underline at rest. No italics anywhere.
- The marketing scale (`heading-display`, `heading-section`, `lead`) exists for landing
  pages; the app uses `heading-sub` for its title and 16px for card titles.

## Spacing and layout

Everything sits on the 4px grid: 4 between nav rows, 8 inside controls and between header
actions, 12 between a tile and its text, 16 between stat cards and inside sidebar blocks,
20 for stat-card padding and the chart card's dividers, 24 for card padding and section
gaps, 32 for page padding and below the page header.

**Shell**

- Sidebar: fixed, 256 wide, full height, `neutral-primary-medium` (#111), 1px hairline on
  the right, `z-index: 40`. Hidden below 1024px (`lg`); the content gets
  `padding-left: 256px` from there.
- Top bar: sticky, 64 tall plus a bottom hairline, `glass-panel` (#0a0a0a at 72%, no
  blur), padding 0 / 24 (0 / 16 on phones), gap 16 (12 on phones). The search sits at the
  left, growing to max 512 (448 below `lg`), and hides below 640px (`sm`). The right cluster
  is pushed with `margin-left: auto`, gap 8 (6 on phones).
- Main: padding 32 on all sides (16 on phones, 24 from `sm`), page header with
  `margin-bottom: 32` (h1, then the subtitle 4 below), then sections stacked 24 apart.
- Grid rhythm on the reference: four stat cards (one column, two from `sm`, four from
  `xl`) with gap 16; the chart card and the goals card stacked (side by side at 2 : 1 only
  from 1536px, `2xl`); three widgets with gap 24 (one column, two from `lg`, three from
  `xl`); then a full-width table. The page is as long as its content (2559px at 1440,
  3259 at 1024, 4015 at 390).

**Sidebar anatomy, top to bottom**

- User row, padding 16, bottom hairline, 73 tall: a 40px square avatar tile (radius 12,
  `brand-softer` fill, hairline, 14 / 600 initials in `fg-brand-strong`), gap 12, the name
  14 / 600 heading over the email 12 body-subtle, both truncated, then a 32px square
  "Switch workspace" button (hairline, radius 12, 16px chevrons icon in body-subtle;
  hover `neutral-secondary-medium` and heading).
- Quick actions, padding 16, bottom hairline: three equal buttons in a grid with gap 8,
  68 tall, column flex, gap 6, padding 12 / 8, radius 12, `neutral-primary-soft` fill,
  hairline, body color: a 20px icon over a 12 / 500 label (Profile, Alerts, Support).
  Hover: `neutral-secondary-medium` fill, heading text.
- Navigation, padding 16 / 12, scrolls. Group label 12 / 500 uppercase +0.2em body-subtle,
  padding 0 / 12, 8 above its rows. Rows 40 tall (padding 10 / 12), radius 12, 14 / 500
  heading, 20px icon, gap 12, 4 between rows. A disclosure row is a button with a 16px
  chevron at the end that rotates 180 degrees when open; its children sit in a list
  indented 20 with a left hairline and 12 of padding, rows 36 tall (padding 8 / 12),
  14 / 400 body. Count badges at the row end: 12 / 600 white on `brand`, radius 12,
  padding 2 / 8.
- Footer group, padding 16 / 12, top hairline, same rows: Documentation, Settings, and
  Log out as a button in `fg-danger` whose hover fill is `danger-soft`.

**Phones (390 wide).** The top bar becomes one row of 40px controls: menu, search, the
Create button with its label, a plus icon button, theme, bell, avatar. The h1 drops to
26px. Cards stack in one column, the chart card's padding drops to 16, its legend wraps,
its footer stacks the segmented control over the link with gap 12, and the table scrolls
horizontally inside its card.

## Components

Values are padding top/right/bottom/left in px unless noted. "Hairline" means 1px
`border-default`. Every corner is `radius-base` (12px) unless noted.

- **Primary button** (Create). `inline-flex`, centered, gap 8, 1px transparent border,
  `font-weight: 500`, `shadow-xs`; size xs is padding 6 / 12 at 12px (30 tall). `brand`
  fill, white text; hover `brand-strong`. Focus: no outline, 4px ring in `brand-medium`.
  Disabled: `disabled` fill, `border-default-medium`, `fg-disabled` text, no shadow,
  `cursor: not-allowed`. One per view. Larger sizes were not observed; scale the padding
  on the 4px grid (8 / 16 at 14px for a 40px button) if you need them.
- **Icon button** (theme, notifications). 40 square, `neutral-secondary-medium` fill,
  `border-default-medium` (renders as the hairline in the preview), heading 20px icon,
  `shadow-xs`, `transition-colors`. Hover: `neutral-tertiary-medium`. Focus: no outline,
  4px ring in `neutral-tertiary`. Notification dot: 8px `danger` circle at top 8 / right
  8 with a 2px ring in `neutral-primary-soft`.
- **Avatar button** (account menu). 36 square, the icon-button skin, 14 / 700 heading
  initials.
- **Top-bar text link** (Logout). Padding 8 / 12, 14 / 600 body, gap 8, 16px icon, radius
  12; hover `neutral-secondary-medium` and heading. Hidden below 768px (`md`).
- **Input** (search). 42 tall, `neutral-secondary-medium`, `border-default-medium`
  (hairline in the preview), padding 10 / 16 / 10 / 44, 14 heading, placeholder
  body-subtle, `shadow-xs`. Leading 16px icon in body-subtle at inset 16, vertically
  centered. Focus-visible: `border-brand`, no outline, 1px `brand` ring.
- **Segmented control** (Last 7 days / Last 14 days). Container `inline-flex`, padding 4,
  `neutral-secondary-medium`, hairline. Buttons 34 tall, padding 6 / 12, 14 / 600,
  1px transparent border, `aria-pressed`, transition on fill, shadow, and color. Pressed:
  `brand` fill, white text. Idle: no fill, body text; hover heading text.
- **Date-range button**. 38 tall, `inline-flex`, gap 8, padding 8 / 12, 14 / 600 body,
  `neutral-secondary-medium`, hairline, `shadow-xs`, a 16px calendar icon before and a
  16px chevron after the label.
- **Badges.** All radius 12 and 12px type. Delta on a stat card: padding 4 / 8, gap 4,
  weight 700, a 14px arrow-up-right or arrow-down-right icon, `success-soft` /
  `fg-success-strong` or `danger-soft` / `fg-danger-strong`. Status in a table: padding
  4 / 10, weight 700, success, warning (`warning-soft` / `fg-warning`), or danger. Tag
  ("On track"): padding 4 / 10, weight 500, `success-soft`, `fg-success-strong`, with
  `border-success-subtle` (hairline in the preview). Count: padding 2 / 8, weight 600,
  white on `brand`. Inline delta text in a list: 12 / 700 semantic text with the 14px
  arrow, gap 2, no fill.
- **Stat card**. Padding 20, hairline, `shadow-xs`, 154 tall. Top row with 16 below: a
  40px square tile (`neutral-primary-soft`, `shadow-xs`, 20px `fg-brand` icon) at the left,
  the delta badge at the right. Then the value 24 / 700 tabular tracking-tight, the label
  14 body 4 below. The preview alternates the fill between `neutral-tertiary-soft` and
  `neutral-secondary-medium` across the row; one fill reads cleaner.
- **Card** (every section). Hairline, `neutral-primary-soft`, `shadow-xs`, padding 24
  (the chart card 16 below `lg`), `aria-labelledby` its h2 or an `aria-label`. Header:
  h2 16 / 600 heading with the subtitle 14 body 4 below, and either a badge or a 40px
  icon tile (`brand-softer` fill, `shadow-xs`, 20px `fg-brand` icon) at the right, gap 16,
  20 to 24 below. Footer actions are text links, or a hairline-topped row with 20 above.
- **Chart card**. 540 tall, column flex. Header row (stacks below `sm`): figure 30 / 700
  tabular tracking-tight with the subtitle 14 body 4 below; the date-range button at the
  right. A hairline divider with 20 above and below. Legend 16 below: 12px body items
  with 10px round dots (gap 8 inside, 20 between, wrapping with 8 between lines). Chart
  area grows (272 tall at 1440). Divider. Footer: segmented control left, text link with
  arrow right.
- **Goals card**. `min-height: 540`, column flex. Header with a tag badge. Summary panel
  with 24 below: `neutral-primary-medium`, hairline, padding 20; the headline 36 / 600
  tabular tracking-tight with its label 14 body, and two 12px body-subtle lines
  right-aligned at the bottom; a progress bar 8 tall 16 below, `radius-full`, with a
  `brand` fill that transitions its width. Give the track a visible step
  (`neutral-tertiary-medium`); the preview's `neutral-tertiary` track vanishes into the
  panel. Goal rows 20 apart: label 14 / 500 heading left, target 14 body-subtle tabular
  right, 8 above a row of the bar (8 tall, `radius-full`, `neutral-tertiary` track) and the
  percentage 14 / 600 tabular heading in a 40px right-aligned slot, gap 12. Footer pinned
  to the bottom with a top hairline and 20 of padding: 12px body-subtle note left, text
  link right.
- **Ranked list card** (Top content). Rows 12 apart, each a link: padding 8, gap 12, radius
  12, 1px transparent border; a 28px square rank tile (`neutral-tertiary-soft`, 12 / 700
  heading), the title 14 / 600 heading truncated over the metric 12 body-subtle, and the
  inline delta at the right. Hover: hairline and `neutral-secondary-medium` fill, title
  turns `fg-brand`. Footer link 16 below the list.
- **Share list card** (Traffic sources). Rows 16 apart: a 16px `fg-brand` icon, the label
  14 / 600 heading, gap 8; the value 14 / 700 tabular heading at the right; 8 below, a bar
  8 tall with a `neutral-tertiary` track and a `brand` fill, radius 12. A 12px body-subtle
  note 16 below the list.
- **Activity feed card**. Items with gap 12: a 36px square tile (`neutral-secondary-medium`,
  `shadow-xs`, 16px `fg-brand` icon) and a text block with a bottom hairline and 16 of
  padding (none on the last): title 14 / 600 heading, description 14 body 2 below, time
  12 body-subtle 4 below.
- **Data table card**. Padding 0, `overflow: hidden`. Head row padding 16 / 24 with a
  bottom hairline: h2 16 / 700 left, text link right. Table 14px, full width, inside an
  `overflow-x: auto` wrapper. Header row: `neutral-secondary-soft` band (invisible on the
  card; use `neutral-primary-medium` if you want the band to show), bottom hairline, th 12
  / 600 uppercase +2px body, padding 12 / 24, left-aligned. Body rows 57 tall with a bottom
  hairline (none on the last); td padding 16 / 24; ids and amounts tabular body, names
  14 / 600 heading, status as a badge. No row hover in the preview.
- **Tiles.** Square, radius 12, `shadow-xs`, pink icon: 40 on stat cards
  (`neutral-primary-soft`), 40 in card headers (`brand-softer`), 36 in the activity feed
  (`neutral-secondary-medium`), 28 for ranks (`neutral-tertiary-soft`, text). The sidebar
  avatar is the 40 `brand-softer` tile with initials in `fg-brand-strong`.
- **Text link**. 14 / 600 `fg-brand` (500 in the goals footer), no underline; with an
  inline 16px arrow-right, gap 6. The preview defines no visible hover; underline on hover
  with offset 4 is the natural one.
- **Skip link**. As in the CSS block: `neutral-primary-medium`, hairline, `shadow-md`,
  padding 12 / 20, heading text, off-screen until focused.

## States

- Hover: one surface step, never a scale. Transparent rows take `neutral-secondary-medium`
  (#111) and heading text; #111 buttons take `neutral-tertiary-medium` (#1a1a1a); list
  rows add the hairline; a row's title turns `fg-brand`.
- Focus-visible: 2px `brand` outline offset 2 with a 12px radius globally; buttons remove
  the outline for a 4px ring (`brand-medium` on primary, `neutral-tertiary` on icon
  buttons); inputs take a `brand` border plus a 1px `brand` ring.
- Active navigation: `brand-softer` fill, `fg-brand-strong` label and icon, 1px border
  (`border-brand-subtle` intended), `aria-current="page"`. Open disclosure: chevron rotated
  180 degrees.
- Pressed segment: `brand` fill, white text.
- Disabled: `disabled` fill, `fg-disabled` text, `border-default-medium`, no shadow,
  `cursor: not-allowed`.
- Danger action (Log out): `fg-danger` text, hover `danger-soft` fill.
- The theme toggle changes nothing: both color-scheme preferences render the same page.

## Charts

Recharts in the reference; the rules hold for any library.

- Height 272 inside the 540 card, horizontal grid lines only (five, including the baseline)
  with stroke `border-default`; no vertical grid, no axis lines, no tick marks. Tick
  labels 12px in `body-subtle`, Y axis in "25k" style.
- Grouped bars 14 wide with a 2px radius on the top corners only, fills `brand`, `purple`,
  `cyan` in series order, no stroke. Give the lead series `brand` and consider greys
  (`quaternary-medium`, `neutral-quaternary`) for the rest when the chart has a story.
- Legends are HTML, not SVG: 12px body text with 10px round dots, left-aligned under the
  figure, with 16 above the chart.
- The headline figure (30 / 700 tabular) and its subtitle sit above the chart; the chart
  carries no title of its own.
- Tooltips were not observed (the wrapper is hidden at rest). Style them as a panel:
  `neutral-primary-medium`, hairline, radius 12, `shadow-md`, 12 to 14px, tabular
  figures.
- Give the Y axis at least 40px of width. The reference's 33px clips "100k" to "l00k".
- Progress bars are 8 tall with a `neutral-tertiary` track; one fill color per list unless
  the colors mean series. The goals card uses `radius-full` while the traffic card uses
  radius 12 on the same bar; pick one.

## Motion

- Two easings in the source: Tailwind's `cubic-bezier(0.4, 0, 0.2, 1)` on rows, icon
  buttons, segments, chevrons, and progress widths, and `ease-out`
  `cubic-bezier(0, 0, 0.2, 1)` on the primary button. 150ms everywhere.
- Transition only colors (`transition-colors`), `background-color, border-color, color,
  box-shadow` on buttons, `transform` on the disclosure chevron, `width` on progress fills,
  and `top` on the skip link. Never `all`, never layout properties.
- Nothing loops, pulses, or enters on load in the app (the marketing logo marquee is the
  one animation, 28s linear, and it stops under reduced motion). Smooth scrolling with an
  88px scroll padding turns off under reduced motion.

## Copy and data

- Page title is the place: "Overview". Card titles are nouns: "Quarterly goals",
  "Top content", "Traffic sources", "Recent activity", "Recent transactions".
- Labels, hints, buttons, and badges end without a period and use sentence case: "Active
  users", "Sales this period", "Most viewed pages this week", "Latest workspace events".
- Deltas: "+12.4%", "-2.3%" with the arrow icon; a comparison states its base: "Pricing page
  up 28% vs yesterday".
- Targets: "$120k goal", "800 / 1,250", "95% target"; shares and progress as integers
  ("42%", "78%"); counts "3 of 4 goals above 70%".
- Dates: "Apr 17 – Apr 23, 2026" with an en dash, "Q2 2026 · Apr – Jun" with a middle dot;
  relative times "12m ago", "1h ago", "5h ago"; "Updated today", "42 days left in Q2".
- Ids as "#4821". Currency without decimals ("$48,210", "$2,480"), thousands separators;
  metrics "18.4k views", "48.2k sessions".
- Section label "Menu" (rendered uppercase). Use one spelling for the same action: the
  preview has both "Logout" and "Log out".

## Keep it designed

An unslop pass over the reference finds a designed system with a few tells. Keep the
signature; do not copy the tells.

**Signature, keep it**

- Pure greys from #050505 to #1a1a1a, no tint. Depth from surface steps and hairlines;
  shadows at most `shadow-xs` on cards.
- One hot pink. Only on data, the active item, the primary action, pink icons, and links.
  Semantic greens, ambers, and reds stay soft and sit on their own dark fills.
- One radius, 12px, on everything. Small things read as pills, large things as rounded
  cards; never add a second radius for "variety".
- Geist Mono everywhere, figures in 700 with tabular numerals, labels in 500 and 600, meta
  at 12px. Uppercase with open tracking only on the sidebar group label and table headers.
- Bento rhythm: a row of equal stat cards, one tall chart, a goals card, three widgets, a
  table; cards 24 apart, stats 16 apart.

**Tells in the reference, avoid them**

- The greeting line ("Welcome back, Jordan. Here's what's happening across your
  workspace."). Use the period or context instead.
- Decorative icon tiles on every stat card and in every card header. Keep a tile only where
  the icon identifies the metric or the item; numbers carry stat cards.
- Three hues in one bar chart with no lead series, and four hues across four goal bars that
  mean nothing. One accent per chart; series hues only when the chart tells series apart.
- The unlayered universal border rule. Every border renders as #1a1a1a: list rows meant to
  be borderless show hairlines, the pink button has a dark edge, the "On track" badge loses
  its green edge, inputs lose their `border-default-medium`. Put the rule in `@layer base`.
- Grey on the same grey: the table head band (#0a0a0a on #0a0a0a) and the summary panel's
  progress track (#111 on #111) are invisible. Step one surface when something must read.
- Two stat-card fills across one row, and two h2 weights (600 and 700) across one page.
  Same thing, same surface, same weight.
- Mixed figure formats ("$48,210" beside "$120k goal" and "18.4k views"), a true minus in
  "−2.1% MoM" beside a hyphen in "-2.3%".
- A "glass" top bar at 72% alpha with no blur, so content smears under it when you scroll.
  Add `backdrop-filter: blur(12px)` or make it solid.
- A theme toggle that does nothing, and a clipped axis label ("l00k").
- Mostly weight 700: the style's bold figures are its voice, but badges, ranks, and table
  headers do not all need 700. Let size and color do more of the work.

**Template check.** Swap the pink for blue and Geist Mono for Inter and this becomes any
dark dashboard. The character lives in the monospaced bold figures, the hot pink on
near-black, and the single 12px radius. Never trade those three.

## Checklist

- [ ] Only `neutral-primary`, `neutral-primary-soft`, `neutral-secondary-medium`, and
      #1a1a1a hairlines on the chrome; pink on data, the active item, the primary action,
      pink icons, and links
- [ ] Geist Mono everywhere, tabular figures, uppercase only on the group label and table
      headers
- [ ] Radius 12 on every element, `radius-full` nowhere unless you accept the second shape
- [ ] Sidebar 256, top bar 64 with 40px controls, main padding 32, cards 24 apart, stats
      16 apart, card padding 24, stat-card padding 20
- [ ] The universal border rule is layered; semantic and transparent borders render
- [ ] Focus rings present: 2px outline globally, 4px rings on buttons, pink border and ring
      on inputs
- [ ] 150ms transitions on color and surface only, nothing animated on load
- [ ] One lead series per chart, horizontal grid only, 12px subtle ticks, Y axis 40 wide,
      tracks visible against their panel
- [ ] No greeting, no trailing periods on labels, one number format, one spelling per action

## Provenance

- Source: https://contemporary-typeui-99b07032.vercel.app/application (and `/` for the
  system's own description), captured 2026-11-08. Stack observed by REA bundle analysis
  (evidence `ev_98e654e9…`, 23 scripts parsed, no failures): Next.js (high confidence) and
  React (medium). Tailwind v4 utilities with lightningcss output, Recharts, and lucide icons
  (20px in the sidebar, tiles, and top bar, 16px in content, 14px in deltas, stroke 2) seen
  in the DOM and CSS.
- REA target listing `ev_61539233…`; passive inspection `ev_c3a7fe6a…`: 915 DOM nodes, 705
  accessibility nodes, one stylesheet, one Geist Mono woff2 in the window, no console events
  in the window. REA screenshot `ev_91756e3f…`, sha256 `641953e1…`.
- Playwright probe: computed styles for 176 element signatures, 143 resolved tokens, palette
  counts, icon inventory, full-page captures at 1440, 1024, and 390. Both
  `prefers-color-scheme` values and the theme button gave identical pages, so the system is
  dark-only.
- Not observed: hover, focus, pressed, disabled, menus, and tooltips as pixels (taken from
  the CSS rules), the phone sidebar drawer, the marketing and e-commerce routes. Where the
  preview's utility classes lost to the unlayered border rule, this guide records what
  rendered and what was intended.
- Audit method adapted from unslop by Damir Sokolovsky (@heydamir), CC BY 4.0.
