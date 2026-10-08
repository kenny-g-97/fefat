# 07 — Tools, accounts, data, and costs

## 1. What to install on this PC (step 0.1)

Already present on 2026-10-05: git 2.55, GitHub CLI 2.97 (signed in), Node 24 + npm 11, uv 0.11 with CPython 3.12 and 3.14, Docker Desktop 29 (not needed by FEFAT), VS Code with the Claude Code extension.

| Tool | Why | How |
| --- | --- | --- |
| Microsoft C++ Build Tools (Desktop development with C++) | Rust's MSVC toolchain links with them | `winget install Microsoft.VisualStudio.2022.BuildTools` with the "Desktop development with C++" workload, or the Visual Studio Installer; one-time, several GB |
| Rust (stable) via rustup | the engine | `winget install Rustlang.Rustup`, then `rustup default stable`; pinned by `engine/rust-toolchain.toml` |
| pnpm | the web app | `corepack enable` (Node ships corepack) then `corepack prepare pnpm@latest --activate`, or `npm install -g pnpm` |
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

Claude Code itself runs on your existing Claude plan.

## 3. Market data purchases (confirmed at the Phase 1 kickoff)

- **Pilot:** Databento's $125 free credit covers about one year of ES trades.
- **Recommended:** one month of Databento Standard ($199) to download the full bar, definition, and settlement history for all eight products, plus 12 months of trades or TBBO. Older years use 1-second bars for fills.
- **Optional:** backfill four more years of trades, roughly $1.0–2.2k at the 2024 per-GB rates (the importer prices every download with `metadata.get_cost` before pulling anything).
- **Crypto:** Binance Vision, Bybit, Hyperliquid archives — $0. If you are US-based, Kraken, Coinbase, and Hyperliquid instead of Binance and Bybit.
- Disk: budget 100–200 GB under `FEFAT_DATA_DIR` for five years of eight products with ticks for the recent year, plus caches.

Details and sources: `appendix/research-market-data.md`.

## 4. Running costs

| Item | Personal phase | Notes |
| --- | --- | --- |
| Hosting, database, storage | $0 | everything is on your PC |
| Tailscale | $0 | personal plan |
| Electricity | a few dollars a month under heavy sweeps | 9950X at full load is about 200 W |
| In-app agent | pay as you go; set a monthly cap in Settings | Opus 5.5: $4 / $20 per million tokens in / out; Sonnet 5.5: $2 / $10; cache reads are much cheaper |
| Claude Code during the build | your plan | each step carries a model hint; heavy multi-agent workflows are off by default |
| Market data | $199 once, up to ~$2.5k for five years of ticks | §3 |

## 5. Product-phase costs (P14 and beyond)

- Windows code signing through a cloud signing service (Azure Trusted Signing or similar): roughly $10–30 a month; traditional certificates are issued on hardware tokens and cannot be used from CI. Apple Developer Program: $99 a year (for macOS notarisation).
- Optional small cloud for licence keys or sync: tens of dollars a month. Not planned in the first release.
- No market-data licensing: customers bring their own data and keys, and FEFAT never hosts data.
