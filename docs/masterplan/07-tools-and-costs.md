# 07 — Tools, accounts, data, and costs

## 1. What to install on this PC (step 0.1)

Already present on 2026-10-05: git 2.55, GitHub CLI 2.97 (signed in), Node 24 + npm 11, uv 0.11 with CPython 3.12 and 3.14, Docker Desktop 29 (not needed by FEFAT), VS Code with the Claude Code extension.

| Tool | Why | How |
| --- | --- | --- |
| Microsoft C++ Build Tools (Desktop development with C++) | Rust's MSVC toolchain links with them | `winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"` (without `--override`, winget installs the bare installer and no C++ workload), or tick "Desktop development with C++" in the Visual Studio Installer; one-time, several GB |
| Rust (stable) via rustup | the engine | `winget install Rustlang.Rustup`, then `rustup default stable`; pinned by `engine/rust-toolchain.toml` |
| pnpm | the web app | `corepack enable --install-directory "$env:APPDATA\npm"` (Node ships corepack; the install directory keeps the shims out of Program Files, which needs administrator rights) then `corepack install -g pnpm@latest` (corepack 0.35 has no `prepare` command), or `npm install -g pnpm` |
| `just` | the task runner | `winget install Casey.Just` or `cargo install just` |
| Python 3.12 | SDK and server | already installed by uv; `.python-version` pins it |
| Playwright browsers (P4) | UI tests | `pnpm exec playwright install chromium` |
| Tailscale (P4) | phone access | `winget install tailscale.tailscale`; sign in with a personal account on the PC and the phone; enable MagicDNS and HTTPS certificates in the Tailscale admin console (step 4.6 walks you through it) |
| Claude Code CLI (optional) | running `claude` from a terminal, not only VS Code | `winget install Anthropic.ClaudeCode` or the installer from the docs |

`just doctor` (written in step 0.1) checks every tool and version and prints what is missing.

## 2. Accounts and keys

| Account | Needed from | Cost | Where the key lives |
| --- | --- | --- | --- |
| GitHub (have) | P0 | free (private repos) | `gh auth` |
| Anthropic Console API key | P8 (the in-app agent); earlier for notebook experiments | pay as you go | OS credential store via the settings page |
| Databento (have data; account for more) | P1 | see §3 | OS credential store; used only by the importer with a cost preview |
| Tailscale | P4 | free personal plan | the Tailscale app |
| Apple Developer membership; a cloud code-signing service for Windows (Azure Trusted Signing or similar — certificates on hardware tokens cannot be used from CI) | P14 only | $99/yr; roughly $10–30 a month | CI secrets |
| Object storage and a small endpoint for the platform data service (Cloudflare R2 or similar) | P14 only | tens of dollars a month at small scale | CI secrets and the service's configuration |
| Distribution licences for platform data delivered to customers | P14 only | see §5 | contracts, recorded in `docs/platform-data-licensing.md` |

Claude Code itself runs on your existing Claude plan.

## 3. Market data for the personal phase (confirmed at the Phase 1 kickoff)

In the personal phase, the platform data for the curated products is built on this PC from your own sources, by the same pipeline the commercial version will run on FEFAT's side (step 1.9). Your own files for other products come in through imports (step 1.10) at no cost.

- **Futures platform products — pilot:** Databento's $125 free credit covers about one year of ES trades.
- **Futures platform products — recommended:** one month of Databento Standard ($199) to download the full bar, definition, and settlement history for all eight products, plus 12 months of trades or TBBO. Older years use 1-second bars for fills.
- **Optional:** backfill four more years of trades, roughly $1.0–2.2k at the 2024 per-GB rates (the importer prices every download with `metadata.get_cost` before pulling anything).
- **Crypto platform products:** Binance Vision, Bybit, Hyperliquid archives — $0 for personal use. If you are US-based, Kraken, Coinbase, and Hyperliquid instead of Binance and Bybit.
- **Your own data:** files from any vendor or platform you already use — $0.
- Disk: budget 100–200 GB under `FEFAT_DATA_DIR` for five years of eight futures products with ticks for the recent year, plus caches.

Details and sources: `appendix/research-market-data.md`.

## 4. Running costs

| Item | Personal phase | Notes |
| --- | --- | --- |
| Hosting, database, storage | $0 | everything is on your PC |
| Tailscale | $0 | personal plan |
| Electricity | a few dollars a month under heavy sweeps | 9950X at full load is about 200 W |
| In-app agent | pay as you go; set a monthly cap in Settings | Opus 5.5: $4 / $20 per million tokens in / out; Sonnet 5.5: $2 / $10; cache reads are much cheaper |
| Claude Code during the build | your plan | each step carries a model hint; heavy multi-agent workflows are off by default |
| CI (GitHub Actions, step 0.6) | $0 within the free plan | the private repository gets 2,000 minutes and 500 MB of artifact storage a month; every push to a pull request runs a Windows and a Linux job, and Windows minutes are priced higher; without a payment method on file, runs stop when the minutes are used up |
| Market data | $199 for the history, up to ~$2.5k for five years of ticks (§3); then a recurring cost to keep the futures platform data current: pay-as-you-go downloads, priced by the sync before each one (at the 2024 rates, daily ticks for the eight products come to tens of dollars a month; bars only, a few dollars), or the $199 plan in months you need more | crypto updates are free |

## 5. Product-phase costs (P14 and beyond)

- Windows code signing through a cloud signing service (Azure Trusted Signing or similar): roughly $10–30 a month; traditional certificates are issued on hardware tokens and cannot be used from CI. Apple Developer Program: $99 a year (for macOS notarisation).
- **Platform data delivered to customers (decision D-24):** every product FEFAT delivers to customers needs a distribution licence. For the CME futures set, the research found about $21k a year for a vendor plan that allows external distribution (such as Databento Plus), plus CME's historical distribution licences whenever customers receive the data itself — which delivering data packs to their machines does — about $105k a year more for the three exchanges involved (CME, NYMEX, COMEX): at least about $127k a year at 2026 fee levels, before legal costs, and every customer must sign CME's subscriber agreement. For crypto, the research found no priced licence that allows redistribution (Tardis forbids it, CoinAPI says it may count as redistribution, Kaiko quotes privately), and the free archives are non-commercial. Confirm with the vendors and CME before committing. Decided product by product in `docs/platform-data-licensing.md` (step 14.6). Sources: `appendix/research-market-data.md` §3.
- **The cheaper alternative for any product:** managed sync with the customer's own vendor account — the platform's catalog, specifications, calendars, rolls, quality checks, and updates, running on the customer's machine with their own key (step 14.6). FEFAT pays no data licence; the customer pays their vendor. Needs written confirmation from each vendor.
- **Platform data service (step 14.7):** object storage for packs plus a small endpoint that checks entitlement tokens — tens of dollars a month at small scale.
- Optional cloud sync for phone access while the PC is off: tens of dollars a month (backlog).
