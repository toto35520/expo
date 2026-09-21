using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum ContextMode
    {
        Off,
        FastEma,
        EmaAndDmi
    }

    /// <summary>
    /// GOLD ORDER FLOW ENGINE (v0.5)
    ///
    /// A microstructure score in [-100, +100] built from the order book and the tick
    /// stream, used to GATE entries and to RELEASE exits, rather than another
    /// oscillator stacked on a chart.
    ///
    /// ---------------------------------------------------------------------------
    /// WHAT THE RESEARCH ACTUALLY SAYS
    ///
    /// Cont, Kukanov & Stoikov, "The Price Impact of Order Book Events"
    /// (arXiv:1011.6402) find that short-horizon price changes are close to linear in
    /// ORDER FLOW IMBALANCE, and that the coefficient scales inversely with depth:
    ///
    ///     dP  ~=  beta * OFI / depth
    ///
    /// OFI is the CHANGE in queue sizes at the best quotes between book events, not a
    /// static bid/ask size ratio:
    ///
    ///     e_n =  1{Pb_n >= Pb_n-1} * qb_n  -  1{Pb_n <= Pb_n-1} * qb_n-1
    ///          - 1{Pa_n <= Pa_n-1} * qa_n  +  1{Pa_n >= Pa_n-1} * qa_n-1
    ///
    /// The static ratio is a different, weaker quantity. This engine computes both and
    /// weights them separately.
    ///
    /// THREE REASONS THE PUBLISHED EFFECT MAY NOT TRANSFER HERE
    ///
    ///   1. Scale. CKS measure impact in ticks on equities, where one tick IS the
    ///      spread. On XAUUSD a 0.9 pip spread spans nine price increments, so the
    ///      signal must predict roughly an order of magnitude more movement before it
    ///      pays for the round trip. This, not book quality, is the binding problem.
    ///
    ///   2. The book is a liquidity provider's, not the market's. A CFD depth ladder
    ///      shows what one broker's LPs will quote, and an LP long gold widens its ask
    ///      to unload inventory. Imbalance there is partly inventory management, so
    ///      the SIGN of the relationship need not match the equity literature.
    ///
    ///   3. It is not the CME tape. There is no aggressor side, no executed volume at
    ///      bid versus ask, no footprint and no true cumulative delta. Everything here
    ///      is inferred from quote changes, which is strictly less information.
    ///
    /// SO THE ENGINE MEASURES ITSELF. Every sample pairs the current OFI with the mid
    /// price change realised over the next few seconds, and the session summary
    /// regresses one on the other and reports beta, its t-statistic and R-squared on
    /// YOUR feed. Run it flat first and read those numbers before trading a cent: if
    /// beta is not significant, no weighting of these features will save the strategy.
    /// ---------------------------------------------------------------------------
    /// </summary>
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC, AddIndicators = true)]
    public class GoldOrderFlow : Robot
    {
        #region 01 - General

        [Parameter("Instance label", Group = "01 - General", DefaultValue = "OFE")]
        public string InstanceLabel { get; set; }

        [Parameter("Verbose logs", Group = "01 - General", DefaultValue = true)]
        public bool Verbose { get; set; }

        [Parameter("On-chart dashboard", Group = "01 - General", DefaultValue = true)]
        public bool ShowDashboard { get; set; }

        [Parameter("Measure only, do not trade", Group = "01 - General", DefaultValue = true)]
        public bool MeasureOnly { get; set; }

        #endregion

        #region 02 - Microstructure

        [Parameter("Depth levels used", Group = "02 - Microstructure", DefaultValue = 5, MinValue = 1, MaxValue = 20)]
        public int DepthLevels { get; set; }

        [Parameter("Flow window (seconds)", Group = "02 - Microstructure", DefaultValue = 10, MinValue = 1, MaxValue = 300)]
        public int FlowWindowSeconds { get; set; }

        [Parameter("Tick window (ticks)", Group = "02 - Microstructure", DefaultValue = 50, MinValue = 5, MaxValue = 1000)]
        public int TickWindow { get; set; }

        [Parameter("Prediction horizon (seconds)", Group = "02 - Microstructure", DefaultValue = 10, MinValue = 1, MaxValue = 300)]
        public int HorizonSeconds { get; set; }

        #endregion

        #region 03 - Score weights

        [Parameter("Weight: order flow imbalance", Group = "03 - Weights", DefaultValue = 30, MinValue = 0, MaxValue = 100)]
        public double WeightOfi { get; set; }

        [Parameter("Weight: depth imbalance", Group = "03 - Weights", DefaultValue = 20, MinValue = 0, MaxValue = 100)]
        public double WeightDepth { get; set; }

        [Parameter("Weight: microprice", Group = "03 - Weights", DefaultValue = 15, MinValue = 0, MaxValue = 100)]
        public double WeightMicroprice { get; set; }

        [Parameter("Weight: tick direction", Group = "03 - Weights", DefaultValue = 15, MinValue = 0, MaxValue = 100)]
        public double WeightTicks { get; set; }

        [Parameter("Weight: absorption", Group = "03 - Weights", DefaultValue = 10, MinValue = 0, MaxValue = 100)]
        public double WeightAbsorption { get; set; }

        [Parameter("Weight: spread quality", Group = "03 - Weights", DefaultValue = 10, MinValue = 0, MaxValue = 100)]
        public double WeightSpread { get; set; }

        [Parameter("OFI normalisation clip", Group = "03 - Weights", DefaultValue = 2.0, MinValue = 0.2, MaxValue = 10, Step = 0.1)]
        public double OfiClip { get; set; }

        #endregion

        #region 04 - Context

        [Parameter("Context filter", Group = "04 - Context", DefaultValue = ContextMode.EmaAndDmi)]
        public ContextMode Context { get; set; }

        [Parameter("Context timeframe", Group = "04 - Context", DefaultValue = "Minute5")]
        public TimeFrame ContextTimeFrame { get; set; }

        [Parameter("Context EMA period", Group = "04 - Context", DefaultValue = 21, MinValue = 2, MaxValue = 200)]
        public int ContextEmaPeriod { get; set; }

        [Parameter("DMI period", Group = "04 - Context", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int DmiPeriod { get; set; }

        [Parameter("Min ADX", Group = "04 - Context", DefaultValue = 18.0, MinValue = 0, MaxValue = 60, Step = 1)]
        public double MinAdx { get; set; }

        #endregion

        #region 05 - Entry and exit

        [Parameter("Min score to enter", Group = "05 - Entry", DefaultValue = 55.0, MinValue = 10, MaxValue = 100, Step = 1)]
        public double MinEntryScore { get; set; }

        [Parameter("Flip score to exit", Group = "05 - Entry", DefaultValue = 35.0, MinValue = 5, MaxValue = 100, Step = 1)]
        public double ExitFlipScore { get; set; }

        [Parameter("Hold runner while flow agrees", Group = "05 - Entry", DefaultValue = true)]
        public bool HoldWhileFlowAgrees { get; set; }

        [Parameter("Stop = ATR x", Group = "05 - Entry", DefaultValue = 1.0, MinValue = 0.2, MaxValue = 10, Step = 0.1)]
        public double StopAtr { get; set; }

        [Parameter("Take profit = R x (0=flow only)", Group = "05 - Entry", DefaultValue = 2.5, MinValue = 0, MaxValue = 20, Step = 0.1)]
        public double TakeProfitR { get; set; }

        [Parameter("Max hold (seconds, 0=off)", Group = "05 - Entry", DefaultValue = 300, MinValue = 0, MaxValue = 7200)]
        public int MaxHoldSeconds { get; set; }

        [Parameter("Cooldown after exit (seconds)", Group = "05 - Entry", DefaultValue = 15, MinValue = 0, MaxValue = 600)]
        public int CooldownSeconds { get; set; }

        #endregion

        #region 06 - Risk

        [Parameter("Risk per trade (% equity)", Group = "06 - Risk", DefaultValue = 0.5, MinValue = 0.05, MaxValue = 5, Step = 0.05)]
        public double RiskPercent { get; set; }

        [Parameter("ATR period", Group = "06 - Risk", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AtrPeriod { get; set; }

        [Parameter("Max spread (pips)", Group = "06 - Risk", DefaultValue = 3.0, MinValue = 0.5, Step = 0.5)]
        public double MaxSpreadPips { get; set; }

        [Parameter("Max trades per day", Group = "06 - Risk", DefaultValue = 20, MinValue = 1, MaxValue = 500)]
        public int MaxTradesPerDay { get; set; }

        [Parameter("Daily loss cap (% equity, 0=off)", Group = "06 - Risk", DefaultValue = 3.0, MinValue = 0, MaxValue = 50, Step = 0.5)]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Session start (UTC hour)", Group = "06 - Risk", DefaultValue = 7.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionStart { get; set; }

        [Parameter("Session end (UTC hour)", Group = "06 - Risk", DefaultValue = 17.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionEnd { get; set; }

        #endregion

        #region State

        private class FlowEvent
        {
            public DateTime Time;
            public double Ofi;
            public double Mid;
        }

        private class Sample
        {
            public DateTime Time;
            public double NormalisedOfi;
            public double Mid;
            public bool Settled;
            public double Outcome;
        }

        private class TickRecord
        {
            public DateTime Time;
            public double Mid;
            public int Direction;
        }

        private readonly List<FlowEvent> _flow = new List<FlowEvent>();
        private readonly List<TickRecord> _ticks = new List<TickRecord>();
        private readonly List<Sample> _samples = new List<Sample>();

        private MarketDepth _depth;
        private ExponentialMovingAverage _contextEma;
        private DirectionalMovementSystem _dmi;
        private AverageTrueRange _atr;
        private Bars _contextBars;

        private string _label;
        private bool _log;
        private bool _depthAvailable;
        private int _depthUpdates;

        private double _prevBidPrice, _prevBidSize, _prevAskPrice, _prevAskSize;
        private bool _bookSeeded;

        private double _ofiWindow;
        private double _depthImbalance;
        private double _micropriceSignal;
        private double _tickDirection;
        private double _absorption;
        private double _spreadQuality;
        private double _score;
        private double _avgDepth = 1;
        private double _spreadAverage;
        private DateTime _lastSampleTime = DateTime.MinValue;

        private DateTime _positionOpened = DateTime.MinValue;
        private DateTime _lastExitTime = DateTime.MinValue;
        private double _positionRiskPips;

        private DateTime _currentDay;
        private double _dayStartEquity;
        private int _tradesToday;
        private bool _dayLocked;
        private string _status = "starting";

        private int _statTrades, _statWins;
        private double _statNet, _statGrossProfit, _statGrossLoss;

        #endregion

        #region Lifecycle

        protected override void OnStart()
        {
            _label = string.IsNullOrWhiteSpace(InstanceLabel) ? "OFE" : InstanceLabel.Trim();
            _log = Verbose && RunningMode != RunningMode.Optimization;

            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);
            _dmi = Indicators.DirectionalMovementSystem(DmiPeriod);
            _contextBars = MarketData.GetBars(ContextTimeFrame);
            _contextEma = Indicators.ExponentialMovingAverage(_contextBars.ClosePrices, ContextEmaPeriod);

            _spreadAverage = SpreadPips;
            StartNewDay();

            _depth = MarketData.GetMarketDepth(SymbolName);
            if (_depth != null) _depth.Updated += OnDepthUpdated;

            Positions.Closed += OnPositionClosed;

            Print("=== GOLD ORDER FLOW ENGINE v0.5 ===");
            Print("Order flow imbalance per Cont, Kukanov & Stoikov (arXiv:1011.6402)");
            Print("Symbol {0} | spread {1:F1} pips | horizon {2}s | flow window {3}s",
                SymbolName, SpreadPips, HorizonSeconds, FlowWindowSeconds);

            if (MeasureOnly)
                Print("MEASURE ONLY is ON: the engine scores and records, and places no orders. "
                    + "Leave it on for a few sessions, read the regression in the summary, and only "
                    + "then decide whether the signal is worth trading.");

            Print("Depth ladder: waiting for the first book update to confirm availability.");
        }

        protected override void OnStop()
        {
            if (_depth != null) _depth.Updated -= OnDepthUpdated;
            Positions.Closed -= OnPositionClosed;
            PrintStatistics();
        }

        protected override void OnTick()
        {
            RollDayIfNeeded();
            RecordTick();
            UpdateSpreadAverage();
            TrimWindows();
            SettleSamples();
            ComputeScore();
            TakeSample();

            ManagePosition();
            EnforceDailyGuard();

            if (!MeasureOnly) ConsiderEntry();

            UpdateDashboard();
        }

        #endregion

        #region Order book

        /// <summary>
        /// Fires whenever the ladder changes. Order flow imbalance is a difference
        /// between consecutive book states, so this is the only place it can be
        /// computed - a snapshot on its own carries no flow information.
        /// </summary>
        private void OnDepthUpdated()
        {
            double bidPrice = 0, bidSize = 0, askPrice = 0, askSize = 0;
            double bidDepth = 0, askDepth = 0;
            int bidLevels = 0, askLevels = 0;

            foreach (MarketDepthEntry entry in _depth.Bids)
            {
                if (bidLevels == 0) { bidPrice = entry.Price; bidSize = entry.Volume; }
                if (bidLevels < DepthLevels) bidDepth += entry.Volume;
                bidLevels++;
            }

            foreach (MarketDepthEntry entry in _depth.Asks)
            {
                if (askLevels == 0) { askPrice = entry.Price; askSize = entry.Volume; }
                if (askLevels < DepthLevels) askDepth += entry.Volume;
                askLevels++;
            }

            if (bidLevels == 0 || askLevels == 0) return;

            _depthUpdates++;
            if (!_depthAvailable)
            {
                _depthAvailable = true;
                Print("Depth ladder available: {0} bid levels, {1} ask levels on the first update.",
                    bidLevels, askLevels);
            }

            double total = bidDepth + askDepth;
            _depthImbalance = total > 0 ? (bidDepth - askDepth) / total : 0;
            _avgDepth = total > 0 ? total / 2.0 : _avgDepth;

            double sizeTotal = bidSize + askSize;
            if (sizeTotal > 0 && askPrice > bidPrice)
            {
                // Microprice leans towards the side with LESS size, because that side
                // is the one likely to be cleared first.
                double microprice = (bidPrice * askSize + askPrice * bidSize) / sizeTotal;
                double mid = (bidPrice + askPrice) / 2.0;
                double spread = askPrice - bidPrice;
                _micropriceSignal = spread > 0 ? 2.0 * (microprice - mid) / spread : 0;
            }

            if (!_bookSeeded)
            {
                _prevBidPrice = bidPrice; _prevBidSize = bidSize;
                _prevAskPrice = askPrice; _prevAskSize = askSize;
                _bookSeeded = true;
                return;
            }

            // Cont, Kukanov & Stoikov (2014), equation for e_n.
            double e = 0;
            if (bidPrice >= _prevBidPrice) e += bidSize;
            if (bidPrice <= _prevBidPrice) e -= _prevBidSize;
            if (askPrice <= _prevAskPrice) e -= askSize;
            if (askPrice >= _prevAskPrice) e += _prevAskSize;

            _flow.Add(new FlowEvent
            {
                Time = Server.Time,
                Ofi = e,
                Mid = (bidPrice + askPrice) / 2.0
            });

            _prevBidPrice = bidPrice; _prevBidSize = bidSize;
            _prevAskPrice = askPrice; _prevAskSize = askSize;
        }

        #endregion

        #region Features

        private void RecordTick()
        {
            double mid = (Symbol.Bid + Symbol.Ask) / 2.0;
            int direction = 0;
            if (_ticks.Count > 0)
            {
                double previous = _ticks[_ticks.Count - 1].Mid;
                if (mid > previous) direction = 1;
                else if (mid < previous) direction = -1;
            }

            _ticks.Add(new TickRecord { Time = Server.Time, Mid = mid, Direction = direction });
            while (_ticks.Count > TickWindow * 3) _ticks.RemoveAt(0);
        }

        private void TrimWindows()
        {
            DateTime cutoff = Server.Time.AddSeconds(-FlowWindowSeconds);
            while (_flow.Count > 0 && _flow[0].Time < cutoff) _flow.RemoveAt(0);
            while (_flow.Count > 20000) _flow.RemoveAt(0);
        }

        private void ComputeScore()
        {
            // --- order flow imbalance over the window, scaled by depth as CKS specify
            _ofiWindow = 0;
            for (int i = 0; i < _flow.Count; i++) _ofiWindow += _flow[i].Ofi;

            double normalisedOfi = _avgDepth > 0 ? _ofiWindow / _avgDepth : 0;
            double ofiSignal = Clip(normalisedOfi / OfiClip);

            // --- tick direction ratio over the last N ticks
            int up = 0, down = 0;
            int from = Math.Max(0, _ticks.Count - TickWindow);
            for (int i = from; i < _ticks.Count; i++)
            {
                if (_ticks[i].Direction > 0) up++;
                else if (_ticks[i].Direction < 0) down++;
            }
            int moved = up + down;
            _tickDirection = moved > 0 ? (double)(up - down) / moved : 0;

            // --- absorption: heavy one-sided flow that fails to move the mid means the
            //     other side is soaking it up, which is a signal AGAINST the flow.
            _absorption = 0;
            if (_flow.Count > 3 && Math.Abs(normalisedOfi) > 0.5)
            {
                double moveInPips = PriceToPips(_flow[_flow.Count - 1].Mid - _flow[0].Mid);
                double expected = normalisedOfi * OfiClip;
                if (Math.Abs(moveInPips) < Math.Abs(expected) * 0.25)
                    _absorption = -Math.Sign(normalisedOfi) * Clip(Math.Abs(normalisedOfi) / OfiClip);
            }

            // --- spread quality is unsigned: it scales conviction rather than direction
            double spread = SpreadPips;
            _spreadQuality = _spreadAverage > 0
                ? Clip01(1.0 - (spread - _spreadAverage) / Math.Max(_spreadAverage, 0.1))
                : 1.0;

            double weightSum = 0;
            double signed = 0;

            if (_depthAvailable)
            {
                signed += WeightOfi * ofiSignal;          weightSum += WeightOfi;
                signed += WeightDepth * _depthImbalance;  weightSum += WeightDepth;
                signed += WeightMicroprice * _micropriceSignal; weightSum += WeightMicroprice;
                signed += WeightAbsorption * _absorption; weightSum += WeightAbsorption;
            }

            signed += WeightTicks * _tickDirection;       weightSum += WeightTicks;

            if (weightSum <= 0) { _score = 0; return; }

            // Spread quality multiplies conviction: a widening book is not a signal.
            _score = (signed / weightSum) * 100.0 * (WeightSpread > 0 ? _spreadQuality : 1.0);
            if (_score > 100) _score = 100;
            if (_score < -100) _score = -100;
        }

        #endregion

        #region Self-measurement

        /// <summary>
        /// Pairs the current normalised OFI with the mid move realised over the next
        /// horizon. Regressing the second on the first is the only way to know whether
        /// the published relationship holds on this broker's feed at this spread.
        /// </summary>
        private void TakeSample()
        {
            if (!_depthAvailable) return;
            if (_lastSampleTime != DateTime.MinValue
                && (Server.Time - _lastSampleTime).TotalSeconds < 1.0) return;

            _lastSampleTime = Server.Time;
            _samples.Add(new Sample
            {
                Time = Server.Time,
                NormalisedOfi = _avgDepth > 0 ? _ofiWindow / _avgDepth : 0,
                Mid = (Symbol.Bid + Symbol.Ask) / 2.0,
                Settled = false
            });

            while (_samples.Count > 50000) _samples.RemoveAt(0);
        }

        private void SettleSamples()
        {
            double mid = (Symbol.Bid + Symbol.Ask) / 2.0;
            for (int i = 0; i < _samples.Count; i++)
            {
                Sample s = _samples[i];
                if (s.Settled) continue;
                if ((Server.Time - s.Time).TotalSeconds < HorizonSeconds) continue;
                s.Outcome = PriceToPips(mid - s.Mid);
                s.Settled = true;
            }
        }

        private void PrintRegression()
        {
            int n = 0;
            double sx = 0, sy = 0;
            for (int i = 0; i < _samples.Count; i++)
            {
                if (!_samples[i].Settled) continue;
                sx += _samples[i].NormalisedOfi;
                sy += _samples[i].Outcome;
                n++;
            }

            if (n < 30)
            {
                Print("Order flow regression: only {0} settled samples, not enough to say anything.", n);
                return;
            }

            double mx = sx / n, my = sy / n;
            double sxx = 0, sxy = 0, syy = 0;
            for (int i = 0; i < _samples.Count; i++)
            {
                if (!_samples[i].Settled) continue;
                double dx = _samples[i].NormalisedOfi - mx;
                double dy = _samples[i].Outcome - my;
                sxx += dx * dx; sxy += dx * dy; syy += dy * dy;
            }

            if (sxx <= 0 || syy <= 0)
            {
                Print("Order flow regression: no variation in the samples.");
                return;
            }

            double beta = sxy / sxx;
            double r2 = (sxy * sxy) / (sxx * syy);
            double residual = Math.Max(syy - beta * sxy, 0);
            double se = Math.Sqrt(residual / Math.Max(1, n - 2) / sxx);
            double t = se > 0 ? beta / se : 0;

            Print("--- order flow regression on YOUR feed ---");
            Print("dMid(pips over {0}s) = alpha + beta * (OFI / depth)", HorizonSeconds);
            Print("n {0} | beta {1:F4} pips per unit | t {2:F2} | R2 {3:F4}", n, beta, t, r2);

            double cost = _spreadAverage;
            Print("Round-trip spread is {0:F2} pips. At this beta, the signal must reach "
                + "OFI/depth of {1:F2} just to cover it.",
                cost, beta != 0 ? Math.Abs(cost / beta) : 0);

            if (Math.Abs(t) < 2.0)
                Print("VERDICT: beta is not significant on this sample. The published effect does "
                    + "not show up on this feed at this horizon. Do not trade this score.");
            else if (beta < 0)
                Print("VERDICT: beta is significant but NEGATIVE - flow leads price the opposite way "
                    + "here, consistent with liquidity-provider inventory skew rather than market "
                    + "pressure. The score's sign would have to be inverted, and that is a finding "
                    + "to verify on fresh data before trusting it.");
            else
                Print("VERDICT: beta is positive and significant. Now check the magnitude above: "
                    + "significance is not the same as clearing the spread.");
            Print("------------------------------------------");
        }

        #endregion

        #region Trading

        private void ConsiderEntry()
        {
            if (MyPositions().Length > 0) return;

            string blocker = EntryBlocker();
            if (blocker != null) { _status = blocker; return; }

            if (Math.Abs(_score) < MinEntryScore)
            {
                _status = string.Format("score {0:+00;-00} < {1:F0}", _score, MinEntryScore);
                return;
            }

            int direction = Math.Sign(_score);
            if (!ContextAgrees(direction))
            {
                _status = "context disagrees";
                return;
            }

            double atr = _atr.Result.LastValue;
            if (double.IsNaN(atr) || atr <= 0) return;

            double stopPips = Math.Round(PriceToPips(atr * StopAtr), 1);
            double floor = Math.Max(1.0, SpreadPips * 2.0);
            if (stopPips < floor) stopPips = floor;

            double? targetPips = TakeProfitR > 0 ? (double?)Math.Round(stopPips * TakeProfitR, 1) : null;

            if (Symbol.PipValue <= 0) return;
            double volume = Symbol.NormalizeVolumeInUnits(
                Account.Equity * RiskPercent / 100.0 / (stopPips * Symbol.PipValue), RoundingMode.Down);

            if (volume < Symbol.VolumeInUnitsMin)
            {
                _status = "size below broker minimum";
                return;
            }

            TradeType tradeType = direction > 0 ? TradeType.Buy : TradeType.Sell;
            TradeResult result = ExecuteMarketOrder(tradeType, SymbolName, volume, _label, stopPips, targetPips);
            if (!result.IsSuccessful || result.Position == null)
            {
                LogVerbose("order rejected: " + result.Error);
                return;
            }

            _tradesToday++;
            _positionOpened = Server.Time;
            _positionRiskPips = stopPips;

            Print("{0} {1} | score {2:F0} | OFI/depth {3:F2} | depth imb {4:+0.00;-0.00} | "
                + "micro {5:+0.00;-0.00} | ticks {6:+0.00;-0.00} | SL {7:F1}p",
                tradeType, SymbolName, _score,
                _avgDepth > 0 ? _ofiWindow / _avgDepth : 0,
                _depthImbalance, _micropriceSignal, _tickDirection, stopPips);
        }

        private bool ContextAgrees(int direction)
        {
            if (Context == ContextMode.Off) return true;

            double ema = _contextEma.Result.LastValue;
            if (double.IsNaN(ema)) return false;

            double price = _contextBars.ClosePrices.LastValue;
            bool emaOk = direction > 0 ? price > ema : price < ema;
            if (Context == ContextMode.FastEma) return emaOk;

            double adx = _dmi.ADX.LastValue;
            double plus = _dmi.DIPlus.LastValue;
            double minus = _dmi.DIMinus.LastValue;
            if (double.IsNaN(adx) || double.IsNaN(plus) || double.IsNaN(minus)) return false;

            bool dmiOk = direction > 0 ? plus > minus : minus > plus;
            return emaOk && dmiOk && adx >= MinAdx;
        }

        /// <summary>
        /// The exit is the other half of the idea: while flow keeps agreeing, the runner
        /// stays on past any fixed target; when it flips hard, the trade is finished
        /// whatever the chart says.
        /// </summary>
        private void ManagePosition()
        {
            Position[] positions = MyPositions();
            if (positions.Length == 0) return;

            for (int i = 0; i < positions.Length; i++)
            {
                Position position = positions[i];
                int direction = position.TradeType == TradeType.Buy ? 1 : -1;

                if (MaxHoldSeconds > 0 && _positionOpened != DateTime.MinValue
                    && (Server.Time - _positionOpened).TotalSeconds >= MaxHoldSeconds)
                {
                    ClosePositionSafe(position, "max hold");
                    continue;
                }

                if (_score * direction <= -ExitFlipScore)
                {
                    ClosePositionSafe(position, string.Format("flow flipped ({0:F0})", _score));
                    continue;
                }

                // Let a winner run past its target while the flow still agrees.
                if (HoldWhileFlowAgrees && position.TakeProfit.HasValue
                    && _score * direction >= MinEntryScore
                    && _positionRiskPips > 0
                    && position.Pips >= _positionRiskPips * TakeProfitR * 0.9)
                {
                    if (ModifyPosition(position, position.StopLoss, (double?)null,
                            ProtectionType.Absolute).IsSuccessful)
                        LogVerbose("target released, flow still agrees");
                }
            }
        }

        private string EntryBlocker()
        {
            if (_dayLocked) return "daily loss cap reached";
            if (!_depthAvailable) return "no depth ladder";
            if (_tradesToday >= MaxTradesPerDay) return "max trades per day";
            if (!InSession()) return "outside session";
            if (SpreadPips > MaxSpreadPips)
                return string.Format("spread {0:F1}p > {1:F1}p", SpreadPips, MaxSpreadPips);
            if (CooldownSeconds > 0 && _lastExitTime != DateTime.MinValue
                && (Server.Time - _lastExitTime).TotalSeconds < CooldownSeconds) return "cooldown";
            return null;
        }

        #endregion

        #region Plumbing

        private Position[] MyPositions() { return Positions.FindAll(_label, SymbolName); }

        private void ClosePositionSafe(Position position, string reason)
        {
            TradeResult result = ClosePosition(position);
            if (result.IsSuccessful)
            {
                LogVerbose(string.Format("closed #{0}: {1}", position.Id, reason));
                _lastExitTime = Server.Time;
                _positionOpened = DateTime.MinValue;
            }
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            Position position = args.Position;
            if (position.Label != _label || position.SymbolName != SymbolName) return;

            _lastExitTime = Server.Time;
            _positionOpened = DateTime.MinValue;

            double net = position.NetProfit;
            _statTrades++;
            _statNet += net;
            if (net > 0) { _statWins++; _statGrossProfit += net; }
            else if (net < 0) _statGrossLoss += -net;
        }

        private void EnforceDailyGuard()
        {
            if (_dayStartEquity <= 0 || MaxDailyLossPercent <= 0) return;

            if (_dayLocked)
            {
                if (MyPositions().Length > 0) CloseAll("daily cap - retry");
                return;
            }

            double change = (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0;
            if (change <= -MaxDailyLossPercent)
            {
                _dayLocked = true;
                Print("DAILY LOSS CAP hit ({0:F2}%)", change);
                CloseAll("daily loss cap");
            }
        }

        private void CloseAll(string reason)
        {
            Position[] positions = MyPositions();
            for (int i = 0; i < positions.Length; i++) ClosePositionSafe(positions[i], reason);
        }

        private void RollDayIfNeeded()
        {
            if (Server.Time.Date != _currentDay) StartNewDay();
        }

        private void StartNewDay()
        {
            _currentDay = Server.Time.Date;
            _dayStartEquity = Account.Equity;
            _tradesToday = 0;
            _dayLocked = false;
        }

        private bool InSession()
        {
            DateTime now = Server.Time;
            if (now.DayOfWeek == DayOfWeek.Saturday || now.DayOfWeek == DayOfWeek.Sunday) return false;
            double hour = now.Hour + now.Minute / 60.0;
            return SessionStart <= SessionEnd
                ? hour >= SessionStart && hour < SessionEnd
                : hour >= SessionStart || hour < SessionEnd;
        }

        private void UpdateSpreadAverage()
        {
            double spread = SpreadPips;
            if (spread <= 0) return;
            _spreadAverage = _spreadAverage <= 0 ? spread : _spreadAverage + (spread - _spreadAverage) * 0.002;
        }

        #endregion

        #region Reporting

        private void PrintStatistics()
        {
            Print("=== GOLD ORDER FLOW ENGINE - session summary ===");
            Print("Depth updates seen {0} | ladder available {1}", _depthUpdates, _depthAvailable);
            Print("Trades {0} | wins {1} ({2:F1}%) | net {3:F2} {4}",
                _statTrades, _statWins, _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet, Account.Asset.Name);
            Print("Profit factor {0}",
                _statGrossLoss > 0 ? (_statGrossProfit / _statGrossLoss).ToString("F2") : "n/a");

            PrintRegression();
        }

        private void UpdateDashboard()
        {
            if (!ShowDashboard || Chart == null) return;

            Position[] positions = MyPositions();
            int settled = 0;
            for (int i = 0; i < _samples.Count; i++) if (_samples[i].Settled) settled++;

            string text = string.Format(
                "ORDER FLOW ENGINE v0.5{0}\n" +
                "score       {1:+000;-000}  (enter at {2:F0})\n" +
                "OFI/depth   {3:+0.00;-0.00}   depth imb {4:+0.00;-0.00}\n" +
                "microprice  {5:+0.00;-0.00}   ticks     {6:+0.00;-0.00}\n" +
                "absorption  {7:+0.00;-0.00}   spread q  {8:F2}\n" +
                "book        {9} ({10} updates)\n" +
                "status      {11}\n" +
                "position    {12} | samples {13}\n" +
                "trades      {14} | net {15:F2}",
                MeasureOnly ? "  [MEASURE ONLY]" : "",
                _score, MinEntryScore,
                _avgDepth > 0 ? _ofiWindow / _avgDepth : 0, _depthImbalance,
                _micropriceSignal, _tickDirection,
                _absorption, _spreadQuality,
                _depthAvailable ? "live" : "unavailable", _depthUpdates,
                _status,
                positions.Length == 0 ? "flat" : positions[0].TradeType.ToString(),
                settled,
                _statTrades, _statNet);

            Chart.DrawStaticText("ofe_dashboard", text, VerticalAlignment.Top, HorizontalAlignment.Right, Color.Gold);
        }

        #endregion

        #region Helpers

        private double SpreadPips { get { return Symbol.Spread / Symbol.PipSize; } }
        private double PriceToPips(double distance) { return distance / Symbol.PipSize; }
        private static double Clip(double v) { return v > 1 ? 1 : (v < -1 ? -1 : v); }
        private static double Clip01(double v) { return v > 1 ? 1 : (v < 0 ? 0 : v); }
        private void LogVerbose(string message) { if (_log) Print(message); }

        #endregion
    }
}
