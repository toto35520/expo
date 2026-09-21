using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum SignalMode
    {
        RegimeTransition,
        Confluence,
        Both
    }

    /// <summary>
    /// GOLD REGIME SHIFT
    ///
    /// Built on the only intraday mechanism that survived the falsification study in
    /// Mesfin (2026), "Structural Limits of OHLCV-Based Intraday Signals in MNQ
    /// Futures", arXiv:2605.04004.
    ///
    /// That study rejected fourteen families of intraday OHLCV signals on five-minute
    /// bars - opening range breakouts, gap fades, volume spikes, liquidity grabs,
    /// expansion continuation - none of which cleared a two-point round-trip friction.
    /// Its two positive controls DID clear it, with t-statistics of 5.83 and 5.15, and
    /// they shared two properties that every rejected signal lacked:
    ///
    ///   1. the entry condition is a REGIME STATE and a REGIME TRANSITION PROBABILITY,
    ///      not a price pattern on a single bar;
    ///   2. the position is held for 12-15 bars, not 1-6.
    ///
    /// This bot implements that mechanism. A Gaussian mixture model is fitted by EM on
    /// a rolling window of bar features, every bar is labelled with its regime, a
    /// Markov transition matrix is estimated from the label sequence, and trades are
    /// taken on regime transitions rather than on candle shapes.
    ///
    /// HONEST LIMITS - read these before trusting anything below.
    ///
    ///   - The positive controls were measured on MNQ (Nasdaq futures). The SAME study
    ///     closed gold intraday research with "D105 - MGC intraday research closed, all
    ///     approaches exhausted". Running this mechanism on gold is a TRANSFER of a
    ///     hypothesis to an instrument where the authors found nothing. It is not a
    ///     replication, and it may well fail.
    ///   - The controls came from a separate research program and the paper does not
    ///     publish the GMM's feature set. The three features used here - normalised
    ///     body, normalised range, volume z-score - are this implementation's choice,
    ///     not theirs.
    ///   - Regime labels from EM are arbitrary, so components are sorted by fitted mean
    ///     return before being named. The paper's "Regime 0/1/2" numbering does not
    ///     transfer and is not assumed.
    ///
    /// In short: the mechanism is evidence-backed, this instantiation of it is not.
    /// Walk-forward it before believing it.
    /// </summary>
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC, AddIndicators = true)]
    public class GoldRegimeShift : Robot
    {
        #region 01 - General

        [Parameter("Instance label", Group = "01 - General", DefaultValue = "GRS")]
        public string InstanceLabel { get; set; }

        [Parameter("Verbose logs", Group = "01 - General", DefaultValue = true)]
        public bool Verbose { get; set; }

        [Parameter("On-chart dashboard", Group = "01 - General", DefaultValue = true)]
        public bool ShowDashboard { get; set; }

        [Parameter("Signal mode", Group = "01 - General", DefaultValue = SignalMode.RegimeTransition)]
        public SignalMode Mode { get; set; }

        [Parameter("Allow shorts", Group = "01 - General", DefaultValue = true)]
        public bool AllowShorts { get; set; }

        #endregion

        #region 02 - Regime model

        [Parameter("Regimes (mixture components)", Group = "02 - Regime", DefaultValue = 3, MinValue = 2, MaxValue = 5)]
        public int RegimeCount { get; set; }

        [Parameter("Fit window (bars)", Group = "02 - Regime", DefaultValue = 600, MinValue = 100, MaxValue = 5000)]
        public int FitWindow { get; set; }

        [Parameter("Refit every (bars)", Group = "02 - Regime", DefaultValue = 50, MinValue = 1, MaxValue = 500)]
        public int RefitEvery { get; set; }

        [Parameter("EM iterations", Group = "02 - Regime", DefaultValue = 60, MinValue = 5, MaxValue = 500)]
        public int EmIterations { get; set; }

        [Parameter("Markov window (bars)", Group = "02 - Regime", DefaultValue = 200, MinValue = 30, MaxValue = 2000)]
        public int MarkovWindow { get; set; }

        [Parameter("Volume z-score window", Group = "02 - Regime", DefaultValue = 50, MinValue = 10, MaxValue = 500)]
        public int VolumeZWindow { get; set; }

        #endregion

        #region 03 - Entry

        [Parameter("Clean-transition lookback (bars)", Group = "03 - Entry", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int CleanTransitionBars { get; set; }

        [Parameter("Min transition probability", Group = "03 - Entry", DefaultValue = 0.15, MinValue = 0, MaxValue = 1, Step = 0.01)]
        public double MinTransitionProbability { get; set; }

        [Parameter("Min volume z-score", Group = "03 - Entry", DefaultValue = 0.5, MinValue = -3, MaxValue = 5, Step = 0.1)]
        public double MinVolumeZ { get; set; }

        [Parameter("Pullback entry = ATR x (0=market)", Group = "03 - Entry", DefaultValue = 0.5, MinValue = 0, MaxValue = 5, Step = 0.1)]
        public double PullbackAtr { get; set; }

        [Parameter("Pullback patience (bars)", Group = "03 - Entry", DefaultValue = 2, MinValue = 1, MaxValue = 20)]
        public int PullbackPatience { get; set; }

        [Parameter("Min bars between trades", Group = "03 - Entry", DefaultValue = 4, MinValue = 0, MaxValue = 100)]
        public int MinBarsBetweenTrades { get; set; }

        #endregion

        #region 04 - Exits

        [Parameter("Hold (bars)", Group = "04 - Exits", DefaultValue = 4, MinValue = 1, MaxValue = 100)]
        public int HoldBars { get; set; }

        [Parameter("Stop = ATR x", Group = "04 - Exits", DefaultValue = 1.5, MinValue = 0.2, MaxValue = 10, Step = 0.1)]
        public double StopAtr { get; set; }

        [Parameter("Take profit = R x (0=off)", Group = "04 - Exits", DefaultValue = 2.0, MinValue = 0, MaxValue = 10, Step = 0.1)]
        public double TakeProfitR { get; set; }

        [Parameter("Exit on regime flip", Group = "04 - Exits", DefaultValue = true)]
        public bool ExitOnRegimeFlip { get; set; }

        [Parameter("Break-even at (R, 0=off)", Group = "04 - Exits", DefaultValue = 1.0, MinValue = 0, MaxValue = 10, Step = 0.1)]
        public double BreakEvenR { get; set; }

        #endregion

        #region 05 - Risk

        [Parameter("Risk per trade (% equity)", Group = "05 - Risk", DefaultValue = 0.5, MinValue = 0.05, MaxValue = 5, Step = 0.05)]
        public double RiskPercent { get; set; }

        [Parameter("Max trades per day", Group = "05 - Risk", DefaultValue = 6, MinValue = 1, MaxValue = 50)]
        public int MaxTradesPerDay { get; set; }

        [Parameter("Daily loss cap (% equity, 0=off)", Group = "05 - Risk", DefaultValue = 3.0, MinValue = 0, MaxValue = 50, Step = 0.5)]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Max spread (pips)", Group = "05 - Risk", DefaultValue = 5.0, MinValue = 0.5, Step = 0.5)]
        public double MaxSpreadPips { get; set; }

        [Parameter("ATR period", Group = "05 - Risk", DefaultValue = 14, MinValue = 2, MaxValue = 100)]
        public int AtrPeriod { get; set; }

        #endregion

        #region 06 - Session (UTC)

        [Parameter("Session start (UTC hour)", Group = "06 - Session", DefaultValue = 7.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionStart { get; set; }

        [Parameter("Session end (UTC hour)", Group = "06 - Session", DefaultValue = 16.0, MinValue = 0, MaxValue = 23.99, Step = 0.25)]
        public double SessionEnd { get; set; }

        [Parameter("Flatten at session end", Group = "06 - Session", DefaultValue = true)]
        public bool FlattenAtSessionEnd { get; set; }

        [Parameter("Trade on Friday", Group = "06 - Session", DefaultValue = true)]
        public bool TradeFriday { get; set; }

        #endregion

        #region State

        private class GaussianMixture
        {
            public int K;
            public int D;
            public double[] Weights;
            public double[][] Means;
            public double[][] Variances;
            public bool Fitted;
        }

        private class TradeState
        {
            public double RiskPips;
            public double RiskMoney;
            public int OpenBarIndex;
            public bool BreakEvenDone;
            public string Setup;
        }

        private const int FeatureCount = 3;

        private readonly List<double[]> _features = new List<double[]>();
        private readonly List<int> _labels = new List<int>();
        private readonly Dictionary<int, TradeState> _states = new Dictionary<int, TradeState>();
        private readonly List<double> _tradeRs = new List<double>();

        private GaussianMixture _model;
        private int[] _regimeByRank;      // rank 0 = most bearish fitted mean, K-1 = most bullish
        private int _activeRegime = -1;   // component with the widest fitted range
        private AverageTrueRange _atr;

        private string _label;
        private bool _log;
        private int _processedBars;
        private int _barsSinceRefit;

        private int _armedDirection;      // +1 long, -1 short, 0 none
        private string _armedSetup;
        private double _armedReference;
        private int _armedBarIndex = int.MinValue;

        private int _lastEntryBarIndex = int.MinValue;
        private DateTime _currentDay;
        private double _dayStartEquity;
        private int _tradesToday;
        private bool _dayLocked;
        private string _status = "starting";

        private DateTime _firstTradingDay = DateTime.MinValue;
        private int _tradingDays;
        private int _signalsArmed;
        private int _statTrades;
        private int _statWins;
        private double _statNet;
        private double _statGrossProfit;
        private double _statGrossLoss;

        #endregion

        #region Lifecycle

        protected override void OnStart()
        {
            _label = string.IsNullOrWhiteSpace(InstanceLabel) ? "GRS" : InstanceLabel.Trim();
            _log = Verbose && RunningMode != RunningMode.Optimization;
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);

            RebuildFeatureHistory();
            StartNewDay();
            Positions.Closed += OnPositionClosed;

            Print("=== GOLD REGIME SHIFT ===");
            Print("Mechanism from the positive controls in Mesfin (2026), arXiv:2605.04004");
            Print("Symbol {0} | timeframe {1} | hold {2} bars | {3} regimes",
                SymbolName, TimeFrame, HoldBars, RegimeCount);
            Print("PipSize {0} | spread now {1:F1} pips | equity {2:F2} {3}",
                Symbol.PipSize, SpreadPips, Account.Equity, Account.Asset.Name);
            Print("CALIBRATION TARGET: the validated signals fired 0.31 (London Signal B) to "
                + "0.72 (RTH Confluence) trades per day. Tune regime count and thresholds until "
                + "this bot's rate lands in that band BEFORE looking at any P&L - frequency is "
                + "the one target that does not overfit the outcome.");
            Print("NOTE: the controls this is built on were measured on Nasdaq futures. "
                + "The same study found nothing on gold intraday. Walk-forward before trusting it.");

            if (TimeFrame != TimeFrame.Minute15 && TimeFrame != TimeFrame.Minute5)
                Print("WARNING: the validated holds were 60-75 minutes. On {0}, a {1}-bar hold is {2}. "
                    + "M15 with a 4-bar hold reproduces the published structure.",
                    TimeFrame, HoldBars, "probably not that");
        }

        protected override void OnStop()
        {
            Positions.Closed -= OnPositionClosed;
            PrintStatistics();
        }

        protected override void OnTick()
        {
            RollDayIfNeeded();
            // The pullback trigger is a price level, so it has to be watched on ticks:
            // checking once per bar open misses a retrace that happens and reverses
            // inside the bar.
            TryFillArmedSignal();
            ManageOpenPositions();
            EnforceDailyGuard();
        }

        protected override void OnBar()
        {
            RollDayIfNeeded();
            AppendClosedBars();

            if (_features.Count < Math.Max(FitWindow / 2, 120))
            {
                _status = string.Format("warming up ({0} bars)", _features.Count);
                UpdateDashboard();
                return;
            }

            MaybeRefit();
            if (_model == null || !_model.Fitted)
            {
                _status = "model not fitted";
                UpdateDashboard();
                return;
            }

            RelabelRecent();

            if (FlattenAtSessionEnd && !InSession())
            {
                CloseAll("session end");
                DisarmSignal("session end");
                _status = "outside session";
                UpdateDashboard();
                return;
            }

            CheckHoldExit();
            TryFillArmedSignal();
            LookForSignal();
            UpdateDashboard();
        }

        #endregion

        #region Features and labels

        private void RebuildFeatureHistory()
        {
            _features.Clear();
            _labels.Clear();
            _processedBars = 0;
            AppendClosedBars();
        }

        private void AppendClosedBars()
        {
            int lastClosed = Bars.Count - 2;
            int start = Math.Max(_processedBars, Math.Max(VolumeZWindow, AtrPeriod) + 1);

            for (int i = start; i <= lastClosed; i++)
            {
                double[] f = BuildFeature(i);
                if (f == null) continue;
                _features.Add(f);
                _labels.Add(-1);
            }

            int cap = Math.Max(FitWindow, MarkovWindow) * 3;
            while (_features.Count > cap)
            {
                _features.RemoveAt(0);
                _labels.RemoveAt(0);
            }

            _processedBars = lastClosed + 1;
        }

        /// <summary>
        /// Three features, each scale-free so the mixture is comparable across
        /// volatility regimes: directional body, activity range, and relative volume.
        /// </summary>
        private double[] BuildFeature(int index)
        {
            if (index < 1 || index >= Bars.Count) return null;

            double open = Bars.OpenPrices[index];
            double high = Bars.HighPrices[index];
            double low = Bars.LowPrices[index];
            double close = Bars.ClosePrices[index];
            if (open <= 0 || close <= 0) return null;

            // A local range scale, independent of the ATR indicator's own warm-up.
            double scale = 0;
            int n = 0;
            for (int i = Math.Max(1, index - AtrPeriod + 1); i <= index; i++)
            {
                scale += Bars.HighPrices[i] - Bars.LowPrices[i];
                n++;
            }
            scale = n > 0 ? scale / n : 0;
            if (scale <= 0) return null;

            double body = (close - open) / scale;
            double range = (high - low) / scale;

            double volumeZ = 0;
            if (index >= VolumeZWindow)
            {
                double mean = 0;
                for (int i = index - VolumeZWindow + 1; i <= index; i++) mean += Bars.TickVolumes[i];
                mean /= VolumeZWindow;

                double variance = 0;
                for (int i = index - VolumeZWindow + 1; i <= index; i++)
                {
                    double d = Bars.TickVolumes[i] - mean;
                    variance += d * d;
                }
                double sd = Math.Sqrt(variance / Math.Max(1, VolumeZWindow - 1));
                volumeZ = sd > 0 ? (Bars.TickVolumes[index] - mean) / sd : 0;
            }

            return new double[] { body, range, volumeZ };
        }

        private void RelabelRecent()
        {
            int from = Math.Max(0, _features.Count - Math.Max(MarkovWindow, HoldBars + CleanTransitionBars + 5) - 5);
            for (int i = from; i < _features.Count; i++)
                _labels[i] = Classify(_features[i]);
        }

        #endregion

        #region Gaussian mixture

        private void MaybeRefit()
        {
            _barsSinceRefit++;
            if (_model != null && _model.Fitted && _barsSinceRefit < RefitEvery) return;

            _barsSinceRefit = 0;
            Fit();
        }

        /// <summary>
        /// Diagonal-covariance Gaussian mixture fitted by expectation-maximisation.
        /// Initialisation is deterministic - the window is sorted by directional body
        /// and split into equal quantile groups - so the same data always produces the
        /// same model. A random seed would make backtests irreproducible.
        /// </summary>
        private void Fit()
        {
            int n = Math.Min(FitWindow, _features.Count);
            if (n < RegimeCount * 20) return;

            double[][] data = new double[n][];
            for (int i = 0; i < n; i++) data[i] = _features[_features.Count - n + i];

            GaussianMixture m = new GaussianMixture
            {
                K = RegimeCount,
                D = FeatureCount,
                Weights = new double[RegimeCount],
                Means = new double[RegimeCount][],
                Variances = new double[RegimeCount][]
            };

            int[] order = new int[n];
            for (int i = 0; i < n; i++) order[i] = i;
            Array.Sort(order, delegate(int a, int b) { return data[a][0].CompareTo(data[b][0]); });

            for (int k = 0; k < m.K; k++)
            {
                int lo = k * n / m.K;
                int hi = (k + 1) * n / m.K;
                if (hi <= lo) hi = lo + 1;

                m.Weights[k] = 1.0 / m.K;
                m.Means[k] = new double[m.D];
                m.Variances[k] = new double[m.D];

                for (int d = 0; d < m.D; d++)
                {
                    double mean = 0;
                    for (int i = lo; i < hi; i++) mean += data[order[i]][d];
                    mean /= (hi - lo);

                    double variance = 0;
                    for (int i = lo; i < hi; i++)
                    {
                        double diff = data[order[i]][d] - mean;
                        variance += diff * diff;
                    }
                    variance /= Math.Max(1, hi - lo - 1);

                    m.Means[k][d] = mean;
                    m.Variances[k][d] = Math.Max(variance, 1e-6);
                }
            }

            double[][] resp = new double[n][];
            for (int i = 0; i < n; i++) resp[i] = new double[m.K];

            for (int iteration = 0; iteration < EmIterations; iteration++)
            {
                // E-step, in log space so tiny densities do not underflow to zero.
                for (int i = 0; i < n; i++)
                {
                    double max = double.NegativeInfinity;
                    for (int k = 0; k < m.K; k++)
                    {
                        double lp = Math.Log(Math.Max(m.Weights[k], 1e-12)) + LogDensity(data[i], m, k);
                        resp[i][k] = lp;
                        if (lp > max) max = lp;
                    }

                    double sum = 0;
                    for (int k = 0; k < m.K; k++)
                    {
                        resp[i][k] = Math.Exp(resp[i][k] - max);
                        sum += resp[i][k];
                    }
                    if (sum <= 0) sum = 1;
                    for (int k = 0; k < m.K; k++) resp[i][k] /= sum;
                }

                // M-step.
                for (int k = 0; k < m.K; k++)
                {
                    double nk = 0;
                    for (int i = 0; i < n; i++) nk += resp[i][k];
                    if (nk < 1e-9) nk = 1e-9;

                    m.Weights[k] = nk / n;

                    for (int d = 0; d < m.D; d++)
                    {
                        double mean = 0;
                        for (int i = 0; i < n; i++) mean += resp[i][k] * data[i][d];
                        mean /= nk;

                        double variance = 0;
                        for (int i = 0; i < n; i++)
                        {
                            double diff = data[i][d] - mean;
                            variance += resp[i][k] * diff * diff;
                        }
                        variance /= nk;

                        m.Means[k][d] = mean;
                        m.Variances[k][d] = Math.Max(variance, 1e-6);
                    }
                }
            }

            m.Fitted = true;
            _model = m;
            RankRegimes();
        }

        private static double LogDensity(double[] x, GaussianMixture m, int k)
        {
            double logp = 0;
            for (int d = 0; d < m.D; d++)
            {
                double variance = m.Variances[k][d];
                double diff = x[d] - m.Means[k][d];
                logp += -0.5 * (Math.Log(2.0 * Math.PI * variance) + diff * diff / variance);
            }
            return logp;
        }

        /// <summary>
        /// EM component indices are arbitrary, so identity is assigned from the fitted
        /// parameters: rank by mean directional body, and call "active" whichever
        /// component has the widest mean range.
        /// </summary>
        private void RankRegimes()
        {
            int k = _model.K;
            _regimeByRank = new int[k];
            for (int i = 0; i < k; i++) _regimeByRank[i] = i;

            GaussianMixture m = _model;
            Array.Sort(_regimeByRank, delegate(int a, int b)
            {
                return m.Means[a][0].CompareTo(m.Means[b][0]);
            });

            _activeRegime = 0;
            for (int i = 1; i < k; i++)
                if (m.Means[i][1] > m.Means[_activeRegime][1]) _activeRegime = i;
        }

        private int Classify(double[] x)
        {
            if (_model == null || !_model.Fitted) return -1;

            int best = 0;
            double bestScore = double.NegativeInfinity;
            for (int k = 0; k < _model.K; k++)
            {
                double score = Math.Log(Math.Max(_model.Weights[k], 1e-12)) + LogDensity(x, _model, k);
                if (score > bestScore)
                {
                    bestScore = score;
                    best = k;
                }
            }
            return best;
        }

        private int BearRegime { get { return _regimeByRank[0]; } }
        private int BullRegime { get { return _regimeByRank[_regimeByRank.Length - 1]; } }

        /// <summary>Empirical P(next label = to | current label = from) over the Markov window.</summary>
        private double TransitionProbability(int from, int to)
        {
            int start = Math.Max(1, _labels.Count - MarkovWindow);
            int fromCount = 0;
            int toCount = 0;

            for (int i = start; i < _labels.Count; i++)
            {
                if (_labels[i - 1] != from) continue;
                fromCount++;
                if (_labels[i] == to) toCount++;
            }

            return fromCount > 0 ? (double)toCount / fromCount : 0;
        }

        #endregion

        #region Signals

        private void LookForSignal()
        {
            if (_armedDirection != 0) return;

            string blocker = EntryBlocker();
            if (blocker != null)
            {
                _status = blocker;
                return;
            }

            int last = _labels.Count - 1;
            if (last < CleanTransitionBars + 2) return;

            int current = _labels[last];
            int previous = _labels[last - 1];
            _status = string.Format("watching (regime {0})", RegimeName(current));

            bool wantTransition = Mode == SignalMode.RegimeTransition || Mode == SignalMode.Both;
            bool wantConfluence = Mode == SignalMode.Confluence || Mode == SignalMode.Both;

            // --- Regime transition: a clean flip from one extreme regime to the other.
            if (wantTransition)
            {
                if (current == BullRegime && previous == BearRegime && IsCleanRunUpTo(last - 1, BearRegime))
                {
                    Arm(1, "TRANSITION");
                    return;
                }
                if (AllowShorts && current == BearRegime && previous == BullRegime && IsCleanRunUpTo(last - 1, BullRegime))
                {
                    Arm(-1, "TRANSITION");
                    return;
                }
            }

            // --- Confluence: active regime, a real probability of rotating into the
            //     directional regime, and volume confirming participation.
            if (wantConfluence && current == _activeRegime)
            {
                double volumeZ = _features[last][2];
                if (volumeZ < MinVolumeZ) return;

                double toBull = TransitionProbability(_activeRegime, BullRegime);
                double toBear = TransitionProbability(_activeRegime, BearRegime);

                if (toBull >= MinTransitionProbability && toBull > toBear)
                    Arm(1, "CONFLUENCE");
                else if (AllowShorts && toBear >= MinTransitionProbability && toBear > toBull)
                    Arm(-1, "CONFLUENCE");
            }
        }

        private bool IsCleanRunUpTo(int index, int regime)
        {
            for (int i = index; i > index - CleanTransitionBars && i >= 0; i--)
                if (_labels[i] != regime) return false;
            return true;
        }

        private void Arm(int direction, string setup)
        {
            _signalsArmed++;
            _armedDirection = direction;
            _armedSetup = setup;
            _armedReference = Bars.ClosePrices.Last(1);
            _armedBarIndex = Bars.Count - 1;

            if (PullbackAtr <= 0)
            {
                TryFillArmedSignal();
                return;
            }

            LogVerbose(string.Format("{0} armed {1}, waiting for a {2:F1} x ATR pullback from {3}",
                setup, direction > 0 ? "long" : "short", PullbackAtr, _armedReference));
        }

        private void DisarmSignal(string reason)
        {
            if (_armedDirection == 0) return;
            LogVerbose("signal disarmed: " + reason);
            _armedDirection = 0;
            _armedSetup = null;
            _armedBarIndex = int.MinValue;
        }

        /// <summary>
        /// The study's working signal entered on a pullback from the signal bar's close
        /// rather than at market. Waiting is tracked internally rather than with a
        /// resting order, so nothing can be left working on the server.
        /// </summary>
        private void TryFillArmedSignal()
        {
            if (_armedDirection == 0) return;

            if (Bars.Count - 1 - _armedBarIndex > PullbackPatience)
            {
                DisarmSignal("pullback never came");
                return;
            }

            if (EntryBlocker() != null) return;

            double atr = _atr.Result.Last(1);
            if (double.IsNaN(atr) || atr <= 0) return;

            double trigger = _armedDirection > 0
                ? _armedReference - atr * PullbackAtr
                : _armedReference + atr * PullbackAtr;

            if (PullbackAtr > 0)
            {
                bool reached = _armedDirection > 0 ? Symbol.Ask <= trigger : Symbol.Bid >= trigger;
                if (!reached) return;
            }

            OpenTrade(_armedDirection > 0 ? TradeType.Buy : TradeType.Sell, _armedSetup, atr);
            _armedDirection = 0;
            _armedSetup = null;
            _armedBarIndex = int.MinValue;
        }

        private string RegimeName(int regime)
        {
            if (_regimeByRank == null || regime < 0) return "?";
            if (regime == BullRegime) return "BULL";
            if (regime == BearRegime) return "BEAR";
            if (regime == _activeRegime) return "ACTIVE";
            return "NEUTRAL";
        }

        #endregion

        #region Trading

        private void OpenTrade(TradeType tradeType, string setup, double atr)
        {
            double stopPips = Math.Round(PriceToPips(atr * StopAtr), 1);
            double floor = Math.Max(1.0, SpreadPips * 2.0);
            if (stopPips < floor) stopPips = floor;

            double? targetPips = TakeProfitR > 0 ? (double?)Math.Round(stopPips * TakeProfitR, 1) : null;

            if (Symbol.PipValue <= 0) return;
            double volume = Symbol.NormalizeVolumeInUnits(
                Account.Equity * RiskPercent / 100.0 / (stopPips * Symbol.PipValue), RoundingMode.Down);

            if (volume < Symbol.VolumeInUnitsMin)
            {
                LogVerbose(string.Format("skip: size below broker minimum for a {0:F1} pip stop", stopPips));
                return;
            }
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;

            TradeResult result = ExecuteMarketOrder(tradeType, SymbolName, volume, _label, stopPips, targetPips);
            if (!result.IsSuccessful || result.Position == null)
            {
                Print("Order rejected ({0}): {1}", setup, result.Error);
                return;
            }

            _tradesToday++;
            _lastEntryBarIndex = Bars.Count - 1;
            _states[result.Position.Id] = new TradeState
            {
                RiskPips = stopPips,
                RiskMoney = stopPips * Symbol.PipValue * volume,
                OpenBarIndex = Bars.Count - 1,
                BreakEvenDone = false,
                Setup = setup
            };

            Print("{0} {1} | {2} | vol {3} | SL {4:F1}p | TP {5} | hold {6} bars | spread {7:F1}p",
                tradeType, SymbolName, setup, volume, stopPips,
                targetPips.HasValue ? targetPips.Value.ToString("F1") + "p" : "none",
                HoldBars, SpreadPips);
        }

        /// <summary>The time exit IS the strategy: the controls held 12-15 bars and exited on count.</summary>
        private void CheckHoldExit()
        {
            Position[] positions = Positions.FindAll(_label, SymbolName);
            int last = _labels.Count - 1;

            for (int i = 0; i < positions.Length; i++)
            {
                Position position = positions[i];
                TradeState state = GetState(position);
                if (state == null) continue;

                if (Bars.Count - 1 - state.OpenBarIndex >= HoldBars)
                {
                    ClosePositionSafe(position, string.Format("hold {0} bars reached", HoldBars));
                    continue;
                }

                if (ExitOnRegimeFlip && last >= 0)
                {
                    int current = _labels[last];
                    bool against = position.TradeType == TradeType.Buy
                        ? current == BearRegime
                        : current == BullRegime;
                    if (against) ClosePositionSafe(position, "regime flipped against the trade");
                }
            }
        }

        private void ManageOpenPositions()
        {
            if (BreakEvenR <= 0) return;

            Position[] positions = Positions.FindAll(_label, SymbolName);
            for (int i = 0; i < positions.Length; i++)
            {
                Position position = positions[i];
                TradeState state = GetState(position);
                if (state == null || state.RiskPips <= 0 || state.BreakEvenDone) continue;

                if (position.Pips / state.RiskPips < BreakEvenR) continue;

                double lockPips = Math.Max(1.0, SpreadPips);
                double target = position.TradeType == TradeType.Buy
                    ? position.EntryPrice + PipsToPrice(lockPips)
                    : position.EntryPrice - PipsToPrice(lockPips);
                target = Math.Round(target, Symbol.Digits);

                if (position.TradeType == TradeType.Buy && target >= Symbol.Bid) continue;
                if (position.TradeType == TradeType.Sell && target <= Symbol.Ask) continue;

                if (ModifyPosition(position, target, position.TakeProfit, ProtectionType.Absolute).IsSuccessful)
                    state.BreakEvenDone = true;
            }
        }

        private TradeState GetState(Position position)
        {
            TradeState state;
            if (_states.TryGetValue(position.Id, out state)) return state;

            double riskPips = position.StopLoss.HasValue
                ? PriceToPips(Math.Abs(position.EntryPrice - position.StopLoss.Value))
                : 0;

            state = new TradeState
            {
                RiskPips = riskPips,
                RiskMoney = riskPips * Symbol.PipValue * position.VolumeInUnits,
                OpenBarIndex = Bars.Count - 1,
                BreakEvenDone = true,
                Setup = "ADOPTED"
            };
            _states[position.Id] = state;
            return state;
        }

        private void ClosePositionSafe(Position position, string reason)
        {
            TradeResult result = ClosePosition(position);
            if (result.IsSuccessful) LogVerbose(string.Format("closed #{0}: {1}", position.Id, reason));
            else Print("Close failed on #{0} ({1}): {2}", position.Id, reason, result.Error);
        }

        private void CloseAll(string reason)
        {
            Position[] positions = Positions.FindAll(_label, SymbolName);
            for (int i = 0; i < positions.Length; i++)
                ClosePositionSafe(positions[i], reason);
        }

        private double RealizedForPosition(int positionId, double fallback)
        {
            double total = 0;
            bool found = false;
            int stop = Math.Max(0, History.Count - 200);

            for (int i = History.Count - 1; i >= stop; i--)
            {
                if (History[i].PositionId != positionId) continue;
                total += History[i].NetProfit;
                found = true;
            }
            return found ? total : fallback;
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            Position position = args.Position;
            if (position.Label != _label || position.SymbolName != SymbolName) return;

            TradeState state;
            double riskMoney = _states.TryGetValue(position.Id, out state) ? state.RiskMoney : 0;
            _states.Remove(position.Id);

            double net = RealizedForPosition(position.Id, position.NetProfit);
            _statTrades++;
            _statNet += net;
            if (net > 0) { _statWins++; _statGrossProfit += net; }
            else if (net < 0) _statGrossLoss += -net;
            if (riskMoney > 0) _tradeRs.Add(net / riskMoney);

            LogVerbose(string.Format("closed #{0} {1:F2} {2} ({3:F2}R)",
                position.Id, net, Account.Asset.Name, riskMoney > 0 ? net / riskMoney : 0));
        }

        #endregion

        #region Guards

        private string EntryBlocker()
        {
            if (_dayLocked) return "daily loss cap reached";
            if (_tradesToday >= MaxTradesPerDay) return "max trades per day";
            if (Positions.FindAll(_label, SymbolName).Length > 0) return "in position";
            if (!InSession()) return "outside session";
            if (SpreadPips > MaxSpreadPips)
                return string.Format("spread {0:F1}p > {1:F1}p", SpreadPips, MaxSpreadPips);
            if (MinBarsBetweenTrades > 0 && _lastEntryBarIndex != int.MinValue
                && Bars.Count - 1 - _lastEntryBarIndex < MinBarsBetweenTrades)
                return "entry spacing";
            return null;
        }

        private void EnforceDailyGuard()
        {
            if (_dayStartEquity <= 0 || MaxDailyLossPercent <= 0) return;

            if (_dayLocked)
            {
                if (Positions.FindAll(_label, SymbolName).Length > 0) CloseAll("daily cap - retry");
                return;
            }

            double change = (Account.Equity - _dayStartEquity) / _dayStartEquity * 100.0;
            if (change <= -MaxDailyLossPercent)
            {
                _dayLocked = true;
                Print("DAILY LOSS CAP hit ({0:F2}%) - flat and idle until tomorrow", change);
                CloseAll("daily loss cap");
                DisarmSignal("daily loss cap");
            }
        }

        private void RollDayIfNeeded()
        {
            if (Server.Time.Date != _currentDay) StartNewDay();
        }

        private void StartNewDay()
        {
            if (_currentDay != default(DateTime) && Server.Time.DayOfWeek != DayOfWeek.Saturday
                && Server.Time.DayOfWeek != DayOfWeek.Sunday)
                _tradingDays++;
            if (_firstTradingDay == DateTime.MinValue) _firstTradingDay = Server.Time.Date;

            _currentDay = Server.Time.Date;
            _dayStartEquity = Account.Equity;
            _tradesToday = 0;
            _dayLocked = false;
            _lastEntryBarIndex = int.MinValue;
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

        #region Reporting

        private void PrintStatistics()
        {
            Print("=== GOLD REGIME SHIFT - session summary ===");
            Print("Trades {0} | wins {1} ({2:F1}%) | net {3:F2} {4}",
                _statTrades, _statWins, _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet, Account.Asset.Name);
            Print("Profit factor {0}",
                _statGrossLoss > 0 ? (_statGrossProfit / _statGrossLoss).ToString("F2") : "n/a");

            int days = Math.Max(1, _tradingDays);
            double perDay = (double)_statTrades / days;
            Print("Frequency: {0} trades over {1} trading days = {2:F2} per day ({3} signals armed)",
                _statTrades, days, perDay, _signalsArmed);
            if (perDay > 1.0)
                Print("TOO FREQUENT: the validated signals fired 0.31-0.72 per day. Raise the regime "
                    + "count, the transition probability floor or the volume z floor until the rate "
                    + "matches, then re-read the expectancy.");
            else if (perDay < 0.15 && _statTrades > 0)
                Print("TOO RARE: below the validated band, and too few trades to conclude anything.");

            if (_tradeRs.Count == 0) return;

            double sumWin = 0, sumLoss = 0, sum = 0, worst = 0;
            int wins = 0, losses = 0;
            for (int i = 0; i < _tradeRs.Count; i++)
            {
                double r = _tradeRs[i];
                sum += r;
                if (r > 0) { wins++; sumWin += r; } else { losses++; sumLoss += -r; }
                if (r < worst) worst = r;
            }

            double avgWin = wins > 0 ? sumWin / wins : 0;
            double avgLoss = losses > 0 ? sumLoss / losses : 0;
            double expectancy = sum / _tradeRs.Count;
            double breakEven = (avgWin + avgLoss) > 0 ? 100.0 * avgLoss / (avgWin + avgLoss) : 0;

            Print("Average win {0:F2}R | average loss {1:F2}R | expectancy {2:F3}R | worst {3:F2}R",
                avgWin, avgLoss, expectancy, worst);
            Print("Win rate {0:F1}% | break-even win rate needed {1:F1}%",
                100.0 * wins / _tradeRs.Count, breakEven);

            if (expectancy <= 0)
                Print("VERDICT: negative expectancy. This configuration loses money over time.");
            else if (_tradeRs.Count < 100)
                Print("VERDICT: positive so far, but {0} trades is not evidence yet.", _tradeRs.Count);
            else
                Print("VERDICT: positive over {0} trades. Check it holds out of sample.", _tradeRs.Count);
        }

        private void UpdateDashboard()
        {
            if (!ShowDashboard || Chart == null) return;

            int last = _labels.Count - 1;
            int current = last >= 0 ? _labels[last] : -1;
            Position[] positions = Positions.FindAll(_label, SymbolName);

            string text = string.Format(
                "GOLD REGIME SHIFT\n" +
                "regime      {0}\n" +
                "P(->BULL)   {1:F2}   P(->BEAR)   {2:F2}\n" +
                "volume z    {3:+0.00;-0.00}\n" +
                "status      {4}\n" +
                "armed       {5}\n" +
                "position    {6} | today {7}/{8}\n" +
                "trades      {9} | win {10:F0}% | net {11:F2}\n" +
                "frequency   {12:F2}/day (target 0.31-0.72)",
                RegimeName(current),
                current >= 0 ? TransitionProbability(current, BullRegime) : 0,
                current >= 0 ? TransitionProbability(current, BearRegime) : 0,
                last >= 0 ? _features[last][2] : 0,
                _status,
                _armedDirection == 0 ? "-" : (_armedSetup + (_armedDirection > 0 ? " long" : " short")),
                positions.Length == 0 ? "flat" : positions[0].TradeType.ToString(),
                _tradesToday, MaxTradesPerDay,
                _statTrades,
                _statTrades > 0 ? 100.0 * _statWins / _statTrades : 0,
                _statNet,
                (double)_statTrades / Math.Max(1, _tradingDays));

            Chart.DrawStaticText("grs_dashboard", text, VerticalAlignment.Top, HorizontalAlignment.Right, Color.Gold);
        }

        #endregion

        #region Helpers

        private double SpreadPips { get { return Symbol.Spread / Symbol.PipSize; } }

        private double PriceToPips(double priceDistance) { return priceDistance / Symbol.PipSize; }

        private double PipsToPrice(double pips) { return pips * Symbol.PipSize; }

        private void LogVerbose(string message) { if (_log) Print(message); }

        #endregion
    }
}
