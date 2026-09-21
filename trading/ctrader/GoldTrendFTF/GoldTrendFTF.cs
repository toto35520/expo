using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum SizingMode
    {
        VolatilityTarget,
        RiskPerTrade
    }

    /// <summary>
    /// GOLD TREND - FORECAST TO FILL
    ///
    /// A cTrader implementation of the strategy described in:
    ///
    ///   Singha, Aguilera-Toste, Lahiri (2025), "Forecast-to-Fill: Benchmark-Neutral
    ///   Alpha and Billion-Dollar Capacity in Gold Futures (2015-2025)", arXiv:2511.08571
    ///
    /// Reported out of sample, on CME gold futures, daily bars, rolling 10-year train
    /// to 6-month test walk-forward over 2,793 trading days: Sharpe 2.88, maximum
    /// drawdown 0.52%, annual return 2.62% at a realised annual volatility of 0.91%,
    /// net of 0.7 bps linear cost and a square-root impact term. Flat on roughly 58%
    /// of days. The paper's headline "43% CAGR" is that 2.62% rescaled to its 15%
    /// volatility budget, not a realised figure - read it as a leverage statement.
    ///
    /// This is NOT a scalper. It trades the DAILY chart, holds for up to 30 days, and
    /// is flat most of the time. That is the point: the same authors' literature, and
    /// the falsification study in the README, find that intraday OHLCV signals on
    /// liquid instruments do not clear their own transaction costs.
    ///
    /// What is taken verbatim from the paper:
    ///   momentum lookback K = 50 days, blend weight omega = 0.6, activation threshold
    ///   0.52, hard stop 2 x ATR(14), trailing stop 1.5 x ATR(14) from peak, timeout
    ///   30 trading days, de-risk when p_bear > 0.5, volatility target 15% annualised,
    ///   leverage cap 2.0, fractional Kelly 0.40.
    ///
    /// What is NOT from the paper, and is therefore yours to walk-forward:
    ///   the EMA smoothing constant. The paper searched it over a 64-configuration
    ///   grid and the published passages do not state the selected value. The default
    ///   below (20 days) is a reasonable starting point, not their number.
    ///
    /// Adaptations for a retail cTrader account:
    ///   - the paper freezes training statistics before each out-of-sample slice; a
    ///     live bot cannot, so the slope's mean and standard deviation are computed on
    ///     a rolling trailing window instead.
    ///   - the paper trades continuous front-month futures with roll P&L; a CFD has no
    ///     roll but pays financing, which this bot does not model.
    /// </summary>
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC, AddIndicators = true)]
    public class GoldTrendFTF : Robot
    {
        #region 01 - General

        [Parameter("Instance label", Group = "01 - General", DefaultValue = "FTF")]
        public string InstanceLabel { get; set; }

        [Parameter("Verbose logs", Group = "01 - General", DefaultValue = true)]
        public bool Verbose { get; set; }

        [Parameter("On-chart dashboard", Group = "01 - General", DefaultValue = true)]
        public bool ShowDashboard { get; set; }

        [Parameter("Allow short side", Group = "01 - General", DefaultValue = false)]
        public bool AllowShorts { get; set; }

        #endregion

        #region 02 - Signal

        [Parameter("Trend EMA (days)", Group = "02 - Signal", DefaultValue = 20, MinValue = 2, MaxValue = 200)]
        public int TrendEmaPeriod { get; set; }

        [Parameter("Momentum lookback K (days)", Group = "02 - Signal", DefaultValue = 50, MinValue = 5, MaxValue = 400)]
        public int MomentumLookback { get; set; }

        [Parameter("Blend weight omega", Group = "02 - Signal", DefaultValue = 0.6, MinValue = 0, MaxValue = 1, Step = 0.05)]
        public double BlendWeight { get; set; }

        [Parameter("Activation threshold", Group = "02 - Signal", DefaultValue = 0.52, MinValue = 0.5, MaxValue = 0.9, Step = 0.01)]
        public double ActivationThreshold { get; set; }

        [Parameter("De-risk threshold", Group = "02 - Signal", DefaultValue = 0.50, MinValue = 0.2, MaxValue = 0.6, Step = 0.01)]
        public double DeriskThreshold { get; set; }

        [Parameter("Slope stats window (days)", Group = "02 - Signal", DefaultValue = 1000, MinValue = 100, MaxValue = 5000)]
        public int StatsWindow { get; set; }

        #endregion

        #region 03 - Exits

        [Parameter("Hard stop = ATR x", Group = "03 - Exits", DefaultValue = 2.0, MinValue = 0.5, MaxValue = 10, Step = 0.1)]
        public double HardStopAtr { get; set; }

        [Parameter("Trailing stop = ATR x", Group = "03 - Exits", DefaultValue = 1.5, MinValue = 0.3, MaxValue = 10, Step = 0.1)]
        public double TrailAtr { get; set; }

        [Parameter("ATR period (days)", Group = "03 - Exits", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AtrPeriod { get; set; }

        [Parameter("Timeout (days)", Group = "03 - Exits", DefaultValue = 30, MinValue = 1, MaxValue = 500)]
        public int TimeoutDays { get; set; }

        #endregion

        #region 04 - Sizing

        [Parameter("Sizing mode", Group = "04 - Sizing", DefaultValue = SizingMode.RiskPerTrade)]
        public SizingMode Sizing { get; set; }

        [Parameter("Risk per trade (% equity)", Group = "04 - Sizing", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double RiskPercent { get; set; }

        [Parameter("Target annual volatility (%)", Group = "04 - Sizing", DefaultValue = 15.0, MinValue = 1, MaxValue = 100, Step = 1)]
        public double TargetAnnualVol { get; set; }

        [Parameter("Max leverage", Group = "04 - Sizing", DefaultValue = 2.0, MinValue = 0.1, MaxValue = 20, Step = 0.1)]
        public double MaxLeverage { get; set; }

        [Parameter("Fractional Kelly", Group = "04 - Sizing", DefaultValue = 0.40, MinValue = 0.05, MaxValue = 1.0, Step = 0.05)]
        public double KellyFraction { get; set; }

        [Parameter("Volatility window (days)", Group = "04 - Sizing", DefaultValue = 60, MinValue = 10, MaxValue = 500)]
        public int VolWindow { get; set; }

        #endregion

        #region State

        private readonly List<double> _slopes = new List<double>();
        private readonly List<double> _returns = new List<double>();

        private AverageTrueRange _atr;
        private string _label;
        private bool _log;

        private double _ema;
        private bool _emaReady;
        private int _processedBars;

        private double _pBull;
        private double _slope;
        private double _zScore;
        private double _peakPrice;
        private int _entryBarIndex = int.MinValue;
        private string _status = "starting";

        private int _statTrades;
        private int _statWins;
        private double _statNet;
        private double _statGrossProfit;
        private double _statGrossLoss;

        #endregion

        #region Lifecycle

        protected override void OnStart()
        {
            _label = string.IsNullOrWhiteSpace(InstanceLabel) ? "FTF" : InstanceLabel.Trim();
            _log = Verbose && RunningMode != RunningMode.Optimization;

            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Simple);

            if (TimeFrame != TimeFrame.Daily)
                Print("WARNING: this strategy was validated on DAILY bars. Current timeframe is {0}.", TimeFrame);

            RebuildHistory();
            Positions.Closed += OnPositionClosed;
            AdoptExistingPosition();

            Print("=== GOLD TREND - FORECAST TO FILL ===");
            Print("Source: Singha, Aguilera-Toste & Lahiri (2025), arXiv:2511.08571");
            Print("Symbol {0} | timeframe {1} | {2} daily bars loaded", SymbolName, TimeFrame, Bars.Count);
            Print("Equity {0:F2} {1} | min volume {2} units", Account.Equity, Account.Asset.Name, Symbol.VolumeInUnitsMin);

            CheckAccountIsLargeEnough();
        }

        protected override void OnStop()
        {
            Positions.Closed -= OnPositionClosed;
            Print("=== session summary ===");
            Print("Trades {0} | wins {1} ({2:F1}%) | net {3:F2} {4}",
                _statTrades, _statWins, _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet, Account.Asset.Name);
            Print("Profit factor {0}",
                _statGrossLoss > 0 ? (_statGrossProfit / _statGrossLoss).ToString("F2") : "n/a");
        }

        protected override void OnBar()
        {
            AppendClosedBar();

            if (!_emaReady || _slopes.Count < Math.Min(StatsWindow, 100) || _returns.Count < VolWindow)
            {
                _status = "warming up";
                UpdateDashboard();
                return;
            }

            UpdateSignal();
            ManageOpenPosition();
            ConsiderEntry();
            UpdateDashboard();
        }

        protected override void OnTick()
        {
            // Stops and trailing are evaluated on daily closes, but the hard stop is a
            // real order on the server, so intraday protection does not depend on ticks.
        }

        #endregion

        #region Signal

        /// <summary>
        /// Walks the loaded history once at startup so the EMA, the slope distribution
        /// and the return distribution start from the same state a long-running bot
        /// would have reached.
        /// </summary>
        private void RebuildHistory()
        {
            _slopes.Clear();
            _returns.Clear();
            _emaReady = false;
            _processedBars = 0;

            // Bars.Count - 1 is the bar currently forming; everything below it is closed.
            for (int i = 0; i < Bars.Count - 1; i++)
                Absorb(Bars.ClosePrices[i], i > 0 ? Bars.ClosePrices[i - 1] : 0);

            _processedBars = Bars.Count - 1;
        }

        private void AppendClosedBar()
        {
            int lastClosed = Bars.Count - 2;
            if (lastClosed < 0) return;

            // OnBar can fire more than once per closed bar after a reconnect; only
            // absorb bars this instance has not already seen.
            for (int i = _processedBars; i <= lastClosed; i++)
                Absorb(Bars.ClosePrices[i], i > 0 ? Bars.ClosePrices[i - 1] : 0);

            _processedBars = lastClosed + 1;
        }

        private void Absorb(double close, double previousClose)
        {
            if (close <= 0) return;

            double y = Math.Log(close);
            double lambda = 1.0 - 2.0 / (TrendEmaPeriod + 1.0);

            if (!_emaReady)
            {
                _ema = y;
                _emaReady = true;
            }
            else
            {
                double previousEma = _ema;
                _ema = lambda * _ema + (1.0 - lambda) * y;
                _slopes.Add(_ema - previousEma);
                if (_slopes.Count > StatsWindow * 2) _slopes.RemoveAt(0);
            }

            if (previousClose > 0)
            {
                _returns.Add(Math.Log(close / previousClose));
                if (_returns.Count > VolWindow * 4) _returns.RemoveAt(0);
            }
        }

        private void UpdateSignal()
        {
            _slope = _slopes[_slopes.Count - 1];

            int window = Math.Min(StatsWindow, _slopes.Count);
            double mean = 0;
            for (int i = _slopes.Count - window; i < _slopes.Count; i++) mean += _slopes[i];
            mean /= window;

            double variance = 0;
            for (int i = _slopes.Count - window; i < _slopes.Count; i++)
            {
                double d = _slopes[i] - mean;
                variance += d * d;
            }
            double sd = Math.Sqrt(variance / Math.Max(1, window - 1));

            _zScore = sd > 0 ? (_slope - mean) / sd : 0;

            // Clip to [-3, 3] then map affinely onto [0, 1].
            double clipped = Math.Max(-3.0, Math.Min(3.0, _zScore));
            double pTrend = (clipped + 3.0) / 6.0;

            // Binary momentum confirmation over K days.
            double momentum = 0;
            int lastClosed = Bars.Count - 2;
            int back = lastClosed - MomentumLookback;
            if (back >= 0 && Bars.ClosePrices[back] > 0)
                momentum = Bars.ClosePrices[lastClosed] > Bars.ClosePrices[back] ? 1.0 : 0.0;

            _pBull = BlendWeight * pTrend + (1.0 - BlendWeight) * momentum;
        }

        #endregion

        #region Trading

        private void ConsiderEntry()
        {
            Position open = FindPosition();
            if (open != null)
            {
                _status = "in position";
                return;
            }

            double atr = _atr.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0)
            {
                _status = "ATR not ready";
                return;
            }

            bool longSignal = _pBull >= ActivationThreshold && _slope > 0;
            bool shortSignal = AllowShorts && (1.0 - _pBull) >= ActivationThreshold && _slope < 0;

            if (!longSignal && !shortSignal)
            {
                _status = string.Format("flat (p_bull {0:F3} < {1:F2})", _pBull, ActivationThreshold);
                return;
            }

            TradeType tradeType = longSignal ? TradeType.Buy : TradeType.Sell;
            double stopPips = PriceToPips(atr * HardStopAtr);
            double volume = ComputeVolume(stopPips);

            if (volume <= 0)
            {
                _status = "signal on, size too small";
                return;
            }

            TradeResult result = ExecuteMarketOrder(tradeType, SymbolName, volume, _label,
                stopPips, (double?)null);
            if (!result.IsSuccessful || result.Position == null)
            {
                Print("Order rejected: {0}", result.Error);
                return;
            }

            _entryBarIndex = Bars.Count - 1;
            _peakPrice = result.Position.EntryPrice;
            _status = "in position";

            Print("{0} {1} | p_bull {2:F3} | z {3:F2} | vol {4} units | stop {5:F1} pips ({6:F2} x ATR)",
                tradeType, SymbolName, _pBull, _zScore, volume, stopPips, HardStopAtr);
        }

        private void ManageOpenPosition()
        {
            Position position = FindPosition();
            if (position == null)
            {
                _entryBarIndex = int.MinValue;
                return;
            }

            if (_entryBarIndex == int.MinValue) _entryBarIndex = Bars.Count - 1;

            double close = Bars.ClosePrices.Last(1);
            double atr = _atr.Result.Last(1);

            // 1. Regime flip: the paper de-risks as soon as the bearish probability takes over.
            bool flipped = position.TradeType == TradeType.Buy
                ? (1.0 - _pBull) > DeriskThreshold
                : _pBull > DeriskThreshold;

            if (flipped)
            {
                ClosePositionSafe(position, string.Format("regime flip (p_bull {0:F3})", _pBull));
                return;
            }

            // 2. Timeout: predictive power of the signal decays past this horizon.
            if (TimeoutDays > 0 && Bars.Count - 1 - _entryBarIndex >= TimeoutDays)
            {
                ClosePositionSafe(position, string.Format("timeout {0} days", TimeoutDays));
                return;
            }

            if (double.IsNaN(atr) || atr <= 0) return;

            // 3. Trailing stop measured from the running peak, not from the current price.
            if (position.TradeType == TradeType.Buy)
            {
                if (close > _peakPrice) _peakPrice = close;
                double trail = _peakPrice - atr * TrailAtr;
                if (close < trail)
                {
                    ClosePositionSafe(position, "trailing stop");
                    return;
                }
                MoveStopUp(position, trail);
            }
            else
            {
                if (_peakPrice <= 0 || close < _peakPrice) _peakPrice = close;
                double trail = _peakPrice + atr * TrailAtr;
                if (close > trail)
                {
                    ClosePositionSafe(position, "trailing stop");
                    return;
                }
                MoveStopUp(position, trail);
            }
        }

        private void MoveStopUp(Position position, double candidate)
        {
            candidate = Math.Round(candidate, Symbol.Digits);

            if (position.TradeType == TradeType.Buy)
            {
                if (candidate >= Symbol.Bid) return;
                if (position.StopLoss.HasValue && candidate <= position.StopLoss.Value) return;
            }
            else
            {
                if (candidate <= Symbol.Ask) return;
                if (position.StopLoss.HasValue && candidate >= position.StopLoss.Value) return;
            }

            ModifyPosition(position, candidate, position.TakeProfit, ProtectionType.Absolute);
        }

        private void ClosePositionSafe(Position position, string reason)
        {
            TradeResult result = ClosePosition(position);
            if (result.IsSuccessful)
                Print("Closed #{0}: {1}", position.Id, reason);
            else
                Print("Close failed on #{0} ({1}): {2}", position.Id, reason, result.Error);
        }

        private Position FindPosition()
        {
            Position[] positions = Positions.FindAll(_label, SymbolName);
            return positions.Length > 0 ? positions[0] : null;
        }

        private void AdoptExistingPosition()
        {
            Position position = FindPosition();
            if (position == null) return;
            _entryBarIndex = Bars.Count - 1;
            _peakPrice = position.EntryPrice;
            Print("Adopted an existing position with label {0}", _label);
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            Position position = args.Position;
            if (position.Label != _label || position.SymbolName != SymbolName) return;

            double net = position.NetProfit;
            _statTrades++;
            _statNet += net;
            if (net > 0) { _statWins++; _statGrossProfit += net; }
            else if (net < 0) _statGrossLoss += -net;

            _entryBarIndex = int.MinValue;
            _peakPrice = 0;

            if (_log)
                Print("Trade closed: {0:F2} {1} ({2:F1} pips)", net, Account.Asset.Name, position.Pips);
        }

        #endregion

        #region Sizing

        private double ComputeVolume(double stopPips)
        {
            double units = Sizing == SizingMode.VolatilityTarget
                ? VolatilityTargetedUnits()
                : RiskBasedUnits(stopPips);

            units = Symbol.NormalizeVolumeInUnits(units, RoundingMode.Down);

            if (units < Symbol.VolumeInUnitsMin)
            {
                Print("Signal skipped: computed size {0} units is below the broker minimum of {1}. "
                    + "The account is too small for a {2:F0} pip stop at this risk level.",
                    units, Symbol.VolumeInUnitsMin, stopPips);
                return 0;
            }

            if (units > Symbol.VolumeInUnitsMax) units = Symbol.VolumeInUnitsMax;
            return units;
        }

        private double RiskBasedUnits(double stopPips)
        {
            if (Symbol.PipValue <= 0 || stopPips <= 0) return 0;
            return Account.Equity * RiskPercent / 100.0 / (stopPips * Symbol.PipValue);
        }

        /// <summary>
        /// The paper's sizing: scale exposure so realised volatility tracks a target,
        /// scale again by how far the signal is past 0.5, then apply fractional Kelly.
        /// Currency conversion rides on PipValue, which is already in account currency.
        /// </summary>
        private double VolatilityTargetedUnits()
        {
            double dailyVol = RealisedDailyVolatility();
            if (dailyVol <= 0 || Symbol.PipValue <= 0) return 0;

            double targetDailyVol = TargetAnnualVol / 100.0 / Math.Sqrt(252.0);
            double volWeight = Math.Min(MaxLeverage, targetDailyVol / dailyVol);

            double confidence = (Math.Max(_pBull, 1.0 - _pBull) - 0.5) / 0.5;
            confidence = Math.Max(0.0, Math.Min(1.0, confidence));

            double weight = volWeight * confidence * KellyFraction;
            if (weight <= 0) return 0;

            // Account-currency value of one whole unit of the asset: moving the price
            // to zero is (price / PipSize) pips, each worth PipValue per unit.
            double unitValue = Symbol.Bid / Symbol.PipSize * Symbol.PipValue;
            if (unitValue <= 0) return 0;

            return Account.Equity * weight / unitValue;
        }

        private double RealisedDailyVolatility()
        {
            int window = Math.Min(VolWindow, _returns.Count);
            if (window < 5) return 0;

            double mean = 0;
            for (int i = _returns.Count - window; i < _returns.Count; i++) mean += _returns[i];
            mean /= window;

            double variance = 0;
            for (int i = _returns.Count - window; i < _returns.Count; i++)
            {
                double d = _returns[i] - mean;
                variance += d * d;
            }
            return Math.Sqrt(variance / Math.Max(1, window - 1));
        }

        /// <summary>
        /// A 2 x ATR(14) stop on daily gold is very wide. On a small account the
        /// smallest lot the broker allows can already risk an unacceptable share of
        /// equity, and no parameter can fix that - say so at startup rather than
        /// silently taking oversized trades.
        /// </summary>
        private void CheckAccountIsLargeEnough()
        {
            double atr = _atr.Result.LastValue;
            if (double.IsNaN(atr) || atr <= 0 || Symbol.PipValue <= 0) return;

            double stopPips = PriceToPips(atr * HardStopAtr);
            double minLotRisk = stopPips * Symbol.PipValue * Symbol.VolumeInUnitsMin;
            double sharePercent = 100.0 * minLotRisk / Account.Equity;

            Print("ATR({0}) = {1:F2} | hard stop {2:F0} pips | smallest possible trade risks {3:F2} {4} = {5:F1}% of equity",
                AtrPeriod, atr, stopPips, minLotRisk, Account.Asset.Name, sharePercent);

            if (sharePercent > RiskPercent * 1.5)
            {
                Print("WARNING: the broker's minimum lot already risks {0:F1}% of this account, "
                    + "against a {1:F1}% target. This strategy needs roughly {2:F0} {3} of equity "
                    + "to be traded at its intended risk on this symbol.",
                    sharePercent, RiskPercent, minLotRisk / (RiskPercent / 100.0), Account.Asset.Name);
            }
        }

        #endregion

        #region Helpers

        private double PriceToPips(double priceDistance)
        {
            return priceDistance / Symbol.PipSize;
        }

        private void UpdateDashboard()
        {
            if (!ShowDashboard || Chart == null) return;

            Position position = FindPosition();

            string text = string.Format(
                "GOLD TREND - FORECAST TO FILL\n" +
                "p_bull      {0:F3}  (entry >= {1:F2})\n" +
                "slope z     {2:+0.00;-0.00}\n" +
                "status      {3}\n" +
                "position    {4}\n" +
                "trades      {5} | win {6:F0}% | net {7:F2}",
                _pBull, ActivationThreshold,
                _zScore,
                _status,
                position == null ? "flat" : string.Format("{0} {1:F1} pips", position.TradeType, position.Pips),
                _statTrades,
                _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet);

            Chart.DrawStaticText("ftf_dashboard", text, VerticalAlignment.Top, HorizontalAlignment.Right, Color.Gold);
        }

        #endregion
    }
}
