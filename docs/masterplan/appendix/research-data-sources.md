# Research: data sources for the source guide (as of 2026-10-12)

> Provenance: research by four Claude subagents on 2026-10-12 from the vendors' and platforms' own pages, for the Phase 1 kickoff (D-38); web reads only, nothing downloaded. A statement with a link is a sourced fact (with the page date where one was visible). **Inference** marks the researcher's reasoning or arithmetic; "(third-party)" marks a non-vendor page used where the vendor's was unavailable. "Not found" means it was searched for and not located. Prices and terms were read on 2026-10-12, and several vendors changed theirs within the year: re-verify an entry before it goes live in the source guide.
>
> How FEFAT uses this: step 1.9 writes the source guide's entries from parts A to C (what each source offers, its cost, its terms for personal use, and whether a desktop app on the trader's machine may use the trader's own account or files), and step 1.10 writes the import presets from part D (the exact export layouts). It complements `research-market-data.md` (2026-10-05), which carries the Databento cost model and the licensing review. No connector is built in Phase 1 (D-38); the connector candidates are in `BACKLOG.md`.

## Bottom line

- **No vendor forbids a desktop app on the customer's machine using the customer's own files or credentials** for historical data. The hard conditions are Databento's platform list for live CME data on the Standard plan, Kibot's two-computer and single-IP rule, Massive's non-professional status and no key sharing, TickData's delete-on-lapse, IQFeed's developer registration ($597 a year, the app vendor signs), dxFeed's per-platform keys (a new app onboards as a partner), and Interactive Brokers' non-commercial API licence.
- **Databento** stays the futures source named first: every CME contract since 2010-06-06 with ticks, bars, definitions, and settlements; Standard $199 a month (since 2026-06-22), pay as you go otherwise, $125 sign-up credit; the metadata, symbology, and account endpoints are free; batch files stay downloadable for 30 days.
- **Cheaper or narrower futures sources:** Massive (ex-Polygon) from 2017 at $0–199 a month, no continuous contracts; Kibot one-off ticks ($580 for the top-10 futures) in headerless Eastern-time CSV; FirstRate Data bars from 2008 stamped at the bar start in Eastern time; Portara/CQG per-symbol one-off files from 1997; Interactive Brokers at $1.55 a month per exchange but only two years of expired contracts; Norgate daily only ($270 a year); CME DataMine quote only; Barchart Premier manual downloads under terms that forbid retransmission and machine learning; TickData quote only.
- **Crypto:** Binance Vision's layouts are confirmed from the official README and listings (spot klines without a header row, futures klines with one since about May 2022, spot timestamps in microseconds since 2025-01-01, inclusive `close_time`, `.CHECKSUM` files), under terms (v1.0, 2026-08-26, CC BY-NC-SA) that allow personal non-production backtesting and forbid hosting; Bybit's and Kraken's column layouts rest on third-party parsers, so an importer asserts the header and timestamp magnitude on the first file; OKX's portal is script-only; Coinbase has no bulk archive and forbids apps for other end users; Hyperliquid's S3 bucket is requester-pays. Bybit excludes the United States in its terms; for Binance.com the exclusion is reported by secondary sources only.
- **Platform exports, for the presets:** NinjaTrader 8 (semicolon, no header, UTC, bars stamped at the close, file names like `ES 12-09.Last.txt`), Sierra Chart (text export with a header, bars stamped at the open; `.scid` records of 40 bytes with microseconds since 1899-12-30 UTC), Databento CSV (header, `ts_event` first, pretty or raw units), and TradingView (`time,open,high,low,close[,Volume]` in Unix seconds UTC, stamped at the open, capped per plan) are documented well enough to write from; TradeStation (close-stamped) and MultiCharts (close-stamped, selectable time zone) rest on community samples and need a real file to confirm; MotiveWave's stamping was not found; Tradovate and Rithmic export no bars; Interactive Brokers exports price history to Excel, and its API bars are documented, so the IBKR preset follows the TWS API bar layout (date, open, high, low, close, volume, average, barCount).

## What the steps take from this

- **1.9, the source guide:** one entry per source below, with a "desktop app with your own account" verdict and the preset that reads its files; the connector candidates (Massive, Bybit, Kraken, Hyperliquid) are entries without a connector until a later phase builds one (`BACKLOG.md`).
- **1.10, the presets:** Databento CSV, IBKR (TWS API bars; the builder's own files define the sample), NinjaTrader (close-stamped, UTC, semicolon, no header), TradingView (open-stamped, UTC, Unix seconds) first; then Sierra Chart (open-stamped) and TradeStation (close-stamped, layout to confirm on a real file). Every preset states its bar stamping and time zone, because those are the two things the research found platforms differ on.
- **1.2 and 1.7:** Databento's continuous symbols (`.c.0`, `.n.0`, `.v.0`) are unadjusted and resolved through the free symbology endpoint; a third-party study puts the mapping switch at 00:00 UTC, which test 2 of step 1.7 checks against the session-open convention.

## Part A — CME futures vendors, group 1: Databento, Massive, FirstRate Data, Kibot, TickData, Portara

Researched 2026-10-12 from the vendors' own pages (web reads only; nothing downloaded). Every fact carries its link; page dates are given where the page shows one. "Inference:" marks my own reasoning. "Not found" means I searched and could not locate it.

### Databento

**Offers**
- Dataset `GLBX.MDP3` = CME, CBOT, NYMEX, COMEX from the MDP 3.0 feed; "full coverage of all futures and options on futures beginning in June 2010"; pre-2017-05 data is from the legacy FIX/FAST feed (https://databento.com/docs/venues-and-datasets/glbx-mdp3). ES catalog page says "Since 2010-06-06 UTC" and lists schemas MBO, MBP-1, MBP-10, TBBO, Trades, BBO-1s/1m, OHLCV-1s/1m/1h/1d, Definition, Statistics, Status, CMBP-1, CBBO-1s/1m (https://databento.com/catalog/cme/GLBX.MDP3/futures/ES).
- Ticks: `trades`, `mbp-1` (top of book), `mbp-10`, `mbo` (full depth). Bars: OHLCV at 1s/1m/1h/1d only; other intervals must be built client-side; `ts_event` "marks the start of each interval"; `ohlcv-1d` is on UTC dates, not exchange sessions (https://databento.com/docs/schemas-and-data-formats/ohlcv).
- Settlements and open interest: `statistics` schema carries venue-published settlement price (final/preliminary flags), cleared volume, open interest, session high/low, price limits for GLBX.MDP3 (https://databento.com/docs/schemas-and-data-formats/statistics). Instrument definitions: `definition` schema (listed on the catalog page above).
- Every individual contract is available ("650,000+ symbols", https://databento.com/pricing); parent symbology `ES.FUT` selects all contracts of a product (https://databento.com/docs/knowledge-base/new-users/licensing).
- Continuous series: symbol `ES.c.0` / `ES.n.0` / `ES.v.0` = front contract by calendar expiry, open interest, or volume; index 1,2,... = later expiries; prices are "the original, unadjusted prices" with no back-adjustment (https://databento.com/docs/examples/symbology/continuous). `n` picks the highest open interest, `v` the highest volume from the previous day; live support for n/v added 2025-04-10 (https://databento.com/blog/live-continuous-contract-symbology, https://databento.com/microstructure/continuous-contract). Roll time of day: not stated on Databento's pages; a third-party study reports the `.v.0` mapping changes at the 00:00 UTC date boundary (https://andrewheekin.github.io/finm37000-grp-6-trading/_sources/contract_rolls.md). Inference: because `n`/`v` use the previous day's data the mapping is knowable before the session, but it is still a vendor-decided roll.

**Delivery and format**
- HTTP API (`hist.databento.com/v0/...`) with Python, C++, Rust clients; streaming or batch download; encodings DBN (binary), CSV (one header line), JSON lines; Zstd compression; prices are int64 in 1e-9 units; timestamps `ts_event`/`ts_recv` are nanoseconds since UNIX epoch (UTC) (https://databento.com/docs/api-reference-historical/basics/rate-limits). Batch files can be re-downloaded for 30 days at no extra charge (https://databento.com/pricing). Live API (raw TCP) uses the same records (https://databento.com/datasets/GLBX.MDP3).

**Cost**
- Standard: $199/month, monthly billing, "No license fees", includes live data, 1 year of L1 history (MBP-1, TBBO, BBO, Trades), 1 month of L2/L3, 16+ years of OHLCV/Definitions/Statistics/Status; Plus $1,750/mo and Unlimited $4,500/mo on annual contracts; Usage-based plan is pay-as-you-go per GB of uncompressed binary with no $/GB figure printed on the page (https://databento.com/pricing). New accounts get $125 in free credits (https://databento.com/docs/knowledge-base/new-users/licensing). CME personal live license "Included with Standard plan (up to 2 devices)"; license fees pass through with a 2.9% Stripe fee (https://databento.com/docs/portal/live-data).
- Price change 2026: from 2026-06-22 the CME Standard plan is $199/mo; existing CME Standard subscribers keep $179/mo for 12 months if continuously active (blog dated 2026-05-29, https://databento.com/blog/updates-to-subscription-pricing).

**Terms for personal use**
- User Agreement (effective 2024-01-31): §1.1 licence "solely for its internal business purposes"; §1.3 only "Authorized Users" (employees/contractors) may use the Platform, "User Credentials are kept confidential and are not disclosed to any third party"; §1.4(b) no timesharing/service-bureau use, (d) no building a competitive service; §1.5(e) use limited "to internal Customer purposes", no Redistribution without exchange/Databento approval; §1.6 any permitted redistribution must credit "Data Provided by Databento" (https://databento.com/legal/databento-user-agreement). Website Terms of Use are separate (https://databento.com/legal/terms-of-use).
- Exchange Data Policy (effective 2025-04-08) for CME live data on the Standard plan: personal use only, "two or fewer devices", funded futures account, and external distribution of real-time data prohibited within 8 hours; "distributing any CME data via an API, whether real-time or historical, requires an Information License Agreement" (https://databento.com/legal/exchange-data-policy). Historical (T+1) data needs no exchange licence (https://databento.com/blog/introduction-market-data-licensing, 2023-10-02).

**Third-party app with own account**
- No clause forbids running your own key inside third-party software for historical data; §1.3 only restricts disclosing credentials to other people (link above). Inference: a desktop app on the customer's own machine using the customer's key is within "internal purposes" as long as the app does not redistribute.
- Live CME data is the catch: Exchange Data Policy Q6 requires that "Real-time CME data may only be used with software that can route orders and execute trades through your broker" and names supported platforms (Architect, Alpaca, Blue Trading Systems, Lightspeed, Lime, Multicharts, Nirvana, Topstep) (https://databento.com/legal/exchange-data-policy). Inference: a research-only desktop app does not satisfy Q6 for the personal live licence; historical use is unaffected.

**Rate limits**
- Per IP: 100 concurrent connections, 100 time-series requests/s, 100 symbology requests/s, 20 metadata requests/s, 20 batch list-jobs/s, 20 batch submit-jobs/min; HTTP 429 with `Retry-After`; no size limit on stream or batch requests (https://databento.com/docs/api-reference-historical/basics/rate-limits).

**Free endpoints**
- Metered-pricing section of the historical API reference: "You will only be billed for usage of time series data. Access to metadata, symbology, and account management is free. The Historical.metadata.get_cost method can be used to determine cost before you request any data." (https://databento.com/docs/api-reference-historical/basics/metered-pricing; the same text is on https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost and https://databento.com/docs/api-reference-historical/metadata/metadata-get-record-count). Inference: `metadata.get_cost`, `metadata.get_record_count` and `metadata.get_billable_size` are metadata endpoints, so they need only an API key and no data purchase; `metadata.list_unit_prices` returns "unit prices in US dollars per gigabyte" per feed mode and schema, which is where the $/GB missing from the pricing page can be read (https://databento.com/docs/api-reference-historical/batch/batch-list-jobs?historical=python, Metadata section).
- Symbology: "This conversion can be done, for no cost, with the symbology.resolve endpoint." (API reference, Symbology section, same page). Rate caps still apply: 20 metadata requests/s and 100 symbology requests/s per IP (Rate limits above).
- Batch downloads: "you are only billed once for the request and, subsequently, you can download the data from the Download center multiple times over 30 days for no additional charge" (https://databento.com/docs/api-reference-historical/basics/metered-pricing; FAQ: "Download the same data multiple times over a 30 day period, for no additional charge", https://databento.com/docs/faqs/streaming-vs-batch-download). The job field `ts_expiration` is "The timestamp of when the batch job will expire from the Download center" (official Rust client source, https://docs.rs/databento/latest/src/databento/historical/batch.rs.html). Other batch limits: 20 submit-job requests per minute; no size limit (batch recommended above 5 GB); files can be split by day/week/month, by instrument, or by 2/4/10 GB size limit; delivery is HTTP or FTP only, S3/disk "coming soon" (https://databento.com/docs/portal/batch-download). A retention period other than the 30-day window: Not found.

**Changes in 2026**
- CME Standard plan $179 → $199 on 2026-06-22 (link above). Client release notes through 2026-09 show new venues/datasets (JPX 2026-08-04, Databento Core Indices 2026-09-18, US equities SIPs 2026-06-02), live Zstd compression (2026-02-04), DBN v3 decoding changes (2026-08-25) (https://databento.com/docs/release-notes). Normalisation changes to GLBX.MDP3 itself: Not found.

**Not found**
- A printed $/GB rate for GLBX.MDP3 (pricing page shows only "<$0.01" without context; the ES catalog page shows no prices; the rate is exposed only via the free `metadata.list_unit_prices` / `metadata.get_cost` endpoints). The per-plan "device" definition beyond "two or fewer devices". An explicit roll-time statement in Databento's own docs.

### Massive (formerly Polygon.io) futures

**Offers**
- CME, CBOT, COMEX, NYMEX real-time and historical trades, quotes, aggregates, contracts, products, schedules; "Records date back to April 3, 2017" (https://massive.com/docs/rest/futures/overview, https://massive.com/docs/rest/futures/trades-quotes/trades). Rebrand from Polygon.io effective 2025-10-30 (https://fisd.net/polygon-io-is-now-massive).
- Ticks: `GET /futures/v1/trades/{ticker}` (price, size, nanosecond exchange timestamp, sequence numbers) and `GET /futures/v1/quotes/{ticker}` (best bid/offer with sizes) (links above). Bars: `GET /futures/v1/aggs/{ticker}` with `resolution` from seconds up to session/week/month/quarter/year (e.g. `1min` … `59min`, then `1hour`); bars are built from trades so empty intervals have no bar; session bars carry `settlement_price` (https://massive.com/docs/rest/futures/aggregates.md). Definitions: Contracts endpoint (first/last trade date, settlement date, tick sizes, point-in-time) and Products endpoint (https://massive.com/docs/rest/futures/contracts.md). Open interest: Not found in the futures endpoints.
- Individual contracts only (tickers like `ESZ5`, `GCJ5`). The marketing page lists "Continuous Contracts" as a feature (https://massive.com/futures) but no continuous-contract endpoint or roll rule appears in the docs index (https://massive.com/docs/llms.txt). Not found: roll rule / adjustment.

**Delivery and format**
- REST + WebSocket, official Python/JS/Go/Java clients (https://massive.com/futures). Timestamps: Unix nanoseconds in UTC for trades, quotes and aggregate `window_start`; `window_start` is the start of the bar; `session_end_date` = exchange trading date (session ending 5:00 pm CT carries that date) (https://massive.com/docs/rest/futures/overview, https://massive.com/docs/rest/futures/aggregates.md).
- Flat files on S3 for CME/CBOT/NYMEX/COMEX: minute aggregates (columns ticker, exchange, session_end_date, window_start, open, high, low, close, volume, dollar_volume, transactions; Starter and up), trades (ticker, timestamp, sequence_number, report_sequence, price, size, correction, exchange, session_end_date; Developer and up), quotes, session aggregates; "Updated at 11a ET to include the previous day" (https://massive.com/docs/flat-files/futures/minute-aggregates/cme.md, https://massive.com/docs/flat-files/futures/trades/cme.md).

**Cost**
- Individual plans: Futures Basic $0 (5 API calls/min, 2 years history, "8-hour historical" bars only), Futures Starter $29/mo (unlimited calls, 10-minute delayed, 2 years), Futures Developer $79/mo (10-min delayed, 5 years, trades/quotes included), Futures Advanced $199/mo (real-time, "7+ Years"/all history); all billed monthly and marked "Individual use" (https://massive.com/pricing?product=futures). Trades/quotes endpoints: not included in Basic/Starter (https://massive.com/docs/rest/futures/trades-quotes/trades). Business plans are per exchange (Futures Business CME/CBOT/NYMEX/COMEX), price not shown on the futures pricing page.

**Terms for personal use**
- Massive for Individuals Terms of Service (Last Updated 2025-07-18): §2 access "solely for your own personal, non-commercial, and non-business purposes"; §3.3 "Unauthorized use of another's account, password, or API keys is strictly prohibited. For the avoidance of doubt, this includes sharing an account or API keys with others"; §6.1(h) no selling/transferring access, (i) no using another user's keys (https://massive.com/legal/individuals-terms-of-service).
- Market Data Terms of Service (Last Updated 2025-08-28): §3 you warrant you are a Non-Professional using data "solely for your personal, non-business use"; §4.3 (CME, between §4.2 and §4.4) you enter the CME Subscriber Addendum and may "access Market Data via a maximum of two Order Routing Devices, provided by Massive"; §5(c) no redistribution, display or transfer of Market Data or "Derived Works" to any third party or any business use (https://massive.com/legal/market-data-terms-of-service). Non-pro questionnaire described at https://massive.com/blog/understanding-professional-status (2020-05-08).

**Third-party app with own account**
- No clause addresses third-party applications; the prohibitions are on sharing keys with other people (§3.3) and on redistribution (§5(c)). Inference: your own key inside a local desktop app used only by you is personal use; the two-"Order Routing Device" CME wording (§4.3) is the only device limit and is not defined further on the page.

**Rate limits**
- Basic "5 API Calls / Minute"; Starter/Developer/Advanced "Unlimited API Calls" (https://massive.com/pricing?product=futures). Page size: trades `limit` max 50,000; aggregates `limit` max 50,000 (docs links above).

**Changes in 2026**
- Docs note CME crypto futures trade near-24/7 from 2026-05-29 (https://massive.com/docs/rest/futures/overview). Futures pricing or terms changes in 2026: Not found (ToS last updated July/Aug 2025).

**Not found**
- Continuous-contract endpoint/roll rule; open interest field; business futures plan prices; any statement on nanosecond vs. millisecond precision in flat files beyond "nanosecond timestamps".

### FirstRate Data

**Offers**
- 1-minute, 5-minute, 30-minute, 1-hour and 1-day OHLCV bars for 122 (list page) / 130 (bundle) futures tickers; ES, NQ, CL, MES, MNQ in the standard list; MGC and MCL "Available only in the Most Active Futures Bundle" (https://firstratedata.com/it/futures). ES: intraday bars from 2008-01-02 to 2026-10-09, individual contracts from ESZ08, plus continuous series in three variants: unadjusted, absolute-adjusted, ratio-adjusted (https://firstratedata.com/i/futures/ES).
- Continuous build: front-month chain rolled "prior to expiry" by custom per-contract rules listed in the 'Other Data' tab; "the contracts are rolled at midnight EST (ie the contract changeover is at 00:00)"; absolute adjustment = close-of-expiring minus open-of-new applied to all prior data; ratio adjustment = the percentage difference (https://firstratedata.com/about/price_adjustment).
- Daily bars include Open Interest; no tick data, settlements or instrument definitions for futures (FAQ format section, https://firstratedata.com/about/faq). Tick bundles exist only for stocks/ETFs/crypto (https://firstratedata.com/bundle/all).

**Delivery and format**
- Zipped CSV from a private customer page; one file per ticker and timeframe named `{ticker}_{period}_{timeframe}_{adjustment}` e.g. `ES_full_1min_continuous_absolute_adjusted.txt`; columns DateTime (yyyy-MM-dd HH:mm:ss), Open, High, Low, Close, Volume (daily adds Open Interest); "Timestamps mark the start of each bar"; all data in US Eastern time (EST/EDT), crypto in UTC (https://firstratedata.com/about/faq).
- Bulk API only for bundles (serves zip archives, `last_update` endpoint, "There are no rate limits"); individual tickers download via the customer page only; updates daily by about 11:30 pm ET (same FAQ).

**Cost**
- One-off purchase with one month of updates; the ES page shows no one-time price in its text (the Buy Now button price is rendered at checkout via FastSpring, local currency incl. tax), updates "$99.95" per year for the ticker (https://firstratedata.com/i/futures/ES). Futures – Most Active bundle (130 tickers, Jan 2007 – Oct 2026): updates "$59.95 per month" after the free month; one-time price not shown in page text (https://firstratedata.com/b/29/futures-most-active). A third-party directory lists the bundle at $299 one-time (https://nexusfi.com/d/data-providers/firstrate-data/) — not verified on FirstRate's site. No discounts or custom bundles (https://firstratedata.com/about/faq).

**Terms for personal use**
- License Agreement: perpetual, "worldwide, royalty-free license to access, copy and use the Data"; (iii) may import into databases; (v) derivative works allowed; Subscriber agrees "(i) not to resell or otherwise redistribute the Data", "(ii) the Data is for the private use of the Subscriber only", "(iii) ... will not make their user details available to another party"; multi-user licences cover one institution (https://firstratedata.com/about/license). No device or machine count stated. Raw-data redistribution (CSV downloads, an API returning bars) is prohibited; rendered charts and derived results are allowed (https://firstratedata.com/about/faq).

**Third-party app with own account**
- The licence lets "service providers" access and operate on the data on the Subscriber's behalf (licence clauses (i) and (ii)) and permits loading into the Subscriber's own systems (link above). There is no API key for single-ticker purchases (download links only). Inference: a desktop app reading the customer's own CSV files on the customer's machine is "private use of the Subscriber"; the only no-go is exposing raw bars to other people.

**Rate limits**
- Bundle API: "There are no rate limits" (https://firstratedata.com/about/faq). Single tickers: no API.

**Changes in 2026**
- Not found (pages carry no change log; data end dates show updates through 2026-10-09).

**Not found**
- One-time USD prices (rendered at checkout); exact per-contract roll offsets (in the customer-only 'Other Data' tab); any tick/quote data for futures.

### Kibot

**Offers**
- 83 futures contracts on CME/CBOT/NYMEX/COMEX/CFE; ES, NQ, CL, GC, MES, MNQ, MGC are listed; MCL is not (QM E-mini crude is) (https://www.kibot.com/futures/futures-symbols.html). Individual contract months "back to inception" plus unadjusted continuous series (https://www.kibot.com/futures.html); futures packages: "Minute and tick data back to 2009" (https://www.kibot.com/buy.html); "over 17 years of minute data for Forex and Futures and over 17 years of tick-by-tick" (https://www.kibot.com/api/historical_data_api_sdk.aspx).
- Intervals: tick, tick+bid/ask, 1s, 10s, 1/5/15/30-min, aggregate bid/ask bars, daily (https://www.kibot.com/buy.html). Daily close is the exchange settlement price and the futures day runs 5 pm–5 pm ET (support page as summarised, https://www.kibot.com/support.aspx). Instrument definitions: expiration rules through 2030 and per-contract specs pages (https://www.kibot.com/futures/futures-expirations.html). Open interest: Not found.
- Continuous rule: "calendar-based unadjusted rollover", fixed offset per product, no back-adjustment, no volume/OI heuristic; ES/NQ/MES/MNQ roll 5 trading days before expiration (Monday of expiry week), CL 3 trading days before expiration, GC/MGC 2 trading days from the end of the prior month; equity-index offset changed from 7 to 5 days in June 2022 (https://www.kibot.com/futures/rollover-rules.html, https://www.kibot.com/futures/continuous-futures.html). Roll time of day: the series switches by date ("Bars dated March 16 forward are real ESM26 trades"); intraday time not stated.

**Delivery and format**
- Headerless comma-delimited text; bars `Date,Time,Open,High,Low,Close,Volume` with `mm/dd/yyyy` and `hh:mm` in US Eastern time (configurable offset or `&timezone=utc`); bar timestamp is the bar open ("10:00 AM is for a period between 10:00:00 AM and 10:00:59 AM"); ticks `Date,Time,Price,Bid,Ask,Size` to the second (https://www.kibot.com/support.aspx, https://www.kibot.com/file-format/millisecond-tick-data.html). Futures millisecond ticks exist but "are not meaningful there" (same page). NinjaTrader/TradeStation variants available (https://www.kibot.com/).
- Channels: account download links, free Kibot Agent (Windows), FTP (RAR archives, updates only), HTTP GET API `api.kibot.com` returning CSV text, gzip on request (https://www.kibot.com/delivery/data-updates.html, https://www.kibot.com/api/api-overview.html).

**Cost**
- One-time packages (full history, 45 days of daily updates then quarterly for a year): Top 10 Futures continuous — 30-min $50, 1-min $220, tick $580, tick+bid/ask $800; Top 10 continuous + individual — 1-min $400, tick $1,100, tick+bid/ask $1,700; Top 25 continuous 1-min $330 / tick $870 / tick+b/a $1,200; Top 25 continuous + individual 1-min $600 / tick $1,650 / tick+b/a $2,550; All Futures continuous 1-min $520 / tick $1,420 / tick+b/a $1,950; All Futures continuous + individual 1-min $820 / tick $2,200 / tick+b/a $3,750 (https://www.kibot.com/buy.html; package names from the same page as rendered at https://www.kibot.com/pricing.aspx). Custom orders from $40; examples "as of 9 October 2026": "ES + NQ 1-minute bars, since 2009 $135.00", "ES + NQ Tick + bid/ask, last 3 years $465.00", "MNQ 1-minute bars, last 5 years, NinjaTrader format $69.83" (https://www.kibot.com/custom-order.html).
- Update subscriptions: Premium $139/mo (daily updates, full API), Professional $69, Standard $40 (one page) / $49 (another page), Basic $24, EOD $14; tick data is never included in a subscription (https://www.kibot.com/subscribe.html, https://www.kibot.com/delivery/data-updates.html).

**Terms for personal use**
- License Agreement: non-exclusive, non-transferable, revocable; "will not resell or redistribute the Data or the Software"; "The Data is for the Licensee's own internal use only"; "The Licensee may use the Data and Software on two computers that are normally accessed by the Licensee"; archival copies allowed; account details must not be given to another party; downloaded data is yours to keep after a subscription lapses (https://www.kibot.com/license.html). All API/Agent requests must come from a single IP per account (https://www.kibot.com/delivery/data-updates.html).

**Third-party app with own account**
- No clause on third-party applications. The API is "provided for use by third-party developers" and emits NinjaTrader-format output (https://www.kibot.com/api/historical_data_api_sdk.aspx). Inference: a desktop app on one of the two licensed computers, using the customer's own login, is "own internal use"; full-interval API calls need Premium (or the 45-day window after a first purchase), otherwise the app must read downloaded files.

**Rate limits**
- Per server: 40 concurrent in-flight requests and 50 requests per 500 ms, exceeded → `403 Login Failed`; keep ≤5 concurrent connections per account across API/FTP/Agent; sessions expire after 20 minutes idle (https://www.kibot.com/delivery/data-updates.html, https://www.kibot.com/api/server-responses.html).

**Changes in 2026**
- Not found as dated announcements; the site shows prices "as of 9 October 2026" (custom-order page) and a tax note that "many governments have further tightened enforcement from 2026" (https://www.kibot.com/support.aspx). Roll-rule changes date from 2022 (rollover page).

**Not found**
- Per-symbol start dates for ES/NQ/CL/GC ticks (specifications page shows only roll offsets); open interest; settlement records; MCL.

### TickData (tickdata.com)

**Offers**
- "Over 280 global futures contracts"; tick-by-tick Level I quotes (bid/ask with size) and trades (price, volume); "Time stamped to the millisecond since July 2011" (seconds since 2003-06-01); front- and back-month data; quote data for all futures from 2010-01-04; all contract months stored since July 2003; electronic/overnight sessions from 2003-07-01; trade volume only for electronic sessions (https://www.tickdata.com/product/historical-futures-data, https://www.tickdata.com/futures-faq/). Company data "as far back as 1974" (https://www.tickdata.com/overview). ES-specific start date: Not found on the site (symbol list is an XLSX: https://tick-data-s3.s3.amazonaws.com/downloads/Tick_Data_SymbolList_Futures.xlsx).
- Bars and continuous series are built by the customer in TickWrite (any tick/second/minute/daily interval; roll methods incl. default FRONT/AUTO, "Most Active", n days before expiration, ratio adjusting) (https://www.tickdata.com/futures-faq/, https://tick-data-s3.s3.amazonaws.com/pdf/TickWrite7_Manual.pdf). "Daily" files are aggregated from ticks and exclude EFP/block trades before 2011-07-01 (FAQ). Settlements/open interest/definitions: a separate "Historical Calendar Information" subscription gives contract first/last trade dates and hours (https://www.tickdata.com/product/historical-calendar-info/); settlement prices: Not found.

**Delivery and format**
- Zipped comma-delimited ASCII; trades and quotes "are not interlaced and are delivered in separate files"; data "delivered in the time zone of the instrument's exchange", convertible to any zone; TickWrite 7 (Windows/Linux), TickWrite Web (browser), TickAPI (hosted REST, stream or download), Deep History files, or hard drive for very large orders (https://www.tickdata.com/futures-faq/, https://www.tickdata.com/). Column layouts for futures files and bar-timestamp convention: Not found online (the Futures File Format Guide is referenced but not located; other asset-class guides show `MM/DD/YYYY, HH:MM:SS.000` layouts, e.g. https://tick-data-s3.s3.amazonaws.com/pdf/TickData_File_Format_Overview_Germany.pdf).

**Cost**
- No public price list for one-off futures data; orders are quoted ("Order data for all symbols or specific symbols and dates", https://www.tickdata.com/product/historical-futures-data). TickAPI: one-year minimum, $250 minimum per month, $0.03 per request, annual $250 Delivery Support Fee; futures/index/FX tiers from $2.00 per symbol-month (1–60) down to $0.26 (5,041–6,120) (https://www.tickdata.com/data-delivery/tickapi). TickWrite software itself is free with licensed data (https://tick-data-s3.s3.amazonaws.com/pdf/Guide_to_Data_Delivery_Options.pdf, 2014). Third-party forum anecdote: "costs start at $1000" (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1247028-arg-isn-t-there-a-reasonable-option-for-historical-tick-data?p=1247036) — unverified.

**Terms for personal use**
- Website Terms of Use cover only the website (https://www.tickdata.com/terms-of-use/). A Tick Data "Leased Data License Agreement" (2021 form, hosted on HubSpot): §2.1 licence "to use, display, analyze and create Derived Data solely in the course of Licensee's internal business use", no distribution to third parties; §2.3 no renting/sublicensing and no use "in a computer-based services business which would allow third parties to access or use the Data"; §2.2 twelve-month auto-renewing term; §7.1 on non-renewal "destroy the Software Product and all Data" (https://f.hubspotusercontent30.net/hubfs/4429683/Google%20Cloud%20(TM)%20Tick_Data_LLC-Leased_Data_License_Agreement.pdf). TickAPI page: "Data is licensed under 'leased' data model; active subscription required for data use" (https://www.tickdata.com/data-delivery/tickapi). Device/user counts: Not found.

**Third-party app with own account**
- No clause found about third-party applications or credential use; the FAQ expressly expects the files to be read by third-party software ("NinjaTrader, MetaTrader, TradeStation, MATLAB", https://www.tickdata.com/futures-faq/). Inference: a local app reading delivered files is internal use under §2.1; under the leased model the data must be deleted if the subscription lapses (§7.1).

**Rate limits**
- Not found (TickAPI pricing is per request; no throttle documented).

**Changes in 2026**
- Not found (no dated pages; delivery guide is 2014, licence form 2021).

**Not found**
- Futures file column layout, bar-timestamp convention, settlement data, one-off prices, user/device limits, 2026 changes.

### Portara / CQG Data Factory

**Offers**
- CQG Data Factory history resold by Portara: daily from 1899, 1-minute intraday from 1987, tick (trades-only and Level 1 bid/ask/trade/settle) (https://portaracqg.com/, https://portaracqg.com/historical-intraday-futures-data/). E-mini S&P (CQG symbol EP): daily from 1997-09-09, 1-min from 1997-09-08, tick trades-only from 1997-09-09 (119.4 GB uncompressed), tick Level 1 from 1997-09-08 (828.9 GB) (https://portaracqg.com/futures/int/ep). MES: all four types from 2019-05-06 (intraday 175.6 MB, tick 36.5 GB, L1 481.3 GB) (https://portaracqg.com/futures/int/mes). Millisecond timestamps only from May/mid-2013; earlier ticks carry minute resolution; trade volume from September 2000, tick count before that (https://portaracqg.com/sample-data/).
- Individual contracts ("tenors") or continuous; continuous built to order: zero, back, forward, ratio adjust; default suggestion "3 days before expiry" for EP/MES, "Roll based on settlement price", roll log supplied; optional columns contractName, unadjusted close, spread, cumulative spread (EP page). Daily files carry O,H,L,C,V,OI with close on last price or settle; Level 1 ticks flag T/B/A/S (trade/bid/ask/settle) (https://portaracqg.com/sample-data/). Bars: 1-min default, any compression; second bars 1–60 s from 2014 (https://portaracqg.com/pricing-tick-level-1-data/). Instrument definitions: contract spec table on each product page (EP page). Continuous-data background article dated 2022-03-01 (https://portaracqg.com/continuous-futures-data/).

**Delivery and format**
- One-off orders are built manually and emailed as download/FTP links, "usually ... within 24hrs" (EP page; https://portaracqg.com/pricing/). CSV/TXT ASCII, delimiter selectable; default columns `date, time, open, high, low, close, volume`; "Timestamp Type: Start of Bar (or you can choose End of Bar)"; "Timezone: Exchange Time, US Central Time (Chicago, UTC-6 / -5 DST)" or custom such as UTC; date/time formats selectable (https://portaracqg.com/futures/int/ep). Subscription path: Portara Charts Windows software with a local CQG database and auto-updates, and the new "Portara Downloader" cloud-to-desktop app (Windows 10/11/Server) (https://portaracqg.com/portara-downloader/). No API.

**Cost**
- 1-minute full history: "$330 (on special: $220) / per commodity", individual or continuous, roll and formatting included; daily $180 (last 30 years) or $360 (full history); 5-min/15-min/hourly cost the same as 1-min (https://portaracqg.com/pricing/, https://portaracqg.com/ninjatrader-pricing/). Tick trades-only per symbol: Standard band (<150 GB, e.g. EP) $695 (2014→date), $895 (2000→date), $1,095 (inception→date), or $125 per historical year with $500 minimum; Level 1 (every bid/ask/trade) by size band: Small $795/$995/$1,195, Medium $995/$1,195/$1,395, Large (500 GB–1 TB, "20% off") $1,295/$1,595/$1,895, Huge $1,695/$1,995/$2,295; trades-with-BBA Small $695/$895/$1,095; second bars $495 (https://portaracqg.com/pricing-tick-level-1-data/). Subscription (software + updates): "$ tailored / yearly / monthly" on quote (https://portaracqg.com/pricing/).

**Terms for personal use**
- Data License – One-off Purchases: §1 perpetual, non-exclusive, non-transferable; §3 use "Within your organization, by up to five people, on your own computers, servers or cloud instances, with backups"; §4 "Research, backtesting, model and AI training, live trading" and publishing derived results allowed; §5 no passing data (or anything it could be reconstructed from) outside the organization, no inclusion in any product/feed/service, no use to build a market-data service — licence terminates automatically; §7 7-day re-issue window, non-refundable (https://portaracqg.com/license/). Software subscription: "single licence per user", extractions may be shared by up to 5 persons in a small fund, "Portara can only be installed on 1 machine per licence" (https://portaracqg.com/pricing/).

**Third-party app with own account**
- There is no account/API key for data; files are plain CSV. §3/§4 allow use on your own computers for research and live trading (link above). Inference: a third-party desktop app reading the purchased files on the customer's machine is squarely within §3; the only limits are the 5-person/organization scope and no redistribution.

**Rate limits**
- Not applicable (no API; manual delivery).

**Changes in 2026**
- Not found as dated items: "Portara Downloader" is labelled NEW (undated, https://portaracqg.com/portara-downloader/); the pricing page's "on special: $220" has no date; software update history has no dates (https://portaracqg.com/update-history/); the blog's latest post is 2025-05-27 (https://portaracqg.com/blog/).

**Not found**
- Portara Downloader/subscription prices; MCL/MGC/MNQ product pages (only EP and MES were linked from the home page; the intraday table is alphabetical and was truncated at "ER"); a stated roll time of day (rolls are by settlement/close date).

### Summary table

| Source | Ticks | Bars | Definitions/settlements | History from | Price for an individual | Personal-use terms | Third-party app with own key |
|---|---|---|---|---|---|---|---|
| Databento | Trades, MBP-1, MBP-10, MBO; ns timestamps | OHLCV 1s/1m/1h/1d (ts = bar open, UTC days) | Definition + statistics (settlement, OI, limits) | 2010-06-06 (all CME) | Standard $199/mo (was $179; change 2026-06-22); usage-based $/GB; $125 free credit | Internal purposes only; credentials confidential (§1.3); CME live: personal, 2 devices, no redistribution <8h | Historical: no clause against it (inference OK). Live CME personal licence requires order-routing-capable, named platforms (Exchange Data Policy Q6) |
| Massive | Trades + BBO quotes, ns timestamps; Developer+ only | Custom bars sec→year via REST; minute/session flat files; window_start = bar open | Contracts/products endpoints; settlement on session bars; no OI | 2017-04-03 | Basic $0, Starter $29, Developer $79, Advanced $199/mo | Non-professional, personal non-business use; no key sharing (§3.3); no redistribution of data or derived works (§5(c)); 2 "Order Routing Devices" for CME (§4.3) | Not addressed; sharing key with other people is the prohibition (inference: own local app OK) |
| FirstRate Data | None for futures | 1/5/30-min, 1h, 1d CSV; ts = bar start, US Eastern; 3 continuous variants, roll 00:00 ET | Daily OI only; no definitions/settlements | ES 2008-01-02 | One-off (price at checkout, not shown); updates $99.95/yr per ticker; bundle updates $59.95/mo | Perpetual, private use of Subscriber only, no raw-data redistribution, no device count | No key for single tickers; licence allows own systems/service providers (inference OK) |
| Kibot | Tick and tick+NBBO-style bid/ask, to the second | 1s/10s/1–30-min/daily, headerless CSV, ts = bar open, ET; unadjusted calendar-roll continuous (ES −5 td, CL −3 td, GC −2 td from prior month end) | Expiration/spec pages; daily close = settlement; no OI found | 2009 (futures minute/tick) | e.g. Top 10 futures 1-min $220, tick+bid/ask $800; ES+NQ 1-min since 2009 $135; Premium API $139/mo | Own internal use, two computers, no redistribution, single IP | Not addressed; API is "for third-party developers" (inference: OK on a licensed computer) |
| TickData | Trades and Level I quotes w/ size; ms since 2011-07 | Built by customer in TickWrite/TickAPI, any interval | Calendar-info subscription (contract dates/hours); settlements not found | Firm data from 1974; ES start not found | Quote only; TickAPI $250/mo min + per symbol-month | Internal business use, leased model, no third-party access via services; destroy on lapse (§7.1) | Not addressed; files meant for third-party tools (inference OK while licence active) |
| Portara / CQG | Trades-only and Level 1 (bid/ask/trade/settle); ms since 2013, minute before | 1-min from 1987 (EP 1997-09-08), any compression, SOB or EOB, exchange or custom TZ; back/forward/ratio/zero adjust to order | Spec table per product; daily O,H,L,C,V,OI with settle; settle records in L1 | EP 1997-09-08; MES 2019-05-06 | 1-min $330 ($220 special) per symbol; EP ticks $695–$1,095; EP L1 $1,295–$1,895 | Perpetual, up to 5 people in your organization on own computers; no redistribution (§3–§5) | No key; CSV files; §3 "on your own computers" (inference OK) |

## Part B — CME futures vendors, group 2: dxFeed, IQFeed, Barchart, Interactive Brokers, CME DataMine, Norgate and free daily sources

Researched 2026-10-12 from vendor pages (web reads only; no market data downloaded). Every fact carries its link; "Inference:" marks my own reasoning or arithmetic; "(third-party)" marks non-vendor pages used only where the vendor page was unavailable. Page dates are given where the page shows one.

### dxFeed (historical data services)

**Offers**
- Futures page: CME, NYMEX, COMEX, CBOT; "Historical: Tick-level & aggregated OHLCV since 2010"; "Rolling futures" continuous symbols; instrument profile service; APIs Java, FIX, C/C#, JavaScript/REST, Python/R (https://choose.dxfeed.com/futures-market-data/).
- CME event types: Bid/Ask, Last Sale, Time and Sale, Price Level Book, Full Order Depth, Profile, Summary, Candles (https://dxfeed.com/market-data/futures/cme/, page dated 2017-12-06). Summary carries day OHLC and OpenInterest; "For futures, Settlement date replaces the last trade in Close when it arrives" (https://kb.dxfeed.com/en/data-model/market-events/model-of-event-publishing.html).
- TickData service: "access to historical data starting from 2014, subject to your entitlements", ~30 hours local cache; the direct API keeps "up to 10 days of tick data" for backfill (https://kb.dxfeed.com/en/data-services/historical-services/how-to-request-tick-data.html). FAQ: "Historical data is available from 2009 for some markets. Some events can be requested only 1000 ticks back." (https://kb.dxfeed.com/en/faq.html).
- Candle depth by default: 1-4 min 43 calendar days, 5+ min 90 days, 1+ hour 285 days, day/week/month all history; max 8000 candles per request (1000 for 1-tick); bid/ask/mark candles ~14 days (https://kb.dxfeed.com/en/data-services/aggregated-services/candle-types.html).
- Symbols: product /ES:XCME, contract /ESM25:XCME (https://kb.dxfeed.com/en/data-model/symbology-guide/general-provisions.html). Continuous roll rule (third-party forum, MultiCharts support relaying dxFeed, 2026-01-05 and 2026-03-19): rollover "defined by the hard-coded rules, which are based on the Last Trading Date offset, and the exchange recommendations. No back adjustment is applied"; equity index futures follow CME Equity Index Roll Dates; MGC and ZS roll "based on the liquidity" with no fixed schedule (https://www.multicharts.com/discussion/viewtopic.php?t=59549). No dxFeed-authored roll-rule page found.

**Delivery and format**
- TickData REST: `https://tools.dxfeed.com/tickdata?records=Quote,Trade&symbols=...&start=YYYYMMDD-HHMMSS[.sss][zone]&stop=...&format=csv|text|binary&compression=zip|gzip`; epoch times are milliseconds (https://kb.dxfeed.com/en/data-services/historical-services/how-to-request-tick-data.html).
- Candlewebservice: records=Candle or TimeAndSale, candle symbols like `ES{=m}`, start/stop with "a maximum range of seven days", format text/csv/binary, compression (https://kb.dxfeed.com/en/data-services/aggregated-services/candlewebservice.html). Candle JSON fields: time (epoch ms), sequence, count, open, high, low, close, volume, vwap, bidVolume, askVolume, impVolatility; candles "aligned to midnight" by default, `a=s` aligns to session (https://kb.dxfeed.com/en/data-services/aggregated-services/how-to-request-candles.html). Inference: the vendor's Java sample skips a candle while `candle.getTime() + period > now`, so `time` marks the bar open.
- Bulk: "One time data extraction in *.csv (tick level or aggregated) ... via link" (https://dxfeed.com/data-services/historical-data-services/, 2020-08-05); Historical Data Lake via Amazon Data Exchange and AWS Snowball for petabyte sets (https://kb.dxfeed.com/en/faq.html). CSV column layout: Not found.

**Cost**
- Retail store (per platform): "Prices from $19/month" (https://choose.dxfeed.com/individuals/); Quantower order form: CME Group (CME, CBOT, NYMEX, COMEX) Top of Book $19/mo, CME Group Market Depth $99/mo, non-professional self-certification (https://get.dxfeed.com/orders/new/quantower/). Bookmap's dxFeed page (third-party partner): CME/CBOT/NYMEX/COMEX full depth $37/mo each or $97/mo bundle (https://bookmap.com/.dxFeed/).
- Retail Top of Book = "Real-time Best Bid and Offer and Last Sale market data + Historical charting" (https://dxfeed-retail.zendesk.com/hc/en-us/articles/4403214704407-CME-Group-CME-CBOT-NYMEX-COMEX). Depth of included history: Not found.
- Bulk historical data is ordered as a custom package via a form (https://dxfeed.com/order-historical-market-data/); price for an individual: Not found. Trial is two weeks; "You need to purchase an exchange license if you represent a company" (https://kb.dxfeed.com/en/faq.html).

**Terms for personal use**
- B2B terms (2024-02-02): "the Services shall be used solely for Customer's internal usage and not for third party (including its affiliates, consultants) access or use"; no selling, sublicensing or providing output to third parties (https://dxfeed.com/general-terms-and-conditions-for-services/).
- Retail Customer Services Agreement: "The Services shall be used solely for Customer's usage and not for third party access or use"; prohibits "downloading (other than to view only where a link is provided) ... electronically extracting or scrubbing" of data accessed via the services (https://get.dxfeed.com/api/files/The_Small_Exchange_Customer_Services_Agreement.pdf).
- CME non-professional: use "solely for the subscriber's personal or private use", own assets only, access "via a maximum of two trading terminals" (https://dxfeed-retail.zendesk.com/hc/en-us/articles/12291144852759-CME-Group-CME-CBOT-NYMEX-COMEX). Exchange terms list: https://dxfeed.com/3pty/.

**Third-party app with own account**
- Retail subscriptions are sold per supported platform (ATAS, Quantower, Bookmap, MotiveWave, NinjaTrader, Exocharts, Medved Trader, Overcharts, Volumetrica); "Don't see your platform in the list? Contact the dxFeed team and tell us the name of the platform" (https://choose.dxfeed.com/individuals/). REST limits table: "B2C usage of B2B service: not allowed" (https://kb.dxfeed.com/en/market-data-api/data-access-solutions/rest.html). Inference: a new desktop app cannot reuse a retail key; the app vendor must be onboarded as a dxFeed partner platform (B2B2C), which is dxFeed's "Market Data as a Service" model (https://choose.dxfeed.com/market-data-service/).

**Rate limits**
- REST: 100 data requests/min, 100 HTTP requests/min, 10 simultaneous connections, 10 WebSockets/min, 200,000-byte POST max (https://kb.dxfeed.com/en/market-data-api/data-access-solutions/rest.html). TickData: "Wait for a request to complete before sending the next one" (tick-data page). Candlewebservice 7-day window and 8000-candle cap (above).

**Changes in 2026**
- Not found on dxFeed pages (KB pages are undated). Third-party thread of 2026-01/03 confirms no back-adjustment of continuous futures.

**Not found**: CSV column layout of bulk extractions; historical-data pricing for individuals; how much history the retail "historical charting" includes; dxFeed-authored roll-rule documentation.

### IQFeed (DTN)

**Offers**
- "180 calendar days of tick history (includes pre-post market) with microsecond timestamps (if available from the exchange feed)"; 1-minute OHLCV "Eminis back to September 2005", "US Stock/Futures/Indexes back to May 2007"; daily/weekly/monthly OHLCVOI "US Futures as far back as 1959"; 500 simultaneous symbols (https://www.iqfeed.net/index.cfm?displayaction=data&section=services).
- History/Lookup commands: ticks HTX/HTD/HTT, intervals HIX/HID/HIT, daily HDX/HDT; historical fields: Time Stamp, Last, Last Size, Total Volume, Period Volume, Bid, Ask, TickID, Basis For Last, Trade Market Center, Trade Conditions, Trade Aggressor, Day Code, High, Low, Open, Close, Number of Trades, Open Interest; daily requests are split-adjusted, ticks and intervals are not (https://iqhelp.dtn.com/api/).
- Tick, volume and n-second bars in history; expired contracts retrievable (e.g. @ESM08); fundamentals include Contract Size, Contract Months, Minimum Tick Size, First Delivery Date, Open/Close Time (http://www.iqfeed.net/dev/).
- Continuous: "#" = front month (@ES#), "#C" = front-month back-adjusted history (@ES#C) (https://ws1.dtn.com/IQ/Guide/futures_cme.html); #C "back adjusted for rollover gaps" since 2010-07-26 (http://www.iqfeed.net/dev/). DTN's symbol guide gives a roll rule per root, e.g. E-mini Dow "Roll 5 trading days before expiration date" (https://ws1.dtn.com/IQ/Guide/futures_cbotmini.html); the ES/NQ/CL/GC guide pages were not retrieved. Third-party DTN rollover calendar: @ES# rolls end of day 2026-09-11, new front month 2026-09-14, expiry 2026-09-18 (https://www.linnsoft.com/support/rollover-calendar); third-party (2025-08-21): DTN's adjustment is the settlement-price difference of the two contracts on the roll date, applied to the whole series (https://www.linnsoft.com/support/continuous-futures-contracts).

**Delivery and format**
- Windows-only IQConnect.exe started with `-login -password -product -version`; apps talk to it over local TCP sockets; protocol 6.2 is current; "It is not a development library" (https://iqhelp.dtn.com/api/, http://www.iqfeed.net/dev/, https://iqhelp.dtn.com/wp-content/uploads/sites/6/2026/01/IQFeed-Users-Guide.pdf).
- Comma-delimited lines; interval rows "[YYYY-MM-DD HH:mm:SS],[OPEN],[LOW],[HIGH],[CLOSE],[VOLUME],[OPEN INTEREST]" (third-party: https://www.quantstart.com/articles/Downloading-Historical-Intraday-US-Equities-From-DTN-IQFeed-with-Python/); time zone Eastern (third-party client default America/New_York: https://rdrr.io/github/bwlewis/iqfeed/man/HIT.html).
- Bar label: the IQFeed `LabelAtBeginning` option is documented by a third-party wrapper as default 0, where "11:17:41 data is reported in ... '11:18'" bar, i.e. bars are labelled at the bar END unless LabelAtBeginning=1 (https://undocumentedmatlab.com/files/IQML/IQML.m). The official protocol page (http://www.iqfeed.net/dev/api/docs/HistoricalviaTCPIP.cfm) is behind the developer login.
- Market Summary files (EDS, FDS, 5MS) for a whole market/security type via the lookup port (https://iqhelp.dtn.com/api/).

**Cost** (price list "as of December 1st, 2025")
- Startup $50; Core $108.15/mo; RT US Futures and Futures Options surcharge $24.87/mo; exchange fees extra (https://iqhelp.dtn.com/core-service-fees/). CME $139.57, CME E-mini $78.58, CBOT $139.57, NYMEX $139.57, COMEX $139.57 per month, identical pro and non-pro (https://www.iqfeed.net/index.cfm?displayaction=data&section=fees).
- Inference: core + futures surcharge + CME E-mini = $211.60/mo; adding NYMEX (CL/MCL) and COMEX (GC/MGC) adds $279.14, i.e. $490.74/mo before tax.
- Non-Professional CME Group Globex package: needs a qualified 3rd-party application that can route orders to the broker, a funded account (the IB plugin checks for at least $500) and non-pro answers; pit data excluded (https://www.iqfeed.net/text/WaiverPluginInstructions.pdf). Its reduced price: Not found on DTN pages.
- Developer (API) licence: $597.00 per year, non-refundable, "exclusive of any fees for the IQfeed Service" (http://www.iqfeed.net/dev/index.cfm?section=register); iqhelp says "contact our Sales Department for API pricing" (https://iqhelp.dtn.com/api/); the 2019 FAQ listed $420 and a 20% discount for annual prepayment (https://www.dtn.com/wp-content/uploads/2019/05/IQFeed_FAQs.pdf).

**Terms for personal use**
- "you can only connect with your IQFeed user ID on one computer at a time" (https://www.dtn.com/wp-content/uploads/2019/05/IQFeed_FAQs.pdf); multiple connections are fine from the same machine (https://iqhelp.dtn.com/api/).
- Non-professional status is judged at registration (trading-company name/address/email, FINRA/SEC/CFTC registration) (https://iqhelp.dtn.com/core-service-fees/).
- Subscriber Agreement text: Not found online (it is referenced by the developer agreement).

**Third-party app with own account**
- Third-party apps with the customer's own login are the product model: "choose from any of the Compatible Software listed on our site or develop your own software after registering as a developer" (https://www.iqfeed.net/index.cfm?displayaction=data&section=services). The developer agreement covers "software for self-use or commercial distribution", licenses the spec "solely in the development of Developer's Software", requires that "the Developer must subscribe to and pay for the IQfeed Service", and requires a separate redistribution agreement only "when the data is redistributed by Developer" (https://iqfeed.net/dev/newagreement.cfm). Inference: the app vendor registers once ($597/yr), ships its product ID, and each user logs in with their own IQFeed credentials; no per-user approval.
- Third-party note: QuantConnect's docs say users without a developer account can log in through IQLink and "enter random numbers for the product id" (https://www.quantconnect.com/docs/v2/lean-cli/live-trading/data-providers/iqfeed).

**Rate limits**
- "You can make no more than 50 historical requests per second" (error "Too many simultaneous history requests"); during 9:30-16:00 ET tick requests return only the last 8 days, 180 days outside RTH; "no limits to how much data or how large a time range you can request" (https://iqhelp.dtn.com/api/).

**Changes in 2026**
- Client releases 6.2.3.4 (2026-03-26), 6.2.3.5 (2026-04-14), 6.2.4.2 (2026-08-14) (https://iqhelp.dtn.com/release-notes/, https://www.iqfeed.net/index.cfm?displayaction=support&section=download). Price list unchanged since 2025-12-01. Users Guide PDF dated 2026/01.

**Not found**: subscriber agreement text; DTN's own roll-rule lines for @ES#, @NQ#, QCL#, QGC#; an official statement on bar labelling and time zone (behind login); current non-pro Globex package price.

### Barchart (OnDemand API and Premier downloads)

**Offers**
- getHistory: "tick, minute bars or end-of-day"; types ticks, minutes, nearbyMinutes, formTMinutes, daily, dailyNearest, dailyContinue, weekly/monthly/quarterly/yearly (+Nearest/+Continue); `nearby` or `ES*1`/`ES*2` notation; `backAdjust` (roll-gap adjusted, default false); `volume` contract/total; `sessionFilter`; the example query also carries `daysToExpiration` and `contractRoll=expiration` (https://www.barchart.com/ondemand/api/getHistory).
- FAQ: "Records are limited to 1000 unless including maxRecords > 1000"; "If using the interval= parameter, data returned will not include the settlement/close price at the end of the market session"; Nearest = "closest unexpired contract ... every chart bar represents the front month at that point in history"; Continue = same delivery month chained (ZSX13, ZSX12, ...); getFuturesSpecifications gives trading hours, contract size, tick size, initial/maintenance margin; getFuturesByExchange EOD flag "s" = settled (https://www.barchart.com/ondemand/faq).
- Other futures endpoints: getFuturesByExchange, getFuturesOptions, getFuturesOptionsEOD, getFuturesSpreads, getRestrictedSessionHistory (https://www.barchart.com/ondemand/free-market-data-api). History depth per exchange: Not found.
- Premier (website): daily back to 01/01/2000, 1-minute "approximately 10 years", weekly/monthly/quarterly to 01/01/1980; max 20,000 records per download; 250 downloads/day (Plus 10, free 1); non-members see 2 years (https://www.barchart.com/membership-comparison, https://www.barchart.com/futures/quotes/ZCH26/price-history/historical). A help article says 10,000 records per request (https://help.barchart.com/support/solutions/articles/242748-how-can-i-download-historical-data-), conflicting with the 20,000 on the comparison page.

**Delivery and format**
- REST: `GET https://ondemand.websol.barchart.com/getHistory.json|.csv|.xml?apikey=...&symbol=...&type=minutes&interval=60&startDate=yyyymmdd[hhmm[ss]]`; dateTime fields "YYYY-MM-DD HH:MI:SS<TIMEZONE_OFFSET>" (https://www.barchart.com/ondemand/api/getHistory). Whether minute timestamps mark bar open or close: Not found.
- Premier: manual CSV from the Price History page or Interactive Chart (https://www.barchart.com/membership-comparison).

**Cost**
- OnDemand: "pricing is based on usage"; packages "small to enterprise"; no public price list; free trial "with limited requests" (https://www.barchart.com/ondemand, https://www.barchart.com/solutions/services/ondemand). The old free API host now answers HTTP 410 Gone (https://marketdata.websol.barchart.com/getHistory.json, checked 2026-10-12).
- Self-serve "Barchart Real-Time and Historical Market Data Service" form (ID=DEV): $149 / $199 / $249 per month by maximum simultaneous symbols, exchange fees extra, "CME Group Trading - Package" selectable, partial-month free trial once per 12 months (https://www.barchart.com/register/realtime/form.php?ID=DEV). What API or history it grants: Not found.
- Premier: $29.95/month, $239.95/year, $419.95/2 years, first 30 days free (https://www.barchart.com/membership-comparison); a help article still says $199.95/year (https://help.barchart.com/support/solutions/articles/242752-what-are-the-benefits-and-cost-of-a-premier-subscription-).
- Firms taking a feed pay CME exchange fees of $750/mo real-time, $375/mo delayed, $60/mo snapshot (https://www.barchart.com/solutions/exchange-fees).

**Terms for personal use**
- Site Terms (Last Updated February 3, 2026): "YOU AGREE NOT TO REPRODUCE, RETRANSMIT, DISSEMINATE, SELL, DISTRIBUTE, PUBLISH, BROADCAST OR CIRCULATE ANY OF THE BARCHART SERVICES OR CONTENT IN ANY MANNER OR FOR ANY PURPOSES (WHETHER PERSONAL OR BUSINESS) WITHOUT THE PRIOR EXPRESS WRITTEN CONSENT" (https://www.barchart.com/terms). CME rider on the same page: Information "is not used for any commercial purpose" and use "for any machine learning and/or artificial intelligence ... is expressly prohibited" (https://www.barchart.com/terms, https://www.barchart.com/solutions/legal/exchange-agreement).
- Web-service user agreement: a user may "store, manipulate, analyze, reformat, print and display information from Barchart only for such user's personal use"; never "publish, retransmit, redistribute" (https://useragreement.websol.barchart.com/).
- Master Terms (OnDemand clients): licence "only as described on the Order Form"; no redistribution or sale of a raw data stream; "Information and Services ... are to be used exclusively for the purposes described in the Order Form" (https://www.barchart.com/legal/media/pdfs/Barchart-Master-Terms-of-Service.pdf).
- CME uniform subscriber agreement: Market Data "only for its own internal business activities and only ... on the Devices designated by Subscriber" (https://www.barchart.com/solutions/legal/exchange-agreement).

**Third-party app with own account**
- OnDemand keys are issued per client under an Order Form and the retrieved terms do not mention third-party applications; obtaining a key means contacting sales (https://www.barchart.com/ondemand). Premier has no API; downloads are manual CSV; automated access by an app is not addressed in the Terms of Use text retrieved. Not found.

**Rate limits**: Not published on the getHistory page or FAQ.
**Changes in 2026**: Terms of Use revised 2026-02-03; free API host returns 410; Premier annual price shows $239.95 (older help article $199.95).
**Not found**: OnDemand price list and rate limits; history depth per exchange; bar-label convention; terms on third-party apps.

### Interactive Brokers (TWS API / Client Portal Web API)

**Offers**
- Bars 1 sec to 1 month; for futures whatToShow TRADES, MIDPOINT, BID, ASK, BID_ASK, SCHEDULE; historical Time and Sales via reqHistoricalTicks; "For futures, the close price of daily bars can be the settlement price if provided by the exchange"; a daily bar is dated by "the day on which the bar closes"; historical volume is filtered (no combos/blocks) (https://interactivebrokers.github.io/tws-api/historical_bars.html, https://interactivebrokers.github.io/tws-api/historical_data.html).
- Unavailable: "Bars whose size is 30 seconds or less older than six months"; "Expired futures data older than two years counting from the future's expiration date"; expired future spreads (https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/unavailable-historical-data.md). Expired contracts need `includeExpired` (https://www.interactivebrokers.com/campus/ibkr-quant-news/historical-options-futures-data-using-tws-api/, 2021-12-23).
- Continuous futures (CONTFUT) are supported; endDateTime "Must be left as an empty string when requesting continuous futures contracts" (https://www.interactivebrokers.com/docs/tws-api/sync-doc/historical-market-data.md). CONTFUT roll/adjustment rule: Not found. Earliest history for ES/NQ/CL/GC: Not found.
- Historical data "has the same market data subscription requirement as receiving streaming top-of-book live data" (https://interactivebrokers.github.io/tws-api/historical_data.html).

**Delivery and format**
- TWS API: TCP socket to the user's own TWS or IB Gateway; Python/Java/C++/C#/VB libraries (https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/). Bar time zone = the time zone chosen at TWS login (historical_bars.html); formatDate 1 = "UTC time in YYYYMMDD-hh:mm:ss format", 2 = epoch (https://www.interactivebrokers.com/docs/tws-api/protobuf/historical-data-request.md). Intraday bar label (open vs close): Not found.
- Web API `GET /iserver/marketdata/history?conid=&period=&bar=`: "maximum of 1000 data points"; bars o, c, h, l, v, t (t = epoch Unix timestamp); startTime "UTC formatted as YYYYMMDD-HH:mm:ss"; step sizes (period 1d: bars 1min-8h; 1y: 8h-1m; 15y: 1w-1m) (https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md). Retail users authenticate through the Client Portal Gateway; "All API Endpoint calls must be made on the same machine where the Client Portal Gateway was authenticated" (https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/limitations-of-the-client-portal-gateway.md).
- No bulk files.

**Cost**
- "CME Real-Time (L1)" non-pro USD 1.55/month per exchange, same for CBOT, NYMEX, COMEX; "(L2)" USD 12.10; professional "(L1, L2)" USD 145.00 per exchange; "US Securities Snapshot and Futures Value Bundle" USD 10.00/month "Includes top of book quotes for CBOT, CME, COMEX, and NYMEX", waived at USD 30 commissions; "US Futures Value Bundle PLUS" USD 5.00 adds depth; "Access to US Futures data requires clients to have US Futures Trading Permissions"; minimum equity USD 500 to subscribe (https://www.interactivebrokers.com/en/pricing/research-news-marketdata.php). Inference: no separate charge for historical data beyond the live subscription.

**Terms for personal use**
- Market data subscriber agreement (GFIS): for non-professionals "the Data is licensed only for personal use"; "Subscriber may access a Subscription through only one internet-connected computer or mobile device at a time"; Security Information must not be disclosed (https://gdcdyn.interactivebrokers.com/Universal/servlet/Registration_v2.formSampleView?formdb=4383).
- TWS API Non-Commercial License (IB text, third-party mirror): "intended only for users who wish to use the API Code ... for the development of their own internal proprietary tools to manage their own IB accounts"; "NOT for anybody who is developing software applications that they wish to: (a) sell to third party users for a fee, or (b) give to third party users to generate an indirect financial benefit" - such vendors must contact IB (https://github.com/deepentropy/ibapi/blob/main/LICENSE). Download page: using the TWS API "to disseminate information is strictly prohibited without prior written approval" (https://download2.interactivebrokers.com/installers/tws-api/index.html).

**Third-party app with own account**
- IB documents third-party platforms (NinjaTrader, MultiCharts) connecting to the customer's own TWS on 127.0.0.1 port 7496/7497 with any clientId; "Connections via the TWS API are not aware of the user name with which you are logged in"; IB offers no support for third-party software; vendors are listed in the Investors' Marketplace (https://interactivebrokers.github.io/tws-api/third_party.html, https://www.interactivebrokers.com/campus/ibkr-api-page/third-party-connections/).
- Web API: "For retail and individual clients, Authentication to our WebAPI is managed using the Client Portal Gateway"; third-party vendors "must receive Compliance approval", "may currently only seek approval for the use of OAuth1.0a", need "an established business entity and a public presence online", with onboarding of roughly 2-3 + 3-6 + 3-5 weeks (https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/, https://www.interactivebrokers.com/docs/web-api/trading/getting-started/trading-access-for-third-parties.md).
- Inference: a desktop app on the client's machine talking to the client's own TWS/Gateway (or CP Gateway) is the documented pattern and needs no vendor approval; selling that app for a fee falls outside the non-commercial API licence and needs IB's consent.

**Rate limits**
- TWS: max 50 open historical requests; for bars of 30 s or less: no identical request within 15 s, no 6+ requests for the same contract/exchange/tick type within 2 s, no more than 60 requests per 10 minutes, BID_ASK counts twice; limits "lifted" for bars of 1 min and up but a "soft" throttle can lead to disconnect; step-size table (https://interactivebrokers.github.io/tws-api/historical_limitations.html).
- Web API: history endpoint 10 req/s and 50 req/min (429 beyond), 5 concurrent requests; global 10 req/s per session (https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md, https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/).

**Changes in 2026**
- 2026-09-09 Web API changelog: history pacing "now capped at 10 requests per second or 50 requests per minute"; /hmds/scanner deprecated (https://www.interactivebrokers.com/docs/web-api/changelog/2026/9/9.md). TWS API 10.51.01 released 2026-09-29, stable 10.50.02 2026-09-09 (https://download2.interactivebrokers.com/installers/tws-api/index.html). OAuth 2.0 (beta) for first- and third-party access (web-api-trading page).

**Not found**: earliest available history per contract; CONTFUT roll rule; intraday bar-label convention; historical tick depth limit.

### CME DataMine

**Offers**
- Datasets: Market by order (MBO), Market depth, Top-of-book (BBO), Time & sales, End-of-day, Block trades, Volume & open interest, third-party data; "more than 450 terabytes of historical market data, some spanning back to the 1970s" (https://www.cmegroup.com/education/files/cme-datamine-overview.pdf); "Earliest Dataset 1972", 50+ datasets, 5,000+ products (https://www.cmegroup.com/market-data/datamine-historical-data.html).
- Top of Book: top bid/ask with sizes, last trade, volume, timestamp for all Globex products; a purchase also includes the Time and Sales and SecDef files; CME electronic from 11/1/2004, CBOT 1/14/2008, NYMEX and COMEX 12/1/1999; ASCII 1999-2025 with a new CSV format from 2025-04-14; three dates missing (https://www.cmegroup.com/confluence/display/EPICSANDBOX/Top+of+Book+-+BBO, updated 2025-09-03).
- Time and Sales: "official record of trade times and prices", quantities for electronic trades; CME pit from 1/4/1982, CME electronic 6/26/1992, CBOT electronic 11/23/2003, NYMEX/COMEX 12/1/1999 (https://www.cmegroup.com/confluence/display/EPICSANDBOX/Time+and+Sales, updated 2025-09-03).
- Market Depth: built from MDP FIX/FAST feeds, 5-10 levels for futures; timestamp granularity differs from BBO/T&S; subscription files kept in the FTP directory for two weeks (https://www.cmegroup.com/market-data/files/cme-group-market-depth-faq.pdf). Formats: MDP 3.0 (current), legacy FIX/FAST 3/2/2009-2016, RLC (https://www.cmegroup.com/confluence/display/EPICSANDBOX/CME+DataMine+Post-Purchase+Information, updated 2025-06-10).
- Individual instruments only; SecDef files give instrument definitions (post-purchase page). Inference: no continuous series are sold.

**Delivery and format**
- Delivery: RESTful download API (CME Group Login + API ID, basic auth), SFTP, automatic S3; list call returns up to 1000 files per page; file ids like `20160107-bbo_xcme_sp_fut_0-rth`; gzip CSV (post-purchase page). Marketing page adds a File Browser (https://www.cmegroup.com/market-data/datamine-historical-data.html).
- Time and Sales CSV v2 (from 2022-08-22): Transaction_Date YYYY-MM-DD; Transaction_Time "YYYY-MM-DDTHH:MM:SS:#########" to the nanosecond, ISO 8601 UTC, e.g. 2025-02-26T23:10:25.833993999Z; Sequence_Number, Ticker_Symbol (ES), Instrument_Symbol (ESH5), Security_ID, FUT/OPT, Delivery_Date YYYYMM, Market_Data_Report_Type TRD/VOL, Trade_Price_Formatted, Trade_Price_Decimal, Trade_Quantity, Vol_Quantity, Trade_Aggressor B/A, Close_Open_Type, User_Defined, Exchange_Code; legacy files have no header row and HHMMSS times (Time and Sales page).
- Top of Book CSV: Transaction_Time nanosecond UTC, Ask/Bid_Level_1_Price (clearing and formatted), quantities, order counts, Market_Data_Report_Type OBS/TRD/VOL, Implied_Book_Indicator, Exchange (https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457418968/Top%2Bof%2BBook%2B-%2BBBO).
- Settlements/OI: "End of Market Summary - Standard" and "Volume and Open Interest" datasets (post-purchase page). Their layouts: Not retrieved.

**Cost**
- Prices are quoted inside the portal ("Get price quotes online", "Simplified pricing structure") (overview PDF). Public price list: Not found. 2026 notice: CME/CBOT/NYMEX/COMEX information fees "will increase by up to 3.5%" from 2026-01-01; "Annual CME DataMine subscription Fees will be effective at your CME DataMine subscription renewal in 2026 and can be found in the CME DataMine product catalog" (https://www.cmegroup.com/market-data/files/2026-market-data-fee-notice-august-14-2025.pdf).
- Older CME FAQ (2018, third-party mirror): "Pricing varies based upon data type and duration of the data request"; purchase online by credit card (https://pdf4pro.com/view/cme-historical-data-faq-487bf8.html).
- For context (display, not DataMine): 2026 fee list, non-pro top-of-book $1.55 per exchange or $4.65 bundle, depth $12.10 or $36.50 (mirror: https://api.databento.com/static/licensing/cme/cme-market-data-fee-list.pdf).

**Terms for personal use**
- Ordering: add a licence option (e.g. "Complete History") to the cart, fill "Licensee Details" and Primary/Technical/Legal "Company Contacts", a usage questionnaire (Derived, Distributed, Display Devices, Non-viewable), sign by click-through or DocuSign, then "The agreement is submitted to CME Group for data licensing review" (https://www.cmegroup.com/tools-information/webhelp/data-services-portal/Content/Ordering-CME-Datamine-Products.html).
- Information License Agreement (June 2026): "Historical Information: ... first accessed at least eight (8) hours after initial transmission"; licence to "use the Information as permitted in the Schedules" and "create limited derivative works ... solely for its internal business purposes", disclosed internally only; no "license, sublicense, transfer, sell, resell, publish, reproduce, or otherwise distribute"; "Licensee Group shall not carry out text and data mining as those terms are defined in EU Directive 2019/790" (https://www.cmegroup.com/market-data/files/information-license-agreement-june-2026.pdf).
- CME advertises an "Individual License" path (https://www.cmegroup.com/market-data/connect-data.html). Policy FAQ (Jan 2025): "Non-Display Use of Historical Information must be licensed, but is not reportable and carries no fees at this time"; non-professionals license through their data provider (https://www.cmegroup.com/market-data/distributor/files/cme-group-data-licensing-policy-guidelines-and-non-display-licensing-faq.pdf).

**Third-party app with own account**
- Access is by the licensee's own CME Group Login and API ID (post-purchase page); the ILA licenses the Licensee Group for internal purposes. Nothing found that permits or forbids a third-party desktop application on the licensee's machine using the licensee's API ID. Not found.

**Rate limits**: list API 1000 results per page with paging (post-purchase page). Download pacing: Not found.
**Changes in 2026**: ILA version June 2026; fees up to +3.5% for 2026; a "January 2027 Market Data Fee List" is already posted (https://www.cmegroup.com/market-data/license-data/market-data-policy-education-center.html); CSV v2 formats since 2025.
**Not found**: public price list; an explicit statement that individuals (not companies) may buy; EOD layout.

### Norgate Data (futures package, daily only) and other cheap daily sources

**Offers**
- "around 100 Futures markets drawn from 11 worldwide exchanges"; history "back to around 1980 or to the first day of trading"; "the Close price in the data is the official settlement price (and not the last-traded price)"; individual contracts plus spot-month continuous contracts "unadjusted and back-adjusted", back-adjustment "calculated arithmetically"; roll for cash-settled contracts "on the business day prior to the last day of trading", for deliverable contracts "on the business day prior to First Notice Day"; lightly traded months skipped (https://norgatedata.com/futurespackage.php).
- Coverage: ES from 9 Sep 1997, NQ 12 Jul 1999, MES and MNQ 6 May 2019, CL 30 Mar 1983, GC 30 Oct 1979; "Continuous contracts are also provided for each market"; continuous Volume and Open Interest are "for the total market" (https://norgatedata.com/data-content-tables.php). MCL and MGC rows: Not found in the retrieved table.
- Daily only: "We do not provide live quotes, delayed quotes, intra-day or 'tick' data" (https://norgatedata.com/). Contract specs (point value, tick size, margin, first notice date) ship with the package; symbols ES-2025M (contract), &ES (unadjusted continuous), &ES_CCB (back-adjusted) (third-party, 2026-04-29: https://concretumgroup.com/futures-database-in-python-complete-pipeline-norgate-data/).

**Delivery and format**
- Windows-only Norgate Data Updater (NDU) keeps a local database; access via supported platform plugins, the free `norgatedata` Python package (pandas/numpy, needs NDU running), or export of daily price data to ASCII/MetaStock formats (https://norgatedata.com/subscribe/subscribe.php, https://pypi.org/project/norgatedata/1.0.45/, https://norgatedata.com/ndu-installation.php). Timestamps are trading dates. ASCII export column layout: Not found.

**Cost**
- Futures package USD 148.50 per 6 months or USD 270 per 12 months (https://norgatedata.com/futurespackage.php); no monthly term, no cancellation, no auto-renew (https://norgatedata.com/). Three-week free trial (Norgate's CIO on Elite Trader: https://www.elitetrader.com/et/threads/norgate-data-data-for-systematic-trading-analysis-survivorship-bias-free-backtesting-charting.364830/).

**Terms for personal use**
- EULA (version 20261002): "Licensee" means one individual natural person; may "install and use the Software on two computers"; Content is for "Personal Use" (own non-commercial trading, research, backtesting); may "export, extract, copy, transmit, store and process Content in any Processing Environment for Personal Use" and "use third-party software, computing, storage, hosting or analysis services to process the Content on the Licensee's behalf"; no commercial or professional use; no disclosure of login details; exported Content must be deleted when the subscription expires (https://norgatedata.com/subscribe/eula.php). FAQ: "our data service can only be licensed for personal use by individuals"; additional NDU installs are paid (https://norgatedata.com/faq.php).

**Third-party app with own account**
- The EULA expressly allows third-party software to process the data for the subscriber's own use (clause 2(iv)), but "Do you have a generic API that I can use for my own application? No. APIs are only provided specifically for applications where external users subscribe to Norgate Data" (https://norgatedata.com/faq.php); app developers building "a Windows-based charting/analysis app for widespread use" are asked to contact Norgate (Elite Trader thread above). Inference: a desktop app can read the user's ASCII exports or call the norgatedata package locally today; a built-in integration needs Norgate's agreement.

**Rate limits**: not applicable (local database).
**Changes in 2026**: EULA re-issued 2026-10-02 with explicit "Processing Environment" rights (other machines, Mac/Linux, cloud) (https://norgatedata.com/subscribe/eula.php); FAQ rewritten to match (https://norgatedata.com/faq.php).

**Other free or cheap daily sources**
- Stooq: free continuous "S&P 500 E-Mini" ES.F, last 7878.00 on 2026-10-12; "Changes series" roll dates 2026-09-14 [Dec 2026], 2026-06-15 [Sep 2026] (https://stooq.com/q/?s=es.f). Inference: it rolls on the Monday of expiry week and shows no adjustment. Daily CSV endpoint `/q/d/l/?s=es.f&i=d` with columns Date,Open,High,Low,Close,Volume, an unpublished daily hit limit, and an on-site API key required since early 2026 (third-party: https://github.com/api-evangelist/stooq). Terms: "Redistribution of data found on the website is not allowed without the consent of Stooq" (https://stooq.com/terms.html). The bulk ASCII database covers stocks, indices, FX, bonds and crypto, no CME futures folder (https://stooq.com/db/h/).
- Nasdaq Data Link CHRIS: the page still says "Free", history "Jul 1959", "600+ contracts" (https://data.nasdaq.com/data/CHRIS-wiki-continuous-futures), but Nasdaq support told users in 2024 "the CHRIS database has been deprecated and is no longer updated" and the API returns 410 (third-party: https://github.com/PacktPublishing/Python-for-Algorithmic-Trading-Cookbook/issues/5, 2024-09-20; https://quant.stackexchange.com/questions/82282/commodity-futures-data-from-nasdaq-former-quandl); the free CME EOD database was deprecated in 2022 (https://stackoverflow.com/questions/72981020/did-quandl-end-cme-data-on-june-30th-2022). Status: dead.
- Yahoo Finance: ES=F is "E-Mini S&P 500 Dec 26", "CME - Delayed Quote" (https://finance.yahoo.com/quote/ES=F/history/); =F symbols are continuous front-month series (third-party, IBKR Campus 2022-07-28: https://www.interactivebrokers.com/campus/ibkr-quant-news/download-futures-data-with-yahoo-finance-library-in-python/). Terms: no data collection "using any automated means, devices, programs, algorithms or methodologies, including but not limited to robots, spiders, scrapers" without permission; no use "to create any database, archive, mobile application, data feed, widget or any other aggregated data source that competes with" Yahoo or its data providers; "you may not access or reuse the Services, or any portion thereof, for any commercial purpose"; no redistribution (https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html). yfinance: "not affiliated, endorsed, or vetted by Yahoo ... the Yahoo! finance API is intended for personal use only" (https://github.com/ranaroussi/yfinance). History start for ES=F: Not found (page defaults to a one-year range).

### Summary table

| Source | Ticks | Bars | Definitions/settlements | History from | Price for an individual | Personal-use terms | Third-party app with own key |
|---|---|---|---|---|---|---|---|
| dxFeed | Yes: REST TickData (quotes, trades, depth) | tick/sec/min/hour/day candles; retail depth 43-285 days intraday, all history daily; 7-day window per call | Profile events / IPF; Summary with settlement and OI | 2009/2010 by market, TickData from 2014 | $19/mo CME L1, $99/mo depth via a partner platform; bulk history by quote | internal/own use only; retail agreement bars extraction; max two terminals | No: retail keys are per approved platform; an app vendor must partner (B2B2C) |
| IQFeed | 180 days, microsecond stamps | 1-min from 2005 (eminis)/2007; n-sec, tick, volume bars; daily OHLCVOI from 1959 | fundamentals (size, tick, months, FND, hours); settlement and OI fields; @ES# / @ES#C continuous | 1959 daily, 2005 1-min, 180 days ticks | $50 setup + $108.15 + $24.87 + CME E-mini $78.58 (+$139.57 per other exchange); dev licence $597/yr | one computer at a time; non-pro rules; data for own use | Yes, by design: vendor registers as developer (product ID), user logs in with own credentials |
| Barchart OnDemand / Premier | OnDemand ticks (depth not stated) | OnDemand minute/daily (+nearest/continuous, back-adjust); Premier 1-min ~10 yrs, daily from 2000, 20,000 rows per file | getFuturesSpecifications; settlement only in daily data | 2000 daily, 1980 weekly (Premier); OnDemand depth not published | OnDemand: no public price (DEV form $149-249/mo + exchange fees); Premier $29.95/mo or $239.95/yr | personal use, no redistribution, "not used for any commercial purpose", no AI/ML use | OnDemand: per Order Form, not addressed; Premier: no API, manual CSV only |
| Interactive Brokers | historical ticks via API (depth limit not stated) | 1 s to 1 month; bars <=30 s only 6 months; expired futures 2 years; CONTFUT | contract details via API; daily close may be settlement | not documented | $1.55/mo per CME exchange non-pro (or $10 bundle, waivable); $500 minimum equity; no history fee | personal use; one device at a time; API licence non-commercial | Yes on the client's own machine via TWS/Gateway or CP Gateway; selling the app needs IB consent; Web API OAuth needs Compliance approval |
| CME DataMine | Yes: T&S from 1982, BBO from 1999/2004/2008, MBO/MBP depth from 2009 | none (EOD files only) | SecDef files; End-of-Day settlement and Volume/OI datasets | 1982 T&S, 1999-2008 BBO, 2009 depth | quoted in portal only; fees +3.5% in 2026 | ILA: internal business purposes, no redistribution, no text/data mining; licence review per order | Not addressed in the ILA |
| Norgate (futures) | No | daily OHLCV+OI only; individual and continuous (&ES, &ES_CCB) | contract specs, settlement close, OI; roll rules published | ~1980 (ES 1997, NQ 1999, MES/MNQ 2019, CL 1983, GC 1979) | USD 270/yr or 148.50/6 months | personal use by one individual, 2 PCs, process anywhere, delete on expiry | own processing allowed; no generic API; packaged integration only by agreement |
| Stooq / CHRIS / Yahoo | No | daily (Stooq also hourly/5-min for some markets) | none | Stooq: Not found; CHRIS 1959 but dead; Yahoo: Not found | free | Stooq: no redistribution; Yahoo: personal, non-commercial, no scraping | Stooq: not addressed; CHRIS: dead; Yahoo: automated access prohibited |

## Part C — Crypto archives, libraries, and paid aggregators

Scope: web reads only (docs, terms, directory listings, S3/exchangeInfo metadata); no market-data archives were downloaded. Every fact carries its source link; "Inference:" marks my own reasoning; "Not found" means searched but not located. Dates in brackets are page dates where visible.

### Binance public data archive (data.binance.vision)

**Offers**
- Spot archive data types: `aggTrades`, `klines`, `trades` (daily and monthly) (S3 listing https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/spot/daily/). USD-M futures (`futures/um`) daily: `aggTrades, bookDepth, bookTicker, indexPriceKlines, klines, markPriceKlines, metrics, premiumIndexKlines, trades`; monthly: `aggTrades, bookTicker, fundingRate, indexPriceKlines, klines, markPriceKlines, premiumIndexKlines, trades` (listing ...prefix=data/futures/um/daily/ and ...prefix=data/futures/um/monthly/). Open interest lives in `metrics` (daily only); funding in `fundingRate` (monthly only).
- History: spot BTCUSDT and ETHUSDT 1m monthly files start `2017-08` (daily `2017-08-17`) (listing ...prefix=data/spot/monthly/klines/BTCUSDT/1m/ ; ...ETHUSDT/1m/ ; ...prefix=data/spot/daily/klines/BTCUSDT/1m/); UM BTCUSDT/ETHUSDT klines and markPriceKlines from `2020-01`, `fundingRate` from `2020-01`, `metrics` from `2020-09-01` (listings ...prefix=data/futures/um/monthly/klines/BTCUSDT/1m/ , .../fundingRate/BTCUSDT/ , ...prefix=data/futures/um/daily/metrics/BTCUSDT/).
- Cadence: "new daily data becoming available the next day and new monthly data at the first monday of the month"; intervals `1s,1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1mo` ("1mo is used instead of 1M") (https://github.com/binance/binance-public-data README).
- REST for backfill: public market data host `https://data-api.binance.vision`; `/api/v3/klines` limit default 500, max 1000; `aggTrades`/`historicalTrades` max 1000; timestamps ms by default, header `X-MBX-TIME-UNIT: MICROSECOND` switches to µs (https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md). Live limits from exchangeInfo on 2026-10-12: spot `REQUEST_WEIGHT 6000/min`, `RAW_REQUESTS 300000/5min` (https://data-api.binance.vision/api/v3/exchangeInfo?symbol=BTCUSDT); USD-M `REQUEST_WEIGHT 2400/min` (https://fapi.binance.com/fapi/v1/exchangeInfo). 429 then 418 IP bans of 2 min to 3 days; limits are per IP (rest-api.md above).

**Delivery and file layout**
- URL pattern: `https://data.binance.vision/data/spot/{daily|monthly}/klines/<SYMBOL>/<interval>/<SYMBOL>-<interval>-<YYYY-MM[-DD]>.zip` (README example `data/spot/monthly/klines/ADABKRW/1h/ADABKRW-1h-2020-08.zip`); futures `data/futures/um/{daily|monthly}/<type>/<SYMBOL>/...`; observed names `BTCUSDT-trades-2017-08.zip`, `BTCUSDT-aggTrades-2017-08.zip`, `BTCUSDT-fundingRate-2020-01.zip`, `BTCUSDT-metrics-2020-09-01.zip`, `markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip` (listings above). Each zip holds one CSV named like the zip, e.g. `BTCUSDT-1h-2023-10-27.csv` (https://github.com/binance/binance-public-data/issues/283).
- Kline columns (spot and UM futures, same order): `Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore` (README). Spot `trades`: `trade Id, price, qty, quoteQty, time, isBuyerMaker, isBestMatch`; UM `trades`: same without `isBestMatch`; spot `aggTrades`: `Aggregate tradeId, Price, Quantity, First tradeId, Last tradeId, Timestamp, Was the buyer the maker, Was the trade the best price match`; UM `aggTrades` drops the last column (README).
- Header row: spot kline CSVs have NO header; futures kline CSVs have header `open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore`; maintainer: "There is difference between spot and futures data, please handle them accordingly" (issue #283, 2023-11-01). Futures files before about May 2022 lack the header and backfilled older files may have it ("the header row is added after that date, earlier files don't contain the header") (https://github.com/binance/binance-public-data/issues/246, 2023-06). Inference: an importer must sniff the first line of every file.
- Timestamp unit: "The timestamp for SPOT Data from January 1st 2025 onwards will be in microseconds" — confirmed; README spot example `1735689600000000 ... 1735693199999999` (µs) versus futures example `1499040000000 ... 1499644799999` (ms) (README). Inference: spot files before 2025-01-01 and all futures files are milliseconds.
- Open time marks the bar start; close time is the last unit before the next bar (spot 1h example `1735689600000000` to `1735693199999999`), i.e. inclusive end (README example; Inference on inclusivity).
- `metrics` CSV columns (from a user report, not README): `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`, 5-minute rows, 288 per day (https://github.com/binance/binance-public-data/issues/491). `fundingRate` CSV columns: Not found in README.
- Checksums: every zip has `<file>.zip.CHECKSUM`; verify with `sha256sum -c BNBUSDT-1m-2021-01.zip.CHECKSUM` (macOS `shasum -a 256 -c`) (README). Archived files can be replaced later; README keeps an "Updates" changelog (2022-04-21, 2022-08-08) (README).
- Archive-host rate limit: Not found (terms only say abide by "posted rate limits"); an open issue asks whether anonymous S3 `ListObjects` is an approved method, unanswered (https://github.com/binance/binance-public-data/issues/511, 2026-10-09).

**Cost**
- Free: "Binance grants any individual or legal entity ... access to the Datasets free of charge" (clause 2.3, https://data.binance.vision/Binance_Vision-Terms_of_Use.pdf).

**Terms for personal use**
- "BINANCE VISION DATASET TERMS, Version 1.0, Last Updated: August 26, 2026", issued by NEST EXCHANGE LIMITED (ADGM) (1.3); scope "made available through www.data.binance.vision and associated endpoints" (2.1); licence "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International" (3.1); you are bound "upon downloading, caching, querying, or otherwise utilizing the Datasets" (3.2); "Commercial licensing is strictly excluded ... requires a separate, written enterprise data license agreement" (3.4) (PDF linked from https://data.binance.vision/terms-of-use.html).
- Permitted (4.1): "academic research, non-monetized open educational projects, algorithmic historical backtesting for purely personal non-production research, and non-commercial open-source data science evaluations". Prohibited: "live proprietary trading execution, automated commercial order generation, or signal distribution to third parties for direct or indirect compensation" (4.2); "license, sub-license, sell, rent, lease, host, or commercially exploit the Datasets or any derivative real-time or historical data feeds" (4.3); integration into "commercial financial products, hedge fund management tools, paid subscription newsletters, or commercial trading bot platforms" (4.4); redistributed derivatives must credit "Binance Vision" and stay CC BY-NC-SA 4.0 (4.5); no scraping routines "designed to circumvent rate restrictions" (7.2); IP bans for breaches (7.3); amendments are prospective and "do not affect your rights to Datasets already downloaded" (1.4) (same PDF).
- Repository code is MIT; the README now links the terms (PR merged 2026-09-30, https://github.com/binance/binance-public-data/pull/506). Users asking whether personal backtesting that leads to live trading of one's own money is allowed, and where to get the enterprise licence, have no official reply as of 2026-10-11 (https://github.com/binance/binance-public-data/issues/502, /issues/514).

**Third-party app**
- No clause addresses a desktop tool downloading on the user's behalf; the only software clauses are 7.2 (no rate-limit circumvention) and 8.2/8.3 (no implying Binance endorsement; no use of the "Binance"/"Binance Vision" names to market "consumer-facing software") (PDF above). Inference: a user running a local app for personal, non-production backtesting sits inside 4.1; a paid app that ships or hosts the data trips 4.3/4.4.
- Binance.com API-key terms and Terms of Use are rendered client-side and could not be fetched (https://www.binance.com/en/terms returned only footer; same finding in https://cryptomarkets.tools/guides/exchange-api-terms). Not found: official text on third-party API clients.

**Geographic restrictions**
- Binance.com: current ToS text Not found (JS page). Secondary: Binance email to users said that under its Terms "Binance is unable to service U.S. persons" and pointed to Binance.US, with 14 days to withdraw (https://www.theblock.co/post/85589/binance-blocking-us-users-14-day-deadline-new-email, 2020-11); "In 2019, the company updated its terms of service to explicitly prohibit US persons ... uses geofencing" (https://legalclarity.org/is-binance-legal-in-the-us-state-bans-and-federal-cases/, 2026-06-18). US alternative is Binance.US with state exclusions (https://support.binance.us/hc/en-us/articles/360046786914-List-of-unsupported-states).
- The archive and `data-api.binance.vision` answered anonymous requests from this machine on 2026-10-12 (listings above); any geo-block on those hosts: Not found.

**Changes in 2026**
- Vision Dataset Terms v1.0 dated 2026-08-26 (PDF above); README terms link 2026-09-30 (PR #506).
- UM `metrics` `create_time` silently changed from end-of-period to start-of-period labels at 2026-06-25 00:00 UTC, duplicating the `2026-06-25 00:00:00` row across two daily files (user report, https://github.com/binance/binance-public-data/issues/491, 2026-08-24; no official reply).
- Spot µs timestamps since 2025-01-01 (README; not a 2026 change).

**Not found**
- Archive-host rate limits; `fundingRate` column spec; official Binance.com ToS/API terms text; any statement whether the archive host is geo-blocked.

### Bybit public archive (public.bybit.com)

**Offers**
- Root directories: `kline_for_metatrader4/`, `premium_index/`, `spot_index/`, `trading/`, `spot/` (https://public.bybit.com/). `trading/` = derivatives trade prints per symbol (USDT, PERP, USD inverse, dated futures) (https://public.bybit.com/trading/); `spot/` = spot trade prints (https://public.bybit.com/spot/).
- History: `trading/BTCUSD` from `2019-10-01`, `trading/BTCUSDT` from `2020-03-25`, `trading/ETHUSDT` from `2020-10-21`, latest file `2026-10-11` on 2026-10-12 (https://public.bybit.com/trading/BTCUSD/ , .../BTCUSDT/ , .../ETHUSDT/); `spot/BTCUSDT` and `spot/ETHUSDT` monthly from `2022-11`, daily from `2022-11-10` to `2026-10-11` (https://public.bybit.com/spot/BTCUSDT/ , .../ETHUSDT/).
- Klines: only `kline_for_metatrader4/<SYMBOL>/<YYYY>/` for 23 symbols, 15- and 60-minute files, years 2020 to 2024 only (https://public.bybit.com/kline_for_metatrader4/ , .../BTCUSDT/ , .../BTCUSDT/2024/). `premium_index/` and `spot_index/BTCUSD/` listings were empty (https://public.bybit.com/premium_index/ , https://public.bybit.com/spot_index/BTCUSD/). Funding-rate or open-interest archive files: Not found on the host.
- Bybit's own download page is JS-rendered ("Data products") (https://www.bybit.com/derivatives/en/history-data); a third-party downloader describes the two datasets as "Public Trading History" (public.bybit.com) and "OrderBook" (`quote-saver.bycsi.com/orderbook/{spot|linear|inverse}`, daily `.data.zip` JSONL snapshots/deltas) (https://github.com/Anton495/bybit-data-downloader, 2026-04).
- REST backfill: `GET /v5/market/kline`, `category` spot/linear/inverse, intervals `1,3,5,15,30,60,120,240,360,720,D,W,M`, `start`/`end` in ms, `limit` 1 to 1000 (default 200), rows `[startTime(ms), open, high, low, close, volume, turnover]` sorted newest first; "closePrice ... Is the last traded price when the candle is not closed" (https://bybit-exchange.github.io/docs/v5/market/kline). IP limit "600 requests within a 5-second window per IP"; on "403, access too frequent" stop and wait at least 10 minutes (https://bybit-exchange.github.io/docs/v5/rate-limit).

**Delivery and file layout**
- Derivatives: `https://public.bybit.com/trading/<SYMBOL>/<SYMBOL><YYYY-MM-DD>.csv.gz` (no separator between symbol and date); spot daily `https://public.bybit.com/spot/<SYMBOL>/<SYMBOL>_<YYYY-MM-DD>.csv.gz` and spot monthly `<SYMBOL>-<YYYY-MM>.csv.gz` (listings above). MT4 klines `<SYMBOL>_<15|60>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv.gz` per month (https://public.bybit.com/kline_for_metatrader4/BTCUSDT/2024/).
- Columns (third-party, no official spec found): contract files `timestamp, symbol, side, size, price, tickDirection, trdMatchID, grossValue, homeNotional, foreignNotional`; spot files `id, timestamp, price, volume, side` (https://github.com/Quantweb3-com/bybit-data-dump). Newer files add an `RPI` (contract) / `rpi` (spot) column; "RPI column is absent in older files (2020). Detected from CSV header" (https://raw.githubusercontent.com/Anton495/bybit-data-downloader/main/bybit_futures_trades.py , .../bybit_spot_trades.py).
- Header row: present (the parsers above read the first line as a header and look for `RPI` in it). Timestamp unit: contract `timestamp` is parsed as Float64 seconds and multiplied by 1,000,000 to get microseconds (bybit_futures_trades.py lines 93 and 297-299); spot `timestamp` is parsed as Int64 (bybit_spot_trades.py line 103), unit not stated. Inference: spot timestamps are integer milliseconds; verify on first file.
- Checksum files: Not found (none in listings). MT4 kline column order: Not found.

**Cost**
- Free, anonymous HTTP (listings above).

**Terms for personal use**
- Archive licence on public.bybit.com: Not found (host serves bare directory listings).
- API Terms & Conditions (help-centre copy "Last updated on 2024-11-14"): "Service Data means any data, or information within the dataset and content that is given by using the API"; you "shall not commercially exploit the APIs"; "shall not ... repackage or resell the services, or any part thereof, API or Service Data"; "may not use or access the API ... to monitor the availability, performance, or functionality ... or for any similar benchmarking purposes" (https://www.bybitglobal.com/en/help-center/article/API-Terms). A third-party review cites a newer version dated 2026-01-16 with numbered clauses 6.7/6.9 on the same points (https://github.com/arhancanli/alphac/pull/75; https://cryptomarkets.tools/guides/exchange-api-terms) — that PDF: Not found.
- General Terms & Conditions, "Last Updated: 23 January 2026" (Bybit Virtual Asset Platform Operator L.L.C. S.P.C) (https://www.bybit.com/common-static/compliance/legal/BYBIT/b2e1c94c53ee5e12e165919de919337e.pdf).

**Third-party app**
- The API terms explicitly contemplate third-party clients: "API Client means any software, applications, websites or systems that accesses and Use the APIs on your behalf"; "An API Client that uses your API Key can operate the API to give user instructions. When you do so, you are authorising that API Client"; "Giving away your API Key is akin to giving away your login credentials"; "you remain liable for any act or omissions of any third-party or API Client that you have authorized" (API-Terms page above). Inference: a local desktop app holding the user's own key is an "API Client" the user authorises; the no-resale/no-benchmarking clauses bind the app's use of Service Data.

**Geographic restrictions**
- Clause 3.4: "We also do not offer Services or products to Users in a few excluded jurisdictions including the United States, the Chinese Mainland, Hong Kong, Singapore, Canada, France, the United Kingdom, Dubai, North Korea, Cuba, Iran, Uzbekistan, Russian-controlled regions of Ukraine ..., Sevastopol, Sudan, Syria ... (the Excluded Jurisdictions)" (General T&C PDF above, 2026-01-23). The archive host answered anonymous requests from this machine on 2026-10-12; any geo-block on public.bybit.com: Not found.

**Changes in 2026**
- General T&C revised 2026-01-23 (PDF above); API terms reportedly revised 2026-01-16 (third-party, above). Spot monthly files stop at `2026-07` while daily files run to `2026-10-11` (listing, 2026-10-12) — Inference: monthly files lag by about three months.

**Not found**
- Official column/timestamp spec, checksums, archive licence, funding/OI archive, Bybit 2026 API-terms PDF.

### OKX historical data download portal

**Offers**
- Five datasets (page https://www.okx.com/historical-data, "Spots and Contracts market data"): Trade history "Tick-level trading history from September 2021 onwards"; Candlestick "OHLC chart history from July 2023 onwards"; Funding rate "Historical perpetual funding rates from March 2022 onwards"; Order book "High-resolution L2 data from March 2023 onwards"; Borrowing rate "from December 2021 onwards". Open-interest and mark/index-price files: Not found on the page.
- REST backfill (official per-endpoint figures could not be extracted from the single-page docs, which only say "The rate limit is different for each endpoint ... error code 50011" (https://www.okx.com/docs-v5/en/)): third-party summaries state `/api/v5/market/candles` returns only the latest 1,440 entries (max 300 per request) and `/api/v5/market/history-candles` serves older data at 100 per request, 20 requests per 2 s per IP, with BTC-USDT daily candles reaching back to late 2017 (https://cryptomarkets.tools/tools/okx-api ; https://docs.rs/fugazi/latest/src/fugazi/sources/okx.rs.html). OKX changelog: "The maximum query range on Get historical market data has been reduced from 20 to 10" (https://www.okx.com/docs-v5/log_en/, date not captured).

**Delivery and file layout**
- Downloads are JS "Download" buttons; the page exposes no file names, formats or columns (https://www.okx.com/historical-data). A 2022-era community script used `https://static.okx.com/cdn/okex/traderecords/{trades|swaprate}/monthly/{YYYYMM}/{file}` with a listing API `https://www.okx.com/priapi/v5/broker/public/orderRecord?path=cdn/okex/traderecords/...` (https://raw.githubusercontent.com/crypto-crawler/historical-data-downloader/main/okx-data-downloader.py); on 2026-10-12 that listing API returned `{"code":404,...,"msg":"Not Found"}` for 2024 and 2026 daily/monthly paths, so current file naming, CSV columns, timestamp unit and checksums: Not found.

**Cost**
- Free download page (no price shown) (https://www.okx.com/historical-data).

**Terms for personal use**
- OKX API Agreement, "Last Updated: 28 July 2026" (published 2026-03-26): 9.4 "Market Data obtained through the API Services is proprietary to OKX or its data licensors"; use "solely for your own personal, non-commercial trading and account management purposes"; "The restrictions in this Section 9.4 apply equally to Market Data accessed through public endpoints"; "The fact that Market Data is publicly accessible does not grant any right to redistribute, resell, or commercially exploit that data"; "Any person accessing OKX Market Data through public endpoints without authentication" is bound; high-volume commercial use needs "a separate data licensing agreement"; 9.2 licence is "limited, revocable, non-exclusive, non-transferable, non-sublicensable" for internal purposes (https://www.okx.com/en-us/help/okx-api-agreement).
- Licence text of the historical-data page itself: Not found on the page; a third-party guide quotes a "revocable, non-exclusive, royalty-free" personal-use licence covering "development of your own trading strategy" with deletion on revocation (https://cryptomarkets.tools/guides/exchange-api-terms) — unverified.

**Third-party app**
- 5.1 "You must not share API Keys with unauthorized persons"; 8.2(a) prohibits "Granting API access or credentials to any third party not authorized under this Agreement"; 3.2(o) only approved brokers/partners may act for end users (API Agreement above). Inference: the agreement does not define whether a locally-run app that stores the user's own key is a "third party"; public endpoints need no key, and 9.4 binds whoever calls them.

**Geographic restrictions**
- OKX relaunched in the US in April 2025 via OKX Inc. (San Jose) after a $500M DOJ settlement (https://www.theblock.co/amp/post/350940/okx-officially-expand-us-following-500-million-doj-settlement); reviewers describe the US product as spot-only without perpetual swaps and unavailable in some states (NY, TX, NV) (https://www.gncrypto.news/news/can-you-use-okx-in-the-us/ ; https://coinbureau.com/review/okx, 2026-01-08) — third-party. Agreement 3.2: "Certain services listed below may not be available in your jurisdiction or region" (API Agreement above).

**Changes in 2026**
- API Agreement published 2026-03-26 and updated 2026-07-28 (page above). Listing API used by community tools now returns 404 (observed 2026-10-12).

**Not found**
- File naming/columns/timestamps/checksums; per-endpoint official rate limits (docs page did not render the market-data section); historical-data page licence text.

### Kraken downloadable OHLCVT and trade history

**Offers**
- OHLCVT CSVs for every pair "from the beginning of each market up to the present", intervals 1, 5, 15, 30, 60, 240, 720, 1440 minutes; "only includes entries for intervals when trades happened"; full dataset covers first trade through 30 June 2026; page "Last updated: 16 September 2026" (https://support.kraken.com/hc/en-us/articles/360047124832-Downloadable-historical-OHLCVT-Open-High-Low-Close-Volume-Trades-data). Note the page lists intervals twice and the second list omits 30 (same page).
- Trades (time and sales) CSVs per pair, first trade through 30 June 2026, "Last updated: 16 September 2026" (https://support.kraken.com/hc/en-us/articles/360047543791-Downloadable-historical-market-data-time-and-sales-).
- Cadence: full ZIP plus "incremental updates ... at the end of each quarter" (both pages). A third-party guide describes the archive as intraday data "2013-2025" for every pair, i.e. XBTUSD starts in 2013 (https://concretumgroup.com/how-to-get-free-full-crypto-intraday-data-2013-2025-from-kraken/, 2026-01-26). Spot only; Kraken Futures data via REST: `GET /api/charts/v1/{tick_type}/{symbol}/{resolution}`, `GET /derivatives/api/v3/history`, `GET /derivatives/api/v3/historicalfundingrates` (https://docs.kraken.com/exchange/guides/general/historical-data.md).
- REST: `GET /0/public/OHLC` up to 720 candles per call, `[time, open, high, low, close, vwap, volume, count]`, paginate with `last`; `GET /0/public/Trades` up to 1000 per call, `since` in nanoseconds, `[price, volume, time, buy/sell, market/limit, miscellaneous, trade_id]`; safe delay 1 s (OHLC) and 1 to 2 s (Trades); the same docs page says "Kraken does not provide a bulk historical data dump" (contradicted by the support pages above) (https://docs.kraken.com/exchange/guides/general/historical-data.md).

**Delivery and file layout**
- OHLCVT full history: five parts of about 2 GB: `https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full_2026Q2.zip.part00` to `.part04`; join with `cat Kraken_OHLCVT_Full_2026Q2.zip.part* > Kraken_OHLCVT_Full_2026Q2.zip` (Windows `copy /b`); per-part checksums `https://assets.kraken.com/marketing/institutions/OHLCVT_Full_PARTS_SHA256SUMS.txt`; merged file `shasum -a 256` expected `fc81b54cba6e12af3e9422dde9416179e6ef76af4831d48d839fbdb43018eaa4`; quarterly `Kraken_OHLCVT_2026Q1.zip`, `Kraken_OHLCVT_2026Q2.zip` (OHLCVT page above).
- OHLCVT rows: `timestamp, open, high, low, close, volume, trades`; "OHLCVT files contain no header row"; one set of CSV files per pair; each archive contains a `MANIFEST.json` describing the build (OHLCVT page). CSV names inside the ZIP: not stated; a Jan 2026 third-party guide shows `XBTUSD_1.csv`, `XBTUSD_5.csv`, `ETHUSD_1.csv`, `ADAEUR_1440.csv` (`<PAIR>_<minutes>.csv`) and warns the archive is sometimes nested (https://concretumgroup.com/how-to-get-free-full-crypto-intraday-data-2013-2025-from-kraken/, 2026-01-26). Timestamp unit: not stated by Kraken; a derived dataset built from these files shows Unix seconds (e.g. `1767225600`) (https://huggingface.co/datasets/tppetrov/kraken-ohlcvt-close-prices). Inference: Unix seconds, bar open time; confirm on first file.
- Trades full history: 13 parts `https://assets.kraken.com/marketing/institutions/Kraken_Trades_Full_2026Q2.zip.part00` to `.part12`; parts checksums `Trades_Full_PARTS_SHA256SUMS.txt`; merged SHA256 `554184802aa7367c02cfde9230411d0069ef5b0b4d6f9617c4ec1a7ec8726e16`; quarterly `Kraken_Trades_2026Q1.zip`, `Kraken_Trades_2026Q2.zip` (Trades page above).
- Trades rows: files "contain a header row; each row has seven columns: `timestamp, price, volume, type, order_type, misc, trade_id`", `type` is `b`/`s`, `order_type` is `l`/`m`, rows sorted by timestamp, one CSV per pair, `MANIFEST.json` included; timestamp unit not stated (Trades page above). Inference: same unit as the REST `Trades` field (seconds with fractional part); confirm.
- Kraken pair codes use `XBT` for BTC (`XBTUSD`) (docs page above).

**Cost**
- Free (support pages above).

**Terms for personal use**
- No licence text on either download page beyond a general "for general information purposes" disclaimer (both pages). Kraken API legal page: Not found (https://www.kraken.com/legal/api returned 404).

**Third-party app**
- "Our API allows third party services (such as trading bots, mobile apps and portfolio management services) to integrate with a Kraken account ... Any account owner who wishes to use a third party service simply needs to create an API key with the appropriate configuration, and provide this key to the third party service" (https://support.kraken.com/hc/en-us/articles/360041395271-Using-the-Kraken-API-with-a-third-party-service, 2025-04-01). The public archive and public endpoints need no key (docs page above).

**Geographic restrictions**
- US served: "Kraken does not offer services to residents of New York (NY), and Maine (ME)" (https://support.kraken.com/articles/quick-start-for-clients-in-the-united-states); FinCEN MSB registration for US clients (https://support.kraken.com/gb/articles/where-is-kraken-licensed-or-regulated, 2026-08-17). US perpetual futures launched 2026-06-15 on Bitnomial (bought by Payward in May 2026), traded on Kraken Pro for eligible US clients (https://www.businesswire.com/news/home/20260615010932/en/Kraken-Launches-Perpetual-Futures-for-US-Clients); nine assets incl. BTC and ETH, 8-hour funding (https://www.thetradenews.com/kraken-launches-first-cftc-regulated-perpetual-futures-for-us-traders/).

**Changes in 2026**
- Archive moved from Google Drive single ZIP (coverage to Q3 2024, per the Jan 2026 guide above) to `assets.kraken.com` multi-part files with SHA256 sums, coverage to 2026-06-30 (pages dated 2026-09-16); trades CSV now has a header and seven columns (older page text described only date/time, price, volume). US perps June 2026 (above).

**Not found**
- Timestamp unit statement; CSV file-name pattern on Kraken's page; data licence; Kraken Futures bulk archive; API legal terms page.

### Coinbase (Exchange / Advanced Trade)

**Offers**
- Advanced Trade: `GET /api/v3/brokerage/market/products/{product_id}/candles` (public, no auth) and `/api/v3/brokerage/products/{product_id}/candles`; `start`/`end` are UNIX-second strings; `granularity` enum `ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, TWO_HOUR, FOUR_HOUR, SIX_HOUR, ONE_DAY`; `limit` default and max 350; candle fields `start` (UNIX seconds), `low, high, open, close, volume` (https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles.md).
- Exchange: `GET /products/{product_id}/candles`, granularity `{60, 300, 900, 3600, 21600, 86400}`, max 300 candles per request, buckets `[time, low, high, open, close, volume]`, "No data is published for intervals where there are no ticks", "should not be polled frequently" (https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles.md).
- Markets via Advanced Trade API: Spot; "US futures: CFTC-regulated futures for eligible US clients"; "Global Derivatives: Perpetuals for eligible non-US clients, traded on a Deribit-powered gateway" (https://docs.cdp.coinbase.com/advanced-trade/docs/rest-api-rate-limits.md). US nano BTC/ETH perpetual-style futures for US customers since 2025-07-21 via Coinbase Financial Markets (https://www.fow.com/insights/coinbase-hails-arrival-of-perpetual-style-futures-in-us, 2025-07-22).
- History: earliest candle date Not found in docs; Coinbase Exchange opened 2015-01-26 (https://www.coindesk.com/coinbases-us-bitcoin-exchange-opens-doors-traders). Inference: BTC-USD history starts in 2015.
- Bulk archive: Not found; Coinbase instead lists authorized redistribution partners (Amberdata, Kaiko, Tardis.dev, CCData, Coin Metrics and others) (https://cryptomarkets.tools/guides/exchange-api-terms).

**Delivery and file layout**
- REST only (JSON); no CSV archive (above). Rate limits (Exchange): public 10 requests/s per IP, burst 15; private 15/s per profile, burst 30 (https://docs.cdp.coinbase.com/exchange/introduction/rate-limits-overview.md). Advanced Trade rate-limit page: Not found (URL redirects to the welcome page). Inference: 350 one-minute candles per call means about 4 calls per day of data.

**Cost**
- Free API access (docs above; no fee schedule for market data found).

**Terms for personal use**
- Market Data Terms of Use, "Last updated: August 7, 2026": licence is "nonexclusive, nontransferable, non-sublicensable, revocable, limited ... solely for you and/or the officers and employees of your entity"; "exclusively for you or your entity's personal or research purposes and may not be used to build an application intended for use by end users other than for you or your officers/employees"; no redistribution of Market Data or "Derived Works" "to any third party outside of your organization"; no benchmarks/indexes; new AI clause: may not "develop, train, fine-tune, teach, validate, benchmark, or otherwise improve any artificial intelligence or machine learning model" with Market Data (https://www.coinbase.com/legal/market_data). "By accessing the Exchange Market Data API, you agree to be bound by the Market Data Terms of Use" (https://docs.cdp.coinbase.com/exchange/docs/rate-limits.md).

**Third-party app**
- CDP Terms of Service, "Last modified: June 23, 2026": "These terms apply whether you use the CDP Tools for your internal purposes or to develop applications or other services for your end users" (https://www.coinbase.com/legal/developer-platform/terms-of-service). Inference: a desktop app the user runs for personal research is use "for you"; the Market Data Terms' "application intended for use by end users other than for you" clause targets apps distributed to others, and the terms do not say whether each end user supplying their own key cures that.

**Geographic restrictions**
- US supported; Coinbase Inc. is NYDFS-licensed and US futures/perps are offered via Coinbase Financial Markets (https://www.coinbase.com/places). Global Derivatives perps are "for eligible non-US clients" (Advanced Trade page above).

**Changes in 2026**
- International derivatives moved off INTX to a Deribit-powered gateway ("Starbase", JSON-RPC 2.0): one docs page says a hard cutover on 2026-09-09, another says "They moved there from INTX on October 1, 2026, and INTX perpetuals are no longer traded through the Advanced Trade API" (https://docs.cdp.coinbase.com/advanced-trade/docs/rest-api-rate-limits ; ...rest-api-rate-limits.md). Market Data Terms revised 2026-08-07 (AI clause); CDP ToS 2026-06-23 (above). Perpetual-style equity index futures on Coinbase Derivatives from 2026-06-08 (https://thedefiant.io/converge/cefi/coinbase-perpetual-equity-index-futures-june-8-yclimy).

**Not found**
- Bulk CSV archive; earliest-candle date; Advanced Trade rate-limit page; product IDs for the US nano perpetual contracts in the candles API.

### Hyperliquid historical data (S3 + API)

**Offers**
- S3 bucket `hyperliquid-archive`: L2 book snapshots `s3://hyperliquid-archive/market_data/[date]/[hour]/[datatype]/[coin].lz4` and asset contexts `s3://hyperliquid-archive/asset_ctxs/[date].csv.lz4`; "uploaded ... approximately once a month. There is no guarantee of timely updates and data may be missing"; "No other historical data sets are provided via S3 (e.g. candles or spot asset data)" (https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data, "Last updated 4 months ago" on 2026-10-12).
- Trades: `s3://hl-mainnet-node-data/node_fills_by_block` (fills streamed from a non-validating node), older `node_fills` (API format) and `node_trades` (different format); funding and other non-trade events in `s3://hl-mainnet-node-data/misc_events_by_block` (same page).
- API: `candleSnapshot` "Only the most recent 5000 candles are available", intervals `1m,3m,5m,15m,30m,1h,2h,4h,8h,12h,1d,3d,1w,1M`; `fundingHistory` by coin with `startTime`/`endTime` in ms; `metaAndAssetCtxs` gives mark price, funding, open interest; responses over a time range return at most 500 elements, paginate with the last timestamp (https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint ; .../info-endpoint/perpetuals). Inference: 5000 one-minute candles is about 3.5 days, so minute history must be built from fills.
- History depth: asset-contexts-derived rows reach back to 2023-05-20 (https://docs.dune.com/data-catalog/curated/perpetuals/hyperliquid/perp-oracle-prices.md, third-party); docs example `market_data/20230916/9/l2Book/SOL.lz4`. First S3 date: Not found (listing needs AWS credentials).

**Delivery and file layout**
- `aws s3 cp s3://hyperliquid-archive/market_data/20230916/9/l2Book/SOL.lz4 /tmp/SOL.lz4 --request-payer requester` then `unlz4` (docs page above). `asset_ctxs` CSV column order: Not found in official docs.
- Rate limits: REST "aggregated weight limit of 1200 per minute" per IP; `candleSnapshot` adds weight per 60 items, `fundingHistory` per 20 items; "For large batch requests, use the S3 bucket instead" (https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

**Cost**
- Data free; "the requester of the data must pay for transfer costs" (docs page above). Requester Pays: "the requester instead of the bucket owner pays the cost of the request and the data download"; "anonymous access to that bucket is not allowed", so an AWS account and credentials are required (https://docs.aws.amazon.com/AmazonS3/latest/userguide/RequesterPaysBuckets.html). AWS egress: first 100 GB/month free aggregated across services; S3 example rate "$0.09 per GB" to the internet (https://aws.amazon.com/s3/pricing/). Inference: budget about $0.09/GB beyond the free 100 GB for US regions (the per-region table did not render).

**Terms for personal use**
- Interface Terms of Use, "Last updated on June 15, 2026": apply to the app ("the Interface"); 1.6 "Restricted Persons include: (a) persons or entities who reside in, are located in, are incorporated in, or have a registered office in the United States of America or Ontario, Canada ... Restricted Persons are strictly prohibited from accessing or using the Interface" (https://app.hyperliquid.xyz/terms). Data licence for the S3 buckets or API: Not found.

**Third-party app**
- Info endpoints need no API key (docs above); terms on third-party software using the API: Not found.

**Geographic restrictions**
- US persons barred from the Interface (terms above); API/S3 geo-blocking statement: Not found. Reported US-entry efforts: a 2026-08-19 presidential statement that the CFTC is working to bring Hyperliquid to the US, possibly via Bitnomial (https://theblock.co/news/regulation/2026-09-04-trump-wants-hyperliquid-enter-us-how-it-could-happen-413594).

**Changes in 2026**
- Terms revised 2026-06-15 adding "Excluded Persons" for outcome markets (terms above). Commercial coverage: CoinAPI flat files add Hyperliquid L4 oracle prices/TWAP/misc/system events (https://www.coinapi.io/products/flat-files/docs/datasets); Tardis "Perpetuals" plan includes Hyperliquid (https://docs.tardis.dev/faq/billing-and-subscriptions).

**Not found**
- `asset_ctxs` columns; first available S3 date; any data licence; API geo-block statement.

### CCXT (library)

**Offers**
- MIT License (Copyright 2024 Igor Kroitor) (https://raw.githubusercontent.com/ccxt/ccxt/master/LICENSE.txt); 100+ exchanges incl. Hyperliquid, Polymarket, Kalshi; JS/TS, Python, C#, PHP, Go, Java, Rust (https://raw.githubusercontent.com/ccxt/ccxt/master/README.md).
- Unified methods: `fetchOHLCV (symbol, timeframe = '1m', since, limit, params)`; `fetchFundingRateHistory (symbol, since, limit, params)`; `fetchOpenInterestHistory (symbol, timeframe = '5m', since, limit, params)` (OKX wants a currency code, e.g. `'BTC'`); mark/index/premium candles via `params {'price': 'mark'|'index'|'premiumIndex'}` or `fetchMarkOHLCV`, `fetchIndexOHLCV`, `fetchPremiumIndexOHLCV` (https://raw.githubusercontent.com/ccxt/ccxt/master/wiki/Manual.md).
- Pagination: `params: {'paginate': True}` with `paginationCalls` (default 10), `paginationDirection` (forward needs `since`), `maxEntriesPerRequest`; "deterministic" concurrent paging for OHLCV, funding rates and open interest (Manual, Pagination section). All unified timestamps are milliseconds; "There's a limit on how far back in time your requests can go"; "the info from the last (current) candle may be incomplete until the candle is closed"; built-in rate limiter `enableRateLimit` is on by default (Manual).
- Per-venue capability flags on master (2026-10-12, `has` dict in `python/ccxt/<id>.py`): binance and bybit: `fetchOHLCV, fetchTrades, fetchFundingRateHistory, fetchOpenInterestHistory, fetchMarkOHLCV, fetchIndexOHLCV, fetchPremiumIndexOHLCV` all True; okx: all True except `fetchPremiumIndexOHLCV`; kraken (spot): `fetchOHLCV, fetchTrades` True, funding/OI/mark False; krakenfutures: `fetchOHLCV, fetchTrades, fetchFundingRateHistory, fetchMarkOHLCV, fetchIndexOHLCV` True; coinbase (Advanced Trade) and coinbaseexchange: `fetchOHLCV, fetchTrades` True, funding/OI False; hyperliquid: `fetchOHLCV, fetchTrades, fetchFundingRateHistory, fetchOpenInterest` True, `fetchOpenInterestHistory` False (https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/binance.py and sibling files).
- Bulk-archive (zip/csv) downloading: Not found in the manual; CCXT wraps REST/WebSocket only (Manual).

**Delivery and file layout**
- In-memory arrays `[timestamp(ms), open, high, low, close, volume]`; per-venue page sizes follow the venue limits above (Manual; venue docs in earlier sections).

**Cost**
- Free (MIT).

**Terms for personal use / Third-party app**
- MIT permits use, modification, distribution and sale of the library (LICENSE above). Inference: the venue's data terms (sections above) still govern the data your app fetches through CCXT.

**Geographic restrictions**
- None in the library; venue rules apply (Inference).

**Changes in 2026**
- Not found (no dated 2026 changelog consulted beyond the README's prediction-market support).

### Tardis.dev (paid)

**Offers**
- Data types: `incremental_book_L2`, `book_snapshot_25`, `book_snapshot_5`, `trades`, `options_chain`, `quotes`, `book_ticker`, `derivative_ticker` (funding, OI, mark/index), `liquidations`; no candle dataset (https://docs.tardis.dev/downloadable-csv-files/data-types.md). Inference: build OHLCV from `trades`.
- History: "all available historical data since 2019-03-30 for majority of the supported exchanges" (Business, yearly); Binance USDS-M futures since 2019-11-17, OI since 2020-05-13 (https://docs.tardis.dev/faq/billing-and-subscriptions ; https://docs.tardis.dev/historical-data-details/binance-futures.md). "Perpetuals" plan covers Binance USDS-M/COIN-M, OKX Swap, Bybit, Kraken Futures, Hyperliquid, dYdX v4 and others (billing FAQ).
- Free: "Historical CSV datasets for the first day of each month are available to download without API key" (binance-futures page above).

**Delivery and file layout**
- CSV `.csv.gz`, comma delimiter, LF, "date time format: microseconds since epoch", UTC; `trades` columns `exchange, symbol, timestamp, local_timestamp, id, side, price, amount`; `derivative_ticker` columns `exchange, symbol, timestamp, local_timestamp, funding_timestamp, funding_rate, predicted_funding_rate, open_interest, last_price, index_price, mark_price` (data-types page). Example URL `https://datasets.tardis.dev/v1/bitmex/derivative_ticker/2019/04/01/ETHUSD.csv.gz`; Inference: pattern `/v1/{exchange}/{data_type}/{YYYY}/{MM}/{DD}/{SYMBOL}.csv.gz`, one file per day, header row (previews show column names).
- API keys: Academic/Solo/Pro 1 active key, 1 source IP per key (billing FAQ).

**Cost (USD per month, from tardis.dev home page on 2026-10-12)**
- Perpetuals: Academic $350, Solo $700, Professional $1,000, Business $3,000; Spot and Derivatives: $450 / $900 / $1,350 / $3,500; All Exchanges: $650 / $1,200 / $2,200 / $6,000; minimum order $300; Academic needs quarterly or yearly billing (https://tardis.dev/). History by billing interval: yearly = 4 years (Academic/Solo/Pro) or all (Business); quarterly = 12 months; monthly = 4 months; Academic/Solo = CSV only, Pro/Business add replay API and tardis-machine; "We do not provide discounts"; no one-off purchases (billing FAQ).

**Terms for personal use**
- Terms of Service (last modified 2026-09-13): Permitted Use is "internal business, research, educational or personal use by the Customer and Customer Users only" (1.1); no "redistribute or resell the Data" except "aggregated and calculated Derived Data, including OHLC or OHLCV candles, at a resolution of 10 minutes or longer" (9.2), not for Coinbase Data except under Clause 23; licence to downloaded Data "is perpetual and survives termination" (9.4); data obtained directly from exchanges stays under the exchange's terms (9.6) (https://docs.tardis.dev/legal/terms-of-service.md).

**Third-party app**
- Personal use permitted; Inference: a local app for the subscriber's own use is fine, while shipping Tardis data inside a distributed app is redistribution unless it is 10-minute-or-coarser candles.

**Geographic restrictions**
- Not found (no geographic clause located).

**Changes in 2026**
- ToS modified 2026-09-13 (above); generated `premiumIndex` channel for Binance futures since 2026-04-11 (binance-futures page).

**Not found**
- Exact per-exchange start dates for Bybit/OKX/Kraken (not fetched); geographic clauses.

### CoinAPI (paid)

**Offers**
- Market Data API (REST, WebSocket, JSON-RPC, FIX) and Flat Files on S3: Quotes, Trades, Full LOB, LOB Snapshot 50, Depth Bands, OHLCV (1SEC/1MIN/1HRS/1DAY), Metrics V2, Hyperliquid oracle prices / TWAP / misc / system events (https://www.coinapi.io/products/flat-files/docs/datasets). History depth per exchange: Not found on the pages read.

**Delivery and file layout**
- Buckets `coinapi` (hourly `D-YYYYMMDDHH` partitions since 2026-06-09, legacy daily before) and `coinapi-daily-tail` (previous day only, 24 h); path `T-TRADES/D-{YYYYMMDD|YYYYMMDDHH}/E-[EXCHANGE]/IDDI-[ID]+SC-[COINAPI_SYMBOL_ID]+S-[EXCHANGE_SYMBOL].csv.gz`; OHLCV as `T-OHLCV_ACTIVE_CONSOLIDATED/.../TP-[TF].csv.gz` (all symbols per exchange); gzip CSV, UTC (datasets page above).

**Cost**
- Market Data API: Pay-As-You-Go metered with $25 free credits; Startup $79/mo ($69 annual), 1k REST credits/day; Streamer $249 ($199); Pro $599 ($499); REST credits $5.26 per 1k for the first 1,000/day, falling with volume (https://www.coinapi.io/products/market-data-api/pricing). Flat Files: PAYG $1/credit; Committed $64/$256/$512/$1024 per month at $0.85 to $0.65 per credit; Trades $24/GiB for the first 0.5 GiB per day per SKU (PAYG), OHLCV 1MIN $2.00/MiB for the first 20.48 MiB/day/SKU, LOB $8/GiB first 1 GiB (https://www.coinapi.io/products/flat-files/pricing).

**Terms for personal use**
- Usage Policy: "Redistribution means CoinAPI data is made available to third parties, whether directly or indirectly"; redistributing raw or normalized data "Not permitted" on any plan; internal trading systems, quant research and AI/ML workflows are internal use; "API keys are issued for your organization and should not be shared with third parties"; displaying data to external users may count as redistribution; the Customer Agreement and Acceptable Usage Policy are binding (https://www.coinapi.io/usage-policy). Commercial apps and derived outputs (candles, indicators) are allowed (https://www.coinapi.io/blog/coinapi-data-commercial-use-policy).

**Third-party app**
- Inference: the user's own key inside a local app is internal use; an app vendor must not embed its key for other users (key-sharing rule above).

**Geographic restrictions**
- Not found.

**Changes in 2026**
- Hourly partitions in `coinapi` from 2026-06-09; `coinapi-daily-tail` rolling bucket; Hyperliquid datasets (datasets page, dates for the latter not stated).

**Not found**
- Per-exchange history start dates; Customer Agreement text; effective date of the Usage Policy.

### Kaiko (bought Amberdata in 2026) (paid)

**Offers**
- Kaiko acquired Amberdata on 2026-06-02 (fifth acquisition, after Cometh in May 2026); combined 260+ institutional clients; "200+ exchanges, 20+ blockchains, and 20,000+ digital assets"; Amberdata brings derivatives analytics and onchain data (https://blog.amberdata.io/kaiko-acquires-amberdata-in-landmark-digital-asset-data-consolidation, 2026-06-02).
- Products: data feeds (trades, order books, aggregates), analytics, indices, oracles; positioned for institutions and regulators (https://www.kaiko.com/). History "since 2014" per a directory listing (https://imas.org.sg/fintech-directory/company/?id=kaiko, third-party); an LSEG reseller listing gives tick history only from October 2024 (https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/kaiko-crypto-data) — depth depends on package.
- Amberdata delivery included REST and S3 bulk downloads (https://docs.amberdata.io/docs/s3-bulk-downloads); post-acquisition packaging "not fully disclosed" (https://www.rfp.wiki/crypto/digital-assets-nfts/crypto-data-analytics-market-risk/amberdata/cryptoquant, third-party).

**Delivery and file layout**
- Kaiko CSV docs (page since moved) describe headerless CSVs with millisecond Unix timestamps (search snippet of https://docs.kaiko.com/v/kaiko-csv-data/market-data/trades/trade-count-ohlcv-candlesticks-and-vwap). Current schema pages: Not found (docs.kaiko.com returned "Page Not Found").

**Cost**
- No public price list; enterprise quotes. Third-party transaction data: roughly $9,500 to $55,000 per year, average about $28,500 (https://vendr.com/marketplace/kaiko). Amberdata tiers were Startup / On-Demand / Enterprise with rate limits 15 calls/s (trial), 20 calls/s and 250k/day (On-Demand), up to 60 calls/s (Enterprise); dollar prices not public (rfp.wiki page above).

**Terms for personal use / Third-party app**
- Not found (no public terms or data licence page located).

**Geographic restrictions**
- Not found.

**Changes in 2026**
- Amberdata acquisition 2026-06-02 and Cometh acquisition May 2026 (press release above).

**Not found**
- Pricing, terms, current CSV schemas, individual/retail plan.

### Summary table

| Source | Spot | Perpetuals | Trades | Funding/OI | History from | Cost | Personal-use terms | US access |
|---|---|---|---|---|---|---|---|---|
| Binance Vision | klines/trades/aggTrades (BTCUSDT from 2017-08) | USD-M klines, mark/index/premium klines, bookTicker/bookDepth | yes (trades, aggTrades) | fundingRate (monthly, 2020-01), metrics = OI (daily, 2020-09-01) | 2017-08 spot; 2020-01 UM | free | CC BY-NC-SA 4.0 (v1.0, 2026-08-26); personal non-production backtesting OK; no live-trading execution, no commercial/hosting | Binance.com blocks US persons (secondary sources); archive host geo-block not found |
| Bybit public | spot trade prints (2022-11) | derivatives trade prints (BTCUSD 2019-10-01, BTCUSDT 2020-03-25); MT4 15/60-min klines 2020-2024 only | yes | not on host (REST only) | 2019-10 inverse; 2020-03 USDT | free | archive licence not found; API terms: no resale/commercial exploitation of Service Data | T&C 3.4 excludes United States |
| OKX portal | trade history, candles | swap trades/candles, funding | yes (Sep 2021) | funding (Mar 2022); OI not found | 2021-09 trades; 2023-07 candles | free | API Agreement 9.4: personal, non-commercial, applies to public endpoints | OKX US exists (spot-only per reviews) |
| Kraken archive | OHLCVT 1m to 1d, trades (all pairs) | none in archive (Futures via REST; US perps on Bitnomial since 2026-06) | yes (7-col CSV with header) | REST only (historicalfundingrates) | first trade per market (XBTUSD 2013) | free | no licence text; third-party API apps explicitly allowed | yes except NY and ME |
| Coinbase | candles (350/300 per call) | US nano perps (CFM), non-US perps on Deribit gateway | REST trades | none | 2015 (exchange launch) | free | Market Data Terms 2026-08-07: personal/research only, no redistribution, no AI training | yes (NYDFS-licensed) |
| Hyperliquid | spot via API only | L2 snapshots + asset_ctxs on S3; candles API last 5000 only | node fills on S3 | funding in asset_ctxs/API; OI in asset_ctxs | 2023-05-20 (asset ctxs, third-party) | free + AWS requester-pays egress (about $0.09/GB after 100 GB) | no data licence found; Interface terms bar US persons | Interface blocks US; API/S3 block not found |
| CCXT | fetchOHLCV/fetchTrades all venues | binance/bybit/okx/krakenfutures/hyperliquid | fetchTrades | fetchFundingRateHistory (not kraken/coinbase); OI history binance/bybit/okx | venue-dependent | free (MIT) | MIT; venue data terms still apply | n/a |
| Tardis.dev | trades, books, quotes | trades, books, derivative_ticker, liquidations | yes (µs timestamps) | derivative_ticker (funding, OI, mark, index) | 2019-03-30 | $350 to $6,000 per month; first-of-month files free | internal/personal use; no redistribution except candles 10 min or coarser; downloaded data licence perpetual | not found |
| CoinAPI | trades, quotes, LOB, OHLCV | same for futures venues | yes | Metrics V2 | not found | PAYG ($25 free) or $79 to $599 per month; flat files per GiB/credit | internal use; no raw redistribution; no key sharing | not found |
| Kaiko (+Amberdata) | trades, books, OHLCV | derivatives analytics (Amberdata) | yes | yes (Amberdata) | 2014 (third-party claim) | enterprise quotes (about $9.5k to $55k per year, third-party) | not found | not found |

## Part D — Platform export formats, for the import presets

Scope: formats a trader gets when exporting their own bar/tick history from each platform, for building import presets. Every factual statement carries its source link. "Inference:" marks my own reasoning. "Not found" marks things searched for but not located. Example lines are copied verbatim from the cited page.

---

### NinjaTrader 8

#### How to export
- Export lives in the Export section of the Historical Data window: pick instrument, interval type ("Tick," "Minute," or "Day" — shown only if that data type is stored), data type ("Ask," "Bid," or "Last"), start date, end date, then Export and choose a file name (https://ninjatrader.com/support/helpGuides/nt8/exporting.htm).
- Granularities: Tick, Minute, Day only (the three interval types offered) (https://ninjatrader.com/support/helpGuides/nt8/exporting.htm).
- Only data already stored locally (downloaded from the provider or collected live) can be exported (https://ninjatrader.com/support/helpGuides/nt8/exporting.htm).
- Limits on bar count or history depth: Not found (no limit documented on the export page).

#### File layout
- Official statement: "The historical data is exported with End of Bar time stamps to the chosen folder as a text file in the same format specified in the 'Understanding import file and data formats' section of the Importing page. The exported data will be in the UTC time zone." (https://ninjatrader.com/support/helpGuides/nt8/exporting.htm)
- Extension `.txt`; fields separated by semicolon; one bar/tick per line; no header row appears in any documented sample (Inference: no header) (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Daily: `yyyyMMdd;open price;high price;low price;close price;volume`, sample `20061023;1377.25;1377.25;1377.25;1377.25;86` (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Minute: `yyyyMMdd HHmmss;open price;high price;low price;close price;volume`, sample `20061023 004400;1377.25;1377.25;1377.25;1377.25;86` (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Tick (second granularity): `yyyyMMdd HHmmss;price;volume`, sample `20061107 000431;1383.00;1` (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Tick (sub-second, to the ten-millionth of a second): `yyyyMMdd HHmmss fffffff;price;volume`, sample `20061107 000431 1000000;1383.00;1`; note: "If you wanted to import in millisecond granularity data then each line must have the remaining '0's behind it to import correctly." (https://ninjatrader.com/support/helpGuides/nt8/importing.htm)
- Tick Replay (sub-second): `yyyyMMdd HHmmss fffffff;last price; bid price; ask price;volume`, sample `20061107 000431 1000000;1383.00;1383.00;1383.25;1`; second-granularity variant `yyyyMMdd HHmmss;last price;bid price;ask price;volume` (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Prices are decimal (samples above); volume is an integer (samples above). Community: a daily import failed with "Format error in line 0: Input string was not in a correct format" because the Volume field contained a decimal (thread not read in full; from search summary) (https://forum.ninjatrader.com/forum/ninjatrader-8/strategy-development/1115489-historical-data-import-error?p=1115556).
- Contract code appears in the file name, not in a column: "the name of the text file to be imported must be the NinjaTrader instrument name followed by a period and 'Last', 'Bid', or 'Ask'", examples `MSFT.Last.txt`, `ES 12-09.Bid.txt`, `EURUSD.Ask.txt` (https://ninjatrader.com/support/helpGuides/nt8/importing.htm). Inference: a March 2024 ES export is therefore named like `ES 03-24.Last.txt`.
- What a real NT8 Tick/Last export actually looks like (community, 2017 and again 2020): `20160725 120101 8340000;98;97.72;98.16;1800`; the Bid export of the same tick was `20160725 120101 8340000;97.72;97.72;98.16;0` and the Ask export `20160725 120101 8340000;98.16;97.72;98.16;0`. Users inferred "Last = last;bid;ask, Bid = bid;bid;ask, Ask = ask;bid;ask"; NinjaTrader support only replied that the three types share one format and are distinguished by file name, and a 2020 follow-up asking which of price1/price2/price3 is bid/ask/last got no answer in the thread (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/94196-historical-data-export-formats). Inference: tick exports from NT8 carry four numeric fields (last, bid, ask, volume) i.e. the "Tick Replay" layout, and the Bid/Ask exports have volume 0; treat the 4-price-field layout as the one to parse, with the 3-field `price;volume` layout as fallback.
- Aggressor side: not present in any documented layout (Not found).

#### Time zone and bar stamping
- Time zone: always UTC on export; "There is not a way to set a different time zone for exported data." (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1117379-timestamps-of-exported-data) and "NinjaTrader exports are always done in the UTC time zone" (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- Bar stamp: CLOSE. "minute bars are timestamped with the close of a bar, so a bar timestamped 133100 would include all ticks between 13:30:00.001 and 13:31:00.000. A daily bar will be timestamped with the closing date of that ETH session." For ES "daily bars will include data from 17:00 the day prior to 16:00 (times listed in US Central) the next day." (NinjaTrader Customer Service, https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1117379-timestamps-of-exported-data)
- On import the user chooses between "NinjaTrader (timestamps in import file(s) represent end of bar time)" and "NinjaTrader (timestamps in import file(s) represent start of bar time)"; "all imported data will always be converted to local PC time" (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).

#### Pitfalls
- A London user saw a 1-hour "lag" between chart and export; cause was simply that exports are UTC while the chart is local/DST (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1117379-timestamps-of-exported-data).
- Prices are rounded to the instrument's tick size on import; futures/forex instruments must exist in the database first, otherwise data is imported as a "Stock" (https://ninjatrader.com/support/helpGuides/nt8/importing.htm).
- "Import field separator could not be identified" error reported for some semicolon files (thread not read in full; from search summary) (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/94084-import-of-historical-data).
- Tick-export field meaning (which of the three prices is bid/ask/last) was never officially confirmed (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/94196-historical-data-export-formats).
- Daily bars for futures are stamped with the ETH session close date (so the ES "20200907" bar starts 17:00 CT on the 6th) (https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1117379-timestamps-of-exported-data).
- Third-party corroboration that the two NinjaTrader conventions exist: MotiveWave offers "Ninja Trader – Start Of Bar Time" and "Ninja Trader – End Of Bar Time" export formats (https://docs.motivewave.com/user-guide/charts-1/exporting-data).

#### Not found
- Whether zero-volume minutes are written as bars or skipped.
- Locale (decimal comma) behaviour of the exporter.
- Any documented maximum number of bars per export.

---

### Sierra Chart

#### How to export
- Three built-in routes, per Sierra Chart support: (1) `Edit >> Export Intraday Data to Text File` for the entire contents of the `.scid` file; (2) `Edit >> Export Bar Data to Text File` for the bars loaded in a particular chart; (3) the `Write Bar Data to File` study for continuous export; daily `.dly` files are already ASCII and can be opened directly (https://www.sierrachart.com/SupportBoard.php?ThreadID=78105).
- `Edit >> Export Bar Data to Text File`: "Each record/line in the text file will represent one bar of data... The file will only contain records for the chart bars loaded into the chart." Bars loaded are controlled by `Chart >> Chart Settings >> Use Number of Days to Load / Use Date Range`; set Session Times to limit time ranges; the file extension "is always TXT"; the exported file is written to the Data Files Folder and opened in the Daily Data Editor (https://www.sierrachart.com/index.php?page=doc/EditMenu.html).
- To export more futures history, enable the Continuous Futures Contract feature for the chart (https://www.sierrachart.com/index.php?page=doc/EditMenu.html). "Export Bar Data to Text File" works for either Daily or Intraday charts (https://www.sierrachart.com/SupportBoard.php?ThreadID=95566).
- `Edit >> Export Intraday Data to Text File` / `Export and Edit Intraday Data`: exports all data in the `.scid` file as `.itxt`/`.txt`; Sierra Chart must be disconnected (`File >> Disconnect`); records "can vary from 1 trade to 1 minute per record line" depending on the Intraday Data Storage Time Unit; for Continuous Futures charts only the current contract's file is exported (https://www.sierrachart.com/index.php?page=doc/ImportExport.html). "There is no limit on the amount of data that can be exported" (https://www.sierrachart.com/SupportBoard.php?Page=1&ThreadID=93304).
- Tick-by-tick: either export the `.scid` contents, or "Set the chart to be a 1 tick chart (Number of Trades with a period of 1) and then use 'Edit >> Export Bar Data to Text File'" (https://www.sierrachart.com/SupportBoard.php?Page=1&ThreadID=102502).
- Granularities: anything the chart can build (the bar export follows the chart's bar period); storage units from 1 tick up to 1 minute per `.scid` record (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html); daily data in `.dly` (https://www.sierrachart.com/index.php?page=doc/ChartDataFiles.html).
- Batch export of many symbols is not built in: ".dly... can be opened and read directly... If you are wanting Intraday data, then there is no way, other than creating your own program or custom study, to get the data for multiple instruments." (https://www.sierrachart.com/SupportBoard.php?PostID=406964)

#### File layout
- `.scid` binary: header `s_IntradayHeader` (56 bytes): `char FileTypeUniqueHeaderID[4]` = "SCID", `u_int32 HeaderSize`, `u_int32 RecordSize`, `u_int16 Version` (currently 1), `u_int16 Unused1`, `u_int32 UTCStartIndex` (0), `char Reserve[36]`. Record `s_IntradayRecord` (40 bytes): `SCDateTimeMS DateTime` (64-bit integer microseconds since 1899-12-30; versions before 2151 used a double), `float Open`, `float High`, `float Low`, `float Close`, `u_int32 NumTrades`, `u_int32 TotalVolume`, `u_int32 BidVolume`, `u_int32 AskVolume`. "This Date and Time value is and must be in the UTC time zone." (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html)
- `.scid` tick records: when a record is one trade, Open = 0 (`SINGLE_TRADE_WITH_BID_ASK = 0.0F`), High = Ask at the trade, Low = Bid at the trade, Close = trade price; Open may also hold `FIRST_SUB_TRADE_OF_UNBUNDLED_TRADE = -1.99900095e+37F` / `LAST_SUB_TRADE_OF_UNBUNDLED_TRADE = -1.99900197e+37F`; duplicate timestamps are made unique by incrementing the microsecond part; aggressor: "When [BidVolume] is a nonzero value and the NumTrades is equal to 1, then this indicates that the trade occurred at the Bid price... the aggressor of the trade was on the sell side" (and AskVolume likewise for buy side) (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html).
- `.scid` price scaling pitfall: "the price values in the data structure, may be native exchange values which are integers with no value to the right of the decimal point... you will see this when using Teton order routing or Rithmic." (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html)
- Intraday text export (`.itxt`/`.txt`): "The format of the exported data is as follows: Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume." "All fields can either be separated by commas or tabs. By default they are separated by commas. The first line always contains the header which explains all of the fields: `Date, Time, Open, High, Low, Last, Volume, Number of Trades, BidVolume, AskVolume`. The Date is formatted as YYYY/MM/DD. The Time is formated as hh:mm:ss." For single-trade records "the NumberOfTrades field will be set to 1... the Open field is equal to the last trade price, the High field is equal to the Ask price, the Low field is equal to the Bid price, and the Last field is equal to the last trade price." "The millisecond portion of the time acts as a counter when there are multiple trades within the same second" (https://www.sierrachart.com/index.php?page=doc/ImportExport.html).
- Bar export fields (`Export Bar Data to Text File`): Intraday charts: Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume; Daily charts: Date, Time ("Always 00:00:00"), Open, High, Low, Last, Volume, OpenInterest ("only available for futures contracts. Otherwise this will be 0") (https://www.sierrachart.com/index.php?page=doc/EditMenu.html). Real daily-chart export as pasted by a user, header `Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume` and line `2015/1/2, 00:00:00, 2016.75, 2029.00, 2000.50, 2008.00, 1358348, 2746750, 0, 0`; support confirmed the "NumberOfTrades" column there "would be the open interest in the case of Daily data" and promised to relabel it (https://www.sierrachart.com/SupportBoard.php?ThreadID=45421). Note the non-zero-padded day/month (`2015/1/2`) and the space after each comma in that sample (Inference from the pasted line).
- `.dly` daily file: text/CSV stored in the Data Files Folder with extension `dly`; file is named by symbol, e.g. `IBM.dly` (https://www.sierrachart.com/index.php?page=doc/TextCSVDataFormat.html, https://www.sierrachart.com/index.php?page=doc/ChartDataFiles.html). Daily data downloaded is "Open, High, Low, Close, Volume, and OpenInterest for a day" stored "in a Text/CSV format" (https://www.sierrachart.com/index.php?page=doc/DownloadingHistoricalDailyData.php). Documented daily example: header `Date, Open, High, Low, Close, Volume, OpenInterest`, line `2013/07/01, 97.625, 98.625, 97.375, 98.375, 1344600, 0` (https://www.sierrachart.com/index.php?page=doc/TextCSVDataFormat.html).
- Text/CSV reader rules (also what the app accepts back): delimiter comma, tab or semicolon; first line is the header; supported line formats include `Date, Time, Open, High, Low, Close, Volume, Number of Trades, Bid Volume, Ask Volume` (intraday) and `Date, Time, Unused, Ask, Bid, Close, Volume, Number of Trades, Bid Volume, Ask Volume` (bid/ask import, "Unused" must be 0) and `UNIXDateTime, Open, High, Low, Close, Volume`; "Close" may be called "Last"; date formats MM/DD/YY, YYYY/MM/DD, YYYY-MM-DD, YYYYMMDD, YYMMDD; time formats HH:MM:SS, HH:MM, HH:MM:SS.MSS, HHMM, HHMMSS, HHMMSSMSS; documented intraday example `2013/06/10, 09:45, 19.17, 19.18, 19.16, 19.17, 5000`; a file is treated as intraday "if there are repeating dates within the first 30 lines" (https://www.sierrachart.com/index.php?page=doc/TextCSVDataFormat.html).
- `Write Bar and Study Data To File` study: writes "Date, Time, Open, High, Low, Last, Volume, Number of Trades, OHLC Average, HLC Average, HL Average, Bid Volume, Ask Volume" plus study subgraphs, default file `[symbol]-BarData.txt` in the Data Files Folder; "The very last bar is not written to the data file since it is not considered complete"; "The time stamping of the data in the file will be the same as the times displayed in the chart. So it is according to the charts Time Zone." (https://www.sierrachart.com/index.php?page=doc/StudiesReference.php&ID=379&Name=Write_Bar_and_Study_Data_To_File). Users have asked (unanswered since 2022) to drop the extra average columns (https://www.sierrachart.com/SupportBoard.php?ThreadID=72412).
- Contract code form: Sierra symbols are service-specific; Not found as a documented pattern in exports (file name follows the chart symbol, e.g. `[symbol].scid`, `IBM.dly`) (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html).

#### Time zone and bar stamping
- Internally "All dates and times within Sierra Chart are obtained and stored in UTC/GMT time" (https://www.sierrachart.com/index.php?page=doc/TimeZone.html).
- Intraday-file text export: "The Date and Time for each record in an exported Intraday data text file is always in GMT/UTC time, no matter what the Time Zone setting in Sierra Chart is." (https://www.sierrachart.com/index.php?page=doc/ImportExport.html); support: "The timestamps are UTC." (https://www.sierrachart.com/SupportBoard.php?Page=1&ThreadID=93304)
- Bar export: Date and Time are "In the Time Zone of the Chart" (https://www.sierrachart.com/index.php?page=doc/EditMenu.html); "make sure the time zone of the chart is set to UTC before exporting" if you intend to re-import (https://www.sierrachart.com/SupportBoard.php?ThreadID=64583).
- Daily data: "the time zone for the open to close for the daily bars is according to the time zone of the exchange for the symbol"; Sierra's own Forex/CFD daily data is US Eastern (https://www.sierrachart.com/index.php?page=doc/TimeZone.html).
- Bar stamp: OPEN. "For charts within Sierra Chart, the timestamp for a chart bar is always its starting time. Potentially this can result in bars being different compared to chart bars in other programs which use the ending time for the timestamp for a bar." (https://www.sierrachart.com/index.php?page=doc/helpdetails43.html); "the displayed time for each chart bar is its starting time... a 60 minute chart bar for the trading day will start at 09:30:00 and end at 10:29:59" and the bar start "is aligned to the Session Times >> Start Time" (https://www.sierrachart.com/index.php?page=doc/SessionTimes.php). Displaying end times instead "is not supported" (https://www.sierrachart.com/SupportBoard.php?ThreadID=13339).
- `.scid` records with a storage unit > 1 second are stamped with the first trade's time inside the aligned interval (e.g. 9:28:22), with a new record starting at the next boundary (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html).

#### Pitfalls
- Two different "exports": the `.scid` text export only covers the current contract file, while the bar export covers the continuous-contract chart but only at chart resolution (https://www.sierrachart.com/index.php?page=doc/ImportExport.html, https://www.sierrachart.com/SupportBoard.php?ThreadID=104953).
- Daily bar export mislabels Open Interest as "NumberOfTrades" in older builds (https://www.sierrachart.com/SupportBoard.php?ThreadID=45421).
- Date components may be unpadded (`2015/1/2`) (https://www.sierrachart.com/SupportBoard.php?ThreadID=45421); Sierra's parser itself accepts both `2007/1/14` and `2007/01/14` (https://www.sierrachart.com/index.php?page=doc/TextCSVDataFormat.html).
- Native integer exchange prices in `.scid` for Teton/Rithmic feeds (https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html).
- Missing bars are not filled; `Include Columns with No Data` inserts flat bars only within days that have data (https://www.sierrachart.com/index.php?page=doc/ChartDataFiles.html).
- Daylight-saving: if the chart time zone has different DST rules than the exchange, times near transitions are wrong; set the chart (or global) time zone to the exchange's zone (https://www.sierrachart.com/index.php?page=doc/TimeZone.html).
- Antivirus scanning of `.itxt`, `.txt`, `.scid` makes export/import "very slow" (https://www.sierrachart.com/index.php?page=doc/ImportExport.html).

#### Not found
- An official sample line of the intraday `.itxt` export (only the daily-chart sample pasted by a user was found).
- Whether the bar export writes a space after each comma in every build (seen in the user-pasted sample only).

---

### TradeStation

#### How to export
- Data Window: "You can export the information in the Data window to a file in ASCII format... click the Save icon in the Data window", choose folder, name, "Save as type... Text Files (*.txt)"; with several symbols a Select Data Stream dialog appears and "You can only save data for one symbol at a time." (https://help.tradestation.com/09_05/ENG/tradestationhelp/orchart/save_export_data_ascii_file.htm; same text in https://help.tradestation.com/10_00/eng/TradeStationHelp/chart_analysis/data_window.htm).
- Data Window contents: open, high, low, close, study values; "the number of upticks and downticks for each bar" on tick charts; "the trade volume for the time period of the bar" (https://help.tradestation.com/10_00/eng/TradeStationHelp/chart_analysis/data_window.htm).
- Granularities: whatever the chart is set to (the Data Window mirrors the chart). Tick-level export via code only, per community (https://nexusfi.com/showthread.php?p=539221, from search summary; thread not read in full).
- Alternative route used in the community: a custom EasyLanguage indicator that prints bars to a file (https://www.hahn-tech.com/?p=9086, from search summary).
- Limits: Not found.

#### File layout
- Data Window `.txt` export: delimiter, header and date/time formatting are not documented on the help pages (https://help.tradestation.com/09_05/ENG/tradestationhelp/orchart/save_export_data_ascii_file.htm). Not found.
- TradeStation third-party ASCII layout (what TS reads, and the layout traders commonly keep "in TS format"): community sample `Date,Time,Open,High,Low,Close,Vol,OI` then `12/13/2012,1615,1419.75,1425.25,1409.75,1412,967938,0` (https://www.trade2win.com/threads/tradestations-9-0-insert-strategy-problem.183956/). Tickstory's working import settings for TS tick data: header `Date,Time,Close,Volume,OpenInt`, data `{Timestamp:yyyyMMdd},{Timestamp:HH:mm:ss},{BidPrice},0,0`, with quotes around header names removed (https://support.tickstory.com/viewtopic.php?p=7180).
- Prices decimal, volume integer, OI integer in the samples above (Inference from the sample lines).
- Contract code form: Not found for files; TradeStation symbols are of the form `ESH24`-style in the platform (not documented in the pages read) — Not found.

#### Time zone and bar stamping
- Bar stamp: CLOSE. "This reserved word returns a numeric expression representing the EasyLanguage time (HHMM format) of the closing price of the current bar." (https://help.tradestation.com/10_00/eng/tsdevhelp/elword/word/time_reserved_word_.htm); "Date... Date of the last trade within a bar; Time... Time of the last trade within a bar (in 24 hour format)" (https://help.tradestation.com/10_00/eng/tsdevhelp/elword/el_definitions/reserved_words.htm); "Bar time and date stamps are always the closing time and closing date of the bar." (https://kjtradingsystems.com/EL_Essentials.pdf); "In TradeStation the time of a bar is the time that it ends... TradeStation designates the date of the midnight bar as the date of the next day" (https://markplex.com/free-tutorials/tutorial-33-capture-close-day-bars-span-midnight/).
- Time zone: "The time zone used by EasyLanguage is determined by your computer's Windows clock settings and the Time Zone selection in the Format Symbol dialog" (https://kjtradingsystems.com/EL_Essentials.pdf). Inference: a Data Window export carries the chart's displayed time (local or exchange per Format Symbol).
- EasyLanguage dates are `YYYMMDD` numerics ("1040615 for June 15, 2004") and times `HHMM` (https://kjtradingsystems.com/EL_Essentials.pdf) — relevant for files written by Print statements.

#### Pitfalls
- Midnight bar is dated with the next day (https://markplex.com/free-tutorials/tutorial-33-capture-close-day-bars-span-midnight/).
- Quoted header names break the import (https://support.tickstory.com/viewtopic.php?p=7180).
- Help pages found are for versions 9.1/9.5/10.0; menus may differ in current TS Desktop (https://help.tradestation.com/10_00/eng/TradeStationHelp/chart_analysis/data_window.htm).

#### Not found
- Exact delimiter/header/date format of the Data Window `.txt` export.
- Any "TS Data" bulk export tool documentation (searched help.tradestation.com and community; only the Data Window save and custom-indicator approaches surfaced).

---

### TradingView

#### How to export
- "Open the dropdown menu on the upper toolbar and choose 'Download chart data…'", select the chart, click Download; "The data you export is what your chart shows you", so scroll/drag the x-axis left first (https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/). Launch post (2019): "Chart data (including ticker symbols & indicators) can now be saved into a CSV file... This feature is available on PRO+ & Premium plans." (https://www.tradingview.com/blog/en/export-chart-data-in-csv-14395)
- Plan today: "Chart data export" is listed as a key feature of Essential, Plus, Premium and Ultimate; "Historical bars available": Basic 5K, Essential 10K, Plus 10K, Premium 20K, Ultimate 40K (https://www.tradingview.com/pricing/). TradersPost adds minute-history limits: Essential 180 days, Plus 365 days, Premium/Ultimate all (https://blog.traderspost.io/article/tradingview-data-export).
- Granularities: any chart interval; the export is a snapshot of loaded bars (https://blog.traderspost.io/article/tradingview-data-export).
- Time format option in the dialog: "UNIX timestamp" (article says milliseconds but its example is `1595311200`) or "ISO time" (example `2020-07-21T06:00:00Z`) (https://quantnomad.com/how-to-grab-data-from-tradingview-charts-and-save-them-as-a-csv-file/). Inference: the 10-digit example is seconds, not milliseconds.

#### File layout
- CSV with header; "a CSV file containing OHLC, volume, and all indicators that you added to your chart" (https://quantnomad.com/how-to-grab-data-from-tradingview-charts-and-save-them-as-a-csv-file/); indicator plots become extra columns (https://blog.traderspost.io/article/tradingview-data-export).
- Column names (community readers of TradingView exports): "Reads the `time,open,high,low,close,...` export schema" (https://docs.rs/lorentzian-classification-core/latest/src/lorentzian_classification_core/csv_io.rs.html); "For TradingView intraday exports, the `time` column is a Unix timestamp encoding both date and time" (https://github.com/davidromeo/tradeblocks/blob/master/docs/market-data.md). Volume only appears if the Volume indicator is on the chart: "In Tradingview you have to put the volume indicator" (https://www.forexfactory.com/thread/1105502-tradingview-to-mt4-csv-converter). Exact volume column name/case: Not found.
- File name: Not found (user upload named `COINEX_WIFUSDT, 240.csv`, i.e. `EXCHANGE_SYMBOL, interval.csv`, seen in https://forum.optuma.com/t/importing-text-csv-files/6196; Inference only).
- Contract code: whatever the chart symbol is (e.g. `CME_MINI:ESH2024`-style) — Not found in docs.

#### Time zone and bar stamping
- UTC: ISO export example ends in `Z` (https://quantnomad.com/how-to-grab-data-from-tradingview-charts-and-save-them-as-a-csv-file/); Pine's `time` is "time zone-agnostic" UNIX time (https://www.tradingview.com/pine-script-docs/concepts/time/).
- Bar stamp: OPEN (Inference). Pine: "The time variable holds the UNIX timestamp of the current bar's opening time" and "time_close... the bar's closing time" (https://www.tradingview.com/pine-script-docs/concepts/time/). Inference: the exported `time` column is the same bar-open timestamp the chart uses.

#### Pitfalls
- Only loaded bars are exported; plan caps bars (https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/, https://www.tradingview.com/pricing/).
- The ISO column may carry an explicit GMT offset that must be split off (an Optuma support reply split the value on `T` and then on `+` "to separate the time and GMT offset") (https://forum.optuma.com/t/importing-text-csv-files/6196).
- Unit ambiguity (seconds vs milliseconds) in third-party descriptions; verify with a known bar (https://quantnomad.com/how-to-grab-data-from-tradingview-charts-and-save-them-as-a-csv-file/).
- No data API: "We don't have an API that gives access to data as of now" (quoted via https://blog.traderspost.io/article/tradingview-data-export).

#### Not found
- Official TradingView page listing the CSV columns or the UNIX unit.

---

### MultiCharts

#### How to export
- QuoteManager: `File → Export Data → ASCII` (or toolbar button / right-click symbol); select symbol(s); "The program always uses the symbol's Price Scale when exporting."; select Resolutions and Fields — "Data will be exported into separate files for each resolution and quote field"; options Export symbol, Export description, "Time Expressed in" (time zone), Export milliseconds, Start/End date-time, drag-and-drop column order; file types `Text files(*.txt)`, `ASCII files (*.asc)`, `Comma-separated values(*.csv)` (https://www.multicharts.com/trading-software/index.php/Exporting_Data).
- Stored resolutions are only 1 tick, 1 minute, 1 day ("Other resolutions are created from these") (https://www.multicharts.com/trading-software/index.php/Importing_Data). Staff: "You can export data from QuoteManager in different resolutions (Tick, Minute, Daily) and data types (Ask, Bid, Trade)... the sessions are not taken into account when exporting. You can export data directly from a chart and in that case resolution, sessions and time zone will be taken into account." (https://www.multicharts.com/discussion/viewtopic.php?t=54236)
- Chart export: `File → Export Data` with options "Export values for indicators based on symbol", "Export milliseconds option to switch time format to millisecond precision", "Export all available fields... e.g. UpVolume, UpTicks" (https://www.multicharts.com/trading-software/index.php/Exporting_Data_from_a_Chart).
- Scheduled export (`Tools → ASCII Export Scheduler`): selectable fields and order "Date, Time, Price, Volume, Open, High, Low, Close, TotVol, UpVol, DnVol, UpTicks, DnTicks, TotTicks, OI"; "Export Symbol Name, Export Description, Export Milliseconds"; Time Zone; "Append to Existing File" (https://www.multicharts.com/trading-software/index.php/ASCII_Export_Scheduler).
- Limits: Not found for export; ASCII files over 4 GB cannot be imported (https://www.multicharts.com/trading-software/index.php/Importing_Data).

#### File layout
- "Data is exported as comma-separated text files"; exportable fields "Symbol, Date, Time, Open, High, Low, Close, Volume, Up volume, Down volume, Unchanged volume, Up ticks, Down ticks, Unchanged ticks, Total ticks" (https://www.multicharts.com/downloads/datasheet.pdf).
- Tick files carry Date, Time, Price, Volume; minute files Date, Time, Open, High, Low, Close, Volume (+ up/down volume and tick counts); daily files Date, Open, High, Low, Close, Volume (+ counts, Open Interest) — these are the import field sets, which match the export field list (https://www.multicharts.com/trading-software/index.php/Importing_Data).
- Date and time text formats of the exported file, and whether a header row is written: Not found in the wiki, datasheet or forum. The importer recognises many templates (e.g. `*d mmm yyyy`, `*h:*m tt@pm`, milliseconds `*h:*m:*s:*f`) (https://www.multicharts.com/trading-software/index.php/Importing_Data, https://www.multicharts.com/discussion/viewtopic.php?p=100506).
- Prices: in the symbol's Price Scale (https://www.multicharts.com/trading-software/index.php/Exporting_Data). Aggressor/bid-ask on ticks: exported per "quote field" (Ask, Bid, Trade) as separate files, not side flags (https://www.multicharts.com/discussion/viewtopic.php?t=54236).
- Contract code form: Not found (symbol naming follows the data source).

#### Time zone and bar stamping
- Time zone is chosen per export ("Time Expressed in") (https://www.multicharts.com/trading-software/index.php/Exporting_Data); charts can be Local or Exchange time (https://www.multicharts.com/trading-software/index.php?title=What_Affects_Chart_Timestamps).
- Bar stamp: CLOSE (staff and community). Staff: "If your chart resolution is 10 seconds then bars close with 10 secs increment starting from the Session Start time... The bar will close at 9:53:20"; user: "I expect the assigned bar time to still be 9:53:20"; staff: "That is correct." (https://www.multicharts.com/discussion/viewtopic.php?t=47499). A user's plan "assuming bar times are end of bar and not beginning" was confirmed by staff: "Yes, the idea is correct." (https://www.multicharts.com/discussion/viewtopic.php?t=10687). Community: "MC uses the bar end time as the bar timestamp. So the hourly Bar that starts at 0400GMT is actually referenced as 0500" (https://www.elitetrader.com/et/threads/problem-with-multicharts-minute-bars.297646/). The ASCII Import Wizard has a "bar end time" setting (https://www.multicharts.com/downloads/datasheet.pdf).

#### Pitfalls
- Re-importing MultiCharts' own 1-minute ASCII export produced wrong candles until the Date template was set manually (https://www.multicharts.com/discussion/viewtopic.php?p=141875).
- Semicolon-separated files "are not being processed correctly and require adjustments" on import (https://www.multicharts.com/trading-software/index.php/Importing_Data).
- Millisecond times need the custom template `*h:*m:*s:*f` (https://www.multicharts.com/discussion/viewtopic.php?p=100506).
- Importing overwrites same-timestamp quotes without warning (https://www.multicharts.com/trading-software/index.php/Importing_Data).
- Daily charts are not session-aware by default; QuoteManager exports ignore sessions (https://www.multicharts.com/trading-software/index.php?title=What_Affects_Chart_Timestamps, https://www.multicharts.com/discussion/viewtopic.php?t=54236).
- Real-time bars are built on PC clock time; backfill timestamps come from the feed (https://www.multicharts.com/discussion/viewtopic.php?t=47499).

#### Not found
- A verbatim sample of a QuoteManager/chart ASCII export (header text, date/time formats).

---

### MotiveWave

#### How to export
- `Chart > Data > Export Data`: Symbol, Bar Size, Bar Count ("Choose All Available to export all available data in the historical database"), "Regular Trading Hours (RTH) Data", Data File, Format (https://docs.motivewave.com/user-guide/charts-1/exporting-data).
- Data Export Groups (`Configure > Settings > Historical Data > Data Export`): Data Format, "Time Zone – Select the time zone you would like the time stamps to be in (used for intraday data)", RTH only, Auto Export (requires restart), Export Directory; add instruments with bar size, amount of data and CSV filename; "any subsequent manual or automatic exported data group will be appended to the original CSV file" (https://docs.motivewave.com/user-guide/charts-1/data-export-groups).
- Granularities: any bar size in the historical database (https://docs.motivewave.com/user-guide/charts-1/exporting-data). Tick export: Not found (only `Chart > Data > Import Tick Data` is documented, CSV/ASCII with a Time Zone setting) (https://docs.motivewave.com/user-guide/charts-1/importing-tick-data).

#### File layout
- Format choices, verbatim: "CSV – yyyyMMdd HHmmss,O,H,L,C,V", "CSV – dd/MM/yyyy HH:mm:ss,O,H,L,C,V", "Ninja Trader – Start Of Bar Time", "Ninja Trader – End Of Bar Time" (https://docs.motivewave.com/user-guide/charts-1/exporting-data). Inference: comma-delimited, one combined date-time field followed by O,H,L,C,V; the two NinjaTrader formats follow NinjaTrader's `yyyyMMdd HHmmss;open;high;low;close;volume` semicolon layout (see NinjaTrader section).
- Header row, example lines, contract code form: Not found.

#### Time zone and bar stamping
- Export-group time zone is user-selected for intraday data (https://docs.motivewave.com/user-guide/charts-1/data-export-groups); for the ad-hoc dialog: Not found.
- Bar stamp: the two NinjaTrader formats make it explicit (start vs end); for the two plain CSV formats: Not found.

#### Pitfalls
- Export groups append to the existing CSV on every run (https://docs.motivewave.com/user-guide/charts-1/data-export-groups).
- Community import report (not read in full; from search summary): times like `0959` had to be zero-padded to import (https://forum.motivewave.com/threads/feedback-on-import-function.677).

#### Not found
- Header row presence, delimiter statement, and stamping convention of the plain CSV formats.

---

### Databento (CSV export)

#### How to export
- Batch download (`batch.submit_job`) with `encoding='csv'`, `compression` `'none'` or `'zstd'`, `pretty_px` ("If prices should be formatted to the correct scale (using the fixed-precision scalar 1e-9). Only applicable for 'csv' or 'json' encodings."), `pretty_ts` ("If timestamps should be formatted as ISO 8601 strings."), `map_symbols` ("If a symbol field should be included with every text encoded record. If `None`, will default to `True` for `csv` and `json` encodings and `False` for `dbn`."), `split_symbols`, `split_duration` ('day','week','month','year','none'; "A week starts on Sunday UTC"), `split_size` (1–10 GB), `stype_in` default `raw_symbol`, `stype_out` default `instrument_id`, `limit` (https://github.com/databento/databento-python/blob/main/databento/historical/api/batch.py). Note the batch defaults are `pretty_px=False`, `pretty_ts=False` (same file).
- Python client: `DBNStore.to_csv(path, pretty_px=True, pretty_ts=True, map_symbols=True, compression='none', schema=None, mode='w')` — "pretty_px... If all price columns should be converted from `int` to `float` at the correct scale (using the fixed-precision scalar 1e-9). Null prices are replaced with an empty string."; "pretty_ts... converted from UNIX nanosecond `int` to tz-aware UTC `pd.Timestamp`"; "map_symbols... create a 'symbol' column, mapping the instrument ID to its requested symbol for every record." (https://github.com/databento/databento-python/blob/main/databento/common/dbnstore.py)
- CLI: `dbn some.dbn --csv --limit 5` "will print the header row and the first 5 data rows" (https://github.com/databento/dbn/blob/main/rust/dbn-cli/README.md).
- Granularities: `ohlcv-1s`, `ohlcv-1m`, `ohlcv-1h`, `ohlcv-1d`, `trades` (plus book schemas); other intervals must be built client-side (https://databento.com/docs/schemas-and-data-formats/ohlcv).
- Limits: "There is no size limit for either stream or batch download requests... we recommend using batch download for requests over 5 GB"; up to 2,000 symbols per request (https://databento.com/docs/api-reference-historical, https://github.com/databento/databento-python/blob/main/databento/historical/api/batch.py).

#### File layout
- "Our CSVs have one header line, followed by one record per line. Lines use UNIX-style `\n` separators." (https://databento.com/docs/api-reference-historical)
- Column order: "When requesting data in CSV and JSON encodings, the first field will be set to this index timestamp [ts_recv if present, else ts_event]. Additionally, for schemas that contain `ts_recv`, the second field will be set to `ts_event`." (https://databento.com/docs/standards-and-conventions/common-fields-enums-types)
- `ohlcv-*` fields: `ts_event` (uint64, "inclusive start time of the bar aggregation period... nanoseconds since the UNIX epoch"), `rtype` (32/33/34/35 for 1s/1m/1h/1d), `publisher_id`, `instrument_id`, `open`, `high`, `low`, `close` (int64, "every 1 unit corresponds to 1e-9"), `volume` (uint64) (https://databento.com/docs/schemas-and-data-formats/ohlcv). With `map_symbols` a trailing `symbol` column is added (https://github.com/databento/databento-python/blob/main/databento/common/dbnstore.py). Third-party sample of a batch CSV with pretty options: header `ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol`, row `2020-11-01T23:00:00.000000000Z,34,1,18581,0.749250000,0.749300000,...` (https://rustybt.readthedocs.io/en/latest/guides/databento-data-import/).
- `trades` fields: `ts_recv`, `ts_event`, `rtype` (always 0), `publisher_id`, `instrument_id`, `action` (always `T`), `side` ("`A`sk for a sell aggressor in a trade, `B`id for a buy aggressor in a trade, or `N`one"), `depth`, `price` (int64 1e-9 units), `size` (uint32), `flags`, `ts_in_delta`, `sequence` (https://databento.com/docs/schemas-and-data-formats/trades); CSV puts `ts_recv` first then `ts_event` (https://databento.com/docs/standards-and-conventions/common-fields-enums-types).
- Pretty timestamp format: `[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:9]Z`, e.g. `1970-01-01T00:00:00.000000001Z`; a zero timestamp prints as empty; pretty prices print all 9 decimals, e.g. `32.500000000`, `-0.000100000`, and `UNDEF_PRICE` for the null sentinel (https://github.com/databento/dbn/blob/main/rust/dbn/src/pretty.rs).
- Raw (non-pretty) values: `ts_*` are integer nanoseconds since the UNIX epoch; prices are signed integers where 1 unit = 1e-9; `UNDEF_TIMESTAMP` = `UINT64_MAX` (https://databento.com/docs/standards-and-conventions/common-fields-enums-types).
- Contract code form: `raw_symbol` is the venue's string (CME examples `CLZ7`, `ESH1`); `instrument_id` "is only guaranteed to be unique within a given day" (https://databento.com/docs/api-reference-historical, https://databento.com/docs/standards-and-conventions/common-fields-enums-types). Batch zips also include `symbology.json`/`symbology.csv`, `metadata.json`, `manifest.json`, `condition.json` (https://rustybt.readthedocs.io/en/latest/guides/databento-data-import/).
- Batch job default file split is per day (https://github.com/databento/databento-python/blob/main/databento/historical/api/batch.py).

#### Time zone and bar stamping
- UTC: "By default, all of our data is set in UTC time zone." (https://databento.com/docs/standards-and-conventions/common-fields-enums-types)
- Bar stamp: OPEN. "The `ts_event` timestamp marks the start of each interval." "If no trade occurs within the interval, no record is printed." (https://databento.com/docs/schemas-and-data-formats/ohlcv)
- `ohlcv-1d` "is based on UTC dates", not exchange sessions, and may differ from official settlement/volume (https://databento.com/docs/schemas-and-data-formats/ohlcv).

#### Pitfalls
- Zero-trade intervals are omitted (https://databento.com/docs/schemas-and-data-formats/ohlcv).
- Batch defaults are raw ints (`pretty_px=False`, `pretty_ts=False`) while `to_csv` defaults are pretty (https://github.com/databento/databento-python/blob/main/databento/historical/api/batch.py, https://github.com/databento/databento-python/blob/main/databento/common/dbnstore.py).
- `ts_event` can be non-monotonic ("any non-monotonicity in the original data will remain"); `ts_recv` is monotonic per symbol and leap-second adjusted at session end (https://databento.com/docs/standards-and-conventions/common-fields-enums-types).
- `instrument_id` reuse across days; prefer the `symbol` column or symbology file (https://databento.com/docs/standards-and-conventions/common-fields-enums-types).

#### Not found
- An official (Databento-hosted) verbatim CSV sample with `pretty_*` on (the docs pages are JS-rendered; the sample above is third-party).

---

### Tradovate

#### How to export
- No built-in bar/tick export found. Tradovate staff: "Although you are able to export CSVs for your own activity using Account Reports, I doubt that this will suit your needs... to record it in CSV format you would need to tap into our REST API and write an application to filter out and record those values manually. (P.S. exporting Account Reports is not supported for market replay...)" (https://community.tradovate.com/t/historical-data-queries/2807).
- History available in the app (user-quoted Tradovate statement): "Tick and Tick-based charts (including Bid-Ask Volume) - 2 weeks; Minute-based charts - Back to a historical date of 1/1/2017; Day-based charts - Back to a historical date of 1/1/2017"; staff: "We don't have a way to request the chart to go to a specific day, nor is there a way to show an expired contract in the workspace (except for replay workspaces)"; an add-on "under Application Settings > Add-ons" gives "365 days of tick data in your charts" (https://community.tradovate.com/t/how-to-access-historical-data/565).

#### File layout
- Not applicable (no export); Account Reports CSV covers orders/fills only (https://community.tradovate.com/t/historical-data-queries/2807).

#### Time zone and bar stamping
- Not found (no export).

#### Pitfalls
- Charts load limited history unless scrolled; profiles built from tick data are throttled (https://community.tradovate.com/t/how-to-access-historical-data/565).

#### Not found
- Any official help-center article describing chart-data export; any documented bar timestamp convention for the API.

---

### Rithmic R|Trader Pro

#### How to export
- No bulk historical bar/tick export. Broker (Optimus Futures) after contacting Rithmic: "the functionality of mass exportation of historical data from R Trader to Microsoft Excel is not possible. The scope of Excel integration with R Trader or R Trader Pro is primarily used to execute orders through Excel or monitor live quotes" (https://community.optimusfutures.com/t/r-trader-historical-mass-download-to-excel/3136).
- Rithmic markets "Stream live quotes, P&L, and order data directly from any R | Trader Pro window into Excel" and "Historical data back to December 2011" (https://www.rithmic.com/products/r-trader-pro) — i.e. live links, not file export.
- What can be exported as CSV: order history (`File > Order History`, one day at a time, only visible columns) (https://community.optimusfutures.com/t/export-all-trades-order-history/5965, https://journalit.co/docs/broker-guides-rithmic). Time & sales ("Market data trade history") to Excel exists as a live window feature (https://community.optimusfutures.com/t/market-data-trade-history-time-and-sales-to-excel-on-r-trader-pro-rithmic/4052).
- Programmatic route: R|API+ tools such as RapiBarFetch "downloads historical minute and second bars via Rithmic's R|API+" and can write NINJA or CSV bar files with times "converted to US/Eastern" (https://github.com/squideyes/RapiBarFetch); Rithmic imposes weekly gigabyte limits on historical downloads (https://www.overcharts.com/en/helpcenter/docs/rithmic/).

#### File layout
- Not applicable for bars. Order-history CSV timestamps carry no offset; the column header names the zone, e.g. `Last Fill Time (CDT)` (https://docs.tradeways.app/import/rithmic).

#### Time zone and bar stamping
- Not found (no bar export).

#### Pitfalls
- Hidden grid columns are not exported; one day per export (https://journalit.co/docs/broker-guides-rithmic, https://community.optimusfutures.com/t/export-all-trades-order-history/5965).

#### Not found
- Any R|Trader Pro chart/bar export feature or file format.

---

### Interactive Brokers TWS

#### How to export
- Price History window: "The Price History shows the Open, High, Low, Close and Volume by date... use the 'Options' button at the bottom of the scroll bar to go to a specific date/time, export the current table to Excel, and show splits/dividends" (https://www.ibkrguides.com/traderworkstation/price-history.htm). Broker walkthrough: right-click instrument → Analysis tools → Historical price developments → Options → Export → choose start/end date (https://www.captrader.com/en/export-data-from-tws/).
- Intraday from the GUI: "the TWS does not have functionality to export intra-day, customers are often directed at the TWS API and its Excel sheets" (https://interactivebrokers.github.io/tws-api/dde_realtime_tutorial.html).
- Excel/DDE historical query: end date `yyyymmdd hh:mm:ss`, duration (e.g. `1 D`, `1 W`, `1 Y`), bar size codes (1 SEC=1 ... 1 MIN=5 ... 1 DAY=11), what-to-show (MIDPOINT, TRADES, BID, ASK, BID_ASK), RTH flag, date format "1... yyyymmdd{space}{space}hh:mm:dd... 2... number of seconds since 1/1/1970 GMT"; "API historical data requests allow you to extract the entire previous calendar year" (https://www.interactivebrokers.co.uk/en/general/education/pdfnotes/PDF-TwsExcelAPI.php/1000, https://interactivebrokers.github.io/tws-api/dde_historical_tutorial.html).
- API bars: `Bar(time, open, high, low, close, volume, count, wap)`; "Volume... only available for TRADES", "WAP... only available for TRADES", "Count... number of trades during the bar's timespan" (https://interactivebrokers.github.io/tws-api/classIBApi_1_1Bar.html). Sync-API sample: `Date: 20251013, Open: 249.31, High: 249.69, Low: 245.56, Close: 247.66, Volume: 187465.43, WAP: 247.952, BarCount: 105768` (https://www.interactivebrokers.com/docs/tws-api/sync-doc/historical-market-data.md).
- Granularities via API: 1 sec to 1 month bars (https://www.interactivebrokers.co.uk/en/general/education/pdfnotes/PDF-TwsExcelAPI.php/1000); GUI Price History: daily rows (https://www.ibkrguides.com/traderworkstation/price-history.htm).
- Limits: pacing violations on repeated requests (https://www.interactivebrokers.co.uk/en/general/education/pdfnotes/PDF-TwsExcelAPI.php/1000).

#### File layout
- Price History export is an Excel file; its columns are OHLC and Volume by date (https://www.ibkrguides.com/traderworkstation/price-history.htm). Delimiter/date format: Not found.
- API `formatDate=1` gives `yyyymmdd hh:mm:ss` strings ("for day bars, only yyyyMMdd format is available"); `formatDate=2` epoch seconds (https://interactivebrokers.github.io/tws-api/historical_bars.html). Newer TWS accepts `yyyymmdd-hh:mm:ss` UTC and `IBM 20220930-15:00:00 US/Eastern` style fields (https://interactivebrokers.github.io/tws-api/historical_data.html). A pandas example parses bar dates with `'%Y%m%d %H:%M:%S'` after stripping a trailing time-zone token (https://www.interactivebrokers.com/campus/ibkr-quant-news/using-pandas-for-market-data-management/).
- Volume: "Historical data at IB is filtered for trade types which occur away from the NBBO... the daily volume from the (unfiltered) real time data functionality will generally be larger than the (filtered) historical volume" (https://interactivebrokers.github.io/tws-api/historical_data.html); stock volume is in lots in older APIs (the decimal `Volume: 187465.43` above suggests hundreds — Inference).
- Contract code form: IB uses `localSymbol` like `ESH4`-style and conId; Not found in the export pages read.

#### Time zone and bar stamping
- "The time zone of returned bars is the time zone chosen in TWS on the login screen." (https://interactivebrokers.github.io/tws-api/historical_bars.html)
- Bar stamp: Not found as an explicit statement. Inference: IB's `Time` field with `keepUpToDate` returning "updates of the most recent partial five-second bar" labelled by its start suggests start-of-bar stamping, but this is not stated.

#### Pitfalls
- Missing bars on holidays are expected; DDE sample shows 3-day request returning 20200904 as last bar for a 20200909 end (https://www.interactivebrokers.com/campus/trading-lessons/diagnosing-issues-and-troubleshooting-with-the-tws-api/).
- Expired futures history "only going back a few years"; no history for expired options (https://www.interactivebrokers.com/campus/?p=116840).
- Market data subscription required for historical data via API (https://interactivebrokers.github.io/tws-api/historical_data.html).

#### Not found
- A TWS chart "export to CSV" command and the Price History Excel file's exact layout.

---

### Generic CSV conventions: Backtrader, Zipline, QuantConnect Lean

#### Backtrader
- `GenericCSVData` defaults: `headers=True`, `separator=','`, `datetime=0`, `time=-1` (separate time column absent), `open=1`, `high=2`, `low=3`, `close=4`, `volume=5`, `openinterest=6` (`-1` = not present), `dtformat='%Y-%m-%d %H:%M:%S'`, `tmformat='%H:%M:%S'`, `nullvalue=NaN`; `dtformat` may be `1` (Unix seconds int) or `2` (Unix float) or a callable (https://www.backtrader.com/docu/dataautoref/, https://www.backtrader.com/docu/datafeed/).
- Inference: the default layout is `datetime,open,high,low,close,volume,openinterest` with `YYYY-MM-DD HH:MM:SS` timestamps; bar stamping is whatever the file says (Backtrader does not shift).
- `YahooFinanceCSVData`: `adjclose=True`, `round=True`, `swapcloses=False`, `reverse=False` ("locally stored files have already been reversed"); lines include `adjclose` (https://www.backtrader.com/docu/dataautoref/). Column names are not spelled out in the reference page (Not found there).

#### Zipline (csvdir bundle)
- "The format of the files should be in OHLCV format, with dates, dividends, and splits." Sample: `date,open,high,low,close,volume,dividend,split` then `2012-01-03,58.485714,58.92857,58.42857,58.747143,75555200,0.0,1.0`; files go in `daily`/`minute` folders and are registered via `csvdir_equities(['daily'], '/path/...')` (https://zipline.ml4trading.io/bundles.html).
- Inference: one CSV per ticker named by symbol (the registration takes a directory); daily dates are session dates.

#### QuantConnect Lean
- "Each data file is a CSV file in a zip archive. Each line of the CSV file is one data point, and the file has no header row." "The first column of every row is the time. In tick, second, and minute files, the time is the number of milliseconds since midnight of the file date... In hour and daily files, the time has the YYYYMMDD HH:mm format, such as 20140606 00:00. The time of a bar is the start of its period." "US Equity, Equity Options, and Index Options files store prices multiplied by 10,000... The files of the other asset classes store the actual prices." "If a security has no activity in a period, the file has no row for that period." Times are in the security's `dataTimeZone` from `market-hours-database.json` (https://www.quantconnect.com/docs/v2/lean-engine/data-format/key-concepts).
- US equity minute trade bar: `15300000,6448000,6448000,6448000,6448000,90`; quote bar: `14400000,6438000,6440600,6438000,6440600,100,6460000,6460000,6460000,6460000,100` (bid OHLC, bid size, ask OHLC, ask size); path `equity / usa / minute / aapl / 20140605_trade.zip` containing `20140605_aapl_minute_trade.csv`; data time zone America/New_York (https://www.quantconnect.com/docs/v2/lean-engine/data-format/us-equity).
- Futures: actual prices; "the data time zone of the cme and comex markets is UTC"; minute trade bar `79200000,1676.75,1677.25,1673.5,1675.25,1884`; quote bar `68400000,1681.5,1681.5,1681.5,1681.5,5,1682,1682,1682,1682,19`; open interest `72360000,2691941`; files per contract, e.g. `20131006_es_minute_quote_201312.csv` (contract month `YYYYMM`), daily `es_quote_201312.csv` (https://www.quantconnect.com/docs/v2/lean-engine/data-format/futures).
- Tick rows: equity trade tick `Time(ms since midnight),Price*10000,Quantity,Exchange,SaleCondition(hex),Suspicious`; futures trade tick `Time,Price,Quantity,Exchange,SaleCondition,Suspicious` (https://www.quantconnect.com/docs/v2/lean-engine/data-format/us-equity, https://www.quantconnect.com/docs/v2/lean-engine/data-format/futures).
- Bar stamp: OPEN ("The time of a bar is the start of its period") (https://www.quantconnect.com/docs/v2/lean-engine/data-format/key-concepts).

---

### Summary table

| Platform | Granularities | Delimiter/header | Timestamp format | Time zone | Open or close stamp | Contract code form | Confidence |
|---|---|---|---|---|---|---|---|
| NinjaTrader 8 | Tick, Minute, Day (Last/Bid/Ask) | `;` no header | `yyyyMMdd HHmmss[ fffffff]` (day: `yyyyMMdd`) | UTC always | CLOSE (end-of-bar; daily = ETH session close date) | file name `ES 12-09.Last.txt` | documented (tick 4-field layout: community) |
| Sierra Chart `.scid` | tick ... 1 min records | binary 56-byte header + 40-byte records | int64 microseconds since 1899-12-30 | UTC | record = first trade time in aligned unit | `[symbol].scid` | documented |
| Sierra Chart text exports | chart bar period / stored records; `.dly` daily | `,` (or tab) with header `Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume`; `.dly`: `Date, Open, High, Low, Close, Volume, OpenInterest` | `YYYY/MM/DD`, `hh:mm:ss` (day may be unpadded) | intraday-file export UTC; bar export chart TZ; daily = exchange TZ | OPEN | symbol-named files | documented |
| TradeStation | chart interval (Data Window) | `.txt` from Data Window: not documented; TS ASCII layout `Date,Time,Open,High,Low,Close,Vol,OI` | `MM/DD/YYYY`, `HHMM` (community sample) | chart/Windows TZ (Format Symbol) | CLOSE | not found | community (layout) / documented (stamping) |
| TradingView | any chart interval; 5K–40K bars by plan | `,` with header `time,open,high,low,close[,Volume,indicators...]` | UNIX seconds (10-digit) or ISO `2020-07-21T06:00:00Z` | UTC | OPEN (inference from Pine `time`) | chart symbol; file like `EXCH_SYM, 240.csv` (inference) | community (columns) / documented (plans, menu) |
| MultiCharts | tick, 1 min, daily (QuoteManager); chart res. (chart export) | comma per datasheet; header not documented | not found (ms option) | selectable (`Time Expressed in`) | CLOSE (staff/community) | not found | community |
| MotiveWave | any bar size; "All Available" | comma; header not documented | `yyyyMMdd HHmmss` or `dd/MM/yyyy HH:mm:ss`; NinjaTrader variants | selectable in export groups | NinjaTrader formats explicit start/end; CSV formats not found | not found | documented (formats) / not found (stamping) |
| Databento CSV | ohlcv-1s/1m/1h/1d, trades | `,` with header; index ts first | ISO `2020-11-01T23:00:00.000000000Z` (pretty) or int ns | UTC | OPEN (`ts_event` = interval start) | `raw_symbol` e.g. `ESH1`, `CLZ7` + `instrument_id` | documented |
| Tradovate | none (API only) | n/a | n/a | n/a | not found | n/a | not found (export absent: community/staff) |
| Rithmic R|Trader Pro | none (orders CSV only; R|API+ for bars) | n/a | n/a | header-suffix TZ on order CSV | not found | n/a | not found (export absent: broker-confirmed) |
| IB TWS | daily (Price History to Excel); 1 sec–1 month via API/Excel DDE | Excel file; API strings | `yyyymmdd hh:mm:ss` or epoch seconds (API) | TWS login time zone | not found | IB localSymbol (not found in export docs) | documented (API) / not found (chart CSV) |
| Backtrader GenericCSVData | any | `,` header | `%Y-%m-%d %H:%M:%S` default; Unix int/float optional | as in file | as in file | n/a | documented |
| Zipline csvdir | daily, minute | `,` header `date,open,high,low,close,volume,dividend,split` | `YYYY-MM-DD` | as in file | as in file | one file per ticker (inference) | documented |
| QuantConnect Lean | tick, second, minute, hour, daily | `,` no header, zipped | ms since midnight (intraday) / `YYYYMMDD HH:mm` (hour, daily) | per-security dataTimeZone (NY for US equity, UTC for CME) | OPEN | `es_quote_201312.csv` (contract `YYYYMM`) | documented |
