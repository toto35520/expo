using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum BlueCloseMode
    {
        PerPosition,
        Basket,
        Both
    }

    public enum EntryBias
    {
        FollowFastEma,
        AlwaysBuy,
        AlwaysSell,
        Alternate
    }

    /// <summary>
    /// GOLD BLUE CLOSE - tick-driven scalper that closes the moment a trade is green.
    ///
    /// Opens a position, adds up to a few more if price moves against it, and closes
    /// whatever is in profit as soon as it is in profit. Everything is evaluated on
    /// ticks, not bars, so the exit fires as fast as the feed allows.
    ///
    /// ---------------------------------------------------------------------------
    /// THE ARITHMETIC, BEFORE YOU RUN IT
    ///
    /// Closing at "green" buys a very high win rate by making each win tiny while
    /// leaving every loss full size. For a driftless walk with a take profit a pips
    /// away and a stop b pips away, P(win) = b / (a + b), so the expectancy is
    ///
    ///     E = P(win) * a - P(loss) * b - cost  =  -cost
    ///
    /// for EVERY choice of a and b. The win rate is a dial; it does not create edge.
    /// On a 0.9 pip spread plus 0.45 pip commission, at a 2 pip net target and a 200
    /// pip stop, that is a 98.35% win rate and -1.35 pips per trade expected.
    ///
    /// In account terms, on a 910 EUR account: a 2 pip win is 0.17 EUR, and a basket
    /// stopped at 3% of equity is 27.30 EUR. One loss erases 161 wins. At twenty
    /// trades a day, a loss lands roughly every three days.
    ///
    /// The equity curve will rise smoothly for weeks and then give it all back in one
    /// session. That is not a bug in this implementation, it is the shape of the
    /// strategy, and no parameter in this file changes it.
    /// ---------------------------------------------------------------------------
    ///
    /// What this implementation refuses to do:
    ///   - no martingale. Added positions are the SAME size. Doubling into a losing
    ///     basket is the mechanism that takes accounts to zero, not merely to a loss.
    ///   - no trading without a basket stop. The basket stop is what makes the worst
    ///     case a bounded loss instead of a margin call, and it is checked on tick.
    ///   - no closing at literally zero. A target below the round-trip cost makes the
    ///     average win zero while the losses stay whole, which is the worst version.
    /// </summary>
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC, AddIndicators = true)]
    public class GoldBlueClose : Robot
    {
        #region 01 - General

        [Parameter("Instance label", Group = "01 - General", DefaultValue = "BLUE")]
        public string InstanceLabel { get; set; }

        [Parameter("Verbose logs", Group = "01 - General", DefaultValue = true)]
        public bool Verbose { get; set; }

        [Parameter("On-chart dashboard", Group = "01 - General", DefaultValue = true)]
        public bool ShowDashboard { get; set; }

        #endregion

        #region 02 - Blue exit

        [Parameter("Close mode", Group = "02 - Blue exit", DefaultValue = BlueCloseMode.Both)]
        public BlueCloseMode CloseMode { get; set; }

        [Parameter("Min profit (pips)", Group = "02 - Blue exit", DefaultValue = 2.0, MinValue = 0, MaxValue = 100, Step = 0.1)]
        public double MinProfitPips { get; set; }

        [Parameter("Min profit (account currency)", Group = "02 - Blue exit", DefaultValue = 0.01, MinValue = 0, Step = 0.01)]
        public double MinProfitCurrency { get; set; }

        [Parameter("Basket target (account currency)", Group = "02 - Blue exit", DefaultValue = 0.05, MinValue = 0, Step = 0.01)]
        public double BasketTarget { get; set; }

        #endregion

        #region 03 - Entry

        [Parameter("Direction", Group = "03 - Entry", DefaultValue = EntryBias.FollowFastEma)]
        public EntryBias Bias { get; set; }

        [Parameter("Fast EMA period", Group = "03 - Entry", DefaultValue = 8, MinValue = 2, MaxValue = 200)]
        public int FastEmaPeriod { get; set; }

        [Parameter("Lots per position", Group = "03 - Entry", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double LotsPerPosition { get; set; }

        [Parameter("Cooldown between entries (seconds)", Group = "03 - Entry", DefaultValue = 3, MinValue = 0, MaxValue = 3600)]
        public int CooldownSeconds { get; set; }

        #endregion

        #region 04 - Grid

        [Parameter("Max positions", Group = "04 - Grid", DefaultValue = 3, MinValue = 1, MaxValue = 10)]
        public int MaxPositions { get; set; }

        [Parameter("Add when against by = ATR x", Group = "04 - Grid", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 20, Step = 0.1)]
        public double GridStepAtr { get; set; }

        [Parameter("ATR period", Group = "04 - Grid", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AtrPeriod { get; set; }

        #endregion

        #region 05 - Hard limits

        [Parameter("Basket stop (% equity)", Group = "05 - Limits", DefaultValue = 2.0, MinValue = 0.2, MaxValue = 20, Step = 0.1)]
        public double BasketStopPercent { get; set; }

        [Parameter("Position stop = ATR x (disconnect net)", Group = "05 - Limits", DefaultValue = 12.0, MinValue = 1, MaxValue = 100, Step = 1)]
        public double PositionStopAtr { get; set; }

        [Parameter("Daily loss cap (% equity, 0=off)", Group = "05 - Limits", DefaultValue = 4.0, MinValue = 0, MaxValue = 50, Step = 0.5)]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Daily profit lock (% equity, 0=off)", Group = "05 - Limits", DefaultValue = 2.0, MinValue = 0, MaxValue = 100, Step = 0.5)]
        public double DailyProfitTargetPercent { get; set; }

        [Parameter("Max trades per day", Group = "05 - Limits", DefaultValue = 60, MinValue = 1, MaxValue = 2000)]
        public int MaxTradesPerDay { get; set; }

        [Parameter("Max spread (pips)", Group = "05 - Limits", DefaultValue = 3.0, MinValue = 0.5, Step = 0.5)]
        public double MaxSpreadPips { get; set; }

        #endregion

        #region 06 - Session (UTC)

        [Parameter("Session start (UTC hour)", Group = "06 - Session", DefaultValue = 7.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionStart { get; set; }

        [Parameter("Session end (UTC hour)", Group = "06 - Session", DefaultValue = 17.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionEnd { get; set; }

        [Parameter("Flatten at session end", Group = "06 - Session", DefaultValue = true)]
        public bool FlattenAtSessionEnd { get; set; }

        [Parameter("Trade on Friday", Group = "06 - Session", DefaultValue = true)]
        public bool TradeFriday { get; set; }

        #endregion

        #region State

        private ExponentialMovingAverage _ema;
        private AverageTrueRange _atr;

        private string _label;
        private bool _log;
        private DateTime _lastEntryTime = DateTime.MinValue;
        private TradeType _lastDirection = TradeType.Sell;

        private DateTime _currentDay;
        private double _dayStartEquity;
        private int _tradesToday;
        private bool _dayLocked;
        private string _status = "starting";

        private int _statTrades;
        private int _statWins;
        private double _statGrossProfit;
        private double _statGrossLoss;
        private double _statNet;
        private double _worstBasket;

        #endregion

        #region Lifecycle

        protected override void OnStart()
        {
            _label = string.IsNullOrWhiteSpace(InstanceLabel) ? "BLUE" : InstanceLabel.Trim();
            _log = Verbose && RunningMode != RunningMode.Optimization;

            _ema = Indicators.ExponentialMovingAverage(Bars.ClosePrices, FastEmaPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);

            StartNewDay();
            Positions.Closed += OnPositionClosed;

            Print("=== GOLD BLUE CLOSE ===");
            Print("Symbol {0} | timeframe {1} | up to {2} positions of {3} lots",
                SymbolName, TimeFrame, MaxPositions, LotsPerPosition);
            Print("PipSize {0} | spread now {1:F1} pips | equity {2:F2} {3}",
                Symbol.PipSize, SpreadPips, Account.Equity, Account.Asset.Name);

            PrintHonestArithmetic();
        }

        protected override void OnStop()
        {
            Positions.Closed -= OnPositionClosed;
            PrintStatistics();
        }

        protected override void OnTick()
        {
            RollDayIfNeeded();

            CloseWhatIsBlue();
            EnforceBasketStop();
            EnforceDailyGuards();

            if (FlattenAtSessionEnd && !InSession())
            {
                CloseAll("session end");
                _status = "outside session";
                return;
            }

            MaybeAddToGrid();
            MaybeOpenFirst();
            UpdateDashboard();
        }

        #endregion

        #region Blue exit

        /// <summary>
        /// "In the blue" means NetProfit above zero, which is what cTrader's own P&L
        /// column shows: commission and swap already deducted. The pip floor exists so
        /// a win is not literally zero - a target under the round-trip cost gives away
        /// the whole payoff while keeping the whole risk.
        /// </summary>
        private void CloseWhatIsBlue()
        {
            Position[] positions = MyPositions();
            if (positions.Length == 0) return;

            if (CloseMode == BlueCloseMode.PerPosition || CloseMode == BlueCloseMode.Both)
            {
                for (int i = 0; i < positions.Length; i++)
                {
                    Position position = positions[i];
                    if (position.NetProfit >= MinProfitCurrency && position.Pips >= MinProfitPips)
                        ClosePositionSafe(position, string.Format("blue {0:F2} {1}",
                            position.NetProfit, Account.Asset.Name));
                }
            }

            if (CloseMode == BlueCloseMode.Basket || CloseMode == BlueCloseMode.Both)
            {
                positions = MyPositions();
                if (positions.Length < 2) return;

                double basket = BasketNetProfit(positions);
                if (basket >= BasketTarget)
                {
                    LogVerbose(string.Format("basket blue at {0:F2} {1} over {2} positions",
                        basket, Account.Asset.Name, positions.Length));
                    CloseAll("basket blue");
                }
            }
        }

        /// <summary>
        /// The rail. Without this the worst case is a margin call rather than a loss,
        /// because a grid that never closes keeps adding exposure to a losing side.
        /// Checked on every tick, ahead of anything that could open more.
        /// </summary>
        private void EnforceBasketStop()
        {
            Position[] positions = MyPositions();
            if (positions.Length == 0) return;

            double basket = BasketNetProfit(positions);
            if (basket < _worstBasket) _worstBasket = basket;

            double limit = -Account.Equity * BasketStopPercent / 100.0;
            if (basket <= limit)
            {
                Print("BASKET STOP hit: {0:F2} {1} over {2} positions (limit {3:F2})",
                    basket, Account.Asset.Name, positions.Length, limit);
                CloseAll("basket stop");
            }
        }

        private double BasketNetProfit(Position[] positions)
        {
            double total = 0;
            for (int i = 0; i < positions.Length; i++) total += positions[i].NetProfit;
            return total;
        }

        #endregion

        #region Entry

        private void MaybeOpenFirst()
        {
            if (MyPositions().Length > 0) return;

            string blocker = EntryBlocker();
            if (blocker != null)
            {
                _status = blocker;
                return;
            }

            TradeType direction = ChooseDirection();
            OpenOne(direction, "OPEN");
        }

        /// <summary>
        /// Adds are the same size as the first position, never larger. Equal-size
        /// averaging is already aggressive; multiplying it is what removes the floor.
        /// </summary>
        private void MaybeAddToGrid()
        {
            Position[] positions = MyPositions();
            if (positions.Length == 0 || positions.Length >= MaxPositions) return;
            if (_dayLocked || !InSession()) return;
            if (SpreadPips > MaxSpreadPips) return;

            double atr = _atr.Result.LastValue;
            if (double.IsNaN(atr) || atr <= 0) return;

            TradeType direction = positions[0].TradeType;
            double step = atr * GridStepAtr;

            // Distance from the entry that is furthest along the losing side.
            double worstEntry = positions[0].EntryPrice;
            for (int i = 1; i < positions.Length; i++)
            {
                if (direction == TradeType.Buy)
                {
                    if (positions[i].EntryPrice < worstEntry) worstEntry = positions[i].EntryPrice;
                }
                else
                {
                    if (positions[i].EntryPrice > worstEntry) worstEntry = positions[i].EntryPrice;
                }
            }

            bool farEnough = direction == TradeType.Buy
                ? Symbol.Ask <= worstEntry - step
                : Symbol.Bid >= worstEntry + step;

            if (!farEnough) return;
            if (_tradesToday >= MaxTradesPerDay) return;

            OpenOne(direction, string.Format("ADD {0}/{1}", positions.Length + 1, MaxPositions));
        }

        private void OpenOne(TradeType direction, string tag)
        {
            double volume = Symbol.NormalizeVolumeInUnits(
                Symbol.QuantityToVolumeInUnits(LotsPerPosition), RoundingMode.Down);

            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;

            double atr = _atr.Result.LastValue;
            double? stopPips = null;
            if (!double.IsNaN(atr) && atr > 0 && PositionStopAtr > 0)
                stopPips = Math.Round(PriceToPips(atr * PositionStopAtr), 1);

            TradeResult result = ExecuteMarketOrder(direction, SymbolName, volume, _label, stopPips, null);
            if (!result.IsSuccessful || result.Position == null)
            {
                LogVerbose("order rejected: " + result.Error);
                return;
            }

            _tradesToday++;
            _lastEntryTime = Server.Time;
            _lastDirection = direction;
            _status = "in position";

            LogVerbose(string.Format("{0} {1} {2} lots | stop {3} | spread {4:F1}p",
                tag, direction, LotsPerPosition,
                stopPips.HasValue ? stopPips.Value.ToString("F0") + "p" : "none", SpreadPips));
        }

        private TradeType ChooseDirection()
        {
            switch (Bias)
            {
                case EntryBias.AlwaysBuy:
                    return TradeType.Buy;
                case EntryBias.AlwaysSell:
                    return TradeType.Sell;
                case EntryBias.Alternate:
                    return _lastDirection == TradeType.Buy ? TradeType.Sell : TradeType.Buy;
                default:
                    double ema = _ema.Result.LastValue;
                    if (double.IsNaN(ema)) return TradeType.Buy;
                    return Symbol.Bid >= ema ? TradeType.Buy : TradeType.Sell;
            }
        }

        private string EntryBlocker()
        {
            if (_dayLocked) return "daily limit reached";
            if (_tradesToday >= MaxTradesPerDay) return "max trades per day";
            if (!InSession()) return "outside session";
            if (SpreadPips > MaxSpreadPips)
                return string.Format("spread {0:F1}p > {1:F1}p", SpreadPips, MaxSpreadPips);
            if (CooldownSeconds > 0 && _lastEntryTime != DateTime.MinValue
                && (Server.Time - _lastEntryTime).TotalSeconds < CooldownSeconds)
                return "cooldown";
            return null;
        }

        #endregion

        #region Guards

        private void EnforceDailyGuards()
        {
            if (_dayStartEquity <= 0) return;

            if (_dayLocked)
            {
                if (MyPositions().Length > 0) CloseAll("daily limit - retry");
                return;
            }

            double change = (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0;

            if (MaxDailyLossPercent > 0 && change <= -MaxDailyLossPercent)
            {
                _dayLocked = true;
                Print("DAILY LOSS CAP hit ({0:F2}%) - flat and idle until tomorrow", change);
                CloseAll("daily loss cap");
            }
            else if (DailyProfitTargetPercent > 0 && change >= DailyProfitTargetPercent)
            {
                _dayLocked = true;
                Print("DAILY PROFIT LOCK hit ({0:F2}%) - flat and idle until tomorrow", change);
                CloseAll("daily profit lock");
            }
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
            if (now.DayOfWeek == DayOfWeek.Friday && !TradeFriday) return false;

            double hour = now.Hour + now.Minute / 60.0;
            return SessionStart <= SessionEnd
                ? hour >= SessionStart && hour < SessionEnd
                : hour >= SessionStart || hour < SessionEnd;
        }

        #endregion

        #region Plumbing

        private Position[] MyPositions()
        {
            return Positions.FindAll(_label, SymbolName);
        }

        private void ClosePositionSafe(Position position, string reason)
        {
            TradeResult result = ClosePosition(position);
            if (result.IsSuccessful) LogVerbose(string.Format("closed #{0}: {1}", position.Id, reason));
            else LogVerbose(string.Format("close failed on #{0} ({1}): {2}", position.Id, reason, result.Error));
        }

        private void CloseAll(string reason)
        {
            Position[] positions = MyPositions();
            for (int i = 0; i < positions.Length; i++)
                ClosePositionSafe(positions[i], reason);
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
        }

        #endregion

        #region Reporting

        private void PrintHonestArithmetic()
        {
            double cost = SpreadPips;
            double winValue = MinProfitPips * Symbol.PipValue * Symbol.QuantityToVolumeInUnits(LotsPerPosition);
            double basketStop = Account.Equity * BasketStopPercent / 100.0;

            Print("--- what this configuration actually is ---");
            Print("Round-trip spread cost {0:F2} pips. Your target is {1:F1} pips net.",
                cost, MinProfitPips);
            Print("One winning trade is worth {0:F3} {1}. The basket stop is {2:F2} {3}.",
                winValue, Account.Asset.Name, basketStop, Account.Asset.Name);

            if (winValue > 0)
                Print("So ONE stopped basket erases {0:F0} winning trades.", basketStop / winValue);

            if (MinProfitPips <= cost)
                Print("WARNING: the target is below the spread. Wins will be near zero while "
                    + "losses stay whole - raise 'Min profit (pips)' above {0:F1}.", cost * 2);

            Print("Expectancy without an edge is minus the round-trip cost, at ANY win rate. "
                + "The win rate here will look excellent and means nothing on its own.");
            Print("-------------------------------------------");
        }

        private void PrintStatistics()
        {
            Print("=== GOLD BLUE CLOSE - session summary ===");
            Print("Trades {0} | wins {1} ({2:F1}%) | net {3:F2} {4}",
                _statTrades, _statWins, _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet, Account.Asset.Name);
            Print("Profit factor {0} | worst basket drawdown {1:F2} {2}",
                _statGrossLoss > 0 ? (_statGrossProfit / _statGrossLoss).ToString("F2") : "n/a",
                _worstBasket, Account.Asset.Name);

            int losses = _statTrades - _statWins;
            if (_statWins > 0 && losses > 0)
            {
                double avgWin = _statGrossProfit / _statWins;
                double avgLoss = _statGrossLoss / losses;
                Print("Average win {0:F3} | average loss {1:F3} | ONE loss erases {2:F0} wins",
                    avgWin, avgLoss, avgLoss / Math.Max(avgWin, 1e-9));
                Print("Win rate {0:F2}% | break-even win rate needed {1:F2}%",
                    100.0 * _statWins / _statTrades,
                    100.0 * avgLoss / (avgWin + avgLoss));
            }

            if (_statNet <= 0)
                Print("VERDICT: negative over this sample. A high win rate did not make it profitable.");
        }

        private void UpdateDashboard()
        {
            if (!ShowDashboard || Chart == null) return;

            Position[] positions = MyPositions();
            double basket = BasketNetProfit(positions);
            double dayChange = _dayStartEquity > 0
                ? (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0 : 0;

            string text = string.Format(
                "GOLD BLUE CLOSE\n" +
                "status      {0}\n" +
                "positions   {1}/{2}   basket {3:F2} {4}\n" +
                "basket stop {5:F2} {4}   worst {6:F2}\n" +
                "spread      {7:F1}p (max {8:F1}p)\n" +
                "today       {9}/{10} trades | P/L {11:F2}%\n" +
                "all-time    {12} | win {13:F1}% | net {14:F2}",
                _status,
                positions.Length, MaxPositions, basket, Account.Asset.Name,
                -Account.Equity * BasketStopPercent / 100.0, _worstBasket,
                SpreadPips, MaxSpreadPips,
                _tradesToday, MaxTradesPerDay, dayChange,
                _statTrades,
                _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet);

            Chart.DrawStaticText("blue_dashboard", text, VerticalAlignment.Top, HorizontalAlignment.Right, Color.DeepSkyBlue);
        }

        #endregion

        #region Helpers

        private double SpreadPips { get { return Symbol.Spread / Symbol.PipSize; } }

        private double PriceToPips(double priceDistance) { return priceDistance / Symbol.PipSize; }

        private void LogVerbose(string message) { if (_log) Print(message); }

        #endregion
    }
}
