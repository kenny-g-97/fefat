# Research: market data for CME futures and crypto (as of 2026-10-05)

> Provenance: research by a Claude subagent on 2026-10-05 from vendor and exchange pages. A statement with a link is a sourced fact (with the page date where one was visible). **Inference** marks the researcher's reasoning or arithmetic. "Not found" means it was searched for and not located.
>
> How FEFAT uses this: Phase 1 (market data) builds the Databento importer and the Binance archive importer described here, and `07-tools-and-costs.md` carries the purchase guidance. The licensing section is why FEFAT is local-first: customers bring their own data and FEFAT never hosts or ships market data.

## Bottom line

- **Personal phase:** Databento for CME and Binance's free archive for crypto. CME data costs about $199 at minimum (one month of the Standard plan), or about $1.2–2.5k if you want five years of ticks. Crypto data is free.
- **A hosted SaaS would need real licences:** Databento Plus plus CME licences, about $21k/yr, rising to $127k+/yr if users can export data. The major free crypto archives (Binance Vision, OKX, Coinbase) have been non-commercial since their mid-2026 terms updates.
- **Local-first is the cheapest compliant model:** the engine runs on the user's machine with the user's own data. Get written confirmation from the vendor before relying on it for a product.

## 1. CME futures: options compared

**Table 1. Sources that offer tick data**

| Source | Data types | History | Delivery / libraries | Price | Continuous contracts / instrument definitions | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| **Databento** | Full order book (MBO), 10-level depth (MBP-10), top-of-book (MBP-1), trades with the prior bid/ask (TBBO), trades, sampled bid/ask (BBO-1s/1m), OHLCV-1s/1m/1h/1d, definitions, statistics, status | From 2010-06-06. Capture timestamps only from 2017-05-21 ([ES catalog](https://databento.com/catalog/cme/GLBX.MDP3/futures/ES), [KB](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3)) | Streaming API and batch files; DBN, CSV, JSON, Parquet. Official Python, Rust and C++ clients | Pay per GB; Standard $199/mo; Plus $1,750/mo; Unlimited $4,500/mo ([pricing](https://databento.com/pricing)) | `ES.c.0` / `.v.0` / `.n.0`, unadjusted ([symbology](https://databento.com/docs/standards-and-conventions/symbology)). Definitions include `min_price_increment`, `unit_of_measure_qty`, `expiration` ([record.rs](https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs)) | Internal business use only. Redistribution must comply with exchange terms and carry attribution ([agreement](https://databento.com/legal/databento-user-agreement)). "External distribution" starts at the Plus plan ([pricing](https://databento.com/pricing)) |
| **Massive** (formerly Polygon) | Trades and top-of-book quotes (ns timestamps); 1-second, 1-minute and session bars; contract and schedule reference data | Records from 2017-04-03 ([docs](https://massive.com/docs/rest/futures/aggregates.md)); plans allow 2, 5 or 7+ years | REST, WebSocket, S3 CSV files; Python, Go, JS, Kotlin ([blog](https://www.massive.com/blog/futures-data-has-arrived)) | $0 / $29 / $79 / $199 per month for individuals ([pricing](https://massive.com/pricing?product=futures)); Business $999/mo per exchange ([business](https://massive.com/business-futures)) | Continuous contracts not found in the docs. Contract data has tick sizes and first/last trade dates; no multiplier field found ([contracts](https://massive.com/docs/rest/futures/contracts.md)) | Individual plans are for own use; showing data to your users needs a commercial licence ([KB](https://massive.com/knowledge-base/article/how-can-i-redistribute-massives-market-data)) |
| **TickData** | Tick trades and top-of-book quotes | From Jul 2003; millisecond stamps from Jul 2011 ([product](https://www.tickdata.com/product/historical-futures-data)) | TickWrite software, TickAPI, zipped CSV | TickAPI: 1-year minimum, $250/mo minimum, $2.00→$0.26 per symbol-month, $0.03 per request, $250/yr support ([TickAPI](https://www.tickdata.com/data-delivery/tickapi)). Store minimum order $1,000 ([store](https://www.tickdata.com/tickdatastore)) | Continuous series built in TickWrite | Not found |
| **Kibot** | Ticks, ticks with bid/ask, 1s, 10s, 1–30 min, daily | From 2009 | CSV | "Top 10" continuous: 1-min $220, 1-sec $450, ticks + bid/ask $800. All futures including individual contracts: up to $3,750. Updates $139/mo ([buy](http://www.kibot.com/Buy.aspx)) | Roll method not stated | Personal/internal, two computers, no redistribution ([licence](http://www.kibot.com/license.html)) |
| **Portara / CQG** | Top-of-book ticks (2014+), 1-min (1987+), daily | — | Portara software, text files ([PortaraNinja](https://portaraninja.com/), [CQG](https://www.cqg.com/products/historical-data)) | Not shown on vendor pages | Custom back-adjusted series | Not found |
| **dxFeed** | Ticks, top-of-book, depth, OHLCV; "since 1998" | — | APIs (incl. Python), CSV ([page](https://dxfeed.com/data-services/historical-data-services/)) | Quote only | Not found | Not found |
| **IQFeed** | Ticks for 180 days only; 11+ years of 1-min ([page](https://www.iqfeed.net/index.cfm?displayaction=data&section=services)) | — | Windows client + socket API | $108.15/mo core + $24.87 futures surcharge + exchange fees (effective 2025-12-01) ([fees](https://iqhelp.dtn.com/core-service-fees/)) | Not checked | Not found |
| **CME DataMine** | Order book, depth, top-of-book, time & sales ([FAQ](https://cmegroup.com/market-data/datamine-faq.html)) | Some products back to the 1970s | Cloud portal | Quote in portal | Exchange definitions | Direct CME licence |

**Table 2. Bars only, daily data and platform exports**

| Source | What you get | Price | Licence |
| --- | --- | --- | --- |
| FirstRate Data | 1/5/30/60-min and daily bars. ES/NQ from 2008-01-02. All individual contracts plus unadjusted, absolute-adjusted and ratio-adjusted continuous series. Rolls at 00:00 ET on custom rules. Timestamps in US Eastern, stamped at bar open; minutes with no trades are omitted ([ES](https://firstratedata.com/i/futures/ES), [FAQ](https://firstratedata.com/about/FAQ), [rolls](https://firstratedata.com/about/price_adjustment)) | One-off prices not shown. Updates $99.95/yr per ticker; $59.95/mo for the 130-contract bundle ([bundle](https://firstratedata.com/b/29/futures-most-active)) | Charts and backtest results allowed commercially; giving users raw data is not ([FAQ](https://firstratedata.com/about/FAQ)) |
| Norgate | Daily only, about 100 futures, from about 1980. Unadjusted and arithmetic back-adjusted series. Rolls the day before last trade, or before first notice day for physically delivered contracts ([page](https://norgatedata.com/futurespackage.php)) | $148.50 per 6 months; $270/yr | "No commercial use" ([subscribe](https://norgatedata.com/subscribe/subscribe.php)) |
| Sierra Chart | Tick-by-tick for popular CME contracts from about 2011 (third-party claim, [Optimus](https://optimusfutures.com/Sierra-Chart.php)) | Packages $26–56/mo plus exchange fees ([packages](https://www.sierrachart.com/index.php?page=doc/Packages.php)) | Not found |
| NinjaTrader | Ticks kept 1 year, minute data from about 2006 (staff forum post, [forum](https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1246489-where-can-i-get-older-tick-data)) | Comes with the platform | Not found |
| Tradovate | About 2 months of ticks; about 1 year with a $9.95/mo add-on (third-party, [source](https://pickmytrade.trade/how-to/tradovate-historical-data/)) | — | Not found |
| Rithmic | About 10,000 ticks maximum per replay request ([docs](https://async-rithmic.readthedocs.io/en/stable/historical_data.html)) | — | Not found |
| Interactive Brokers | Bars only. Expired futures unavailable more than 2 years after expiry. Bars of 30 seconds or less unavailable beyond 6 months ([IBKR](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/unavailable-historical-data)) | Market-data subscriptions | Not found |
| Barchart | Premier membership allows downloads | $29.95/mo in a 2020 help article; current price not verified ([help](https://help.barchart.com/support/solutions/articles/242752-what-are-the-benefits-and-cost-of-a-premier-subscription-)) | Not found |

**Inference:** Databento is the only CME vendor reviewed that combines every contract tick-by-tick with top-of-book, settlement prices and instrument definitions, pay-per-use pricing, and official Rust crates. Massive is a cheaper second source from 2017 but has no continuous contracts. FirstRate has the most product-friendly licence, but no futures tick data was found.

## 2. Databento in detail

**Plans** ([pricing](https://databento.com/pricing); Standard rose from $179 to $199 on 2026-06-22 per [this post](https://databento.com/blog/updates-to-subscription-pricing)):

- **Usage-based:** historical data only, pay per GB.
- **Standard, $199/mo:** live data with exchange licence fees included for up to 2 devices; 16+ years of "L0" history (all OHLCV bars, definitions, statistics, status); 1 year of "L1" history (trades, TBBO, MBP-1, sampled bid/ask); 1 month of order-book history; pay per GB beyond that.
- **Plus, $1,750/mo (annual contract):** 16+ years of L1 history and "External distribution".
- **Unlimited, $4,500/mo (annual contract):** 16+ years of every schema.
- **Free credit:** $125, for historical data only, expires 6 months after signup, one per team.

**Per-GB rates.** The pricing page no longer prints them. The latest published sheet ([2024-12-11](http://databento-media.s3-website-us-east-1.amazonaws.com/media/unit-pricing-2024-12-11.pdf)) lists CME historical rates per GB:

| Schema | $/GB |
| --- | --- |
| Trades, TBBO | $28 |
| OHLCV-1s, OHLCV-1m | $70 |
| OHLCV-1h, OHLCV-1d | $190 |
| MBP-1, MBO | $1.80 |
| MBP-10 | $0.50 |
| Definitions | $1.70 |
| Statistics | $1.00 |

These rates reproduce two real quotes to the cent: Databento's own example of 1,735,003 ESH4 trades over 12–16 Feb 2024 costing $2.17 ([blog](https://databento.com/blog/api-demo-python)), and a July-2026 user report of full-history MES + MNQ 1-min bars, 419.5 MB, quoted at $27.35, with full CL history at about 4.8 GB, about $315 ([Reddit mirror](https://reddit.sentinel-team.org/posts/1ut17wm/snapshots/2026-07-12T20%3A11%3A36.310762Z)).

**Inference:** billing is per GiB of uncompressed DBN. Record sizes are 48 bytes per trade, 80 per TBBO/MBP-1 row and 56 per bar. The L1 rates have not been re-verified since 2024. Run `metadata.get_cost` (free) before buying.

**Table 3. Five-year estimate, about 1,260 sessions, front month only (all inference)**

| Schema | ES rows per day | ES, 5 years | 8 products: ES, NQ, CL, GC, MES, MNQ, MCL, MGC (≈3–5× ES activity) |
| --- | --- | --- | --- |
| OHLCV-1m | up to 1,380 | 0.1 GB, ≈ $6 | 0.6–0.8 GB, ≈ $40–50; $0 extra on Standard |
| OHLCV-1s | 40–60k (estimate) | 2.8–4.2 GB, ≈ $185–275 | 8–21 GB, ≈ $0.6–1.4k; $0 extra on Standard |
| Trades | 265–350k ([Databento staff post](https://www.elitetrader.com/et/threads/how-big-is-x1-day-s-p-500-e-mini-data-file-for-tick-l1-and-lob-l2.380833/), [blog](https://databento.com/blog/api-demo-python)) | 16–21 GB, ≈ $420–550 | 48–106 GB, ≈ $1.3–2.8k |
| TBBO | same row count as trades | 27–35 GB, ≈ $700–920 | 80–176 GB, ≈ $2.1–4.6k |
| MBP-1 | about 4.9M on a quiet day ([same post](https://www.elitetrader.com/et/threads/how-big-is-x1-day-s-p-500-e-mini-data-file-for-tick-l1-and-lob-l2.380833/)) | about 490 GB, $820 or more | 1.5–2.5+ TB, $2.5–4k or more |

- Standard's included 12 months cuts the trades/TBBO/MBP-1 costs by about 20%.
- zstd-compressed files are about 31% of these sizes (same post).
- Pulling every expiry and spread is much bigger for curve-heavy products. CL's full history is about 4.8 GB, versus about 0.3 GB for the front month alone (≈15×, inference).

**Continuous-contract symbology** ([docs](https://databento.com/docs/standards-and-conventions/symbology)):

- Format is `[ROOT].[ROLL_RULE].[RANK]`, with rank 0 the front contract. `c` (calendar) is the offset from the nearest expiry; `n` ranks contracts by open interest at the previous day's close; `v` ranks them by the previous day's volume.
- Prices are "original, unadjusted": Databento does no back-adjustment.
- `ES.FUT` returns every ES contract, including spreads.
- Symbol mappings come as date ranges. Whether a mapping switches at 00:00 UTC or at the 17:00 CT session open: not found.
- Raw symbols get reused across years (e.g. ESZ6 in 2016 and 2026).

**DBN format and libraries:**

- DBN is fixed-width binary records with a metadata header. It compresses well with zstd and is Apache-2.0 ([repo](https://github.com/databento/dbn)).
- Rust crates `dbn` 0.71.0 ([docs.rs](https://docs.rs/crate/dbn/latest)) and `databento` 0.63.0 (tokio-based, with `historical`/`live` features; [docs.rs](https://docs.rs/crate/databento/latest)) were both released on 2026-09-29.
- The Python client has `to_df` and `to_parquet` ([Parquet post](https://databento.com/blog/parquet-python)).
- Prices are int64 in units of 1e-9; timestamps are nanoseconds since epoch, UTC.
- OHLCV bars: `ts_event` is "the inclusive start time of the bar aggregation period based on the ts_recv from trade messages" ([docs](https://databento.com/docs/schemas-and-data-formats/ohlcv)).
- CME history was re-normalised retroactively on 2026-08-08 ([blog](https://databento.com/blog/cme-normalization-changes-2026-07)); keep raw files immutable with a manifest so a re-download can be detected.

## 3. Licensing for a product

**CME rules.** ES/NQ/MES/MNQ trade on the CME exchange, CL/MCL on NYMEX and GC/MGC on COMEX, so a hosted product would need licences for three exchanges.

- **Time categories:** real-time is within 10 minutes; delayed is 10 minutes to 8 hours; historical is 8 hours or more.
- **Historical distribution licence:** "Any entity that distributes Historical Information must hold a Historical Distribution License for each applicable" exchange ([guidelines](https://www.cmegroup.com/market-data/distributor/files/cme-group-data-licensing-policy-guidelines-historical-information-distribution.pdf)).
- **Feed fee:** any download, export or API access by users triggers a "Subscriber Feed" fee. View-only charts still need the licence but not that fee.
- **Subscriber agreements:** required with every subscriber.
- **2026 fees per exchange** ([fee list](https://api.databento.com/static/licensing/cme/cme-market-data-fee-list.pdf), effective 2026-01-01):

| Item | Fee |
| --- | --- |
| Historical distribution via data feed | $35,220/yr |
| Real-time distribution | $29,280/yr |
| Delayed distribution | $21,840/yr |
| Professional display device | $134.50/mo |
| Non-pro top-of-book device | $1.55/mo ($4.65 for all four CME exchanges) |
| Non-pro depth device | $12.10/mo ($36.50 for all four) |
| Public website | $487/mo |

- Whether view-only historical distribution carries any fee: not found.
- **Backtesting on your own servers:** non-display use of historical data alone "must be licensed, but is not reportable and carries no fees at this time." CME's policy applies whether data comes from CME directly or from a vendor ([non-display FAQ](https://www.cmegroup.com/market-data/distributor/files/cme-group-data-licensing-policy-guidelines-and-non-display-licensing-faq.pdf)).
- **Trend:** CME is tightening. Free end-of-day licences and website fee waivers ended in April 2025 ([notice](https://www.cmegroup.com/market-data/files/fee-and-policy-adjustments-futures-and-options-september-2025.pdf), [WatersTechnology, 2026-02-24](https://www.waterstechnology.com/data-management/7952957/cme-rankles-market-data-users-with-licensing-changes)).

**Databento User Agreement** (effective 2024-01-31, [link](https://databento.com/legal/databento-user-agreement)):

- §1.1: the licence is "solely for its internal business purposes".
- §1.3: only the customer's employees and contractors may use it, and credentials must not be disclosed to third parties.
- §1.5(e): "Redistribution" includes furnishing "information derived from the same to entities other than Customer". It's allowed only where exchange terms permit.
- §1.6: redistributed data must carry the attribution "Data Provided by Databento".

Databento's own licensing guide says "we don't recommend" bring-your-own-data for hosted products ([guide](https://databento.com/blog/introduction-market-data-licensing)).

**Is bring-your-own-data accepted?** No CME or Databento page endorses a hosted bring-your-own-key model. QuantConnect, the closest real-world example, takes the user's own Databento key but downloads historical data only to the user's machine through its local CLI; its cloud only streams live data ([CLI](https://www.quantconnect.com/docs/v2/lean-cli/datasets/databento), [cloud](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/databento)). **Inference:** bring-your-own-data keeps a product out of "distribution" only if the product never receives, stores or serves the data — the desktop-platform model, which is what FEFAT adopts. FirstRate's licence explicitly lets a service provider host data on the subscriber's behalf ([licence](https://firstratedata.com/about/license)).

## 4. Crypto

**Table 4. Free exchange data**

| Venue | Free history | Depth, format, limits | Commercial use |
| --- | --- | --- | --- |
| Binance | data.binance.vision: spot and futures klines (1s to 1 month), trades, aggTrades. USD-M perpetuals also have funding rates, open-interest metrics and mark/index/premium klines. Top-of-book (bookTicker) only covers 2023-05 to 2024-04 ([repo](https://github.com/binance/binance-public-data)) | Spot 1-min from 2017-08; perp trades from 2019-09; funding from 2020-01; open interest from 2020-09. Zipped CSV with checksums. Spot timestamps in microseconds since 2025-01-01. REST limits 6,000 (spot) / 2,400 (USD-M) request weight per minute ([spot](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits), [futures](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)) | Terms "Last Updated: August 26, 2026": CC BY-NC-SA. Personal non-production backtesting is allowed; commercial use needs an enterprise licence; hosting the data is prohibited ([terms](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md)) |
| Bybit | public.bybit.com: perp trades (BTCUSDT from 2020-03-25), spot trades (from 2022-11) ([trading](https://public.bybit.com/trading/BTCUSDT/), [spot](https://public.bybit.com/spot/BTCUSDT/)) | csv.gz. "IP addresses located in the US or Mainland China are restricted" ([docs](https://bybit-exchange.github.io/docs/v5/guide)) | API terms (2026-01-16) bar repackaging or commercially exploiting the data ([Bybit](https://www.bybit.com/en/help-center/article/API-Terms/)) |
| OKX | Download portal: trades, candles, funding, order books ([page](https://www.okx.com/en-us/historical-data)) | Start dates not found | Personal, non-commercial; no SaaS or analytics platforms (API Agreement, 2026-07-28) ([link](https://www.okx.com/en-us/help/okx-api-agreement)) |
| Coinbase | No bulk archive; REST candles return at most 300 per request ([docs](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles.md)) | — | Personal or research only; no apps for end users (terms dated 2026-08-07) ([terms](https://www.coinbase.com/legal/market_data)) |
| Kraken | OHLCVT bars and full trade history from each market's start through 2026-06-30, updated quarterly ([OHLCVT](https://support.kraken.com/hc/en-us/articles/360047124832-Downloadable-historical-OHLCVT-Open-High-Low-Close-Volume-Trades-data), [trades](https://support.kraken.com/hc/en-us/articles/360047543791-Downloadable-historical-market-data-time-and-sales-)) | ZIP of CSVs | For your own benefit only; other uses need permission ([terms](https://www.kraken.com/legal/global-terms)) |
| Hyperliquid | S3 bucket where you pay transfer costs: order-book snapshots, funding/open-interest contexts, fills; "no guarantee" of timely updates ([docs](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)) | API returns only the most recent 5,000 candles; 1,200 request weight per minute | Not found |

**Table 5. Paid aggregators and CCXT**

| Vendor | Coverage | Price | Licence |
| --- | --- | --- | --- |
| Tardis.dev | 50+ venues; tick data from 2019-03-30; first day of each month free. Exchange `timestamp` and arrival `local_timestamp`, both microseconds UTC ([CSV docs](https://docs.tardis.dev/downloadable-csv-files)) | Academic $350–650, Solo $700–1,200, Pro $1,000–2,200, Business $3,000–6,000 per month ([pricing](https://tardis.dev/#pricing)) | Internal use; may not be used in your products. Only derived bars of 10 minutes or longer may be resold ([terms](https://docs.tardis.dev/legal/terms-of-service)) |
| CoinAPI | REST/WebSocket: bars, trades, quotes, order books | Startup $79, Streamer $249, Pro $599 per month ([pricing](https://www.coinapi.io/products/market-data-api/pricing)) | Showing data to customers "may be considered redistribution"; API keys must not be shared ([policy](https://www.coinapi.io/usage-policy)) |
| Kaiko (bought Amberdata on 2026-06-02) | Institutional | Quote only ([news](https://kaiko.com/news/kaiko-acquires-amberdata-in-landmark-digital-asset-data-consolidation)) | Enterprise |
| CCXT | Free MIT library for 100+ exchanges: historical bars, trades, funding and open interest, with built-in rate limiting ([GitHub](https://github.com/ccxt/ccxt)) | Free | Each exchange's own data terms still apply |

**Inference:** default to Binance USD-M perpetuals and Binance spot (longest consistent free archive with trades, funding and open interest), with Bybit as a cross-check. If you are US-based, Binance.com and Bybit block US users; use Kraken or Coinbase for spot and Hyperliquid for perpetuals instead. CCXT is the client for gaps and live data, not an archive, and gives no licence.

## 5. Data-engineering notes

**Table 6. ES volume, front month, DBN format (inference, 252 sessions per year)**

| Data | Rows per day | GB/yr uncompressed | GB/yr zstd |
| --- | --- | --- | --- |
| Trades | 265–350k | 3.2–4.2 | 1.0–1.3 |
| TBBO | same as trades | 5.3–7.1 | 1.7–2.2 |
| MBP-1 | about 4.9M | about 98 | about 30 |
| 1-second bars | 40–60k | 0.6–0.85 | — |
| 1-minute bars | up to 1,380 | about 0.02 | — |

**Session, calendar and roll pitfalls:**

- **Trade date isn't the calendar date.** CME publishes its hours in Central Time, so UTC session boundaries shift with daylight saving. Holiday sessions fold into the next trade date: orders entered from Sunday 6 Sep 2026 count for Tuesday 8 Sep ([CME hours](https://www.cmegroup.com/trading-hours.html)).
- **Rolls differ by product.** CME's equity roll date is the Monday before the third-Friday expiry; in June 2026 the contract expired on Thursday 18 June because of Juneteenth ([CME](https://www.cmegroup.com/trading/equity-index/rolldates.html)). MCL stops trading one business day before CL ([CME](https://www.cmegroup.com/markets/energy/crude-oil/micro-wti-crude-oil_contractSpecs_futures.html)). GC traders roll before first notice day ([eSignal](https://kb.esignal.com/hc/en-us/articles/6362165225243)).
- **Daily bars aren't settlements.** Databento's `ohlcv-1d` is cut on UTC dates; official settlements and open interest are in the `statistics` schema ([docs](https://databento.com/docs/schemas-and-data-formats/ohlcv)). Settlements are published with variable delay ([Databento](https://medium.databento.com/top-6-things-about-daily-market-data-that-even-institutional-traders-get-wrong-a1cee70f4d45)), and the ES settlement window moved in 2020 ([ohlcv.io](https://ohlcv.io/posts/backtesting-pitfalls/04-bar-resolution/)).
- **Bars are sparse and stamped at the open.** A bar is only printed when a trade occurs ([gist](https://gist.github.com/databento-bot/833ba14d87ffa09dbcb36a38b0c832e6)), and its timestamp is the interval open ([Nautilus](https://nautilustrader.io/docs/latest/integrations/databento)).
- **Old data has known gaps.** Some 2010–2015 days return "far fewer bars" ([issue D-8175](https://issues.databento.com/roadmap/cme-globex-mdp2-data-has-incomplete-bars-for-many-days)).

**Timestamps:** `ts_event` is the matching-engine time and `ts_recv` the capture-server time, both in nanoseconds UTC ([record.rs](https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs)). NautilusTrader orders events by `ts_recv` to keep them monotonic ([Nautilus](https://nautilustrader.io/docs/latest/integrations/databento)).

**How established backtesters build continuous series:** QuantConnect separates the adjusted continuous price (ratio, Panama or none) from the real "Mapped" contract: "The continuous Futures contract isn't a tradable security" ([QC](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/requesting-data/universes)). Zipline offers `mul`, `add` or no adjustment ([QuantRocket](https://support.quantrocket.com/t/behavior-of-adjustment-param-in-continuous-future/1701)).

**Inference, for FEFAT:** store raw per-contract data; decide rolls only from information available before the roll; build adjustments incrementally so a value at time t reflects only rolls up to t; simulate fills and prop-firm drawdown on the real contract's raw ticks, using its own tick size and multiplier; treat a bar as available only at its close. NautilusTrader already loads Databento and Tardis data into Parquet in Rust ([Tardis adapter](https://nautilustrader.io/docs/latest/integrations/tardis/)), so it is a useful reference design.

## 6. Recommendations

**Personal phase:**

1. Spend the $125 credit on a pilot, for example one year of ES trades (about $95, inference).
2. Take one month of Databento Standard ($199). Download the full bar, definition and settlement history for all 8 products, plus 12 months of TBBO. Use 1-second bars for fills before that 12-month window.
3. Optionally backfill 4 more years of trades, about $1.0–2.2k at the 2024 rates.
4. For crypto, use Binance Vision, the Bybit archive and Hyperliquid's S3 bucket, with CCXT to fill gaps. Cost is $0.
5. Total: about $199 at minimum, about $1.2–2.5k with five years of ticks.

**Product phase:** local-first (adopted). Customers run the engine with their own data keys and files; FEFAT never hosts market data. Confirm in writing with Databento before launch. A hosted alternative would cost Databento Plus ($21k/yr), CME licences for three exchanges, and $105,660/yr more if exports are allowed; crypto would need Kaiko, CoinAPI or a Tardis commercial agreement.

**Not found:** current Databento per-GB rates for trades, TBBO and MBP-1; CME's fee for view-only historical display; FirstRate, Portara and dxFeed prices; Bybit, OKX and Kraken rate limits; Hyperliquid's data terms; whether Databento's continuous mappings switch at UTC midnight or at the session open.
