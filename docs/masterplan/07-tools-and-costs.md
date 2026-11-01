# 07 — Tools, accounts, data, and costs

## 1. What to install on this PC (step 0.1)

Already present on 2026-10-05: git 2.55, GitHub CLI 2.97 (signed in), Node 24 + npm 11, uv 0.11 with CPython 3.12 and 3.14, Docker Desktop 29 (not needed by FEFAT), VS Code with the Claude Code extension.

| Tool | Why | How |
| --- | --- | --- |
| Microsoft C++ Build Tools (Desktop development with C++) | Rust's MSVC toolchain links with them | `winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"` (without `--override`, winget installs the bare installer and no C++ workload), or tick "Desktop development with C++" in the Visual Studio Installer; one-time, several GB |
| Rust (stable) via rustup | the engine | `winget install Rustlang.Rustup`, then `rustup default stable`; pinned by `engine/rust-toolchain.toml` |
| pnpm | the web app | `corepack enable --install-directory "$env:APPDATA\npm"` (Node ships corepack; the install directory keeps the shims out of Program Files, which needs administrator rights) then `corepack install -g pnpm@latest` (corepack 0.35 has no `prepare` command), or `npm install -g pnpm` |
| `just` | the task runner | `winget install Casey.Just` or `cargo install just` |
| cargo-mutants 27.1 | mutation testing at the phase exits, `just mutants` (step 2.15) | `cargo install cargo-mutants --locked`; `just doctor` checks it |
| Python 3.12 | SDK and server | already installed by uv; `.python-version` pins it |
| Playwright browsers (P4) | UI tests | `pnpm exec playwright install chromium` |
| Claude Code CLI (optional) | running `claude` from a terminal, not only VS Code | `winget install Anthropic.ClaudeCode` or the installer from the docs |

`just doctor` (written in step 0.1) checks every tool and version and prints what is missing.

## 2. Accounts and keys

| Account | Needed from | Cost | Where the key lives |
| --- | --- | --- | --- |
| GitHub (have) | P0 | free (private repos) | `gh auth` |
| Anthropic Console API key | P8 (the in-app agent); earlier for notebook experiments | pay as you go | OS credential store via the settings page |
| Databento (have data; account for more) | P1 (files only; a key once a connector exists, D-38) | see §3 | nowhere in Phase 1: downloads happen on Databento's website and the files are imported; later, the OS credential store |
| Apple Developer membership; a cloud code-signing service for Windows (Azure Trusted Signing or similar — certificates on hardware tokens cannot be used from CI) | P14 only | $99/yr; roughly $10–30 a month | CI secrets |
| Static host for the signed catalog index (GitHub Releases, or object storage) | P14 only | about $0 a month; a few dollars on object storage | CI secrets and the publishing workflow |
| Written vendor confirmations that the app may use a customer's own account on the customer's machine | P14 only | $0 | recorded in `docs/data-sources.md` |

Claude Code itself runs on your existing Claude plan.

## 3. Market data for the personal phase (confirmed at the Phase 1 kickoff)

Confirmed on 2026-10-12 (D-38): the app connects to no data source in Phase 1 and imports the files you feed it, so every purchase below happens on the vendor's website, and its files come through the importers (steps 1.6 and 1.10). FEFAT ships no data (D-37), so a customer's copy is filled the same way. Your own files for other products come in through imports at no cost.

- **On this PC today:** 1-minute bars for every MCL, MGC, MES, and MNQ contract, 2010 to 2026-09 (`docs/data-inventory.md`), bought from Databento before the plan; no purchase is planned in Phase 1.
- **Futures catalog products, when ticks are wanted (Phase 2 at the latest):** Databento pay as you go, about $28 per GB for trades (one year of ES trades is about $95, which the $125 sign-up credit covers if it is unspent), or one month of Databento Standard ($199) for the full bar, definition, and settlement history of all eight products plus 12 months of trades or TBBO. Older years use 1-second bars for fills.
- **Optional:** backfill four more years of trades, roughly $1.0–2.2k at the 2024 per-GB rates; `metadata.get_cost` on Databento's site prices any request before you pay.
- **Crypto catalog products:** Binance Vision, Bybit, Hyperliquid archives — $0 for personal use, downloaded by hand until a connector exists (`BACKLOG.md`). If you are US-based, Kraken, Coinbase, and Hyperliquid instead of Binance and Bybit.
- **Your own data:** files from any vendor or platform you already use — $0.
- Disk: budget 100–200 GB under `FEFAT_DATA_DIR` (left at its default, `%LOCALAPPDATA%\FEFAT\data`) for five years of eight futures products with ticks for the recent year, plus caches.

Details and sources: `appendix/research-market-data.md` and `appendix/research-data-sources.md`.

## 4. Running costs

| Item | Personal phase | Notes |
| --- | --- | --- |
| Hosting, database, storage | $0 | everything is on your PC |
| Electricity | a few dollars a month under heavy sweeps | 9950X at full load is about 200 W |
| In-app agent | pay as you go; set a monthly cap in Settings | Opus 5.5: $4 / $20 per million tokens in / out; Sonnet 5.5: $2 / $10; cache reads are much cheaper |
| Claude Code during the build | your plan | each step carries a model hint; heavy multi-agent workflows are off by default |
| CI (GitHub Actions, step 0.6) | $0 within the free plan | the private repository gets 2,000 minutes and 500 MB of artifact storage a month; every push to a pull request runs a Windows and a Linux job, and Windows minutes are priced higher; a push that changes the engine or the benchmarks also runs the Linux Benchmarks job of step 2.15, about 10 minutes on its first, cold run, which is why it runs on no other; without a payment method on file, runs stop when the minutes are used up |
| Market data | $199 for the history, up to ~$2.5k for five years of ticks (§3); then a recurring cost to keep the futures catalog products current through your Databento account: pay-as-you-go downloads, priced on Databento's website before each one until a connector exists (D-38), then by the sync (at the 2024 rates, daily ticks for the eight products come to tens of dollars a month; bars only, a few dollars), or the $199 plan in months you need more | crypto updates are free |

## 5. Product-phase costs (P14 and beyond)

- Windows code signing through a cloud signing service (Azure Trusted Signing or similar): roughly $10–30 a month; traditional certificates are issued on hardware tokens and cannot be used from CI. Apple Developer Program: $99 a year (for macOS notarisation).
- **Market data for customers (D-37):** FEFAT delivers none, so it needs no distribution licence. Each customer connects their own sources under the vendor's terms for personal use and pays the vendor directly (the §3 figures, for Databento and the crypto archives). The research found that delivering the CME products would have cost at least about $127k a year at 2026 fee levels (a vendor plan that allows external distribution plus CME's historical distribution licences for three exchanges), and that hosted backtests on FEFAT-licensed data still count as redistribution of derived information (`BACKLOG.md`, declined 2026-10-12).
- **Vendor confirmations (Phase 14 kickoff):** ask each vendor in the source guide to confirm in writing that the app may use a customer's own account on the customer's machine. Databento's licensing guide discourages bring-your-own-data for hosted products, and FEFAT is not hosted. A source without a confirmation stays in the guide as "check the terms yourself".
- **Signed catalog updates (step 14.7):** a static host for the catalog index (specifications, calendars, roll rules, presets, the source guide; never data), about $0 a month on GitHub Releases, or a few dollars on object storage.
- Optional cloud sync for phone access while the PC is off: tens of dollars a month (backlog, after the phone item of D-54).
