using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum SessionMode
    {
        AllDay,
        LondonOnly,
        NewYorkOnly,
        LondonAndNewYork,
        Custom
    }

    public enum DirectionFilter
    {
        Both,
        LongOnly,
        ShortOnly
    }

    public enum MarketRegime
    {
        Unknown,
        Trend,
        Range,
        Chaos
    }

    public enum EntryExecution
    {
        Market,
        LimitRetrace
    }

    public enum EquityCurveMode
    {
        Off,
        ReduceRisk,
        Pause
    }

    /// <summary>
    /// GOLD SCALPER PRO v2 - XAUUSD intraday scalping engine for cTrader Automate.
    ///
    /// The bot never fires on a single indicator. Every bar it runs this pipeline:
    ///
    ///   1. HARD GATES      session / rollover / news / spread / volatility / daily caps
    ///   2. REGIME          ADX + ATR(fast)/ATR(slow) classify Trend, Range or Chaos
    ///   3. SETUP           Trend  -> EMA pullback rejection or range breakout
    ///                      Range  -> Bollinger band fade back inside
    ///   4. QUALITY SCORE   trend strength + HTF separation + momentum + candle + cost
    ///                      -> 0..100, entry needs MinQualityScore, size can scale with it
    ///   5. SIZING          % equity risk / ATR stop, adapted by streak, equity curve and score
    ///   6. EXECUTION       market range order with slippage cap
    ///   7. MANAGEMENT      TP ladder (2 partials + runner), break-even, ATR trail,
    ///                      time stop, spread-spike panic exit, session flatten
    ///   8. PYRAMIDING      optional add-ons on a winning position, at reduced risk
    ///
    /// Capital protection: daily loss cap, daily profit lock, max trades/day,
    /// consecutive-loss cooldown, equity-curve filter on the bot's own results.
    /// </summary>
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC, AddIndicators = true)]
    public class GoldScalperPro : Robot
    {
        #region 01 - General

        [Parameter("Instance label", Group = "01 - General", DefaultValue = "GSP")]
        public string InstanceLabel { get; set; }

        [Parameter("Verbose logs", Group = "01 - General", DefaultValue = true)]
        public bool Verbose { get; set; }

        [Parameter("Draw signals on chart", Group = "01 - General", DefaultValue = true)]
        public bool DrawOnChart { get; set; }

        [Parameter("On-chart dashboard", Group = "01 - General", DefaultValue = true)]
        public bool ShowDashboard { get; set; }

        #endregion

        #region 02 - Risk

        [Parameter("Base risk per trade (% equity)", Group = "02 - Risk", DefaultValue = 0.5, MinValue = 0.05, MaxValue = 5.0, Step = 0.05)]
        public double RiskPercent { get; set; }

        [Parameter("Risk ceiling (% equity)", Group = "02 - Risk", DefaultValue = 1.0, MinValue = 0.05, MaxValue = 10.0, Step = 0.05)]
        public double MaxRiskPercent { get; set; }

        [Parameter("Use fixed lots instead", Group = "02 - Risk", DefaultValue = false)]
        public bool UseFixedLots { get; set; }

        [Parameter("Fixed lots", Group = "02 - Risk", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double FixedLots { get; set; }

        [Parameter("Use broker min lot if size too small", Group = "02 - Risk", DefaultValue = false)]
        public bool AllowMinVolumeFallback { get; set; }

        [Parameter("Risk factor after a loss", Group = "02 - Risk", DefaultValue = 0.7, MinValue = 0.1, MaxValue = 1.0, Step = 0.05)]
        public double RiskFactorAfterLoss { get; set; }

        [Parameter("Risk factor after a win", Group = "02 - Risk", DefaultValue = 1.15, MinValue = 1.0, MaxValue = 2.0, Step = 0.05)]
        public double RiskFactorAfterWin { get; set; }

        [Parameter("Scale risk with quality score", Group = "02 - Risk", DefaultValue = true)]
        public bool ScaleRiskWithQuality { get; set; }

        [Parameter("Equity curve filter", Group = "02 - Risk", DefaultValue = EquityCurveMode.ReduceRisk)]
        public EquityCurveMode EquityCurveFilter { get; set; }

        [Parameter("Equity curve lookback (trades)", Group = "02 - Risk", DefaultValue = 10, MinValue = 3, MaxValue = 200)]
        public int EquityCurveLookback { get; set; }

        [Parameter("Equity curve risk factor", Group = "02 - Risk", DefaultValue = 0.5, MinValue = 0.1, MaxValue = 1.0, Step = 0.05)]
        public double EquityCurveRiskFactor { get; set; }

        #endregion

        #region 03 - Capital protection

        [Parameter("Max open positions", Group = "03 - Protection", DefaultValue = 1, MinValue = 1, MaxValue = 10)]
        public int MaxOpenPositions { get; set; }

        [Parameter("Max trades per day", Group = "03 - Protection", DefaultValue = 15, MinValue = 1, MaxValue = 200)]
        public int MaxTradesPerDay { get; set; }

        [Parameter("Daily loss cap (% equity, 0=off)", Group = "03 - Protection", DefaultValue = 3.0, MinValue = 0, MaxValue = 50, Step = 0.5)]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Daily profit lock (% equity, 0=off)", Group = "03 - Protection", DefaultValue = 4.0, MinValue = 0, MaxValue = 100, Step = 0.5)]
        public double DailyProfitTargetPercent { get; set; }

        [Parameter("Max consecutive losses", Group = "03 - Protection", DefaultValue = 3, MinValue = 0, MaxValue = 20)]
        public int MaxConsecutiveLosses { get; set; }

        [Parameter("Cooldown after streak (minutes)", Group = "03 - Protection", DefaultValue = 45, MinValue = 0, MaxValue = 1440)]
        public int CooldownMinutes { get; set; }

        #endregion

        #region 04 - Execution cost

        [Parameter("Max spread (pips)", Group = "04 - Cost", DefaultValue = 5.0, MinValue = 0.5, Step = 0.5)]
        public double MaxSpreadPips { get; set; }

        [Parameter("Max spread / ATR ratio (0=off)", Group = "04 - Cost", DefaultValue = 0.25, MinValue = 0, MaxValue = 2, Step = 0.01)]
        public double MaxSpreadToAtrRatio { get; set; }

        [Parameter("Spread spike vs average (0=off)", Group = "04 - Cost", DefaultValue = 2.0, MinValue = 0, MaxValue = 20, Step = 0.1)]
        public double SpreadSpikeMultiplier { get; set; }

        [Parameter("Panic exit on spread spike", Group = "04 - Cost", DefaultValue = true)]
        public bool PanicExitOnSpreadSpike { get; set; }

        [Parameter("Slippage protection", Group = "04 - Cost", DefaultValue = true)]
        public bool UseSlippageProtection { get; set; }

        [Parameter("Max slippage (pips)", Group = "04 - Cost", DefaultValue = 4.0, MinValue = 0.5, Step = 0.5)]
        public double MaxSlippagePips { get; set; }

        #endregion

        #region 05 - Higher timeframe bias

        [Parameter("Bias timeframe", Group = "05 - Bias", DefaultValue = "Minute15")]
        public TimeFrame BiasTimeFrame { get; set; }

        [Parameter("Bias fast EMA", Group = "05 - Bias", DefaultValue = 50, MinValue = 3, MaxValue = 400)]
        public int BiasFastPeriod { get; set; }

        [Parameter("Bias slow EMA", Group = "05 - Bias", DefaultValue = 200, MinValue = 5, MaxValue = 1000)]
        public int BiasSlowPeriod { get; set; }

        [Parameter("Require bias slope", Group = "05 - Bias", DefaultValue = true)]
        public bool RequireBiasSlope { get; set; }

        [Parameter("Bias slope lookback (bars)", Group = "05 - Bias", DefaultValue = 3, MinValue = 1, MaxValue = 50)]
        public int BiasSlopeLookback { get; set; }

        [Parameter("Direction filter", Group = "05 - Bias", DefaultValue = DirectionFilter.Both)]
        public DirectionFilter Direction { get; set; }

        #endregion

        #region 06 - Regime

        [Parameter("ADX period", Group = "06 - Regime", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AdxPeriod { get; set; }

        [Parameter("Trend ADX threshold", Group = "06 - Regime", DefaultValue = 22.0, MinValue = 5, MaxValue = 60, Step = 1)]
        public double TrendAdxLevel { get; set; }

        [Parameter("Range ADX ceiling", Group = "06 - Regime", DefaultValue = 18.0, MinValue = 5, MaxValue = 40, Step = 1)]
        public double RangeAdxLevel { get; set; }

        [Parameter("ATR period (fast)", Group = "06 - Regime", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AtrFastPeriod { get; set; }

        [Parameter("ATR period (slow)", Group = "06 - Regime", DefaultValue = 100, MinValue = 10, MaxValue = 500)]
        public int AtrSlowPeriod { get; set; }

        [Parameter("Min ATR fast/slow ratio", Group = "06 - Regime", DefaultValue = 0.75, MinValue = 0, MaxValue = 3, Step = 0.05)]
        public double MinVolatilityRatio { get; set; }

        [Parameter("Chaos ATR fast/slow ratio (0=off)", Group = "06 - Regime", DefaultValue = 3.0, MinValue = 0, MaxValue = 20, Step = 0.1)]
        public double ChaosVolatilityRatio { get; set; }

        [Parameter("Min ATR (pips, 0=off)", Group = "06 - Regime", DefaultValue = 0, MinValue = 0, Step = 1)]
        public double MinAtrPips { get; set; }

        #endregion

        #region 07 - Trend setups

        [Parameter("Enable trend mode", Group = "07 - Trend setups", DefaultValue = true)]
        public bool EnableTrendMode { get; set; }

        [Parameter("Fast EMA (entry TF)", Group = "07 - Trend setups", DefaultValue = 8, MinValue = 2, MaxValue = 100)]
        public int FastEmaPeriod { get; set; }

        [Parameter("Pullback EMA (entry TF)", Group = "07 - Trend setups", DefaultValue = 21, MinValue = 3, MaxValue = 200)]
        public int PullbackEmaPeriod { get; set; }

        [Parameter("Pullback entries", Group = "07 - Trend setups", DefaultValue = true)]
        public bool UsePullbackEntry { get; set; }

        [Parameter("Pullback tolerance (pips)", Group = "07 - Trend setups", DefaultValue = 6.0, MinValue = 0, Step = 0.5)]
        public double PullbackTolerancePips { get; set; }

        [Parameter("Breakout entries", Group = "07 - Trend setups", DefaultValue = true)]
        public bool UseBreakoutEntry { get; set; }

        [Parameter("Breakout lookback (bars)", Group = "07 - Trend setups", DefaultValue = 12, MinValue = 3, MaxValue = 100)]
        public int BreakoutLookback { get; set; }

        [Parameter("Min candle body / ATR", Group = "07 - Trend setups", DefaultValue = 0.25, MinValue = 0, MaxValue = 3, Step = 0.05)]
        public double MinBodyToAtr { get; set; }

        [Parameter("RSI period", Group = "07 - Trend setups", DefaultValue = 7, MinValue = 2, MaxValue = 50)]
        public int RsiPeriod { get; set; }

        [Parameter("RSI long trigger", Group = "07 - Trend setups", DefaultValue = 52.0, MinValue = 30, MaxValue = 70, Step = 0.5)]
        public double RsiLongTrigger { get; set; }

        [Parameter("RSI short trigger", Group = "07 - Trend setups", DefaultValue = 48.0, MinValue = 30, MaxValue = 70, Step = 0.5)]
        public double RsiShortTrigger { get; set; }

        [Parameter("RSI overbought block", Group = "07 - Trend setups", DefaultValue = 82.0, MinValue = 50, MaxValue = 100, Step = 1)]
        public double RsiOverbought { get; set; }

        [Parameter("RSI oversold block", Group = "07 - Trend setups", DefaultValue = 18.0, MinValue = 0, MaxValue = 50, Step = 1)]
        public double RsiOversold { get; set; }

        #endregion

        #region 08 - Range setups

        [Parameter("Enable range mode (fade)", Group = "08 - Range setups", DefaultValue = true)]
        public bool EnableRangeMode { get; set; }

        [Parameter("Bollinger period", Group = "08 - Range setups", DefaultValue = 20, MinValue = 5, MaxValue = 200)]
        public int BollingerPeriod { get; set; }

        [Parameter("Bollinger deviations", Group = "08 - Range setups", DefaultValue = 2.2, MinValue = 0.5, MaxValue = 5, Step = 0.1)]
        public double BollingerDeviations { get; set; }

        [Parameter("Fade RSI long threshold", Group = "08 - Range setups", DefaultValue = 28.0, MinValue = 5, MaxValue = 50, Step = 1)]
        public double FadeRsiLong { get; set; }

        [Parameter("Fade RSI short threshold", Group = "08 - Range setups", DefaultValue = 72.0, MinValue = 50, MaxValue = 95, Step = 1)]
        public double FadeRsiShort { get; set; }

        [Parameter("Range take profit (R)", Group = "08 - Range setups", DefaultValue = 1.0, MinValue = 0.2, MaxValue = 5, Step = 0.1)]
        public double RangeTpRewardRatio { get; set; }

        #endregion

        #region 09 - Quality score

        [Parameter("Min quality score (0-100)", Group = "09 - Quality", DefaultValue = 45.0, MinValue = 0, MaxValue = 100, Step = 1)]
        public double MinQualityScore { get; set; }

        [Parameter("Min bars between trades", Group = "09 - Quality", DefaultValue = 3, MinValue = 0, MaxValue = 200)]
        public int MinBarsBetweenTrades { get; set; }

        [Parameter("Entry execution", Group = "09 - Quality", DefaultValue = EntryExecution.Market)]
        public EntryExecution Execution { get; set; }

        [Parameter("Limit offset (pips)", Group = "09 - Quality", DefaultValue = 1.0, MinValue = 0, MaxValue = 50, Step = 0.5)]
        public double LimitOffsetPips { get; set; }

        [Parameter("Limit expiry (bars)", Group = "09 - Quality", DefaultValue = 3, MinValue = 1, MaxValue = 50)]
        public int LimitExpiryBars { get; set; }

        #endregion

        #region 10 - Exits

        [Parameter("Stop loss = ATR x", Group = "10 - Exits", DefaultValue = 1.2, MinValue = 0.2, MaxValue = 10, Step = 0.1)]
        public double SlAtrMultiplier { get; set; }

        [Parameter("Hard take profit = R x (0=off)", Group = "10 - Exits", DefaultValue = 3.0, MinValue = 0, MaxValue = 20, Step = 0.1)]
        public double TpRewardRatio { get; set; }

        [Parameter("Min stop (pips, 0=auto)", Group = "10 - Exits", DefaultValue = 0, MinValue = 0, Step = 1)]
        public double MinStopPips { get; set; }

        [Parameter("Stop buffer = spread x", Group = "10 - Exits", DefaultValue = 2.0, MinValue = 0, MaxValue = 20, Step = 0.5)]
        public double StopSpreadBufferMult { get; set; }

        [Parameter("TP ladder", Group = "10 - Exits", DefaultValue = true)]
        public bool UseTpLadder { get; set; }

        [Parameter("TP1 at (R)", Group = "10 - Exits", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double Tp1AtR { get; set; }

        [Parameter("TP1 size (%)", Group = "10 - Exits", DefaultValue = 40.0, MinValue = 5, MaxValue = 90, Step = 5)]
        public double Tp1Percent { get; set; }

        [Parameter("TP2 at (R)", Group = "10 - Exits", DefaultValue = 1.8, MinValue = 0.2, MaxValue = 20, Step = 0.1)]
        public double Tp2AtR { get; set; }

        [Parameter("TP2 size (% of remainder)", Group = "10 - Exits", DefaultValue = 50.0, MinValue = 5, MaxValue = 90, Step = 5)]
        public double Tp2Percent { get; set; }

        [Parameter("Break-even", Group = "10 - Exits", DefaultValue = true)]
        public bool UseBreakEven { get; set; }

        [Parameter("Break-even at (R)", Group = "10 - Exits", DefaultValue = 0.8, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double BreakEvenAtR { get; set; }

        [Parameter("Break-even lock (pips, 0=auto)", Group = "10 - Exits", DefaultValue = 0, MinValue = 0, Step = 1)]
        public double BreakEvenLockPips { get; set; }

        [Parameter("ATR trailing stop", Group = "10 - Exits", DefaultValue = true)]
        public bool UseTrailing { get; set; }

        [Parameter("Trail starts at (R)", Group = "10 - Exits", DefaultValue = 1.2, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double TrailStartAtR { get; set; }

        [Parameter("Trail distance = ATR x", Group = "10 - Exits", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double TrailAtrMultiplier { get; set; }

        [Parameter("Trail min step (pips)", Group = "10 - Exits", DefaultValue = 2.0, MinValue = 0.1, Step = 0.5)]
        public double TrailStepPips { get; set; }

        [Parameter("Time stop (bars, 0=off)", Group = "10 - Exits", DefaultValue = 60, MinValue = 0, MaxValue = 5000)]
        public int MaxBarsInTrade { get; set; }

        [Parameter("Give-back stop (% of peak R, 0=off)", Group = "10 - Exits", DefaultValue = 0, MinValue = 0, MaxValue = 100, Step = 5)]
        public double GiveBackPercent { get; set; }

        [Parameter("Exit trend trades on EMA flip", Group = "10 - Exits", DefaultValue = false)]
        public bool ExitOnTrendBreak { get; set; }

        #endregion

        #region 11 - Pyramiding

        [Parameter("Enable pyramiding", Group = "11 - Pyramiding", DefaultValue = false)]
        public bool EnablePyramiding { get; set; }

        [Parameter("Max add-ons", Group = "11 - Pyramiding", DefaultValue = 1, MinValue = 1, MaxValue = 5)]
        public int MaxAddOns { get; set; }

        [Parameter("Add-on when open trade >= (R)", Group = "11 - Pyramiding", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Step = 0.1)]
        public double AddOnAtR { get; set; }

        [Parameter("Add-on risk factor", Group = "11 - Pyramiding", DefaultValue = 0.5, MinValue = 0.1, MaxValue = 1.0, Step = 0.05)]
        public double AddOnRiskFactor { get; set; }

        #endregion

        #region 12 - Clock (UTC)

        [Parameter("Session", Group = "12 - Clock", DefaultValue = SessionMode.LondonAndNewYork)]
        public SessionMode Session { get; set; }

        [Parameter("Custom session start (UTC hour)", Group = "12 - Clock", DefaultValue = 7.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double CustomStartHour { get; set; }

        [Parameter("Custom session end (UTC hour)", Group = "12 - Clock", DefaultValue = 17.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double CustomEndHour { get; set; }

        [Parameter("Flatten outside session", Group = "12 - Clock", DefaultValue = true)]
        public bool CloseOutsideSession { get; set; }

        [Parameter("Rollover hour (UTC)", Group = "12 - Clock", DefaultValue = 21, MinValue = 0, MaxValue = 23)]
        public int RolloverHourUtc { get; set; }

        [Parameter("Avoid rollover +/- (minutes)", Group = "12 - Clock", DefaultValue = 15, MinValue = 0, MaxValue = 180)]
        public int AvoidRolloverMinutes { get; set; }

        [Parameter("News blackout times (UTC, HH:mm,...)", Group = "12 - Clock", DefaultValue = "12:30,14:00")]
        public string NewsBlackoutTimes { get; set; }

        [Parameter("News blackout +/- (minutes)", Group = "12 - Clock", DefaultValue = 12, MinValue = 0, MaxValue = 180)]
        public int NewsBlackoutMinutes { get; set; }

        [Parameter("Trading hours UTC (empty=all)", Group = "12 - Clock", DefaultValue = "")]
        public string TradingHoursMask { get; set; }

        [Parameter("Trade on Friday", Group = "12 - Clock", DefaultValue = true)]
        public bool TradeFriday { get; set; }

        [Parameter("Friday cutoff (UTC hour)", Group = "12 - Clock", DefaultValue = 19, MinValue = 0, MaxValue = 23)]
        public int FridayCutoffHour { get; set; }

        #endregion

        #region State

        private class TradeState
        {
            public double RiskPips;
            public double RiskMoney;
            public int PartialsDone;
            public bool BreakEvenDone;
            public int OpenBarIndex;
            public double PeakR;
            public string Setup;
            public bool IsAddOn;
        }

        private class Bucket
        {
            public int Trades;
            public int Wins;
            public double Net;
            public double GrossProfit;
            public double GrossLoss;
        }

        private readonly Dictionary<int, TradeState> _states = new Dictionary<int, TradeState>();
        private readonly List<int> _blackoutMinutesOfDay = new List<int>();
        private readonly List<double> _equityCurve = new List<double>();

        private ExponentialMovingAverage _emaFast;
        private ExponentialMovingAverage _emaPullback;
        private ExponentialMovingAverage _biasFast;
        private ExponentialMovingAverage _biasSlow;
        private RelativeStrengthIndex _rsi;
        private AverageTrueRange _atrFast;
        private AverageTrueRange _atrSlow;
        private DirectionalMovementSystem _dms;
        private BollingerBands _bollinger;
        private Bars _biasBars;

        private string _label;
        private bool _log;
        private int _minBarsRequired;

        private DateTime _currentDay;
        private double _dayStartEquity;
        private int _tradesToday;
        private bool _dayLocked;
        private int _consecutiveLosses;
        private int _consecutiveWins;
        private DateTime _cooldownUntil;
        private int _lastEntryBarIndex = int.MinValue;
        private int _addOnsInCluster;

        private double _spreadAverage;
        private double _lastQualityScore;
        private MarketRegime _regime = MarketRegime.Unknown;
        private string _lastBlocker = "starting";
        private bool _calibrationPrinted;

        private readonly Dictionary<int, string> _setupOf = new Dictionary<int, string>();
        private readonly bool[] _hourAllowed = new bool[24];
        private int _pendingBarIndex = int.MinValue;
        private string _pendingSetup;
        private bool _awaitingLimitFill;
        private double _slippageSumPips;
        private int _slippageCount;

        private double _cumulativeNetProfit;
        private int _statTrades;
        private int _statWins;
        private double _statGrossProfit;
        private double _statGrossLoss;
        private double _statSumR;
        private double _statPeakEquity;
        private double _statMaxDrawdown;

        #endregion

        #region Lifecycle

        protected override void OnStart()
        {
            _label = string.IsNullOrWhiteSpace(InstanceLabel) ? "GSP" : InstanceLabel.Trim();
            _log = Verbose && RunningMode != RunningMode.Optimization;

            if (BiasSlowPeriod <= BiasFastPeriod)
                Print("WARNING: bias slow EMA <= bias fast EMA, the bias filter will be unreliable.");
            if (MaxRiskPercent < RiskPercent)
                MaxRiskPercent = RiskPercent;
            if (RangeAdxLevel > TrendAdxLevel)
                Print("WARNING: range ADX ceiling above trend ADX threshold, regimes will overlap.");
            if (TpRewardRatio <= 0 && !UseTpLadder && !UseTrailing && MaxBarsInTrade <= 0)
                Print("WARNING: no hard take profit, no ladder, no trailing and no time stop. "
                    + "Positions could only ever exit on their stop loss. Enable at least one.");

            _emaFast = Indicators.ExponentialMovingAverage(Bars.ClosePrices, FastEmaPeriod);
            _emaPullback = Indicators.ExponentialMovingAverage(Bars.ClosePrices, PullbackEmaPeriod);
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            _atrFast = Indicators.AverageTrueRange(AtrFastPeriod, MovingAverageType.Exponential);
            _atrSlow = Indicators.AverageTrueRange(AtrSlowPeriod, MovingAverageType.Simple);
            _dms = Indicators.DirectionalMovementSystem(AdxPeriod);
            _bollinger = Indicators.BollingerBands(Bars.ClosePrices, BollingerPeriod, BollingerDeviations,
                MovingAverageType.Simple);

            _biasBars = MarketData.GetBars(BiasTimeFrame);
            _biasFast = Indicators.ExponentialMovingAverage(_biasBars.ClosePrices, BiasFastPeriod);
            _biasSlow = Indicators.ExponentialMovingAverage(_biasBars.ClosePrices, BiasSlowPeriod);

            _minBarsRequired = Math.Max(Math.Max(AtrSlowPeriod, PullbackEmaPeriod),
                Math.Max(BollingerPeriod, BreakoutLookback + 5)) + 5;

            _spreadAverage = SpreadPips;
            _statPeakEquity = Account.Equity;

            ParseBlackoutTimes();
            ParseTradingHours();
            StartNewDay();
            AdoptExistingPositions();

            Positions.Opened += OnPositionOpened;
            Positions.Closed += OnPositionClosed;

            Print("=== GOLD SCALPER PRO v2 ===");
            Print("Symbol {0} | entry TF {1} | bias TF {2}", SymbolName, TimeFrame, BiasTimeFrame);
            Print("PipSize {0} | Digits {1} | live spread {2:F1} pips", Symbol.PipSize, Symbol.Digits, SpreadPips);
            Print("Min volume {0} units | equity {1:F2} {2}", Symbol.VolumeInUnitsMin, Account.Equity, Account.Asset.Name);
            Print("The first bar prints a full CALIBRATION block. Read it before trusting any pip-based setting.");
        }

        protected override void OnStop()
        {
            Positions.Opened -= OnPositionOpened;
            Positions.Closed -= OnPositionClosed;
            PrintStatistics();
        }

        protected override void OnTick()
        {
            RollDayIfNeeded();
            UpdateSpreadAverage();
            ManageOpenPositions();
            EnforceDailyGuards();
        }

        protected override void OnBar()
        {
            RollDayIfNeeded();

            if (Bars.Count < _minBarsRequired || _biasBars.Count < BiasSlowPeriod + BiasSlopeLookback + 2)
            {
                _lastBlocker = "warming up";
                return;
            }

            if (!_calibrationPrinted)
            {
                PrintCalibration();
                _calibrationPrinted = true;
            }

            _regime = ClassifyRegime();
            ExpirePendingOrders();
            ApplyTrendBreakExit();

            if (CloseOutsideSession && !IsInSession())
            {
                CloseAll("session end");
                _lastBlocker = "outside session";
                UpdateDashboard();
                return;
            }

            string blocker = EntryBlocker();
            _lastBlocker = blocker;

            if (blocker == null)
                TryEnter();
            else
                LogVerbose("skip: " + blocker);

            UpdateDashboard();
        }

        #endregion

        #region Regime

        private MarketRegime ClassifyRegime()
        {
            double adx = _dms.ADX.Last(1);
            double atrFast = _atrFast.Result.Last(1);
            double atrSlow = _atrSlow.Result.Last(1);

            if (double.IsNaN(adx) || double.IsNaN(atrFast) || double.IsNaN(atrSlow) || atrSlow <= 0)
                return MarketRegime.Unknown;

            double ratio = atrFast / atrSlow;
            if (ChaosVolatilityRatio > 0 && ratio > ChaosVolatilityRatio)
                return MarketRegime.Chaos;

            if (adx >= TrendAdxLevel) return MarketRegime.Trend;
            if (adx <= RangeAdxLevel) return MarketRegime.Range;
            return MarketRegime.Unknown;
        }

        #endregion

        #region Entry

        private void TryEnter()
        {
            int bias = ComputeBias();
            TradeType? direction = null;
            string setup = null;

            if (_regime == MarketRegime.Trend && EnableTrendMode && bias != 0)
            {
                double rsi = _rsi.Result.Last(1);
                if (double.IsNaN(rsi)) return;

                if (bias > 0 && rsi < RsiOverbought)
                {
                    if (UsePullbackEntry && IsPullbackLong()) setup = "TREND-PULLBACK";
                    else if (UseBreakoutEntry && IsBreakoutLong()) setup = "TREND-BREAKOUT";
                    if (setup != null) direction = TradeType.Buy;
                }
                else if (bias < 0 && rsi > RsiOversold)
                {
                    if (UsePullbackEntry && IsPullbackShort()) setup = "TREND-PULLBACK";
                    else if (UseBreakoutEntry && IsBreakoutShort()) setup = "TREND-BREAKOUT";
                    if (setup != null) direction = TradeType.Sell;
                }
            }
            else if (_regime == MarketRegime.Range && EnableRangeMode)
            {
                if (IsFadeLong())
                {
                    setup = "RANGE-FADE";
                    direction = TradeType.Buy;
                }
                else if (IsFadeShort())
                {
                    setup = "RANGE-FADE";
                    direction = TradeType.Sell;
                }
            }

            if (direction == null) return;

            if (direction.Value == TradeType.Buy && Direction == DirectionFilter.ShortOnly) return;
            if (direction.Value == TradeType.Sell && Direction == DirectionFilter.LongOnly) return;

            bool isAddOn;
            if (!PositionSlotAvailable(direction.Value, out isAddOn))
                return;

            double score = ComputeQualityScore(direction.Value);
            _lastQualityScore = score;

            if (score < MinQualityScore)
            {
                LogVerbose(string.Format("skip: quality {0:F0} < {1:F0} ({2})", score, MinQualityScore, setup));
                return;
            }

            OpenTrade(direction.Value, setup, score, isAddOn);
        }

        /// <summary>Higher timeframe direction: +1 bullish, -1 bearish, 0 undecided.</summary>
        private int ComputeBias()
        {
            double fast = _biasFast.Result.Last(1);
            double slow = _biasSlow.Result.Last(1);
            double fastBefore = _biasFast.Result.Last(1 + BiasSlopeLookback);

            if (double.IsNaN(fast) || double.IsNaN(slow) || double.IsNaN(fastBefore))
                return 0;

            if (fast > slow && (!RequireBiasSlope || fast > fastBefore)) return 1;
            if (fast < slow && (!RequireBiasSlope || fast < fastBefore)) return -1;
            return 0;
        }

        private bool IsPullbackLong()
        {
            double ema = _emaPullback.Result.Last(1);
            double open = Bars.OpenPrices.Last(1);
            double close = Bars.ClosePrices.Last(1);
            double low = Bars.LowPrices.Last(1);
            double rsi = _rsi.Result.Last(1);
            double rsiPrev = _rsi.Result.Last(2);

            bool touched = low <= ema + PipsToPrice(PullbackTolerancePips);
            bool rejected = close > ema && close > open;
            bool aligned = _emaFast.Result.Last(1) > ema;
            bool momentum = rsi >= RsiLongTrigger && rsi > rsiPrev;

            return touched && rejected && aligned && momentum && HasMeaningfulBody();
        }

        private bool IsPullbackShort()
        {
            double ema = _emaPullback.Result.Last(1);
            double open = Bars.OpenPrices.Last(1);
            double close = Bars.ClosePrices.Last(1);
            double high = Bars.HighPrices.Last(1);
            double rsi = _rsi.Result.Last(1);
            double rsiPrev = _rsi.Result.Last(2);

            bool touched = high >= ema - PipsToPrice(PullbackTolerancePips);
            bool rejected = close < ema && close < open;
            bool aligned = _emaFast.Result.Last(1) < ema;
            bool momentum = rsi <= RsiShortTrigger && rsi < rsiPrev;

            return touched && rejected && aligned && momentum && HasMeaningfulBody();
        }

        private bool IsBreakoutLong()
        {
            return Bars.ClosePrices.Last(1) > HighestHigh(BreakoutLookback, 2)
                && _rsi.Result.Last(1) >= RsiLongTrigger
                && _emaFast.Result.Last(1) > _emaPullback.Result.Last(1)
                && HasMeaningfulBody();
        }

        private bool IsBreakoutShort()
        {
            return Bars.ClosePrices.Last(1) < LowestLow(BreakoutLookback, 2)
                && _rsi.Result.Last(1) <= RsiShortTrigger
                && _emaFast.Result.Last(1) < _emaPullback.Result.Last(1)
                && HasMeaningfulBody();
        }

        /// <summary>Range fade: the bar pierced the lower band and closed back inside, RSI washed out.</summary>
        private bool IsFadeLong()
        {
            double bottom = _bollinger.Bottom.Last(1);
            double main = _bollinger.Main.Last(1);
            if (double.IsNaN(bottom) || double.IsNaN(main)) return false;

            double low = Bars.LowPrices.Last(1);
            double close = Bars.ClosePrices.Last(1);
            double open = Bars.OpenPrices.Last(1);
            double rsi = _rsi.Result.Last(1);

            return low < bottom
                && close > bottom
                && close > open
                && close < main
                && rsi <= FadeRsiLong;
        }

        private bool IsFadeShort()
        {
            double top = _bollinger.Top.Last(1);
            double main = _bollinger.Main.Last(1);
            if (double.IsNaN(top) || double.IsNaN(main)) return false;

            double high = Bars.HighPrices.Last(1);
            double close = Bars.ClosePrices.Last(1);
            double open = Bars.OpenPrices.Last(1);
            double rsi = _rsi.Result.Last(1);

            return high > top
                && close < top
                && close < open
                && close > main
                && rsi >= FadeRsiShort;
        }

        private bool HasMeaningfulBody()
        {
            if (MinBodyToAtr <= 0) return true;
            double atr = _atrFast.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0) return false;
            double body = Math.Abs(Bars.ClosePrices.Last(1) - Bars.OpenPrices.Last(1));
            return body >= atr * MinBodyToAtr;
        }

        private double HighestHigh(int count, int shift)
        {
            double max = double.MinValue;
            for (int i = shift; i < shift + count; i++)
            {
                double v = Bars.HighPrices.Last(i);
                if (v > max) max = v;
            }
            return max;
        }

        private double LowestLow(int count, int shift)
        {
            double min = double.MaxValue;
            for (int i = shift; i < shift + count; i++)
            {
                double v = Bars.LowPrices.Last(i);
                if (v < min) min = v;
            }
            return min;
        }

        #endregion

        #region Quality score

        /// <summary>
        /// Confluence score in 0..100. Each block is independent so a weak
        /// dimension cannot be hidden by a strong one.
        ///   trend strength 25 | HTF separation 20 | momentum 20 | candle 15 | cost 20
        /// </summary>
        private double ComputeQualityScore(TradeType tradeType)
        {
            double atr = _atrFast.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0) return 0;

            double score = 0;

            double adx = _dms.ADX.Last(1);
            if (!double.IsNaN(adx))
                score += 25.0 * Clamp01((adx - RangeAdxLevel) / 25.0);

            double separation = Math.Abs(_biasFast.Result.Last(1) - _biasSlow.Result.Last(1)) / atr;
            if (!double.IsNaN(separation))
                score += 20.0 * Clamp01(separation / 3.0);

            double rsi = _rsi.Result.Last(1);
            if (!double.IsNaN(rsi))
            {
                double distance = tradeType == TradeType.Buy ? rsi - 50.0 : 50.0 - rsi;
                if (_regime == MarketRegime.Range) distance = Math.Abs(rsi - 50.0);
                score += 20.0 * Clamp01(distance / 25.0);
            }

            double body = Math.Abs(Bars.ClosePrices.Last(1) - Bars.OpenPrices.Last(1)) / atr;
            score += 15.0 * Clamp01(body);

            double atrPips = PriceToPips(atr);
            double costBudget = MaxSpreadToAtrRatio > 0 ? atrPips * MaxSpreadToAtrRatio : MaxSpreadPips;
            if (costBudget > 0)
                score += 20.0 * Clamp01(1.0 - SpreadPips / costBudget);

            return score;
        }

        private static double Clamp01(double value)
        {
            if (value < 0) return 0;
            if (value > 1) return 1;
            return value;
        }

        #endregion

        #region Order placement

        private bool PositionSlotAvailable(TradeType tradeType, out bool isAddOn)
        {
            isAddOn = false;
            Position[] positions = Positions.FindAll(_label, SymbolName);

            if (positions.Length == 0)
            {
                _addOnsInCluster = 0;
                return true;
            }

            if (positions.Length < MaxOpenPositions && !EnablePyramiding)
                return true;

            if (!EnablePyramiding) return false;
            if (_addOnsInCluster >= MaxAddOns) return false;
            if (positions.Length >= MaxOpenPositions + MaxAddOns) return false;

            double bestR = double.MinValue;
            for (int i = 0; i < positions.Length; i++)
            {
                if (positions[i].TradeType != tradeType) return false; // never hedge against ourselves

                TradeState state = GetOrRebuildState(positions[i]);
                if (state == null || state.RiskPips <= 0) return false;

                double r = positions[i].Pips / state.RiskPips;
                if (r > bestR) bestR = r;
            }

            if (bestR < AddOnAtR) return false;

            isAddOn = true;
            return true;
        }

        private void OpenTrade(TradeType tradeType, string setup, double score, bool isAddOn)
        {
            double atr = _atrFast.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0) return;

            double stopPips = PriceToPips(atr) * SlAtrMultiplier;
            double floorPips = Math.Max(MinStopPips, SpreadPips * StopSpreadBufferMult);
            if (stopPips < floorPips) stopPips = floorPips;
            stopPips = Math.Round(stopPips, 1);
            if (stopPips <= 0) return;

            double rewardRatio = setup == "RANGE-FADE" ? RangeTpRewardRatio : TpRewardRatio;
            double? targetPips = rewardRatio > 0 ? (double?)Math.Round(stopPips * rewardRatio, 1) : null;

            double riskPercent = ResolveRiskPercent(score, isAddOn);
            double volume = ComputeVolume(stopPips, riskPercent);
            if (volume <= 0) return;

            if (Execution == EntryExecution.LimitRetrace && !isAddOn)
            {
                PlaceRetraceLimit(tradeType, setup, score, volume, stopPips, targetPips);
                return;
            }

            double requested = tradeType == TradeType.Buy ? Symbol.Ask : Symbol.Bid;

            TradeResult result;
            if (UseSlippageProtection)
            {
                result = ExecuteMarketRangeOrder(tradeType, SymbolName, volume, MaxSlippagePips,
                    requested, _label, stopPips, targetPips);
            }
            else
            {
                result = ExecuteMarketOrder(tradeType, SymbolName, volume, _label, stopPips, targetPips);
            }

            if (!result.IsSuccessful || result.Position == null)
            {
                Print("Order rejected ({0}): {1}", setup, result.Error);
                return;
            }

            _tradesToday++;
            _lastEntryBarIndex = Bars.Count - 1;
            if (isAddOn) _addOnsInCluster++;

            RecordSlippage(tradeType, requested, result.Position.EntryPrice);

            _setupOf[result.Position.Id] = setup;
            _states[result.Position.Id] = new TradeState
            {
                RiskPips = stopPips,
                RiskMoney = stopPips * Symbol.PipValue * volume,
                PartialsDone = 0,
                BreakEvenDone = false,
                OpenBarIndex = Bars.Count - 1,
                PeakR = 0,
                Setup = setup,
                IsAddOn = isAddOn
            };

            Print("{0}{1} {2} | {3} | score {4:F0} | risk {5:F2}% | vol {6} | SL {7:F1}p | TP {8} | spread {9:F1}p",
                isAddOn ? "ADD-ON " : "", tradeType, SymbolName, setup, score, riskPercent, volume, stopPips,
                targetPips.HasValue ? targetPips.Value.ToString("F1") + "p" : "trail only", SpreadPips);

            DrawSignal(tradeType, setup);
        }

        /// <summary>
        /// Instead of paying the spread to chase the signal bar's close, rest a limit
        /// at the level the setup was built on and let price come back to us. Fewer
        /// fills, materially better entry price on the ones that do fill.
        /// </summary>
        private void PlaceRetraceLimit(TradeType tradeType, string setup, double score,
            double volume, double stopPips, double? targetPips)
        {
            bool isBuy = tradeType == TradeType.Buy;
            double level;

            if (setup == "RANGE-FADE")
                level = isBuy ? _bollinger.Bottom.Last(1) : _bollinger.Top.Last(1);
            else if (setup == "TREND-BREAKOUT")
                level = isBuy ? HighestHigh(BreakoutLookback, 2) : LowestLow(BreakoutLookback, 2);
            else
                level = _emaPullback.Result.Last(1);

            if (double.IsNaN(level)) return;

            // Offset towards current price: slightly worse fill price, materially better fill rate.
            double limitPrice = isBuy
                ? level + PipsToPrice(LimitOffsetPips)
                : level - PipsToPrice(LimitOffsetPips);
            limitPrice = Math.Round(limitPrice, Symbol.Digits);

            // The retrace has to still be ahead of us, otherwise this is just a worse market order.
            if (isBuy && limitPrice >= Symbol.Ask) return;
            if (!isBuy && limitPrice <= Symbol.Bid) return;

            TradeResult result = PlaceLimitOrder(tradeType, SymbolName, volume, limitPrice,
                _label, stopPips, targetPips, (DateTime?)null);

            if (!result.IsSuccessful)
            {
                Print("Limit rejected ({0}): {1}", setup, result.Error);
                return;
            }

            _awaitingLimitFill = true;
            _pendingSetup = setup;
            _pendingBarIndex = Bars.Count - 1;
            _lastEntryBarIndex = Bars.Count - 1;

            Print("LIMIT {0} {1} | {2} | score {3:F0} | at {4} ({5:F1}p below market) | SL {6:F1}p",
                tradeType, SymbolName, setup, score, limitPrice,
                PriceToPips(Math.Abs((isBuy ? Symbol.Ask : Symbol.Bid) - limitPrice)), stopPips);
        }

        /// <summary>A resting limit is a stale opinion once the setup's bar is a few bars old.</summary>
        private void ExpirePendingOrders()
        {
            PendingOrder[] orders = PendingOrders.FindAll(_label, SymbolName);

            if (orders.Length == 0)
            {
                _awaitingLimitFill = false;
                _pendingSetup = null;
                _pendingBarIndex = int.MinValue;
                return;
            }

            bool stale = _pendingBarIndex != int.MinValue
                && Bars.Count - 1 - _pendingBarIndex >= LimitExpiryBars;
            bool shutDown = _dayLocked
                || Server.Time < _cooldownUntil
                || (CloseOutsideSession && !IsInSession());

            if (!stale && !shutDown) return;

            for (int i = 0; i < orders.Length; i++)
                CancelPendingOrder(orders[i]);

            LogVerbose(stale ? "limit order expired" : "limit order cancelled (bot standing down)");
            _awaitingLimitFill = false;
            _pendingSetup = null;
            _pendingBarIndex = int.MinValue;
        }

        /// <summary>
        /// A trend trade whose trend is gone is no longer the trade that was taken.
        /// Only ever applied once the position is out of its initial risk.
        /// </summary>
        private void ApplyTrendBreakExit()
        {
            if (!ExitOnTrendBreak) return;

            double fast = _emaFast.Result.Last(1);
            double slow = _emaPullback.Result.Last(1);
            if (double.IsNaN(fast) || double.IsNaN(slow)) return;

            Position[] positions = Positions.FindAll(_label, SymbolName);
            for (int i = 0; i < positions.Length; i++)
            {
                Position position = positions[i];
                TradeState state = GetOrRebuildState(position);
                if (state == null || state.RiskPips <= 0) continue;
                if (state.Setup == null || !state.Setup.StartsWith("TREND")) continue;
                if (position.Pips < 0) continue;

                bool broken = position.TradeType == TradeType.Buy ? fast < slow : fast > slow;
                if (broken) ClosePositionSafe(position, "trend break");
            }
        }

        private void RecordSlippage(TradeType tradeType, double requested, double filled)
        {
            if (requested <= 0 || filled <= 0) return;
            _slippageSumPips += PriceToPips(tradeType == TradeType.Buy ? filled - requested : requested - filled);
            _slippageCount++;
        }

        /// <summary>Base risk adjusted by streak, quality score and the bot's own equity curve.</summary>
        private double ResolveRiskPercent(double score, bool isAddOn)
        {
            double risk = RiskPercent;

            if (_consecutiveLosses > 0) risk *= RiskFactorAfterLoss;
            else if (_consecutiveWins > 0) risk *= RiskFactorAfterWin;

            if (ScaleRiskWithQuality)
                risk *= 0.6 + 0.8 * Clamp01(score / 100.0);

            if (EquityCurveFilter == EquityCurveMode.ReduceRisk && IsEquityCurveDegraded())
                risk *= EquityCurveRiskFactor;

            if (isAddOn) risk *= AddOnRiskFactor;

            if (risk > MaxRiskPercent) risk = MaxRiskPercent;
            if (risk < 0.01) risk = 0.01;

            return risk;
        }

        private double ComputeVolume(double stopPips, double riskPercent)
        {
            if (UseFixedLots)
                return Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(FixedLots), RoundingMode.Down);

            double pipValue = Symbol.PipValue;
            if (pipValue <= 0 || stopPips <= 0)
            {
                Print("Cannot size position: pip value {0}, stop {1}", pipValue, stopPips);
                return 0;
            }

            double riskAmount = Account.Equity * riskPercent / 100.0;
            double units = Symbol.NormalizeVolumeInUnits(riskAmount / (stopPips * pipValue), RoundingMode.Down);

            if (units < Symbol.VolumeInUnitsMin)
            {
                if (!AllowMinVolumeFallback)
                {
                    LogVerbose(string.Format(
                        "skip: risk {0:F2} {1} too small for a {2:F1} pip stop (below broker min lot)",
                        riskAmount, Account.Asset.Name, stopPips));
                    return 0;
                }
                units = Symbol.VolumeInUnitsMin;
            }

            if (units > Symbol.VolumeInUnitsMax)
                units = Symbol.VolumeInUnitsMax;

            return units;
        }

        #endregion

        #region Position management

        private void ManageOpenPositions()
        {
            Position[] positions = Positions.FindAll(_label, SymbolName);
            if (positions.Length == 0)
            {
                _addOnsInCluster = 0;
                return;
            }

            double atr = _atrFast.Result.LastValue;
            bool atrOk = !double.IsNaN(atr) && atr > 0;
            bool outsideSession = CloseOutsideSession && !IsInSession();
            bool spreadSpike = IsSpreadSpike();

            for (int i = 0; i < positions.Length; i++)
            {
                Position position = positions[i];
                TradeState state = GetOrRebuildState(position);
                if (state == null || state.RiskPips <= 0) continue;

                if (outsideSession)
                {
                    ClosePositionSafe(position, "session end");
                    continue;
                }

                if (MaxBarsInTrade > 0 && Bars.Count - 1 - state.OpenBarIndex >= MaxBarsInTrade)
                {
                    ClosePositionSafe(position, "time stop");
                    continue;
                }

                double rMultiple = position.Pips / state.RiskPips;
                if (rMultiple > state.PeakR) state.PeakR = rMultiple;

                // A spread explosion turns a scalp into a lottery ticket: get out while flat-ish.
                if (PanicExitOnSpreadSpike && spreadSpike && rMultiple >= 0 && rMultiple < BreakEvenAtR)
                {
                    ClosePositionSafe(position, "spread spike");
                    continue;
                }

                if (GiveBackPercent > 0 && state.PeakR >= Math.Max(BreakEvenAtR, 0.5)
                    && rMultiple <= state.PeakR * (1.0 - GiveBackPercent / 100.0))
                {
                    ClosePositionSafe(position, string.Format("gave back {0:F0}% of {1:F2}R", GiveBackPercent, state.PeakR));
                    continue;
                }

                if (UseTpLadder)
                {
                    if (state.PartialsDone == 0 && rMultiple >= Tp1AtR && TryPartialClose(position, Tp1Percent, "TP1"))
                        state.PartialsDone = 1;
                    else if (state.PartialsDone == 1 && rMultiple >= Tp2AtR && TryPartialClose(position, Tp2Percent, "TP2"))
                        state.PartialsDone = 2;
                }

                if (UseBreakEven && !state.BreakEvenDone && rMultiple >= BreakEvenAtR)
                {
                    double lockPips = BreakEvenLockPips > 0 ? BreakEvenLockPips : Math.Max(1.0, SpreadPips);
                    double target = position.TradeType == TradeType.Buy
                        ? position.EntryPrice + PipsToPrice(lockPips)
                        : position.EntryPrice - PipsToPrice(lockPips);

                    if (TryMoveStop(position, target))
                    {
                        state.BreakEvenDone = true;
                        LogVerbose(string.Format("break-even set on #{0}", position.Id));
                    }
                }

                if (UseTrailing && atrOk && rMultiple >= TrailStartAtR)
                {
                    double distance = PipsToPrice(PriceToPips(atr) * TrailAtrMultiplier);
                    double candidate = position.TradeType == TradeType.Buy
                        ? Symbol.Bid - distance
                        : Symbol.Ask + distance;

                    TryMoveStop(position, candidate);
                }
            }
        }

        private bool TryPartialClose(Position position, double percent, string tag)
        {
            double closeVolume = Symbol.NormalizeVolumeInUnits(
                position.VolumeInUnits * percent / 100.0, RoundingMode.Down);

            if (closeVolume < Symbol.VolumeInUnitsMin) return false;
            if (position.VolumeInUnits - closeVolume < Symbol.VolumeInUnitsMin) return false;

            TradeResult result = ClosePosition(position, closeVolume);
            if (result.IsSuccessful)
            {
                LogVerbose(string.Format("{0}: closed {1} units of #{2} at {3:F1} pips",
                    tag, closeVolume, position.Id, position.Pips));
                return true;
            }

            Print("{0} failed on #{1}: {2}", tag, position.Id, result.Error);
            return false;
        }

        /// <summary>Moves a stop only in the protective direction, respecting a minimum step.</summary>
        private bool TryMoveStop(Position position, double newStop)
        {
            newStop = Math.Round(newStop, Symbol.Digits);
            double step = PipsToPrice(TrailStepPips);

            if (position.TradeType == TradeType.Buy)
            {
                if (newStop >= Symbol.Bid) return false;
                if (position.StopLoss.HasValue && newStop <= position.StopLoss.Value + step) return false;
            }
            else
            {
                if (newStop <= Symbol.Ask) return false;
                if (position.StopLoss.HasValue && newStop >= position.StopLoss.Value - step) return false;
            }

            // Absolute: newStop is a price level, not a pip distance.
            // On a pre-5.0 cTrader, drop the ProtectionType argument.
            return ModifyPosition(position, newStop, position.TakeProfit, ProtectionType.Absolute).IsSuccessful;
        }

        private void ClosePositionSafe(Position position, string reason)
        {
            TradeResult result = ClosePosition(position);
            if (result.IsSuccessful)
                LogVerbose(string.Format("closed #{0} ({1})", position.Id, reason));
            else
                Print("Close failed on #{0} ({1}): {2}", position.Id, reason, result.Error);
        }

        private void CloseAll(string reason)
        {
            // A resting limit must die with the positions, or the daily cap can be
            // breached by an order that fills a minute after the bot stood down.
            PendingOrder[] orders = PendingOrders.FindAll(_label, SymbolName);
            for (int i = 0; i < orders.Length; i++)
                CancelPendingOrder(orders[i]);
            if (orders.Length > 0)
            {
                _awaitingLimitFill = false;
                _pendingSetup = null;
                _pendingBarIndex = int.MinValue;
            }

            Position[] positions = Positions.FindAll(_label, SymbolName);
            for (int i = 0; i < positions.Length; i++)
                ClosePositionSafe(positions[i], reason);
        }

        private TradeState GetOrRebuildState(Position position)
        {
            TradeState state;
            if (_states.TryGetValue(position.Id, out state))
                return state;

            // Bot restarted while a position was open: rebuild the risk unit from the live stop.
            double riskPips = position.StopLoss.HasValue
                ? PriceToPips(Math.Abs(position.EntryPrice - position.StopLoss.Value))
                : 0;

            state = new TradeState
            {
                RiskPips = riskPips,
                PartialsDone = 2,
                BreakEvenDone = riskPips <= 0,
                OpenBarIndex = Bars.Count - 1,
                PeakR = 0,
                Setup = "ADOPTED",
                IsAddOn = false
            };

            _states[position.Id] = state;
            return state;
        }

        private void AdoptExistingPositions()
        {
            Position[] positions = Positions.FindAll(_label, SymbolName);
            for (int i = 0; i < positions.Length; i++)
                GetOrRebuildState(positions[i]);

            if (positions.Length > 0)
                Print("Adopted {0} existing position(s) with label {1}", positions.Length, _label);
        }

        private void OnPositionOpened(PositionOpenedEventArgs args)
        {
            Position position = args.Position;
            if (position.Label != _label || position.SymbolName != SymbolName) return;
            if (_states.ContainsKey(position.Id)) return; // the market path already registered it

            double riskPips = position.StopLoss.HasValue
                ? PriceToPips(Math.Abs(position.EntryPrice - position.StopLoss.Value))
                : 0;
            string setup = _pendingSetup == null ? "LIMIT" : _pendingSetup;

            _setupOf[position.Id] = setup;
            _states[position.Id] = new TradeState
            {
                RiskPips = riskPips,
                RiskMoney = riskPips * Symbol.PipValue * position.VolumeInUnits,
                PartialsDone = 0,
                BreakEvenDone = false,
                OpenBarIndex = Bars.Count - 1,
                PeakR = 0,
                Setup = setup,
                IsAddOn = false
            };

            if (_awaitingLimitFill)
            {
                _tradesToday++;
                _awaitingLimitFill = false;
                _pendingSetup = null;
                _pendingBarIndex = int.MinValue;
                Print("LIMIT FILLED {0} {1} | {2} | entry {3} | SL {4:F1}p",
                    position.TradeType, SymbolName, setup, position.EntryPrice, riskPips);
                DrawSignal(position.TradeType, setup);
            }
        }

        /// <summary>
        /// Sums every historical fill belonging to one position. A laddered trade closes in
        /// several pieces, and Position.NetProfit at the close event only carries the last
        /// one - reading that alone scores a winning trade as a loss whenever the runner
        /// comes back to break-even, which would poison the streak logic and the stats.
        /// </summary>
        private double RealizedForPosition(int positionId, double fallback)
        {
            double total = 0;
            bool found = false;
            int stop = Math.Max(0, History.Count - 200);

            for (int i = History.Count - 1; i >= stop; i--)
            {
                HistoricalTrade trade = History[i];
                if (trade.PositionId != positionId) continue;
                total += trade.NetProfit;
                found = true;
            }

            return found ? total : fallback;
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            Position position = args.Position;
            if (position.Label != _label || position.SymbolName != SymbolName) return;

            TradeState state;
            bool hadState = _states.TryGetValue(position.Id, out state);
            double riskPips = hadState ? state.RiskPips : 0;
            double riskMoney = hadState ? state.RiskMoney : 0;
            _states.Remove(position.Id);

            double netProfit = RealizedForPosition(position.Id, position.NetProfit);
            _cumulativeNetProfit += netProfit;
            _equityCurve.Add(_cumulativeNetProfit);

            _statTrades++;
            if (netProfit > 0)
            {
                _statWins++;
                _statGrossProfit += netProfit;
                _consecutiveWins++;
                _consecutiveLosses = 0;
            }
            else if (netProfit < 0)
            {
                _statGrossLoss += -netProfit;
                _consecutiveLosses++;
                _consecutiveWins = 0;

                if (MaxConsecutiveLosses > 0 && _consecutiveLosses >= MaxConsecutiveLosses && CooldownMinutes > 0)
                {
                    _cooldownUntil = Server.Time.AddMinutes(CooldownMinutes);
                    _consecutiveLosses = 0;
                    Print("{0} losses in a row -> cooldown until {1:HH:mm} UTC", MaxConsecutiveLosses, _cooldownUntil);
                }
            }

            if (riskMoney > 0) _statSumR += netProfit / riskMoney;
            else if (riskPips > 0) _statSumR += position.Pips / riskPips;

            double equity = Account.Equity;
            if (equity > _statPeakEquity) _statPeakEquity = equity;
            double drawdown = _statPeakEquity - equity;
            if (drawdown > _statMaxDrawdown) _statMaxDrawdown = drawdown;

            LogVerbose(string.Format("closed #{0} {1} | total {2:F2} {3} ({4:F2}R)",
                position.Id, _setupOf.ContainsKey(position.Id) ? _setupOf[position.Id] : "?",
                netProfit, Account.Asset.Name,
                riskMoney > 0 ? netProfit / riskMoney : 0));
        }

        #endregion

        #region Guards

        /// <summary>Returns null when a new trade is allowed, otherwise the blocking reason.</summary>
        private string EntryBlocker()
        {
            if (_dayLocked) return "daily limit reached";
            if (Server.Time < _cooldownUntil) return "cooldown active";
            if (_tradesToday >= MaxTradesPerDay) return "max trades per day";

            if (EquityCurveFilter == EquityCurveMode.Pause && IsEquityCurveDegraded())
                return "equity curve below its average";

            if (MinBarsBetweenTrades > 0 && _lastEntryBarIndex != int.MinValue
                && Bars.Count - 1 - _lastEntryBarIndex < MinBarsBetweenTrades)
                return "entry spacing";

            if (!IsInSession()) return "outside session";
            if (!_hourAllowed[Server.Time.Hour])
                return string.Format("hour {0:00}h off", Server.Time.Hour);
            if (PendingOrders.FindAll(_label, SymbolName).Length > 0) return "limit order working";
            if (IsRolloverWindow()) return "rollover window";
            if (IsNewsBlackout()) return "news blackout";

            if (_regime == MarketRegime.Chaos) return "chaotic volatility";
            if (_regime == MarketRegime.Unknown) return "no clear regime";
            if (_regime == MarketRegime.Trend && !EnableTrendMode) return "trend mode disabled";
            if (_regime == MarketRegime.Range && !EnableRangeMode) return "range mode disabled";

            double spread = SpreadPips;
            if (spread > MaxSpreadPips)
                return string.Format("spread {0:F1}p > {1:F1}p", spread, MaxSpreadPips);
            if (IsSpreadSpike())
                return string.Format("spread spike {0:F1}p vs avg {1:F1}p", spread, _spreadAverage);

            double atrFast = _atrFast.Result.Last(1);
            double atrSlow = _atrSlow.Result.Last(1);
            if (double.IsNaN(atrFast) || double.IsNaN(atrSlow) || atrFast <= 0 || atrSlow <= 0)
                return "ATR not ready";

            double atrPips = PriceToPips(atrFast);
            if (MinAtrPips > 0 && atrPips < MinAtrPips)
                return string.Format("ATR {0:F1}p < {1:F1}p", atrPips, MinAtrPips);

            if (MaxSpreadToAtrRatio > 0 && spread > atrPips * MaxSpreadToAtrRatio)
                return string.Format("spread {0:F1}p too big vs ATR {1:F1}p", spread, atrPips);

            if (MinVolatilityRatio > 0 && atrFast / atrSlow < MinVolatilityRatio)
                return string.Format("volatility too low (ratio {0:F2})", atrFast / atrSlow);

            return null;
        }

        private bool IsEquityCurveDegraded()
        {
            if (EquityCurveFilter == EquityCurveMode.Off) return false;
            if (_equityCurve.Count < EquityCurveLookback) return false;

            double sum = 0;
            for (int i = _equityCurve.Count - EquityCurveLookback; i < _equityCurve.Count; i++)
                sum += _equityCurve[i];

            return _cumulativeNetProfit < sum / EquityCurveLookback;
        }

        private void EnforceDailyGuards()
        {
            if (_dayStartEquity <= 0) return;

            if (_dayLocked)
            {
                // A close can be rejected (requote, market closed, connection drop).
                // Being locked must never mean being locked *and still exposed*.
                if (Positions.FindAll(_label, SymbolName).Length > 0)
                    CloseAll("daily limit - retry");
                return;
            }

            double changePercent = (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0;

            if (MaxDailyLossPercent > 0 && changePercent <= -MaxDailyLossPercent)
            {
                _dayLocked = true;
                Print("DAILY LOSS CAP hit ({0:F2}%) -> flat and idle until tomorrow", changePercent);
                CloseAll("daily loss cap");
            }
            else if (DailyProfitTargetPercent > 0 && changePercent >= DailyProfitTargetPercent)
            {
                _dayLocked = true;
                Print("DAILY PROFIT LOCK hit ({0:F2}%) -> flat and idle until tomorrow", changePercent);
                CloseAll("daily profit lock");
            }
        }

        private void RollDayIfNeeded()
        {
            if (Server.Time.Date != _currentDay)
                StartNewDay();
        }

        private void StartNewDay()
        {
            _currentDay = Server.Time.Date;
            _dayStartEquity = Account.Equity;
            _tradesToday = 0;
            _dayLocked = false;
            _consecutiveLosses = 0;
            _consecutiveWins = 0;
            _lastEntryBarIndex = int.MinValue;
        }

        private void UpdateSpreadAverage()
        {
            double spread = SpreadPips;
            if (spread <= 0) return;
            // ~200 tick EMA, enough to know what "normal" looks like for this broker.
            _spreadAverage = _spreadAverage <= 0 ? spread : _spreadAverage + (spread - _spreadAverage) * 0.005;
        }

        private bool IsSpreadSpike()
        {
            if (SpreadSpikeMultiplier <= 0 || _spreadAverage <= 0) return false;
            return SpreadPips > _spreadAverage * SpreadSpikeMultiplier;
        }

        #endregion

        #region Clock

        private bool IsInSession()
        {
            DateTime now = Server.Time;
            DayOfWeek day = now.DayOfWeek;

            if (day == DayOfWeek.Saturday || day == DayOfWeek.Sunday) return false;
            if (day == DayOfWeek.Friday && !TradeFriday) return false;
            if (day == DayOfWeek.Friday && now.Hour >= FridayCutoffHour) return false;

            double hour = now.Hour + now.Minute / 60.0;

            switch (Session)
            {
                case SessionMode.AllDay:
                    return true;
                case SessionMode.LondonOnly:
                    return hour >= 7.0 && hour < 11.5;
                case SessionMode.NewYorkOnly:
                    return hour >= 12.5 && hour < 17.0;
                case SessionMode.LondonAndNewYork:
                    return hour >= 7.0 && hour < 17.0;
                case SessionMode.Custom:
                    return CustomStartHour <= CustomEndHour
                        ? hour >= CustomStartHour && hour < CustomEndHour
                        : hour >= CustomStartHour || hour < CustomEndHour;
                default:
                    return true;
            }
        }

        private bool IsRolloverWindow()
        {
            if (AvoidRolloverMinutes <= 0) return false;
            int nowMinutes = Server.Time.Hour * 60 + Server.Time.Minute;
            return CircularMinuteDistance(nowMinutes, RolloverHourUtc * 60) <= AvoidRolloverMinutes;
        }

        private bool IsNewsBlackout()
        {
            if (NewsBlackoutMinutes <= 0 || _blackoutMinutesOfDay.Count == 0) return false;
            int nowMinutes = Server.Time.Hour * 60 + Server.Time.Minute;
            for (int i = 0; i < _blackoutMinutesOfDay.Count; i++)
            {
                if (CircularMinuteDistance(nowMinutes, _blackoutMinutesOfDay[i]) <= NewsBlackoutMinutes)
                    return true;
            }
            return false;
        }

        /// <summary>Accepts "7-11,13-16" or "7,8,9". Empty means every hour is allowed.</summary>
        private void ParseTradingHours()
        {
            bool empty = string.IsNullOrWhiteSpace(TradingHoursMask);
            for (int h = 0; h < 24; h++) _hourAllowed[h] = empty;
            if (empty) return;

            string[] parts = TradingHoursMask.Split(new char[] { ',', ';', ' ' },
                StringSplitOptions.RemoveEmptyEntries);

            int opened = 0;
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i].Trim();
                string[] range = part.Split('-');
                int from = 0;
                int to = 0;

                if (range.Length == 1 && int.TryParse(range[0], out from))
                    to = from;
                else if (range.Length == 2 && int.TryParse(range[0], out from) && int.TryParse(range[1], out to))
                    { }
                else
                {
                    Print("Ignored invalid trading hour: '{0}' (expected 9 or 7-11)", part);
                    continue;
                }

                if (from < 0 || from > 23 || to < 0 || to > 23 || to < from)
                {
                    Print("Ignored out-of-range trading hour: '{0}'", part);
                    continue;
                }

                for (int h = from; h <= to; h++)
                {
                    if (!_hourAllowed[h]) opened++;
                    _hourAllowed[h] = true;
                }
            }

            if (opened == 0)
            {
                Print("WARNING: 'Trading hours UTC' opened no hour at all. Falling back to every hour.");
                for (int h = 0; h < 24; h++) _hourAllowed[h] = true;
            }
            else
            {
                Print("Trading hours restricted to {0} hour(s) UTC.", opened);
            }
        }

        private static int CircularMinuteDistance(int a, int b)
        {
            int diff = Math.Abs(a - b);
            return Math.Min(diff, 1440 - diff);
        }

        private void ParseBlackoutTimes()
        {
            _blackoutMinutesOfDay.Clear();
            if (string.IsNullOrWhiteSpace(NewsBlackoutTimes)) return;

            string[] parts = NewsBlackoutTimes.Split(new char[] { ',', ';', ' ' },
                StringSplitOptions.RemoveEmptyEntries);

            for (int i = 0; i < parts.Length; i++)
            {
                string[] hm = parts[i].Trim().Split(':');
                int h, m;
                if (hm.Length == 2 && int.TryParse(hm[0], out h) && int.TryParse(hm[1], out m)
                    && h >= 0 && h < 24 && m >= 0 && m < 60)
                    _blackoutMinutesOfDay.Add(h * 60 + m);
                else
                    Print("Ignored invalid blackout time: '{0}' (expected HH:mm)", parts[i]);
            }
        }

        #endregion

        #region Reporting

        private void UpdateDashboard()
        {
            if (!ShowDashboard || Chart == null) return;

            double dayChange = _dayStartEquity > 0
                ? (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0
                : 0;

            string text = string.Format(
                "GOLD SCALPER PRO v2\n" +
                "regime      {0}\n" +
                "status      {1}\n" +
                "score       {2:F0} / min {3:F0}\n" +
                "spread      {4:F1}p (avg {5:F1}p)\n" +
                "slippage    {6}\n" +
                "open        {7} | pending {8} | today {9}/{10}\n" +
                "day P/L     {11:F2}%\n" +
                "trades      {12} | win {13:F0}% | PF {14} | {15:F2}R avg",
                _regime,
                _lastBlocker ?? "ready",
                _lastQualityScore, MinQualityScore,
                SpreadPips, _spreadAverage,
                _slippageCount > 0 ? (_slippageSumPips / _slippageCount).ToString("F2") + "p avg" : "n/a",
                Positions.FindAll(_label, SymbolName).Length,
                PendingOrders.FindAll(_label, SymbolName).Length,
                _tradesToday, MaxTradesPerDay,
                dayChange,
                _statTrades,
                _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                Pf(_statGrossProfit, _statGrossLoss),
                _statTrades > 0 ? _statSumR / _statTrades : 0);

            // Top-left is where cTrader stacks the indicator legend, so the panel goes right.
            Chart.DrawStaticText("gsp_dashboard", text, VerticalAlignment.Top, HorizontalAlignment.Right, Color.Gold);
        }

        /// <summary>
        /// Printed once, on the first usable bar. Pip size for gold differs between
        /// brokers, so every pip-denominated default has to be checked against reality.
        /// </summary>
        private void PrintCalibration()
        {
            double atr = _atrFast.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0) return;

            double atrPips = PriceToPips(atr);
            double stopPips = Math.Max(atrPips * SlAtrMultiplier,
                Math.Max(MinStopPips, SpreadPips * StopSpreadBufferMult));
            double suggestedMaxSpread = Math.Ceiling(Math.Max(_spreadAverage * 2.5, 1.0));
            double riskAmount = Account.Equity * RiskPercent / 100.0;
            double units = Symbol.PipValue > 0 && stopPips > 0
                ? Symbol.NormalizeVolumeInUnits(riskAmount / (stopPips * Symbol.PipValue), RoundingMode.Down)
                : 0;

            Print("--- CALIBRATION ({0}) ---", SymbolName);
            Print("1 pip = {0} in price | digits {1} | spread now {2:F1} pips (avg {3:F1})",
                Symbol.PipSize, Symbol.Digits, SpreadPips, _spreadAverage);
            Print("ATR({0}) = {1:F1} pips -> stop {2:F1} pips | TP1 {3:F1} | TP2 {4:F1}",
                AtrFastPeriod, atrPips, stopPips, stopPips * Tp1AtR, stopPips * Tp2AtR);
            Print("'Max spread (pips)' is set to {0:F1}. Suggested for this broker: {1:F0}",
                MaxSpreadPips, suggestedMaxSpread);
            if (MaxSpreadPips > suggestedMaxSpread * 3)
                Print("WARNING: 'Max spread' is far too permissive here. Lower it to about {0:F0} pips.",
                    suggestedMaxSpread);
            Print("Risk {0:F2}% of {1:F2} {2} = {3:F2} -> {4} units ({5:F2} lots), broker minimum {6} units",
                RiskPercent, Account.Equity, Account.Asset.Name, riskAmount, units,
                Symbol.VolumeInUnitsToQuantity(units), Symbol.VolumeInUnitsMin);
            if (units < Symbol.VolumeInUnitsMin)
                Print("WARNING: account too small for {0:F2}% risk on a {1:F1} pip stop. Trades will be skipped unless 'Use broker min lot if size too small' is enabled.",
                    RiskPercent, stopPips);
            Print("Session window is UTC. Server time now: {0:HH:mm} UTC, in session: {1}",
                Server.Time, IsInSession());
            Print("--------------------------");
        }

        private void PrintStatistics()
        {
            Print("=== GOLD SCALPER PRO v2 - session summary ===");
            Print("Trades {0} | wins {1} ({2:F1}%)", _statTrades, _statWins,
                _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0);
            Print("Gross profit {0:F2} | gross loss {1:F2} | net {2:F2} {3}",
                _statGrossProfit, _statGrossLoss, _cumulativeNetProfit, Account.Asset.Name);
            Print("Profit factor {0} | average {1:F2}R | max drawdown {2:F2} {3}",
                Pf(_statGrossProfit, _statGrossLoss),
                _statTrades > 0 ? _statSumR / _statTrades : 0,
                _statMaxDrawdown, Account.Asset.Name);
            if (_slippageCount > 0)
                Print("Entry slippage {0:F2} pips on average over {1} market fills",
                    _slippageSumPips / _slippageCount, _slippageCount);

            PrintBreakdown();
        }

        /// <summary>
        /// Where the performance work actually happens: which setup pays, and at which hour.
        /// Built from History and grouped by position id, so a laddered exit counts once.
        /// </summary>
        private void PrintBreakdown()
        {
            Dictionary<int, double> netByPosition = new Dictionary<int, double>();
            Dictionary<int, DateTime> entryByPosition = new Dictionary<int, DateTime>();

            for (int i = 0; i < History.Count; i++)
            {
                HistoricalTrade trade = History[i];
                if (trade.Label != _label || trade.SymbolName != SymbolName) continue;

                if (netByPosition.ContainsKey(trade.PositionId))
                {
                    netByPosition[trade.PositionId] += trade.NetProfit;
                }
                else
                {
                    netByPosition[trade.PositionId] = trade.NetProfit;
                    entryByPosition[trade.PositionId] = trade.EntryTime;
                }
            }

            if (netByPosition.Count == 0) return;

            Dictionary<string, Bucket> bySetup = new Dictionary<string, Bucket>();
            Bucket[] byHour = new Bucket[24];

            foreach (KeyValuePair<int, double> pair in netByPosition)
            {
                string setup = _setupOf.ContainsKey(pair.Key) ? _setupOf[pair.Key] : "UNKNOWN";
                if (!bySetup.ContainsKey(setup)) bySetup[setup] = new Bucket();
                AddToBucket(bySetup[setup], pair.Value);

                int hour = entryByPosition[pair.Key].Hour;
                if (byHour[hour] == null) byHour[hour] = new Bucket();
                AddToBucket(byHour[hour], pair.Value);
            }

            Print("--- by setup ---");
            foreach (KeyValuePair<string, Bucket> pair in bySetup)
            {
                Bucket b = pair.Value;
                Print("{0,-16} {1,4} trades | win {2,3:F0}% | net {3,9:F2} | PF {4}",
                    pair.Key, b.Trades, b.Trades > 0 ? 100.0 * b.Wins / b.Trades : 0,
                    b.Net, Pf(b.GrossProfit, b.GrossLoss));
            }

            Print("--- by hour (UTC) ---");
            for (int h = 0; h < 24; h++)
            {
                Bucket b = byHour[h];
                if (b == null) continue;
                Print("{0:00}h{1,18} trades | win {2,3:F0}% | net {3,9:F2} | PF {4}",
                    h, b.Trades, b.Trades > 0 ? 100.0 * b.Wins / b.Trades : 0,
                    b.Net, Pf(b.GrossProfit, b.GrossLoss));
            }

            Print("Cut the setups and the hours that do not pay, with 'Trading hours UTC' and the mode switches.");
        }

        private static void AddToBucket(Bucket bucket, double net)
        {
            bucket.Trades++;
            bucket.Net += net;
            if (net > 0)
            {
                bucket.Wins++;
                bucket.GrossProfit += net;
            }
            else if (net < 0)
            {
                bucket.GrossLoss += -net;
            }
        }

        private static string Pf(double grossProfit, double grossLoss)
        {
            return grossLoss > 0 ? (grossProfit / grossLoss).ToString("F2") : "n/a";
        }

        #endregion

        #region Helpers

        private double SpreadPips
        {
            get { return Symbol.Spread / Symbol.PipSize; }
        }

        private double PriceToPips(double priceDistance)
        {
            return priceDistance / Symbol.PipSize;
        }

        private double PipsToPrice(double pips)
        {
            return pips * Symbol.PipSize;
        }

        private void LogVerbose(string message)
        {
            if (_log) Print(message);
        }

        private void DrawSignal(TradeType tradeType, string setup)
        {
            if (!DrawOnChart || Chart == null) return;

            string name = string.Format("{0}_{1}_{2}", _label, setup, Bars.OpenTimes.LastValue.Ticks);
            if (tradeType == TradeType.Buy)
                Chart.DrawIcon(name, ChartIconType.UpArrow, Bars.OpenTimes.LastValue,
                    Bars.LowPrices.Last(1), Color.Lime);
            else
                Chart.DrawIcon(name, ChartIconType.DownArrow, Bars.OpenTimes.LastValue,
                    Bars.HighPrices.Last(1), Color.Red);
        }

        #endregion
    }
}
