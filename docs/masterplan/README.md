# FEFAT masterplan

A step-by-step plan for building FEFAT ("feature engineering for algorithmic trading") with Claude Code. Every step is one Claude Code session and one pull request, with a copy-paste prompt, a definition of done, checks you perform yourself in a few minutes, and what to do if it fails.

Written 2026-10-06 from your idea (`../../raw_app_idea.txt`), four rounds of decisions, three research reports, and three design reviews. Decisions are logged in `DECISIONS.md`. The code lives in the private repository [kenny-g-97/fefat](https://github.com/kenny-g-97/fefat); this folder is its clone.

## What FEFAT becomes

A local-first research platform for futures and crypto traders that runs on your own PC, is used from the browser and from your phone (over Tailscale), and is packaged as a desktop app at the end. Four pillars: a feature lab and strategy workspace with a Claude agent; a backtester with its own Rust engine and strict strategy versioning; a prop-firm account simulator with an account-management policy layer; and full use from the phone. Details in `00-product-spec.md`.

## How to use this plan

1. Read `00-product-spec.md`, `01-architecture.md`, and `05-build-process.md` once. Skim the rest; the phase files point back to the sections they need.
2. Install the tools in `07-tools-and-costs.md` §1 — step 0.1 walks you through it.
3. Work through the phases in order. Open Claude Code in the repository root, start a fresh session, and either paste the step's **Prompt** or (from step 0.5 on, once step 0.4 has created the runner) type `/step N.M`.
4. After each step: run **Your checks**, wait for CI, merge the pull request. `PROGRESS.md` is the status table.
5. At the start of each phase run `/phase-kickoff N`; at the end, `/phase-exit N`. The kickoff asks you the phase's open decisions and reconciles the steps with the code as it then stands.
6. Keep `uv run python docs/masterplan/tools/check_masterplan.py` green whenever a step file is edited. (On this PC, bare `python` is a Microsoft Store stub; always go through `uv run python` or `python3.12`.)

The session protocol, reviews, verification approach, and test-data policy are in `05-build-process.md`. The Claude Code configuration (installed in step 0.4) is in `06-claude-code-setup.md`.

## Documents

| File | Content |
| --- | --- |
| `00-product-spec.md` | What FEFAT is, scope, non-goals, key journeys, glossary |
| `01-architecture.md` | System overview, stack, repository and runtime layout, data model, API, local server security, seams, conventions |
| `02-engine-and-data.md` | Market data, engine, strategy kinds, fill and cost model, feature runtime, results, validation, libraries |
| `03-prop-simulator.md` | Rule schema, account state machine, exact mode and fast replay, policy layer, Monte Carlo, pages |
| `04-agent.md` | The in-app agent: runtime, sessions, tools, skills, proposals, cost, safety |
| `05-build-process.md` | The step template, session protocol, reviews, verification, test-data policy, guardrails |
| `06-claude-code-setup.md` | CLAUDE.md, rules, skills, subagents, hooks, permissions, integrations; verified Claude Code facts |
| `07-tools-and-costs.md` | What to install, accounts and keys, market-data purchases, running and product costs |
| `phases/P00` … `phases/P14` | The 128 steps, one file per phase, with kickoff and exit prompts |
| `PROGRESS.md` | Step status, kickoffs and exits, milestones |
| `BACKLOG.md` | Future improvements (cloud sync, ML, live trading, store apps, licensing) |
| `DECISIONS.md` | The decision log; ADR-marked entries become `docs/adr/` records in step 0.7 |
| `appendix/research-*.md` | The three research reports with sources |
| `appendix/risk-register.md` | Risks and mitigations by phase |
| `tools/check_masterplan.py` | Consistency checks and the PROGRESS row generator |

## Phase map

| Phase | What you get | Steps | Milestone |
| --- | --- | --- | --- |
| P0 Foundations | Tools, repository, Claude Code setup, test and data-safety guards | 8 | |
| P1 Market data | Databento files and crypto archives in one clean store; calendars, bars, rolls | 9 | |
| P2 Engine | The backtest engine, proven against the readable reference | 14 | first notebook backtest at 2.2 (step 19); trustworthy at 2.14 (step 31) |
| P3 Features | Feature library, leak detector, indicators, analytics, from notebooks | 8 | |
| P4 Local app and phone access | Local server, login, web shell, jobs, executor, the app on your phone | 6 | app on the phone at 4.6 (step 45) |
| P5 Backtesting in the app | Strategy versions, runs, results, trade review chart, notifications | 12 | web MVP at 5.12 (step 57) |
| P6 Feature lab and builder | Editor with live preview; no-code strategy builder | 9 | |
| P7 Prop simulator | Rule presets, exact and fast modes, policies, Monte Carlo, pages | 11 | step 77 |
| P8 In-app agent | Chat, tools, skills, proposals, evals, safety tests | 11 | step 88 |
| P9 Event strategies | Python `on_bar` strategies and their editor | 6 | |
| P10 Alternative data | Uploads, recipes, publication-time joins, agent ingestion | 7 | |
| P11 Research tools | Sweeps, optimization, safeguards, walk-forward, robustness | 8 | |
| P12 Phone polish | Install, notifications, touch, speed, offline | 5 | |
| P13 Hardening | Security review, robustness, diagnostics, backups, runbook | 7 | step 121 |
| P14 Desktop packaging | Tauri shell, installers, auto-update, first run (product phase) | 7 | step 128 |

The written order is the default. Phases P7 to P12 can be reordered at a kickoff by amending the `Depends on` line of the moved phase's first step (and any step that uses a later phase's capability, which the phase headers name); the checker then verifies the new order. P14 is optional for personal use.

## Effort and cost (estimates)

Each step is one Claude Code session plus 5–15 minutes of your checks. At three to five steps a working day, the build is roughly 26 to 43 working days plus a kickoff and an exit session per phase, and some steps will split. Running costs are $0 a month; market data and the in-app agent are pay-as-you-go (`07-tools-and-costs.md`).

## Conventions in the phase files

- Step heading: `### N.M Title`. Meta line: `Depends on · Plan mode · Reviews · Security · Model hint`.
- Sections, always in this order: Purpose, Prerequisites, Prompt, Done means, Your checks, If it fails.
- Prompts start with "Masterplan step N.M — Title" and always end with "Not in this step".
- Finished steps are never rewritten; changes come through phase kickoffs or an "Amendment" block appended to the step.
