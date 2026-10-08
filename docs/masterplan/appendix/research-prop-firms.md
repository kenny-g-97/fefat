# Research: prop-firm rules for the FEFAT prop simulator (as of 2026-10-05)

> Provenance: research by a Claude subagent on 2026-10-05, primarily from the firms' own help-center and rules pages. Bracketed keys such as [TS3] point to the Sources section at the end; each source has a URL and an "as of" date (the page's own updated date, or "acc." for the access date, 2026-10-05).
>
> Conventions: **†** means the only source found was a third party (not confirmed on the firm's own page). **NF** means not found. Dollar figures are for 50K accounts unless noted. Text under **Inference** is the researcher's reading, not a firm's stated rule. Many firms change rules by purchase date ("legacy" groups keep older terms): treat every preset as dated.
>
> How FEFAT uses this: Phase 7 turns the taxonomy (section 1) into the rule schema, and the per-firm tables (section 2) into dated preset files with worked examples. The `prop-preset-refresh` skill re-reads the sources listed here. Rules change often; verify before relying on any number.

## 1. Rule taxonomy

| # | Parameter | Variants seen | Where |
| --- | --- | --- | --- |
| **A** | **Program and lifecycle** | | |
| A1 | Stage graph | 1-step evaluation → sim-funded → live (most futures firms). 2-step evaluation (FTMO 2-Step, HyroTrader, CFT, BitFunded, FundedNext Stellar 2-Step/Lite). 3-phase (CFT). Instant / direct-to-funded (Tradeify Lightning, LucidDirect, Alpha Direct, ETF DTF, FundedNext Stellar Instant, BitFunded Instant, HyroTrader Zero-Step). Invite-only pre-live stage (LucidMaxx†). Two-round fixed-prize "Challenge" with no profit split (Topstep Labs). | TF4, LU3, AL3, ET1, FX1, BF1, HY1, CF1, TS13, LU8† |
| A2 | Pass condition | Reach target; some say "reach **and maintain**" (Alpha). Target counted on closed P&L only, or flat required to advance (FundedNext Futures, BitFunded). Auto-pass even with a position open (Breakout). Pass assessed after end of day (Apex, FTMO Futures). Manual review before funding (Bulenox up to 24 h; FTMO 1–4 business days). | AL2, FN5, BF2, BO5, AP4, FF1, BX1, FT1 |
| A3 | Evaluation expiry / billing | No limit. One-time fee buys 30 calendar days (Apex; 5-packs share one clock†). 10 calendar days, auto-fail (ETF Fast Track). Monthly subscription until pass (Topstep, TPT, Alpha, ETF, TradeDay, E2T, FTMO Futures, Bulenox). At renewal: progress carries over (ETF) or you get a free reset (TradeDay). | AP11, ET6, ET4, TD5, AP13† |
| A4 | Activation | Fee on pass: Topstep $149 (Standard path), Apex $79–$149, TPT $130, Bulenox $143–$898, E2T $139 (deducted from first withdrawal). $0 at Alpha Zero/Standard, MFFU, Tradeify, Lucid, FundedNext, TradeDay, FTMO Futures. "No activation fee" option sold at a higher evaluation price (Topstep, Apex). Activation deadline: Apex 7 days. | TS8, AP12, TP6, BX1, E6, AL6, MF5, TF12, TD3, FF2 |
| A5 | Recurring funded-stage costs | None. Subscription continues while funded (Alpha Qualified "same monthly price"; ETF $87/mo on Fast Track, ~$80/mo others†). Market data (Topstep Level 2 $38/mo; E2T pro $135/exchange/mo). Third-party API (Bulenox $100/mo; Topstep API $29/mo). | AL6, ET6, ET10†, TS8, E6, BX2, TS12 |
| A6 | Funded starting balance | Nominal size (Apex, Tradeify sim). $0 with a negative floor (Topstep XFA, MFFU Rapid/Builder sim; live accounts at Lucid, Tradeify Elite, TradeDay, TPT PRO+). | TS6, MF2, LU3, TF11, TD4 |
| A7 | Next-stage trigger | **Payout count:** Lucid 5 → review; MFFU Pro 3 consecutive; MFFU Builder 5; TradeDay Fast Pass on the 5th request; Bulenox 3†; Tradeify 3 on one account or 10 total (eligibility only). **Cumulative payouts:** ETF $25K per trader. **Profit events:** MFFU $10K in one day; TradeDay Quick Pay $10K gross profit → pause, excess removed, review; LucidDaily max daily profit†; MFFU Pro profit above the $100K cap. **Discretionary:** Topstep, TPT PRO+. | LU3, MF1, MF4, MF5, TD2, TD3, TF11, ET2, TS5, TP7 |
| A8 | Transition side effects | Mandatory, cannot decline (Topstep, Tradeify; Bulenox: declining forfeits†). All other XFA/sim/evaluation accounts closed (Topstep, Tradeify, Lucid — including "evaluations in reserve"). Unwithdrawn sim profit forfeited (Tradeify, MFFU). Live capital released in tranches (Topstep: 20% now, 80% reserve in 25% steps). Cash-out instead of going live (Lucid: 50% of live start). Cooldown after losing a live account (TradeDay 3 months; Lucid 2 weeks†). Household lock-out while live (Tradeify Elite). | TS5, TF11, TF13, LU3, MF4, TD4 |
| A9 | Terminal and queued states | Breach. Closed after the payout cap (Apex after 6th payout; FundedNext Bolt "Concluded" after 5th, including the buffer). Inactivity closure. Pending queue when over the funded cap (FundedNext; BitFunded "To Be Active"; Bulenox†). Consolidation into one funded account (Bulenox†). | AP8, FN11, FN8, BF1, BX3† |
| A10 | Resets / reactivation | **Evaluation reset:** Topstep = monthly price; Alpha $79–$449; ETF $47; TPT $79–$199†. **Funded reset:** TPT PRO up to 3 ($449–$1,499†); Alpha Qualified $399–$999; ETF Elite up to 10. **No resets:** Apex 4.0, Tradeify Lightning, Bulenox Master, Breakout (paid "breach insurance"†). **Reactivation after a funded loss:** Topstep Back2Funded $599–$829. | TS8, AL6, ET4, TF12, BX1, TP8†, BO6† |
| A11 | Trader-level status that overrides plan rules | Topstep Responsible Trading Program (forced DLL, Consistency path only). Apex "Trader Probation". Tradeify "Elite-Only Mode" (Select only, full price). | TS17, AP10, TF11 |
| A12 | Account caps and scope | **Evaluations:** MFFU 10; Lucid 10 per household; FundedNext $750K allocation; HyroTrader $400K; unlimited at TPT and FTMO Futures. **Funded:** Apex 20 per household; Topstep 5 XFA + 1 LFA; Tradeify 5; TPT 5; Alpha 5 (3 if any Advanced, one person per household); FundedNext 5 per household and ≤10 issued per month; Lucid 5 funded / 10 total / 5 live; MFFU 5, or 3 if any 100K/150K; Bulenox 5; ETF 5; TradeDay 5 live; FTMO Futures 3; HyroTrader $200K; CFT $300K. | MF6, LU4, FN8, HY6, TP7, FF4, AP6, TS2, TS5, TF6, AL10, BX1, ET3, TD4, CF3 |
| **B** | **Maximum loss (drawdown)** | | |
| B1 | Type | Static from initial balance. End-of-day (EOD) trailing. Intraday trailing on peak equity including unrealized P&L. Trailing on balance high-water mark (CFT 1-Phase, FundedNext Stellar Instant). Midnight-snapshot trailing (FTMO 1-Step). | ET1, BO1, FT1, AP3, CF1, FX3 |
| B2 | High-water-mark source | Closing or settled balance (Topstep; Apex at 4:59:59 PM ET; Tradeify; Alpha; TradeDay at 4 PM CT; FTMO Futures). Realized balance only (ETF EOD; TPT Test "not on open positions"). Peak equity tick by tick (Apex Intraday, MFFU Rapid funded, TPT PRO, ETF 1-Step, Bulenox Option 1). **Gross** profit including past payouts (TradeDay Quick Pay funded). FundedNext's two pages disagree: "highest balance reached that day" vs "highest end-of-day balance". | TS6, AP2, TF1, AL6, TD1, ET3, TP5, AP3, MF2, FN4, FN5 |
| B3 | Breach test | Real-time equity / net liquidation including unrealized P&L (every firm checked). Commissions and swaps included (FTMO, FTMO Futures, Bulenox). Touching the line is a breach: Apex "touches or falls below"; Topstep "hit or go below"; Alpha and TradeDay "hit or exceed". | AP2, TF1, FT1, FF1, BX2, TS1, AL2, TD5 |
| B4 | Lock level (stops trailing) | **Starting balance:** Topstep Combine, Alpha, FundedNext Legacy, TPT, E2T, TradeDay, FTMO Futures, CFT 1-Phase, FundedNext Instant. **Start + $100:** Apex PA, Tradeify funded, Lucid, Bulenox Master, ETF, FundedNext Rapid/Flex, MFFU Builder/Rapid EOD. **Profit-target balance:** Apex evaluations on Rithmic/WealthCharts. **Never:** Apex evaluations on Tradovate; Bulenox Qualification†. **$0 or $100 on $0-start accounts:** Topstep XFA, MFFU Rapid, Lucid Live. | TS6, AL6, FN4, TP5, E6, TD6, FF1, AP2, AP3, TF1, LU2, BX1, ET4, MF3, BX3† |
| B5 | Lock triggers other than the high-water mark | Payout **request** locks the floor immediately (Tradeify; Lucid Live; LucidFlex†). First payout moves the floor to start (TradeDay Fast Pass) or start + $100 (MFFU Pro). First withdrawal resets the floor to initial (FundedNext Legacy). Any payout sets the floor to $0 (Topstep XFA). | TF1, LU3, TD2, MF4, FN2, TS3 |
| B6 | Effect of payouts on the floor | None — "no MLL slide" (Alpha). Lock as in B5. Floor keeps trailing on gross profit (TradeDay Quick Pay). Full reset when a new account is issued after a reward (FTMO 1-Step). | AL2, TD1, FT1 |
| B7 | Profit give-back rule | After +20% growth, losing more than 35% of accumulated profit removes the account (ETF). | ET4 |
| B8 | Payout floor (buffer / safety net) | DD + $100 for the account's life (Apex, MFFU, Lucid Pro/Daily, Bulenox reserve, ETF). Equal to DD (TPT PRO). Fixed balance (FundedNext Bolt $52,100). None (LucidFlex, Tradeify Flex, TradeDay). | AP8, MF1, LU1, BX1, ET4, TP7, FN11, TF5, TD3 |
| **C** | **Daily loss** | | |
| C1 | Presence | None. Mandatory. Optional at checkout (Topstep — with a price discount and doubled payout caps; LucidDaily; FundedNext Flex add-on). | TS7, TS3, FN12, LU8† |
| C2 | Breach effect | **Soft** (flatten and lock until next session): Topstep, Apex, Tradeify, Alpha DLG, Lucid, Bulenox, MFFU Builder, FundedNext Rapid Daily, FTMO Futures Growth (funded), E2T funded. **Hard** (account fails): ETF EOD (soft with the "TradeShield" add-on), E2T evaluation†, FTMO Futures Pro evaluation, all crypto/CFD firms. | TS7, AP5, TF7, AL11, BX2, MF5, FN3, FF1, ET3, E7†, BO1 |
| C3 | Size basis | Fixed $ by account size. % of initial (FTMO, FundedNext CFD, BitFunded, HyroTrader). % of the start-of-day balance (Breakout 3% of the 00:30 UTC balance). % of starting balance (Alpha 2%). | FT1, FX1, BF2, BO2, AL11 |
| C4 | What it is measured against | Day's net P&L including open positions (Topstep, Apex, Tradeify, Alpha, Bulenox). Balance snapshot minus allowance (FTMO at 00:00 CE(S)T; Breakout at 00:30 UTC excluding open positions). The day's equity peak, i.e. trailing (HyroTrader; "Swing" add-on = start-of-day equity†). Realized plus floating loss for the day (BitFunded). | TS7, AP5, AL11, FT1, BO2, HY7†, BF2 |
| C5 | Dynamic DLL | Tiers by EOD balance, never below level 1 (Apex PA). 60% of peak EOD profit, ratchet-up only ("LucidScale"†). Raised at +6% profit (Tradeify). Moves with balance (Topstep LFA). Removed when the floor locks (ETF; Bulenox†) or on request (E2T). A payout lowers the daily floor by the payout amount (Breakout†). | AP5, LU8†, TF7, TS5, ET3, BX3†, E6, BO6† |
| **D** | **Consistency** | | |
| D1 | Window | Evaluation only. Per payout cycle, resetting on approval. Account lifetime (Bulenox Master†). | AP8, AL1, BX3† |
| D2 | Numerator | Best day's net P&L. Best single **trade** (HyroTrader Zero-Step, 50%). Best **instrument** (BitFunded Instant: one pair ≥60% of profit → 50% payout penalty). | AP8, HY3, BF3 |
| D3 | Denominator | Net profit in the window (Apex, Topstep XFA, Tradeify, Alpha, Lucid, Bulenox). Profit **target** (Topstep Combine 55%; FundedNext Legacy 40%; HyroTrader 40%). Sum of **profitable days only** (FTMO 1-Step). **Gross** profit including payouts (TradeDay Fast Pass). | AP8, TS4, TF2, AL1, LU1, BX1, FN1, HY3, FT1, TD2 |
| D4 | Threshold and comparison | 20–55%. Inclusive "≤" passes (Tradeify). Strict "<" required (Apex: "50% or more" fails; Alpha: "≥ 40%" fails). Graduated by payout number: Tradeify Lightning 20/25/30%; Bulenox Fast Track 20/25/30%†. | TF2, AP8, AL1, BX3† |
| D5 | Consequence | **Target raised** to best ÷ threshold (Topstep ÷0.55; FundedNext ÷0.40; TradeDay ÷0.30†). TPT: total must exceed 2 × best day. **Payout blocked** until diluted (Apex, Alpha, Tradeify, Bulenox, Lucid). **Excess day profit not counted** toward the target (HyroTrader). **Payout penalty** (BitFunded). | TS4, FN1, TP5, AP8, AL1, TF2, BX1, HY3, BF3 |
| **E** | **Activity, sessions, conduct** | | |
| E1 | Minimum days and "trading day" definition | 0–5 days. A day counts if ≥1 position opened (FTMO, Bulenox), P&L ≠ 0 (FundedNext CFD), or ≥1 closed trade of at least 5% of initial notional that moved ≥1% (HyroTrader). | FT1, BX2, FX1, HY2 |
| E2 | Payout qualifying days | N days of at least $X: Topstep 5×$150; Apex 5×$200/$250; Alpha 5×$200; FundedNext 5×$200; TradeDay Fast Pass 5×$150; FTMO Futures 4–5 days. **Relative** threshold: ETF counts a day only if ≥$200 **and** ≥23% of your best day. N trading days: Bulenox 10. The request day does not count; the new cycle starts next session (Topstep, ETF, TradeDay). | TS2, AP8, AL3, FN2, TD2, FF3, ET4, BX1 |
| E3 | Calendar gates | 24 h (MFFU Rapid) or 48 h (Builder) after first trade. 14 days (MFFU Pro; FTMO). Trader-chosen "Profit Sharing Day" 2–60 days (BitFunded). | MF1, MF5, FT3, BF3 |
| E4 | Inactivity | 30 days (Topstep XFA, HyroTrader). Two +$50 days per 30 days (Apex PA). 1 trade per 7 days (MFFU Pro). 1 trade per week (Tradeify, ETF, TPT PRO). 5 consecutive trading days (E2T). 60 days (FundedNext CFD). | TS2, HY1, AP7, MF4, TF8, ET3, TP3, E6, FX1 |
| E5 | Session and holding | Flat-by times (see §3.2). Overnight/weekend allowed: ETF Diamond Hands, FTMO evaluations and Swing accounts, crypto firms, FundedNext CFD. Maximum holding time: BitFunded 10/7/5 days. | ET1, FT4, FX2, BF1 |
| E6 | News | Unrestricted. No positions/orders within ±N minutes of tier-1 news: MFFU ±2 min (Rapid/Pro funded); TPT ±1 min; Alpha ±2 min (no executions); FTMO funded Standard ±2 min. No full position size into scheduled news (Topstep). News-trade profit counted at 40% (FundedNext CFD). | MF9, TP3, AL9, TS11, FX3 |
| E7 | Price-limit rule | Exit before a CME price limit (TPT). "Within 2% of a CME price limit" rule (FTMO Futures; TradeDay†). | TP3, FF4 |
| E8 | Hold time / trade frequency | >50% of trades **and** of profit must come from trades held >10 s (Tradeify, payout gate). >50% of profit from trades ≤5 s is flagged (Lucid). Profit share from trades closed <10 s: 30% warning, ≥40% hold (FundedNext Futures). 10 s minimum hold (ETF†). Tick-scalping pattern and >100 trades/day (Alpha). ≥2 trades held ≥10 min per payout period (BitFunded). | TF8, LU7, FN1, ET10†, AL7, BF1 |
| E9 | Hedging | Banned across a trader's own accounts, including correlated and mini/micro pairs (all firms). Allowed within one account (Breakout, HyroTrader). | AP10, TP4, BO1, HY3 |
| E10 | Where a strategy comes from | Third-party/off-the-shelf strategies banned (Breakout; HyroTrader). Same approach required in evaluation and funded (Breakout). Your bot must not be used at other firms (Tradeify). No account structures where "failure of some … increases the likelihood of success of others" (TPT). Account stacking / stockpiling evaluations / "storing multiple passed accounts" banned (Topstep, Apex, Alpha). | BO2, HY4, TF9, TP2, TS11, AP10, AL7 |
| **F** | **Size and exposure** | | |
| F1 | Contracts and scaling | Fixed maximum (micros count 10:1). Scaling tiers by EOD balance, moving both ways with a floor (Apex PA; Bulenox Option 2). Cumulative, never drops (Tradeify Select). +1 contract per $2,000 EOD profit (TradeDay Fast Pass). New limits apply next session (Topstep, Apex, Tradeify). Per-product caps (Topstep micro BTC/ETH). | TS9, AP5, BX3†, TF5, TD4 |
| F2 | Crypto/CFD exposure | Leverage by asset tier (Breakout 10x/5x/3x/2x; FundedNext crypto 1:1; BitFunded ≤5x; CFT up to 1:100 on Bybit). Margin cap (HyroTrader 25%; BitFunded 65%). Notional ≤2× initial (HyroTrader funded). ≤5 open positions (BitFunded). Maximum loss per trade (HyroTrader 3%†; FundedNext CFD 3% at any time). | BO1, FX2, BF1, CF1, HY5, HY7†, FX3 |
| F3 | Profit caps | $10K per day/trade; excess deducted (CFT). A large daily profit forces a move to live (LucidDaily†; MFFU $10K). | CF1, LU8†, MF1 |
| **G** | **Payouts** | | |
| G1 | Amount rule | % of balance (Topstep 50%; TradeDay Fast Pass 50%). % of profit (Alpha 50%; Tradeify Flex 50%; FundedNext Legacy 50%, rising to 100% after 30 qualifying days; FTMO Futures 50% Growth / 100% Pro). Multiple of cycle profit (Tradeify Daily 2×). Everything above the buffer (TPT, MFFU Rapid, LucidDaily). ≥50% of the request must be profit made since the last payout (FTMO Futures). | TS3, TD2, AL3, TF5, FN2, FF3, TP7, MF2 |
| G2 | Caps | Fixed per request (Topstep, Alpha, FTMO Futures). Ladder by payout number (Apex 6 steps; ETF cycles; Lucid Pro/Direct; Tradeify Lightning; Bulenox first 3). Uncapped (TPT; MFFU Rapid EOD). Per-user simulated cap (MFFU Pro $100K; ETF $25K). | TS3, AL3, AP9, ET2, TF6, BX1, TP7, MF3, MF4 |
| G3 | Profit split | 90/10. 80/20. 100% (Apex; ETF up to $25K). Lifetime tier (Bulenox 100% of first $10K). Tier by current profit (TradeDay Quick Pay 50% below $4K, pro-rated; E2T 50% below a threshold). Rises over time (HyroTrader 80 → 90%). Paid add-on (Breakout 90/10). Penalty for withdrawing the buffer early (TPT 50%†). | TS3, AP8, ET2, BX1, TD1, E6, HY2, BO1, TP8† |
| G4 | Cadence and processing | Daily. Every N qualifying days (Alpha max 4 per month). Every 14 days. Weekly batch (Bulenox and E2T Wednesdays; ETF Mon/Wed). One open request at a time (Tradeify). Trading allowed while pending but auto-denied if the balance falls below the requirement (Apex, Lucid). No trading until paid (TradeDay Fast Pass). Must be flat to request (FTMO, Breakout). Copier unlinked during payout (Topstep†). | MF1, AL3, MF4, BX1, E6, ET4, TF5, AP9, LU1, TD2, FT3, TS15† |
| G5 | Forced withdrawal | At +5% (HyroTrader†). Withdraw the profit goal to step up capital (E2T Trader Career Path). Withdraw the cycle maximum to advance, otherwise unused amount is forfeited (ETF). | HY7†, E2, ET5 |
| G6 | Fee refunds | Refund with 1st reward (FundedNext 2-Step, FTMO 2-Step) or 3rd (FundedNext 1-Step/Lite; BitFunded 2-Step). Deposit returned with first payout (HyroTrader). | FX4, BF3, HY2 |

## 2. Firm presets

### 2A. Futures: evaluation and risk rules (50K)

| Firm (as of) | Fees | Target / max loss | DLL | Consistency (eval → funded) | Days / flat-by / news |
| --- | --- | --- | --- | --- | --- |
| **Topstep** (help center, Jun–Oct 2026) | $49/mo + $149 activation, **or** $95/mo with no activation; reset = monthly price [TS8] | $3,000 / $2,000 EOD trailing, enforced on real-time equity, locks at start. XFA starts at $0 with floor −$2,000, locks at $0 [TS1, TS6] | Optional $1,000, soft [TS7] | Combine: best day <55% of target (else target = best ÷ 0.55). XFA "Consistency" path: ≤40% [TS4] | ≥2 days implied. Day runs 5 PM–3:10 PM CT, flat by 3:10 PM CT. No full size into major news [TS1, TS10, TS11] |
| **Apex 4.0** (since 2026-03-01) | One-time, 30-day access, no resets. Intraday $249 + $89 activation; EOD $590 + $119† [AP11, AP13†] | $3,000 / $2,000. **EOD** = closing balance at 4:59:59 PM ET; **Intraday** = peak including unrealized. Evaluations lock at target balance (Rithmic/WealthCharts) or never (Tradovate). PA locks at start + $100 [AP1–AP4] | EOD evaluation $1,000 soft (resets 6 PM ET); none on Intraday evaluation. PA tiers $1,000 → $3,000 [AP5, AP7] | None in evaluation → PA best day <50% of profit since last payout [AP8] | 0 days. Evaluation 6 contracts; PA 2 → 4 by tier. Flat before close. News allowed for your normal strategy [AP1, AP5, AP10] |
| **My Funded Futures** (help center, Jun–Aug 2026) | One-time since 2026-08-25†; $0 activation. Rapid $157, Pro $227, Builder $153 [MF5, MF11†] | $3,000 / $2,000 EOD in evaluation. Funded: Rapid **intraday** trailing from $0, locks at $100; Rapid EOD / Builder lock at +$100; Pro locks at start + $100 after first payout [MF2–MF5] | Builder only: $1,000 soft [MF5] | Rapid 50%, Rapid EOD 30%, Pro 50%, Builder none → funded none, except Builder 50% per cycle [MF2–MF5] | Pro 2 days, Rapid EOD 4, Builder 1. Auto-flat 4:10 PM ET. Tier-1 news ±2 min banned on Rapid/Pro funded [MF9, MF10] |
| **Tradeify** (help center, Aug–Sep 2026) | One-time, $0 activation. Growth $145; Lightning $349–$729, no resets [TF12] | $3,000 / $2,000 EOD trailing on net liquidation. Funded locks at start + $100 at the threshold **or on payout request** [TF1] | Soft, resets 6 PM ET. Growth $1,250; Select evaluation none; Select Daily $1,000; Select Flex none. Raised at +6% profit [TF7] | Select evaluation 40% (≤) → none funded. Growth funded 35%. Lightning 20/25/30% by payout number [TF2] | Select ≥3 days. ≥1 trade per week [TF3, TF8] |
| **Take Profit Trader** (help center, Aug–Sep 2026) | Monthly Test ($150–$360 list†) + $130 activation [TP6, TP8†] | 6% / $2,000. Test EOD trailing, locks at start. PRO **intraday** trailing including unrealized. PRO+ EOD [TP5, TP7] | None [TP5] | Test: best day <50% of net P/L (target raised, not failed) → none funded [TP5] | Test 3 days (tests bought since 2026-08-17). Auto-flat 4:55 PM ET†. PRO/PRO+ flat ±1 min around listed news [TP3, TP5] |
| **Alpha Futures** (help center, Jul–Aug 2026) | Monthly, continuing into Qualified: Zero $139, Standard $129, Advanced $209. Advanced $149 activation [AL6, AL13] | $3,000 (Advanced $4,000) / $2,000 (Advanced $1,750), EOD trailing, stops at starting balance [AL6] | DLG 2% soft (includes unrealized and fees; lock until 6 PM ET). Zero: evaluation and Qualified. Standard: Qualified only. Advanced: none [AL11, AL6] | Zero none, Standard 50%, Advanced 40% → Qualified Zero/Standard 40%, Direct 20%, Advanced none [AL1] | Zero 1 day, Standard 2. Flat by 4:20 PM ET. Qualified (not Advanced): no executions ±2 min of red-folder news [AL12, AL9] |
| **FundedNext Futures** (help center 2026; Rapid/Bolt discontinued 2026-07-10) | One-time, no activation; price NF [FN10] | Legacy $3,000 / $2,000; Flex $2,500 / $1,500. EOD trailing, breach on floating loss. Locks at initial (Legacy) or initial + $100 (Rapid Pro/Daily, Flex) [FN4, FN5] | Rapid Daily $1,000 soft (resets 5 PM CT); Flex optional add-on [FN3, FN12] | Legacy: ≤40% **of target** → none funded. Rapid Pro: 40% funded [FN1, FN5] | Micro-scalping thresholds (§E8). No overnight/weekend holding [FN1, FN10] |
| **Lucid** (support pages Aug 2026; much of this is †) | One-time, no activation. Pro ~$185–$192, Flex ~$140–$146† [LU8†] | $3,000 / $2,000 EOD, locks at start + $100 above $52,100. LucidDaily funded trails intraday† [LU2, LU8†] | Pro/Direct $1,200 → "LucidScale"†; Flex none [LU8†] | Flex/Daily 50%, Pro none → Pro 40% per cycle, Direct 20% [LU1, LU8†] | Flat by 4:45 PM ET† [LU8†] |
| **Bulenox** (help pages, acc. 2026-10-05) | Monthly Qualification (price NF). Master activation $148 one-time; no Master resets [BX1] | $3,000† / $2,500. Option 1: real-time trailing including commissions and unrealized. Option 2: EOD trailing. Master locks at start + $100 [BX1, BX2] | Option 2: $1,100 soft (includes unrealized and commissions, 5 PM–4 PM CT); removed when the floor locks† [BX2, BX3†] | None → Master 40% (lifetime†) [BX1] | 0 days (≥1 traded day). Flat by 3:59 PM CT [BX2] |
| **Elite Trader Funding** (help center 2025–26) | Monthly; resets $47; funded monthly fee [ET1, ET6] | 1-Step: live trailing on unrealized. EOD: EOD trailing on realized. Static: fixed. Lock at start + $100 once realized profit ≥ DD + $100 [ET3, ET4, ET5] | EOD plan $1,100 **hard** (TradeShield add-on makes it soft); 1-Step none [ET3] | None on 1-Step/EOD; Fast Track 40% [ET6] | 5 days. Flat 1 min before close. Diamond Hands allows overnight [ET1, ET3] |
| **TradeDay 2.0** (since 2026-05-29) | Monthly, no activation. Quick Pay $59/mo promo (list $131)† [TD3, TD7†] | $3,000 / $2,000. Quick Pay: intraday or EOD evaluation; Fast Pass: EOD. Floor freezes at starting balance [TD3, TD4, TD6] | None [TD5] | Quick Pay 30%, Fast Pass 45% (target raised) → Fast Pass funded 45% of **gross** profit (accounts opened ≥2026-07-26) [TD5, TD2] | Quick Pay 5 days, Fast Pass 3. Session 5 PM–4 PM CT [TD2, TD5] |
| **Earn2Trade** (rules update 2026-07-06) | Monthly (price NF) [E1] | $3,000 / $2,000 EOD trailing, locks at start [E1, E6] | $1,100 (fails in evaluation†; pauses when funded) [E1, E7†] | 30% in evaluation → none funded [E1, E6] | No fixed minimum days. Contract progression ladder. Trade until 3:50 PM CT [E1, E6] |
| **FTMO Futures** (beta 2026-08-31; launched 09-17) | Monthly ($119 Growth / $139 Pro†), no activation [FF2, FF5†] | $3,000 / EOD trailing ($2,000 Growth, $3,000 Pro), locks at initial [FF1, FF3] | Growth: none in evaluation, $1,000 soft funded. Pro: **hard** in evaluation [FF1] | 40% Growth / 50% Pro† → none funded [FF1, FF5†] | No minimum days. Day 6 PM–4:10 PM ET, auto-flat 4:10 PM ET [FF3, FF4] |

### 2B. Futures: funded stage, payouts, lifecycle

| Firm | Payout gate | Amount / caps / split | Lifecycle and account caps |
| --- | --- | --- | --- |
| Topstep | Standard: 5 days ≥$150 + net profit since last payout. Consistency path: 3 traded days + ≤40% [TS3] | ≤50% of balance, cap $2K Standard / $3K Consistency (doubled with DLL), min $125. Any payout sets MLL to $0. Split 90/10 [TS3] | LFA by risk-team call-up, cannot decline, all XFAs closed. 20% tradable / 80% reserve. API not allowed on LFA. Limits 5 XFA, 1 LFA [TS2, TS5, TS12] |
| Apex | 5 days ≥$250 EOD / ≥$200 Intraday. Balance ≥ $52,600 (safety net + $500). <50% rule [AP8, AP9] | Intraday caps by payout #1–6: 1.5K/2K/2.5K/2.5K/3K/3K. EOD: 1.5K/1.5K/2K/2.5K/2.5K/3K†. Min $500. Split 100% [AP9, AP13†] | Up to weekly. PA closes after 6th payout. 20 PAs per household [AP6, AP8] |
| MFFU | Rapid: $2,100 buffer, 24 h. Pro: 14 days + buffer. Builder: 48 h, buffer + $500, 2 days per cycle [MF1–MF5] | Rapid: daily, min $500, 90/10. Pro: min $1K, max $100K per user, 80/20. Builder: ≤$2K per cycle, 80/20 [MF1, MF4, MF5] | $10K in one day → live. Pro: 3 consecutive payouts → review. Builder: 5 payouts → live. Limits 10 evaluations / 5 funded (3 if any 100K+) [MF1, MF4, MF6] |
| Tradeify | Cycle profit >0; one open request. **>50% of trades and profit from trades held >10 s** [TF5, TF8] | Flex: 5 winning days, ≤50% of profit, cap $2,500. Daily: ≤2× cycle profit, cap $1,000. Split 90/10 [TF5, TF12] | Elite Live: mandatory once selected, ≤5 live accounts, 80/20, other accounts closed. 5 sim-funded [TF6, TF11] |
| TPT | Above buffer (start + DD = $52,000); no day count [TP7] | Uncapped. PRO 80/20; PRO+ 90/10. Withdrawals ≤$250 cost $50† [TP6, TP7, TP8†] | PRO+ by invitation. 5 PRO, same allowance carries to PRO+ [TP7] |
| Alpha | 5 days ≥$200; ≤4 requests per month [AL3] | ≤50% of profit. Caps: Zero $1.5K, Standard $3K, Advanced $15K. Split 90%. MLL unchanged by payouts [AL3, AL2] | 5 Qualified (3 if any Advanced). Live ("Alpha Prime") criteria NF [AL10] |
| FundedNext Fut. | Legacy: 5 days ≥$200 + $500 cycle profit [FN2] | ≤50%, cap $6K (100% after 30 qualifying days). Min $250. Share 80%. Withdrawing all profit = breach [FN2] | 5 funded per household, ≤10 issued per month, extras queued [FN8] |
| Lucid | Pro: $500 cycle goal + 40% + above buffer [LU1] | Pro: cap $2K then $2.5K†; Flex: 50% up to $2K†. Split 90/10 [LU1, LU8†] | Live pool after 5 payouts. All accounts with ≥1 payout move to live; other sim accounts close. 5 funded / 5 live [LU3, LU4] |
| Bulenox | ≥10 trading days, $2,600 reserve, 40% [BX1] | First 3 payouts capped ($1,500), min $1,000, paid Wednesdays. 100% of first $10K, then 90/10 [BX1] | Funded after 3 payouts (discretionary)†. 5 Masters [BX1, BX3†] |
| ETF | 8, then 10 qualifying days (≥$200 and ≥23% of best day) [ET4] | Cycle caps 1-Step $1K → $1.75K; EOD $1.25K → $2K. 100% split until $25K per trader [ET2, ET4] | LIVE ELITE at $25K (80/20). 5 sim-funded [ET3, ET9] |
| TradeDay | Quick Pay: positive balance. Fast Pass: 5 days ≥$150, 45%, ≤50% of balance, cap $1,500 [TD1, TD2] | Quick Pay 50/50 below $4K, 80/20 above. Fast Pass 80/20. Live 90/10 [TD1, TD4] | Quick Pay paused at $10K gross. Fast Pass → live on 5th request. 5 live [TD3, TD4] |
| Earn2Trade | No buffer, no minimum days [E7†] | 50% below $2,250, 80% above; min $100 net; Wednesdays [E1, E7†] | LiveSim → Live; Trader Career Path steps up capital [E2, E6] |
| FTMO Futures | 4 (Growth) / 5 (Pro) qualifying days [FF3] | Growth 50%, caps $2.5–4K. Pro 100%, caps $5–8K. ≥50% new profit. Split 90/10 [FF2, FF3] | 3 sim-funded; unlimited evaluations [FF4] |

### 2C. Crypto presets

| Firm (as of) | Structure / targets / fees | Daily loss (anchor) | Max loss | Leverage / exposure | Payouts / other |
| --- | --- | --- | --- | --- | --- |
| **Breakout** (Kraken-owned; program rules 2026) | 1-Step Classic / Pro / Turbo: 10% / 12% / 9%; no minimum days, no consistency. $100K price $800 / $545 / $330 [BO1, BO5] | 3% of balance at **00:30 UTC** (open positions excluded), checked against live equity; hard [BO2] | Static 6% / 5% / 3% of initial, on equity [BO1] | BTC 10x; majors 5x; some 3x; rest 2x [BO1] | 80/20 (90/10 add-on). On-demand USDC ($50 min†). Weekend holding allowed [BO1, BO6†] |
| **HyroTrader** (site 2026) | One-Step 10% (5 days); Two-Step 10% → 5%; Zero-Step [HY1, HY2] | 4% / 5% **trailing the day's equity peak**, reset 00:00 UTC† [HY7†] | Static 6% / 10% of initial [HY2] | Funded: margin ≤25%, notional ≤2× initial [HY5] | 80% → 90%. Deposit refunded with first payout. One day ≤40% of target (excess not counted) [HY2, HY3] |
| **Crypto Fund Trader** (FAQ 2026) | 2-Phase 8% → 5%; 1-Phase 10% [CF1, CF2] | 5% / 4% from balance at **12:05 AM UTC**; breach on equity [CF1] | 2-Phase static 10%. 1-Phase 6% trailing the **balance** high, locks at initial [CF1] | Up to 1:100 on Bybit (USDT perpetuals only) [CF1] | $10K per day/trade profit cap. 80% (90% add-on). $300K allocation [CF1, CF3] |
| **BitFunded** (FAQ 2026) | 2-Step 8% → 5%; 1-Step 10%. Express/Instant figures conflict between pages [BF1, BF4] | Day's realized + floating loss vs a fixed % of starting balance; reset 00:00 UTC+8 [BF2] | Static 10% → 8% / 6% [BF1] | 1–5x; ≤5 open positions; margin ≤65%; max holding time [BF1] | Trader-chosen payout day. 80% (Instant 60%). No bots, no copying [BF1, BF3] |
| **FTMO (CFD incl. crypto)** | 2-Step 10% / 5% (4 days); 1-Step 10% [FT1] | Balance at 00:00 CE(S)T − 5% (2-Step) or 3% (1-Step) of initial; equity includes swaps/fees [FT1] | 2-Step static 10%. 1-Step EOD trailing from the midnight balance [FT1] | Crypto leverage NF | Rewards from day 14. 1-Step 90%; 2-Step 80% (up to 90%). Best day ≤50% of profitable days (1-Step) [FT1, FT3] |
| **FundedNext CFD** (Stellar) | 2-Step 8% / 5%; 1-Step 10%; Lite 8% / 4%; Instant [FX1] | 5% / 3% / 4% of initial, including swaps and commissions; reset 0:00 server time [FX1] | Static 10% / 6% / 8%; Instant 6% trailing [FX1, FX3] | Crypto 1:1 [FX2] | Split up to 95%. News-trade profit counted at 40%. 3% maximum risk at any time [FX3, FX4] |

**How crypto programs differ from futures programs (facts).** Limits are percentages of initial balance. Maximum loss is usually **static**; trailing appears mainly in 1-step or instant products [BO1, FT1, FX1, CF1]. Daily limits are **hard** breaches, anchored to a **UTC/server balance snapshot** instead of a CME session [BO2, CF1, BF2, FT1]. Markets run 24/7 and holding is usually allowed; an open loss carried across the reset counts in full against the new day [FT1, BF2]. Leverage tiers, margin caps, and per-trade risk caps replace contract limits [BO1, HY5, FX3]. 2-step programs and 8–12% targets are common; fees are often refundable, and splits scale over time [FT1, HY2, BF3].

**Inference.** The simulator needs a "day anchor" (UTC time plus balance-vs-equity basis) that is separate from the exchange session, plus swap/funding costs that count toward the limits.

## 3. Precision notes for the simulation

### 3.1 Drawdown types: exactly what is computed

| Type | High-water mark tracks | Floor updates | Breach test | Firms |
| --- | --- | --- | --- | --- |
| Static | — (initial balance) | Never | Equity (including open P&L, fees, swaps) ≤ floor at any instant | ETF Static, Breakout, HyroTrader, FTMO 2-Step, FundedNext Stellar [ET5, BO1, HY2, FT1, FX1] |
| EOD trailing (futures) | Highest **closing** balance. Firms require flat by the close, so this equals realized balance; ETF and TPT say "realized" explicitly | Once per day (Apex 4:59:59 PM ET; TradeDay 4:00 PM CT), effective next session | **Real-time equity**, intraday | Topstep, Apex EOD, Tradeify, Alpha, Lucid, TPT Test, TradeDay, E2T, FTMO Futures [TS6, AP2, TF1, TD6] |
| EOD trailing (24 h markets) | Highest balance at the 00:00 CE(S)T snapshot, open positions excluded | Daily | Equity | FTMO 1-Step [FT1] |
| Intraday trailing | Peak **equity including unrealized**, tick by tick | Continuous | Equity | Apex Intraday, MFFU Rapid, TPT PRO, ETF 1-Step, Bulenox Option 1 [AP3, MF2, ET4, BX2] |
| Balance trailing | Highest realized balance | On each trade close | Equity | CFT 1-Phase, FundedNext Instant [CF1, FX3] |

Two edge cases: TradeDay Quick Pay keeps the high-water mark on **gross** profit, so payouts do not lower it [TD1]. FTMO Futures Pro allows 100% withdrawal, which can leave the balance exactly at the locked floor; touching the floor is a breach [FF1, FF5†].

### 3.2 Trading-day boundaries

| Firm | Day / session | End-of-day calculation | Flat-by | DLL reset |
| --- | --- | --- | --- | --- |
| Topstep | 5 PM–3:10 PM CT [TS1] | End of day; best day locks 3:10 PM CT [TS4] | 3:10 PM CT [TS10] | 5 PM CT [TS7] |
| Apex | Opens 6 PM ET | 4:59:59 PM ET [AP2] | Before close [AP10] | 6 PM ET [AP5] |
| MFFU | 6 PM–4:10 PM ET [MF10] | Session close | 4:10 PM ET (auto) | — |
| Tradeify | — | End of day; reconciliation 6–8 PM ET [TF6] | NF | 6 PM ET [TF7] |
| TPT | 6 PM–5 PM ET† | Close (5 PM ET†) | 4:55 PM ET† | — |
| Alpha | 6 PM–5 PM ET [AL12] | NF | 4:20 PM ET [AL12] | 6 PM ET [AL11] |
| FundedNext Fut. | NF | End of day | No overnight (time NF) | 5 PM CT [FN5] |
| Bulenox | 5 PM–4 PM CT [BX2] | End of day | 3:59 PM CT [BX2] | 5 PM CT [BX2] |
| TradeDay | 5 PM–4 PM CT [TD2] | 4:00 PM CT settled balance [TD6†] | NF | — |
| Earn2Trade | DLL window 5 PM–5 PM CT† | End of day | 3:50 PM CT [E1] | 5 PM CT† |
| FTMO Futures | 6 PM–4:10 PM ET [FF1] | Start of trading day | 4:10 PM ET [FF4] | Start of day [FF1] |
| Crypto | Breakout 00:30 UTC; HyroTrader 00:00 UTC†; CFT 12:05 AM UTC; BitFunded 00:00 UTC+8 (effective 00:00–00:10); FTMO 00:00 CE(S)T; FundedNext CFD 0:00 server time [BO2, HY7†, CF1, BF2, FT1, FX1] | | | |

### 3.3 Daily loss limits and unrealized losses

- **Futures firms count unrealized losses.** Examples: Topstep's "Net P&L hits the DLL" [TS7]; Apex "total account equity, including both realized and unrealized" [AP5]; Alpha includes commissions and fees [AL11]; Bulenox includes commissions [BX2]. A soft breach means: flatten, cancel orders, locked until next session.
- **Fills can go past the limit.** Tradeify and Alpha both warn that liquidation fills may exceed the DLL [TF7, AL11]. A DLL hit with slippage can therefore cross the MLL.
- **Crypto anchors** are in §3.2 and the crypto table. HyroTrader's trailing daily drawdown means intraday gains _shrink_ the remaining room [HY7†]. BitFunded's design means earlier gains that day _add_ room [BF2].

### 3.4 How consistency percentages are calculated

- **General formula:** ratio = best day's P&L in the window ÷ denominator (see D3). Pass if ratio ≤ θ (Tradeify) or < θ (Apex, Alpha). The day's P&L is net (Topstep), excludes commissions (Tradeify), or uses closed trades only (FTMO) [TS4, TF2, FT1].
- **When a breach raises the target:** required total = max(target, best day ÷ θ) [TS4, FN1].
- **Losing days** are part of net profit, so they _raise_ the ratio. FTMO's profitable-days-only denominator ignores losing days [FT1].
- **Window resets** on payout approval. Topstep excludes the request day [TS3]; TradeDay starts the new cycle at the next session [TD2].

### 3.5 Inference: bar-based replay

- **Intraday trailing needs an intrabar path.** With OHLC bars, the order of high and low within a bar is unknown. The worst case is that the favorable extreme came first and raised the high-water mark before the adverse move. Use tick or 1-second data, per-trade MAE/MFE (as StrategyQuant's analyzer does [PA10]), or bound the result using both orderings.
- **Rule checks need distinct events:** intrabar (breach, DLL), session-end (EOD high-water mark, scaling tier, qualifying-day tally), and firm-day-anchor (crypto daily limits).
- **Swing strategies** must be flattened at each firm's flat-by time unless the plan allows holding. That changes their P&L materially.

## 4. Automation and copy-trading policies

| Firm | Automation | Key conditions (quoted where possible) | Copying across your own accounts |
| --- | --- | --- | --- |
| Topstep | Allowed in Combine and XFA | "All trading activity must originate from your personal device. The use of VPS, VPNs, and remote servers is prohibited." "Live funded accounts are not allowed to trade through the ProjectX API." HFT banned. "Unfair technology — software, AI, ultra-high speed systems" banned [TS12, TS11] | TopstepX copier, Combine/XFA only; unlinked during payout† [TS15†] |
| Apex | **Prohibited** | "No Automation or Algorithm Usage allowed"; HFT banned [AP10] | Own accounts allowed†; copying with other traders banned [AP10] |
| MFFU | Allowed | Allowed if tailored to your own settings and "do not aim to exploit the favorable fills offered in the Simulated Environment"; "High-frequency Trading is not allowed" [MF7] | All account types [MF8] |
| Tradeify | Allowed with conditions | Prove sole ownership; live video of enabling the code; scans for similar orders on other accounts; "using it across multiple firms is against Tradeify's policy"; no HFT [TF9, TF13] | Group trading up to 5 accounts [TF10] |
| TPT | **Prohibited** | "Automated trading systems, bots, or algorithmic execution tools are not permitted" [TP1] | Allowed, with approved copiers [TP2] |
| Alpha | **Prohibited** (semi-auto allowed) | "The use of AI, bots, and other automated trading mechanisms is strictly prohibited across all account types"; signal tools OK if you place and manage trades manually; >100 trades/day restricted [AL7] | Single user only [AL8] |
| FundedNext Futures | Allowed | EAs/bots allowed; no latency abuse or order flooding; HFT prohibited [FN6, FN9] | Yes, even across other prop firms if the same verified owner [FN7] |
| Lucid | Allowed | "Automated trading systems and trade copiers are permitted"; HFT banned [LU6, LU5] | Yes [LU6] |
| Bulenox | Permitted (inference) | $100/mo fee to connect copiers, algorithms, or bots via third-party API; the explicit FAQ answer could not be retrieved [BX2] | Yes (same fee) |
| ETF | **Prohibited unless authorized** | AI/bots/EAs need written authorization; "The only automated trading tools currently authorized are the approved trade copiers" [ET7, ET8] | Approved copiers only [ET7] |
| TradeDay | Unclear | No statement found on TradeDay's own pages; third-party reports conflict [TD7†] | Own accounts† |
| Earn2Trade | No permission granted | Bans "software, artificial intelligence, or ultra-fast data entry techniques that could … provide an unfair advantage" [E4] | **Forbidden** [E3] |
| FTMO Futures | NF | — | NF |
| Breakout | Not listed as prohibited; "allowed"† | Bans third-party/off-the-shelf strategies and switching approach between evaluation and funded [BO2, BO6†] | Copying third parties banned; same household/IP banned [BO2] |
| HyroTrader | Allowed (own strategy) | "Allows trading bots, as long as the strategy is your own" [HY4] | Mirror/multi-account trading prohibited in evaluations [HY8] |
| CFT | Allowed with exclusions | HFT, tick-scalping, arbitrage, and multi-account reverse-trading EAs banned [CF1] | Break program only† |
| BitFunded | **Prohibited** | "Not allowed. Every trade has to be placed manually" [BF1] | Prohibited [BF1] |
| FTMO (CFD) | Allowed | Third-party EAs risk max-allocation denial; limits of 200 orders / 2,000 positions per day [FT2] | NF |
| FundedNext CFD | Allowed | EAs must be customized to you; Instant requires an add-on [FX3] | Between own challenge accounts up to $300K, not funded accounts [FX5] |

## 5. Prior art

| Tool | What it models | Gaps (stated, or observed) |
| --- | --- | --- |
| PropSim [PA1] | 61 configurations across 11 futures firms; EOD vs intraday trailing; floor lock; soft/hard DLL; consistency; expiry. Outputs pass rate, EV, cost, days, and an R:R optimizer | Uses summary stats, not trades; single account; funded lifecycle not described |
| PropFirmBacktester [PA2] | 20+ rule inputs including funded terms; failure modes; probability of reaching a withdrawal; ROI over 5–200 challenges | Generic payout assumptions |
| LuxAlgo Prop Firm Sim (2026-08-29) [PA9] | Imports trade history; EOD / intraday-unrealized / lock drawdowns; DLL anchoring; payout gates (days, buffers, caps); multi-phase; joint pass probability with confidence intervals; overlap audit across ≤5 strategies | States which rules it cannot simulate; no account-management policy layer |
| StrategyQuant X b144 + 2-Step Analyzer [PA10] | Full backtest; intraday worst case from per-trade MAE; Monte Carlo that preserves losing streaks; EV by account tier | Built for FTMO-style rules; no futures payout mechanics |
| Build Alpha [PA11] | Prop constraints as filters in strategy search | No lifecycle |
| PropFirmsData [PA4] | Static / EOD / intraday drawdown, DLL, minimum and maximum days | Says it omits correlated streaks, costs, payout-blocking consistency, news, gaps |
| Tanto, DanFin, Funded.Now, DealPropFirm, others [PA3, PA5, PA7, PA8] | Independent-trade Monte Carlo with firm presets | Funded.Now says it omits locks, scaling, minimum profitable days, expiry |
| Sadra.nl [PA6] | Firm rules plus a "multi-account strategy lab": P(≥1 pass), P(all pass), expected passes, expected $/month | Correlation model not specified |

**Published analyses.**

- **NexusFi** [PA12]: EV(N) = P(survive) × E[profit] × N − Cost(N). It warns that copied accounts have 0.7–0.9 correlation, so running identical trades makes "blowing ALL accounts" closer to 40% likely than 0.01%. It recommends rotating accounts in groups.
- **Vantage Stack** (vendor, 2.88M simulations) [PA13]: a timed evaluation (Apex's 30 days) forces aggressive sizing; untimed evaluations reward conservative sizing; it recommends switching to conservative sizing once funded.
- **arXiv 2609.14859** (Hall, 2026-09-14) [PA14]: under EOD trailing, the evaluation rewards "fast, lumpy" trading while the funded stage punishes it ("a factor of nine in the joint gate"). Sizing alone with zero skill gives about 0.40 pass probability, against a measured 0.168. It found no positive-EV configuration in its strategy universe. Code is on GitHub.
- **Industry statistics:** about 14% pass, about 7% ever paid, average payout about 4% of nominal (FPFX data, ~300K accounts†) [PA15]. TPT itself disclosed a 20.37% pass rate for Jan–Aug 2023 [TP6].

**Inference: what existing tools miss.**

1. Replaying an actual bar or tick series, with intrabar ordering, for intraday trailing and DLL.
2. Firm-specific funded payout logic: payout ladders, relative qualifying days, how payouts move the floor, high-water mark on gross vs net profit.
3. An account-management policy layer: buy/reset decisions, household caps, pending queues, 30-day expiry, activation windows, monthly vs one-time fees, promotions.
4. Correlation between accounts running the same strategy.
5. Live-transition side effects (accounts force-closed, forfeiture, reserves).
6. Rule versions by purchase date.
7. Conduct rules (hold-time shares, automation and copier bans) as feasibility filters on a strategy.

## 6. Suggested schema shape (inference)

```text
Firm{ id, timezone, accountCaps{eval, funded, live, scope:user|household, overflow:queue|block}, conduct{automation, copyOwn, hedging, minHold} }
Plan{ id, firmId, version{effectiveFrom, appliesTo:purchaseDate}, size, fees{model:oneTime|monthly, price, activation, reset, fundedMonthly, data}, stages[] }
Stage{ kind:eval|funded|live|prelive, expiry, minDays{n, dayDef}, target{amount, basis:closed|equity, requireFlat},
  drawdown{type:static|eod|intraday|balanceTrail, amount, hwmSource:close|realized|peakEquity|gross, enforceOn:equity, touchIsBreach,
           lock{level:start|start+X|target|none, triggers:[hwm, payoutRequest, firstPayout]}, onPayout:none|lock|resetTo0|keepGross},
  dailyLoss{mode:none|soft|hard, amount|pct, anchor:sessionPnL|snapshotBalance|dayPeakEquity, resetTime, dynamic:tiers|pctOfPeakProfit, removeWhenLocked},
  consistency{window, numerator:day|trade|instrument, denominator:netProfit|target|positiveDays|gross, theta[], inclusive, effect:raiseTarget|blockPayout|discount|penalty},
  session{dayStart, flatBy, overnight, weekend, news[]}, position{maxContracts, microRatio, scaling{basis, table, effective:nextSession}},
  payout{gates[], amount{rule, caps[] byPayoutNo, min}, split{schedule}, cadence, lifetimeCap{count|usd}, whilePending:trade|noTrade|flat},
  transitions[{trigger, to, mandatory, sideEffects:[closeOthers, forfeitSim, reserve, cooldown]}] }
```

## 7. Not found or conflicting

- **Topstep:** maximum concurrent Combines (NF); 150K Standard price is $199 on Topstep's page vs $149 on third-party sites.
- **Apex:** EOD payout ladder seen only on third-party pages; live path under 4.0 (NF).
- **Tradeify:** Growth and Lightning cap tables not extracted.
- **Alpha:** live-account ("Alpha Prime") criteria (NF).
- **FundedNext Futures:** prices (NF); its two pages disagree on the high-water-mark wording.
- **Lucid:** most per-plan numbers are third-party only.
- **Bulenox:** prices, targets, and contract limits third-party only; whether consistency is lifetime or per cycle unconfirmed; automation FAQ could not be opened.
- **ETF:** 10-second hold rule and ~$80/mo funded fee third-party only.
- **TradeDay:** automation policy and Funded Sim cap not on its own pages.
- **Earn2Trade:** whether the DLL is hard or soft at each stage, and prices.
- **FTMO Futures:** Pro consistency 50% and Pro funded DLL third-party only; automation policy NF.
- **TPT:** buffer-withdrawal penalty, $50 small-withdrawal fee, and 4:55 PM ET flat time third-party only.
- **BitFunded:** Express/Instant figures conflict between its FAQ and an Aug-2026 article.
- **HyroTrader:** trailing daily mechanics and 3%-per-trade cap third-party only.
- **FTMO:** crypto leverage (NF).
- **Breakout:** explicit bot permission on its own pages (NF).

## Sources

**Topstep**

- TS1 https://help.topstep.com/en/articles/8284197-trading-combine-parameters (acc.)
- TS2 https://help.topstep.com/en/articles/8284215-express-funded-account-parameters (2026-08-05)
- TS3 https://help.topstep.com/en/articles/8284233-topstep-payout-policy (acc.)
- TS4 https://help.topstep.com/en/articles/8284208-consistency-at-topstep (acc.)
- TS5 https://help.topstep.com/en/articles/10657969-live-funded-account-parameters ; https://www.topstep.com/live-funded-account-rules (2026-07-01)
- TS6 https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit
- TS7 https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account
- TS8 https://help.topstep.com/en/articles/9208217-topstep-pricing
- TS9 https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan (2026-07-16)
- TS10 https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade
- TS11 https://help.topstep.com/en/articles/10305426 (2026-06-10) ; https://help.topstep.com/en/articles/10296582-prohibited-conduct
- TS12 https://help.topstep.com/en/articles/11187768-topstepx-api-access
- TS13 https://help.topstep.com/en/articles/15520357-topstep-labs
- TS15† https://proptradingvibes.com/blog/topstep-copy-trading-rules
- TS17 https://help.topstep.com/en/articles/13620045-what-is-the-responsible-trading-program

**Apex** (base https://apextraderfunding.com/help-center/)

- AP1 …/eod-trailing-drawdown-accounts/eod-evaluations/
- AP2 https://support.apextraderfunding.com/hc/en-us/articles/45631563363483-EOD-Drawdown-Explained
- AP3 …/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-explained/ (2026-01-21)
- AP4 …/evaluation-accounts-ea/intraday-trailing-drawdown-evaluations/
- AP5 …/additional-helpful-items/daily-loss-limit-explained/
- AP6 …/eod-trailing-drawdown-accounts/eod-performance-accounts-pa/
- AP7 …/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-performance-accounts-pa/
- AP8 …/eod-trailing-drawdown-accounts/eod-payouts/
- AP9 …/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-payouts/
- AP10 …/getting-started/prohibited-activities/ (2026-07-31)
- AP11 …/billing/evaluation-plan-fees-and-access-explained/
- AP12 …/billing/pa-activation-process-deadline-explained/
- AP13† https://www.futureshive.com/blog/apex-trader-funding-review (2026-10-05) ; https://traderssecondbrain.com/guides/apex-payout-rules-explained (2026-09-22)

**My Funded Futures** (base https://help.myfundedfutures.com/en/articles/)

- MF1 13745661 (2026-08-25)
- MF2 13134709
- MF3 16158363
- MF4 11802674 (2026-06-30) + https://myfundedfutures.com/plans/pro
- MF5 14290805 (2026-07-07) + https://myfundedfutures.com/plans/builder
- MF6 16498635
- MF7 8444599 (2026-08-24)
- MF8 10771500
- MF9 8230009 (2026-08-31)
- MF10 9558251
- MF11† https://proptradingvibes.com/blog/myfundedfutures-pricing

**Tradeify** (base https://help.tradeify.co/en/articles/)

- TF1 10495897 (2026-08-26)
- TF2 10468320 (2026-08-19)
- TF3 13252431
- TF4 10495938
- TF5 12853966
- TF6 10495932
- TF7 10468321 (2026-08-25)
- TF8 12268167
- TF9 10468318 (2026-08-12)
- TF10 10468299
- TF11 12969284
- TF12 14369021 (2026-09-01)
- TF13 https://tradeify.co/funded-trader-agreement

**Take Profit Trader** (base https://takeprofittraderhelp.zendesk.com/hc/en-us/articles/)

- TP1 34431153546397
- TP2 34431223270557
- TP3 15172006753821 (2026-09-22)
- TP4 30331694826909
- TP5 https://takeprofittrader.com/blog/3-day-evals (2026-08-17)
- TP6 https://takeprofittrader.com/
- TP7 https://try.takeprofittrader.com/TPT-FAQs-nf40-4-0725
- TP8† https://phidiaspropfirm.com/education/take-profit-trader-payout-rules ; https://damnpropfirms.com/futures-prop-firms/take-profit-trader/

**Alpha Futures** (base https://help.alpha-futures.com/en/articles/; help-center pages dated Jul–Aug 2026)

- AL1 9492048
- AL2 11632512
- AL3 9492051
- AL5 11634907
- AL6 https://alpha-futures.com/how-it-works ; https://alpha-futures.com/product/standard
- AL7 9508585
- AL8 10573989
- AL9 9492063
- AL10 9492088
- AL11 9492014
- AL12 9492096
- AL13 https://alpha-futures.com/posts/how-to-pass-a-futures-prop-evaluation-2026

**FundedNext Futures** (base https://helpfutures.fundednext.com/en/articles/)

- FN1 17229536
- FN2 17229581
- FN3 17229762
- FN4 14298225
- FN5 https://fundednext.com/general-rules/futures/trading-objectives
- FN6 14298560
- FN7 14298572
- FN8 17225812
- FN9 15358782
- FN10 17225788
- FN11 14282044
- FN12 14255818

**Lucid** (base https://support.lucidtrading.com/en/articles/)

- LU1 12890092
- LU2 12890192
- LU3 16558826
- LU4 11404617
- LU5 11404736
- LU6 11404728
- LU7 https://lucidtrading.com/general-faq/
- LU8† https://spicyfutures.com/lucid-trading-rules/ (2026-09-27) ; https://proptradingvibes.com/blog/lucid-vs-myfundedfutures

**Bulenox**

- BX1 https://bulenox.com/help/master-account/
- BX2 https://bulenox.com/help/qualification-account/
- BX3† https://tradetanto.com/learn/bulenox-rules-what-traders-need-to-know ; https://tradeharbor.co/prop-firm-rules/bulenox

**Elite Trader Funding** (base https://elitetraderfunding.app/)

- ET1 evaluations
- ET2 help/how-do-payouts-work
- ET3 help/how-the-end-of-day-plan-works
- ET4 help/how-the-1-step-plan-works
- ET5 help/how-the-static-account-plan-works
- ET6 help/how-the-revamped-fast-track-plan-works
- ET7 help/trade-copier-disclaimer
- ET8 terms-of-service
- ET9 help/live-elite-turning-strategy-into-income
- ET10† https://blog.traderspost.io/article/elite-trader-funding-review

**TradeDay** (base https://tradeday.freshdesk.com/en/support/solutions/articles/)

- TD1 103000335937
- TD2 103000404096
- TD3 103000405228
- TD4 103000405229
- TD5 103000008847
- TD6 103000250682
- TD7† https://comparefuturesprop.com/firms/tradeday ; https://blog.traderspost.io/article/tradeday-review ; https://propnavi.io/en/firms/tradeday/

**Earn2Trade**

- E1 https://www.earn2trade.com/gauntlet-mini
- E2 https://www.earn2trade.com/trader-career-path
- E3 https://help.earn2trade.com/en/articles/12034590
- E4 https://help.earn2trade.com/en/articles/9286647
- E5 https://help.earn2trade.com/en/articles/5660666
- E6 https://www.earn2trade.com/blog/after-funded-with-earn2trade/ (update 2026-07-06)
- E7† https://tradeharbor.co/prop-firm-rules/earn2trade

**FTMO Futures**

- FF1 https://ftmo.com/en/futures/trading-objectives-and-rules
- FF2 https://ftmo.com/en/press-release/ftmo-launches-ftmo-futures/ (2026-09-17)
- FF3 https://ftmo.com/en/futures/blog/ftmo-futures-is-here-prove-your-edge-in-the-futures-market/
- FF4 https://ftmo.com/en/futures/faq/which-instruments-can-i-trade-with-ftmo-futures/
- FF5† https://thepropjournalist.com/news/ftmo-futures-launch/ ; https://trailingstoploss.com/ftmo-futures-launch/

**Crypto firms**

- Breakout: BO1 https://www.breakoutprop.com/program-rules/ ; BO2 https://www.breakoutprop.com/breakout-evaluation-agreement/ ; BO3 https://intercom.help/breakoutprop/en/articles/11647201 ; BO5 https://www.breakoutprop.com/article/pass-prop-firm-evaluation/ ; BO6† https://cryptoslate.com/prop-firms/breakout-review/ ; https://fundedwiki.com/breakout
- HyroTrader: HY1 https://www.hyrotrader.com/trading-rules/ ; HY2 https://www.hyrotrader.com/one-step-evaluation-prop-firm/ ; HY3 https://www.hyrotrader.com/faq/trading-restrictions/i-have-one-trading-day-that-exceeds-the-profit-distribution-rule-what-happens-now/ ; HY4 https://www.hyrotrader.com/faq/hyrotrader-account/can-i-use-trading-bots-or-signal-bots-during-the-challenge-or-on-a-funded-account/ ; HY5 https://www.hyrotrader.com/faq/rules/are-there-any-other-rules-for-a-funded-account/ ; HY6 https://www.hyrotrader.com/faq/trading-restrictions/what-are-prohibited-trading-actions/ ; HY7† https://cryptoslate.com/prop-firms/hyrotrader-review/ ; HY8 https://www.hyrotrader.com/terms-and-conditions/
- Crypto Fund Trader: CF1 https://cryptofundtrader.com/faq/ ; CF2 https://cryptofundtrader.com/crypto-risk-management-prop-trading/ ; CF3 https://cryptofundtrader.com/automated-crypto-trading-prop-firm-funding/
- BitFunded: BF1 https://www.bitfunded.com/faq/ ; BF2 https://bitfunded.gitbook.io/support/introduction/criteria-to-be-success ; BF3 https://bitfunded.gitbook.io/support/common-questions/how-to-withdraw ; BF4 https://www.bitfunded.com/how-to-choose-the-right-prop-trading-challenge-2-step-vs-1-step-vs-1-step-express-vs-instant-accounts/
- FTMO: FT1 https://ftmo.com/en/trading-objectives/ ; FT2 https://ftmo.com/en/faq/which-instruments-can-i-trade-and-what-strategies-am-i-allowed-to-use/ ; FT3 https://ftmo.com/en/faq/how-do-i-withdraw-my-profits/ ; FT4 https://ftmo.com/en/faq/do-i-have-to-close-my-positions-overnight-or-before-the-weekend/
- FundedNext CFD: FX1 https://fundednext.com/general-rules/cfds/trading-objectives ; FX2 https://fundednext.com/general-rules/cfds/symbols-and-conditions ; FX3 https://help.fundednext.com/en/articles/17253243-stellar-instant-account ; FX4 https://fundednext.com/usa/cfds/stellar-2-step ; FX5 https://help.fundednext.com/en/articles/8019805-what-is-the-copy-trading-rule-at-fundednext

**Prior art**

- PA1 https://propsim.io/
- PA2 https://propfirmbacktester.com/
- PA3 https://tradetanto.com/tools/prop-firm-simulator
- PA4 https://www.propfirmsdata.com/tools/pass-probability-calculator/
- PA5 https://danfin.net/
- PA6 https://sadra.nl/prop-calculator
- PA7 https://dealpropfirm.com/challenge-simulator
- PA8 https://funded.now/trading-tools/challenge-simulator
- PA9 https://www.luxalgo.com/blog/introducing-prop-firm-sim/
- PA10 https://strategyquant.com/codebase/the-2-step-challenge-analyzer-for-ftmo-know-if-your-strategy-will-pass-before-you-pay/
- PA11 https://www.buildalpha.com/build-alpha-for-metatrader/
- PA12 https://nexusfi.com/a/prop-firms/expected-value-prop-firm-evaluations ; https://nexusfi.com/a/prop-firms/multiple-funded-accounts
- PA13 https://vantage-stack.com/articles/prop-firm-analysis
- PA14 https://arxiv.org/abs/2609.14859
- PA15† https://proptraderreviews.com/guides/how-prop-firms-actually-make-money-revenue-streams-a-book-vs-b-book-and-where-your-payout-comes-from
