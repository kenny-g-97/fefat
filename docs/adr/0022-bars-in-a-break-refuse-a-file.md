# ADR-0022: Bars in a break refuse a file, and the sessions beside them go with them

Decision log: [D-104](../masterplan/DECISIONS.md), 2026-11-17

## Context

Every import compares a file's records with its product's session calendar, and refuses a file whose records run late or early, as one read in the wrong time zone or with the wrong bar stamping does (step 1.10, `02-engine-and-data.md` §1.8). Two of its tests gave the wrong cause on platform exports. The test for one bar early called a whole file a bar early where any break held a bar closing at the next session's open, since nothing prints in the minute before an open. The test for hours ran on each part of a file on one side of a change of the calendar's offset from UTC, however few minutes that part held.

The plan of step 5.15 measured the 62 files of the builder's NinjaTrader ES and MNQ exports, in timestamps and counts alone. A bar closing at a session's open is in six of them, and in each it is the edge of a stretch the platform stamped early. On the clock-change Sundays 2024-03-10 and 2025-03-09 the hour before the open holds the session's first hour and the session's first hour its second, 60 of those 60 closes equal to the store's Databento MNQ closes an hour later, none in place. The sessions of 2020-09-10 and 09-11 and of 2020-10-19 to 10-23 equal the vendor's at no shift. Every other break with bars holds strays, 1 to 4 in 565 of 605 such breaks and 30 at most, of which a backtest reads nothing: the signal grid has no row for them, and the engine neither fills nor marks on a bar opening in a break (F-SES-02).

A merge cannot be taken back, and nothing in FEFAT removes a stored record (ADR-0021). Leaving out the bars in such a break alone would import the stretch it marks, bars an hour early inside a session, which is a look-ahead (D-12).

## Decision

- **Offsets first, on all the file's bars.** A file whose records run late or early is refused for that offset, under every choice, and is never offered the correction below:
  - **hours** over the whole file, as before; over a part of the file on one side of a change of the calendar's offset from UTC only where that part, moved back by them, holds a whole session, its bars reaching from under 30 minutes and a bar after a session's open to within 30 minutes and a bar of that session's close, or lands inside sessions on three or more trade dates, so that a few hours after a clock change do not count while thin sessions an hour off still do;
  - **one bar early** where a session holds a bar that closes at its open, its last bucket holds no bar, and the bucket before it holds one, as a file stamped at the bars' opens and read as their closes gives; or where at least half the sessions with bars hold a bar closing at their open;
  - **one bar late** as before.
- **Bars in a break.** Otherwise, each break that holds a bar opening after the close and closing at the next open refuses the file, named by the trade date of the session it follows, with its bars, and the sessions on both sides of it with their records.
- **The correction you approve.** Told to (`BarsInBreaks.LEAVE_OUT`, `--bars-in-breaks leave-out`, the wizard's review), the import leaves out every record dated to the session before or the session after each such break, the break's own bars among them, and every record of a session joined to a session left out by a break that holds a bar, repeating until none joins; it changes or moves none. Bars in other breaks stay, as before (D-43).
- **Only where what remains can be timed.** The records the correction would leave are checked again: where they show an offset, or the calendar can no longer test their timing, the file is refused under both choices and the correction is not offered, since one bar before one open may be the only sign of a thin file stamped a bar early.
- **One reading per file.** Under the correction a file without such a break is refused. The choice is one of the arguments that decide a file's records, so the raw manifest records it, and the file read again under the other choice is refused (D-50).
- **Bars alone.** Ticks and daily bars are not tested for bars in a break.

## Consequences

- The builder's six files import under the correction without 10, 2, 2, 10, 2, and 2 sessions, and nothing early comes in. A session left out is a gap in the quality report until a file that holds it merges in, which adds it as new sessions (ADR-0021).
- Sessions that are right go with the stretch: three Fridays of the builder's exports equal the vendor's bars, and the two files of December 2020 lose 2020-09-14 and 10-26 too, each joined by a weekend break with bars to a session left out. It is the price of a rule that needs no second source, and `BACKLOG.md` keeps the way to take such sessions back.
- A reviewer of the rule traced the cases it closes: a thin file a bar early whose only sign is one bar before one open, which the correction would otherwise import a bar early once that session went; thin sessions an hour off before a clock change, which a whole session alone would pass in silence; and a Friday an hour late whose spill into the weekend reaches no open, which leaving out the sessions beside alone would keep.
- A file of several contracts loses the sessions beside such a break for every contract it holds, since the check reads a file's contracts together.
- What an import says of what it left out holds counts and trade dates, no price (D-21), in the reading, the import's report, and the wizard's review.
- A stretch displaced without reaching a session's edge is not seen, as before: on the autumn clock-change Sundays 2022-11-06 and 2025-11-02 the builder's exports hold the session's first hour an hour late, inside the session, and import as they are (`BACKLOG.md`, aimed at step 5.16). Nor is a stretch displaced late by less than a break.
- A product that trades through its calendar's break, and a platform that puts a print at an open's exact instant in the bar stamped at the open, put a bar before the open of most sessions, and such a file reads as a bar early, as before; so does a top-up of two sessions with one such bar. A file whose last part after a clock change is a few hours an hour off reads as bars in a break, and the bar closing at a product's first open is dated before its first trade date, a problem that refuses the file before the calendar check sees a break (`BACKLOG.md`).
- `validate_calendar` reports such a break in data the store already holds.
- The code is `fefat.market.calendar_breaks` (the finding and the choice), `calendar_offset` (the two tests), `calendar_check`, `importers.file_import` and `importers.file_report`, the app's import models, its runner, and the wizard's review.

## How we would know it is wrong

If a clean export were refused for bars in a break, as a platform that prints a settlement bar after the close as its own would be; if a file stamped a bar early, wholly or in part, or read hours off, were offered the correction; if a store written under the correction held a record of a session beside such a break, or failed the leak detector; if traders often needed the sessions left out and had no clean file to fill them; or if stretches displaced inside sessions, as the autumn clock changes are, proved common.

## Status

Accepted; recorded at the plan of step 5.15. It refines step 1.10's test of a file's timing (`02-engine-and-data.md` §1.8) and leaves the merge of [ADR-0021](0021-imports-merge-into-the-partitions-they-overlap.md) as it is.
