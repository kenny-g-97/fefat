// FEFAT's cross-check strategy for NinjaTrader 8's Strategy Analyzer (step 2.14, D-59): the
// same bar-close strategy as scripts/xcheck.py's `market` strategy. Long when the close is above
// the previous close, short when below, one contract, a stop and a target at fixed ticks from
// the signal bar's close, entries inside a window of the platform's clock, flat by a time of it.
// Run it on MNQ 09-26, a 5-minute series, with the order fill resolution High on 1-minute bars
// (python/tests/external/README.md has the runbook); export the Trades tab for `just xcheck`.
#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class FefatCrossCheck : Strategy
    {
        private const string LongEntry = "L";
        private const string ShortEntry = "S";
        private const string FlatByExit = "FlatBy";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "FEFAT cross-check (step 2.14): bar-close momentum with a stop and a target at fixed prices";
                Name = "FefatCrossCheck";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = false;
                IsFillLimitOnTouch = true;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.High;
                OrderFillResolutionType = BarsPeriodType.Minute;
                OrderFillResolutionValue = 1;
                Slippage = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Gtc;
                TraceOrders = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 2;
                IsInstantiatedOnEachOptimizationIteration = true;

                StopTicks = 40;
                TargetTicks = 40;
                WindowStart = 935;
                WindowEnd = 1530;
                FlatBy = 1600;
                TradeFrom = new DateTime(2026, 8, 3);
                TradeTo = new DateTime(2026, 8, 31);
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 1)
                return;

            // Time[0] is the bar's close on the platform's clock, as FEFAT's ts_close is in UTC.
            int clock = ToTime(Time[0]) / 100;
            if (clock >= FlatBy)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong(FlatByExit, LongEntry);
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort(FlatByExit, ShortEntry);
                return;
            }
            if (Position.MarketPosition != MarketPosition.Flat)
                return;
            DateTime day = Time[0].Date;
            if (day < TradeFrom.Date || day > TradeTo.Date)
                return;
            if (clock < WindowStart || clock >= WindowEnd)
                return;

            if (Close[0] > Close[1])
            {
                SetStopLoss(LongEntry, CalculationMode.Price, Close[0] - StopTicks * TickSize, false);
                SetProfitTarget(LongEntry, CalculationMode.Price, Close[0] + TargetTicks * TickSize);
                EnterLong(1, LongEntry);
            }
            else if (Close[0] < Close[1])
            {
                SetStopLoss(ShortEntry, CalculationMode.Price, Close[0] + StopTicks * TickSize, false);
                SetProfitTarget(ShortEntry, CalculationMode.Price, Close[0] - TargetTicks * TickSize);
                EnterShort(1, ShortEntry);
            }
        }

        #region Properties
        [NinjaScriptProperty]
        [Range(1, int.MaxValue)]
        [Display(Name = "Stop ticks", Description = "The stop's distance from the signal bar's close, in ticks", Order = 1, GroupName = "Parameters")]
        public int StopTicks { get; set; }

        [NinjaScriptProperty]
        [Range(1, int.MaxValue)]
        [Display(Name = "Target ticks", Description = "The target's distance from the signal bar's close, in ticks", Order = 2, GroupName = "Parameters")]
        public int TargetTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "Window start (HHmm)", Description = "Entries from this time of the platform's clock (935 is 08:35 Chicago on a US Eastern clock)", Order = 3, GroupName = "Parameters")]
        public int WindowStart { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "Window end (HHmm)", Description = "No entry from this time of the platform's clock (1530 is 14:30 Chicago)", Order = 4, GroupName = "Parameters")]
        public int WindowEnd { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "Flat by (HHmm)", Description = "The position is closed at the first bar closing at or after this time of the platform's clock (1600 is 15:00 Chicago)", Order = 5, GroupName = "Parameters")]
        public int FlatBy { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Trade from", Description = "The first day with entries; earlier bars only feed the previous close", Order = 6, GroupName = "Parameters")]
        public DateTime TradeFrom { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Trade to", Description = "The last day with entries", Order = 7, GroupName = "Parameters")]
        public DateTime TradeTo { get; set; }
        #endregion
    }
}
