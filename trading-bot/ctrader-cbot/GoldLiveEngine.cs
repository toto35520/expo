// =====================================================================================
//  GoldLiveEngine v1.0 — cBot cTrader Automate pour XAUUSD (M1 / M5)
//
//  Un seul fichier, deux usages :
//    1. cTrader Automate : le cBot "GoldLiveEngine" (bas du fichier).
//    2. Outil de recherche hors ligne (dossier research/) : le MÊME moteur est compilé
//       avec le symbole GLE_OFFLINE et rejoué sur l'historique. Aucune divergence possible
//       entre la logique backtestée et la logique live.
//
//  Pipeline : MarketData -> RegimeDetector -> Setups -> ConfluenceEngine (score)
//             -> RiskEngine -> Execution (adaptateur) -> ExitEngine -> SafetyEngine
//
//  Règles anti look-ahead : toutes les décisions d'entrée utilisent uniquement des bougies
//  CLÔTURÉES. Les swings ne sont confirmés que S bougies après leur formation. Le contexte
//  M15 n'utilise que des bougies M15 terminées.
// =====================================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace GoldLive.Core
{
    public enum Side { Buy = 1, Sell = -1 }

    public enum Regime { TrendUp, TrendDown, Range, Breakout, HighVolatility, LowVolatility, Transition }

    public enum SetupType { LiquiditySweep, BreakoutContinuation, TrendPullback, MomentumExpansion }

    internal static class Num
    {
        public static bool Ok(double x) { return !double.IsNaN(x) && !double.IsInfinity(x); }

        public static string F(double x, int digits = 2)
        {
            return Ok(x) ? x.ToString("F" + digits, CultureInfo.InvariantCulture) : "NaN";
        }

        public static int Dir(Side s) { return (int)s; }

        public static string Name(Side s) { return s == Side.Buy ? "BUY" : "SELL"; }
    }

    // =================================================================================
    //  CONFIGURATION
    // =================================================================================
    public sealed class EngineConfig
    {
        // --- Données / indicateurs (NE PAS optimiser : valeurs standard) ---
        public int SignalTfMinutes = 5;
        public int EmaFast = 20, EmaMid = 50, EmaSlow = 200;
        public int AtrPeriod = 14, AtrBasePeriod = 200, AdxPeriod = 14;
        public int HtfMinutes = 15, HtfEmaPeriod = 50;
        public int SwingStrength = 2;
        public int SlopeLookback = 10;

        // --- RISK ---
        public double RiskPercent = 0.35;
        public double MaxOpenRiskPercent = 1.0;

        // --- SESSIONS ---
        public bool TradeAsia = false, TradeLondon = true, TradeNewYork = true;
        public bool AvoidRollover = true, AvoidFridayClose = true;
        public bool FlattenBeforeWeekend = true;
        public int ReopenSkipBars = 6;

        // --- REGIME ---
        public double AdxTrend = 22, AdxRange = 18;
        public double HighVolRatio = 2.2, LowVolRatio = 0.65;
        public double MinSlopeAtr = 0.3;

        // --- SETUPS ---
        public bool EnableSweep = true, EnableBreakout = true, EnablePullback = true, EnableMomentum = true;
        public int StructureLookback = 20;
        public int BoxBars = 12;
        public double BoxMaxAtr = 3.0;
        public int PullbackBars = 8;
        public double ExpansionAtr = 1.6;
        public double MaxExtensionAtr = 2.5;
        public int MinScore = 55;
        public bool UseHtfScore = true; // désactivable pour les tests d'ablation

        // --- EXECUTION ---
        public double MaxSpreadAtr = 0.20;
        public double MaxSpreadPips = 0;  // 0 = désactivé
        public double MaxSlippageAtr = 0.15;
        public double SlBufferAtr = 0.25, MinSlAtr = 0.8, MaxSlAtr = 3.5;
        public int CooldownBars = 3, MaxTradesPerDay = 12, MaxConcurrentPositions = 1;

        // --- EXITS ---
        public double Tp1R = 0.8, Tp1ClosePct = 40;
        public double Tp2R = 1.5, Tp2ClosePct = 30;
        public double Tp3R = 3.0;
        public double StopAfterTp1R = -0.3, StopAfterTp2R = 0.4;
        public double TrailStartR = 1.8, TrailAtr = 2.0;
        public int MaxBarsInTrade = 36;

        // --- SAFETY ---
        public double MaxDailyLossPercent = 2.0, MaxWeeklyLossPercent = 4.0;
        public int MaxConsecutiveLosses = 5;
        public bool EmergencyStop = false;
        public int MaxExecutionFailures = 3;

        // Constantes de protection (volontairement non exposées)
        public const double NewsSpikeAtr = 4.0;
        public const int NewsPauseBars = 6;

        public EngineConfig Clone() { return (EngineConfig)MemberwiseClone(); }

        public int WarmupBars
        {
            get
            {
                int htfRatio = Math.Max(1, HtfMinutes / Math.Max(1, SignalTfMinutes));
                int need = Math.Max(EmaSlow * 3, AtrBasePeriod * 2);
                need = Math.Max(need, HtfEmaPeriod * 3 * htfRatio);
                return need + 10;
            }
        }

        public List<string> Validate()
        {
            var e = new List<string>();
            Action<bool, string> req = (ok, msg) => { if (!ok) e.Add(msg); };
            req(SignalTfMinutes >= 1 && SignalTfMinutes <= 15, "Timeframe du graphique : M1 à M15 attendu");
            req(HtfMinutes % SignalTfMinutes == 0 && HtfMinutes > SignalTfMinutes, "HTF doit être un multiple du timeframe");
            req(RiskPercent > 0 && RiskPercent <= 2, "RiskPercent doit être dans ]0 ; 2]");
            req(MaxOpenRiskPercent >= RiskPercent, "MaxOpenRiskPercent doit être >= RiskPercent");
            req(TradeAsia || TradeLondon || TradeNewYork, "Au moins une session doit être active");
            req(AdxRange < AdxTrend, "AdxRange doit être < AdxTrend");
            req(LowVolRatio > 0 && LowVolRatio < 1 && HighVolRatio > 1, "Ratios de volatilité incohérents");
            req(EnableSweep || EnableBreakout || EnablePullback || EnableMomentum, "Au moins un setup doit être actif");
            req(MinScore >= 0 && MinScore <= 100, "MinScore dans [0 ; 100]");
            req(MaxSpreadAtr > 0, "MaxSpreadAtr doit être > 0");
            req(MinSlAtr > 0 && MaxSlAtr > MinSlAtr, "MinSlAtr < MaxSlAtr attendu");
            req(SlBufferAtr >= 0, "SlBufferAtr >= 0");
            req(MaxConcurrentPositions >= 1 && MaxTradesPerDay >= 1 && CooldownBars >= 0, "Limites anti-overtrading invalides");
            req(Tp1R > 0 && Tp2R > Tp1R && Tp3R > Tp2R, "Il faut 0 < TP1 < TP2 < TP3");
            req(Tp1ClosePct >= 0 && Tp2ClosePct >= 0 && Tp1ClosePct + Tp2ClosePct < 100, "Les clôtures partielles doivent laisser un runner");
            req(StopAfterTp1R > -1 && StopAfterTp1R < StopAfterTp2R && StopAfterTp2R < Tp1R,
                "Il faut -1 < StopAfterTp1R < StopAfterTp2R < TP1R");
            req(TrailStartR >= Tp2R && TrailAtr > 0, "TrailStartR doit être >= TP2R");
            req(MaxDailyLossPercent > 0 && MaxWeeklyLossPercent >= MaxDailyLossPercent, "Limites de perte invalides");
            req(MaxConsecutiveLosses >= 1, "MaxConsecutiveLosses >= 1");
            return e;
        }
    }

    // =================================================================================
    //  MARKET DATA (indicateurs incrémentaux, sans repaint)
    // =================================================================================
    public struct Candle
    {
        public DateTime OpenTimeUtc;
        public double Open, High, Low, Close, Volume;

        public Candle(DateTime t, double o, double h, double l, double c, double v)
        {
            OpenTimeUtc = DateTime.SpecifyKind(t, DateTimeKind.Utc);
            Open = o; High = h; Low = l; Close = c; Volume = v;
        }

        public bool IsValid
        {
            get
            {
                return Num.Ok(Open) && Num.Ok(High) && Num.Ok(Low) && Num.Ok(Close)
                       && Low > 0 && High >= Low && Open >= Low && Open <= High && Close >= Low && Close <= High;
            }
        }

        public double Range { get { return High - Low; } }
    }

    public sealed class BarState
    {
        public Candle C;
        public long Seq;
        public double EmaFast, EmaMid, EmaSlow, Atr, AtrBase, Adx, VolAvg;
        public int HtfBias;
        public int BarsSinceGap;

        public double AtrRatio { get { return Num.Ok(Atr) && Num.Ok(AtrBase) && AtrBase > 0 ? Atr / AtrBase : double.NaN; } }
    }

    internal sealed class IncEma
    {
        private readonly double _k;
        public double Value = double.NaN;
        public IncEma(int period) { _k = 2.0 / (period + 1); }
        public double Update(double x) { Value = double.IsNaN(Value) ? x : Value + _k * (x - Value); return Value; }
    }

    internal sealed class Wilder
    {
        private readonly int _n;
        private int _count;
        private double _sum;
        public double Value = double.NaN;
        public Wilder(int n) { _n = n; }

        public double Update(double x)
        {
            if (_count < _n)
            {
                _sum += x;
                _count++;
                if (_count == _n) Value = _sum / _n;
            }
            else
            {
                Value = (Value * (_n - 1) + x) / _n;
            }
            return Value;
        }
    }

    internal sealed class AdxCalc
    {
        private readonly Wilder _tr, _pdm, _mdm, _dx;
        public AdxCalc(int n) { _tr = new Wilder(n); _pdm = new Wilder(n); _mdm = new Wilder(n); _dx = new Wilder(n); }

        public double Update(Candle c, Candle prev)
        {
            double up = c.High - prev.High, down = prev.Low - c.Low;
            double pdm = up > down && up > 0 ? up : 0;
            double mdm = down > up && down > 0 ? down : 0;
            double tr = Math.Max(c.High - c.Low, Math.Max(Math.Abs(c.High - prev.Close), Math.Abs(c.Low - prev.Close)));
            _tr.Update(tr); _pdm.Update(pdm); _mdm.Update(mdm);
            if (!Num.Ok(_tr.Value) || _tr.Value <= 0) return double.NaN;
            double pdi = 100 * _pdm.Value / _tr.Value, mdi = 100 * _mdm.Value / _tr.Value;
            double sum = pdi + mdi;
            _dx.Update(sum > 0 ? 100 * Math.Abs(pdi - mdi) / sum : 0);
            return _dx.Value;
        }
    }

    internal sealed class Sma
    {
        private readonly Queue<double> _q = new Queue<double>();
        private readonly int _n;
        private double _sum;
        public Sma(int n) { _n = n; }

        public double Update(double x)
        {
            _q.Enqueue(x); _sum += x;
            if (_q.Count > _n) _sum -= _q.Dequeue();
            return _q.Count == _n ? _sum / _n : double.NaN;
        }
    }

    /// <summary>Agrège les bougies du timeframe de signal en bougies HTF. Seules les bougies HTF terminées comptent.</summary>
    internal sealed class HtfAggregator
    {
        private readonly TimeSpan _tf, _htf;
        private readonly IncEma _ema;
        private readonly List<double> _emaHistory = new List<double>();
        private DateTime _bucket = DateTime.MinValue;
        private double _close;
        private bool _open;
        private int _completed;
        public int Bias { get; private set; }

        public HtfAggregator(int tfMinutes, int htfMinutes, int emaPeriod)
        {
            _tf = TimeSpan.FromMinutes(tfMinutes);
            _htf = TimeSpan.FromMinutes(htfMinutes);
            _ema = new IncEma(emaPeriod);
        }

        public void Update(Candle c)
        {
            DateTime bucket = new DateTime(c.OpenTimeUtc.Ticks - c.OpenTimeUtc.Ticks % _htf.Ticks, DateTimeKind.Utc);
            if (_open && bucket != _bucket) CloseBucket();
            _bucket = bucket;
            _close = c.Close;
            _open = true;
            if (c.OpenTimeUtc + _tf >= _bucket + _htf) CloseBucket();
        }

        private void CloseBucket()
        {
            _open = false;
            _completed++;
            double ema = _ema.Update(_close);
            _emaHistory.Add(ema);
            if (_emaHistory.Count > 10) _emaHistory.RemoveAt(0);
            if (_completed < 20 || _emaHistory.Count < 4) { Bias = 0; return; }
            double slope = ema - _emaHistory[_emaHistory.Count - 4];
            if (_close > ema && slope > 0) Bias = 1;
            else if (_close < ema && slope < 0) Bias = -1;
            else Bias = 0;
        }
    }

    public struct SwingPoint
    {
        public long Seq;
        public double Price;
    }

    public sealed class MarketData
    {
        private const int MaxKeep = 6000, TrimChunk = 1000, MaxSwings = 20;
        private readonly EngineConfig _cfg;
        private readonly List<BarState> _bars = new List<BarState>();
        private readonly List<SwingPoint> _swingHighs = new List<SwingPoint>(), _swingLows = new List<SwingPoint>();
        private readonly IncEma _emaFast, _emaMid, _emaSlow, _atrBase;
        private readonly Wilder _atr;
        private readonly AdxCalc _adx;
        private readonly Sma _vol;
        private readonly HtfAggregator _htf;
        private long _seq;
        private long _appended;
        private int _barsSinceGap;

        public MarketData(EngineConfig cfg)
        {
            _cfg = cfg;
            _emaFast = new IncEma(cfg.EmaFast);
            _emaMid = new IncEma(cfg.EmaMid);
            _emaSlow = new IncEma(cfg.EmaSlow);
            _atrBase = new IncEma(cfg.AtrBasePeriod);
            _atr = new Wilder(cfg.AtrPeriod);
            _adx = new AdxCalc(cfg.AdxPeriod);
            _vol = new Sma(20);
            _htf = new HtfAggregator(cfg.SignalTfMinutes, cfg.HtfMinutes, cfg.HtfEmaPeriod);
        }

        public int Count { get { return _bars.Count; } }
        public long LastSeq { get { return _seq; } }
        public TimeSpan Timeframe { get { return TimeSpan.FromMinutes(_cfg.SignalTfMinutes); } }
        public DateTime LastOpenTime { get { return _bars.Count > 0 ? _bars[_bars.Count - 1].C.OpenTimeUtc : DateTime.MinValue; } }
        public DateTime LastCloseTime { get { return LastOpenTime + Timeframe; } }

        public bool Has(int ago) { return ago >= 0 && ago < _bars.Count; }

        /// <summary>0 = dernière bougie clôturée.</summary>
        public BarState Ago(int ago)
        {
            if (!Has(ago)) throw new ArgumentOutOfRangeException("ago", "Historique insuffisant");
            return _bars[_bars.Count - 1 - ago];
        }

        public bool IsReady
        {
            get
            {
                if (_appended < _cfg.WarmupBars || _bars.Count < _cfg.StructureLookback + 10) return false;
                var b = Ago(0);
                return Num.Ok(b.EmaSlow) && Num.Ok(b.Atr) && b.Atr > 0 && Num.Ok(b.AtrBase) && Num.Ok(b.Adx) && Num.Ok(b.VolAvg);
            }
        }

        public bool Append(Candle c)
        {
            if (!c.IsValid) return false;
            if (_bars.Count > 0 && c.OpenTimeUtc <= LastOpenTime) return false;

            BarState prev = _bars.Count > 0 ? _bars[_bars.Count - 1] : null;
            var s = new BarState { C = c, Seq = ++_seq };
            s.EmaFast = _emaFast.Update(c.Close);
            s.EmaMid = _emaMid.Update(c.Close);
            s.EmaSlow = _emaSlow.Update(c.Close);
            double tr = prev == null
                ? c.Range
                : Math.Max(c.Range, Math.Max(Math.Abs(c.High - prev.C.Close), Math.Abs(c.Low - prev.C.Close)));
            s.Atr = _atr.Update(tr);
            s.AtrBase = Num.Ok(s.Atr) ? _atrBase.Update(s.Atr) : double.NaN;
            s.Adx = prev == null ? double.NaN : _adx.Update(c, prev.C);
            s.VolAvg = _vol.Update(c.Volume);

            bool gap = prev != null && c.OpenTimeUtc - prev.C.OpenTimeUtc > TimeSpan.FromHours(2);
            _barsSinceGap = gap ? 0 : _barsSinceGap + 1;
            s.BarsSinceGap = _barsSinceGap;

            _htf.Update(c);
            s.HtfBias = _htf.Bias;

            _bars.Add(s);
            _appended++;
            DetectSwing();
            Trim();
            return true;
        }

        private void DetectSwing()
        {
            int n = _cfg.SwingStrength;
            int k = _bars.Count - 1 - n; // pivot candidat, confirmé par les n bougies suivantes
            if (k - n < 0) return;
            double h = _bars[k].C.High, l = _bars[k].C.Low;
            bool isHigh = true, isLow = true;
            for (int i = 1; i <= n; i++)
            {
                if (_bars[k - i].C.High >= h || _bars[k + i].C.High > h) isHigh = false;
                if (_bars[k - i].C.Low <= l || _bars[k + i].C.Low < l) isLow = false;
            }
            if (isHigh) AddSwing(_swingHighs, _bars[k].Seq, h);
            if (isLow) AddSwing(_swingLows, _bars[k].Seq, l);
        }

        private static void AddSwing(List<SwingPoint> list, long seq, double price)
        {
            list.Add(new SwingPoint { Seq = seq, Price = price });
            if (list.Count > MaxSwings) list.RemoveAt(0);
        }

        private void Trim()
        {
            if (_bars.Count > MaxKeep) _bars.RemoveRange(0, TrimChunk);
        }

        /// <summary>+1 = HH + HL, -1 = LH + LL, 0 = structure mixte ou insuffisante.</summary>
        public int Structure()
        {
            if (_swingHighs.Count < 2 || _swingLows.Count < 2) return 0;
            bool hh = _swingHighs[_swingHighs.Count - 1].Price > _swingHighs[_swingHighs.Count - 2].Price;
            bool hl = _swingLows[_swingLows.Count - 1].Price > _swingLows[_swingLows.Count - 2].Price;
            if (hh && hl) return 1;
            if (!hh && !hl) return -1;
            return 0;
        }
    }

    // =================================================================================
    //  SESSIONS (conversion fiable UTC -> heures locales Londres / New York, DST inclus)
    // =================================================================================
    public sealed class SessionState
    {
        public bool Asia, London, NewYork, Rollover, FridayClose, WeekendFlatten;
        public bool Overlap { get { return London && NewYork; } }

        public string Name
        {
            get
            {
                if (Overlap) return "London/NY";
                if (London) return "London";
                if (NewYork) return "NewYork";
                return Asia ? "Asia" : "Off";
            }
        }
    }

    public sealed class SessionClock
    {
        private readonly TimeZoneInfo _london, _newYork;
        public bool UsingFallback { get { return _london == null || _newYork == null; } }

        public SessionClock()
        {
            _london = Find("Europe/London", "GMT Standard Time");
            _newYork = Find("America/New_York", "Eastern Standard Time");
        }

        private static TimeZoneInfo Find(params string[] ids)
        {
            foreach (var id in ids)
            {
                try { return TimeZoneInfo.FindSystemTimeZoneById(id); }
                catch (Exception) { /* essai de l'identifiant suivant (IANA puis Windows) */ }
            }
            return null;
        }

        public SessionState At(DateTime utc)
        {
            utc = DateTime.SpecifyKind(utc, DateTimeKind.Utc);
            // Repli sans fuseaux : heures d'hiver approximatives (signalé au démarrage)
            DateTime lon = _london != null ? TimeZoneInfo.ConvertTimeFromUtc(utc, _london) : utc;
            DateTime ny = _newYork != null ? TimeZoneInfo.ConvertTimeFromUtc(utc, _newYork) : utc.AddHours(-5);
            double lonH = lon.TimeOfDay.TotalHours, nyH = ny.TimeOfDay.TotalHours, utcH = utc.TimeOfDay.TotalHours;

            return new SessionState
            {
                Asia = utcH >= 23 || utcH < 6,                 // Tokyo 08:00-15:00 JST (pas de DST)
                London = lonH >= 8 && lonH < 16.5,
                NewYork = nyH >= 8 && nyH < 16.5,
                Rollover = nyH >= 16.75 && nyH < 18.25,        // élargissement des spreads au rollover
                FridayClose = (ny.DayOfWeek == DayOfWeek.Friday && nyH >= 15.5) || ny.DayOfWeek == DayOfWeek.Saturday,
                WeekendFlatten = ny.DayOfWeek == DayOfWeek.Friday && nyH >= 16.5,
            };
        }
    }

    // =================================================================================
    //  REGIME DETECTOR
    // =================================================================================
    public sealed class RegimeState
    {
        public Regime Regime;
        public int TrendDir;
        public double AtrRatio, Adx, SlopeAtr;
        public int Structure, HtfBias;

        public override string ToString()
        {
            return string.Format(CultureInfo.InvariantCulture, "{0} (ADX {1}, ATRx {2}, pente {3}, structure {4}, HTF {5})",
                Regime, Num.F(Adx, 1), Num.F(AtrRatio, 2), Num.F(SlopeAtr, 2), Structure, HtfBias);
        }
    }

    public static class RegimeDetector
    {
        public static RegimeState Detect(MarketData md, EngineConfig c)
        {
            var b = md.Ago(0);
            var old = md.Ago(Math.Min(c.SlopeLookback, md.Count - 1));
            var r = new RegimeState
            {
                AtrRatio = b.AtrRatio,
                Adx = b.Adx,
                SlopeAtr = (b.EmaMid - old.EmaMid) / b.Atr,
                Structure = md.Structure(),
                HtfBias = b.HtfBias,
            };

            if (b.C.Close > b.EmaSlow && b.EmaMid > b.EmaSlow && r.SlopeAtr >= c.MinSlopeAtr) r.TrendDir = 1;
            else if (b.C.Close < b.EmaSlow && b.EmaMid < b.EmaSlow && r.SlopeAtr <= -c.MinSlopeAtr) r.TrendDir = -1;

            r.Regime = Classify(md, c, r);
            return r;
        }

        private static Regime Classify(MarketData md, EngineConfig c, RegimeState r)
        {
            if (r.AtrRatio >= c.HighVolRatio) return Regime.HighVolatility;
            if (r.Adx >= c.AdxTrend && r.TrendDir != 0) return r.TrendDir > 0 ? Regime.TrendUp : Regime.TrendDown;
            if (IsDonchianBreak(md, c.StructureLookback) && r.AtrRatio >= 1.0) return Regime.Breakout;
            if (r.AtrRatio <= c.LowVolRatio) return Regime.LowVolatility;
            if (r.Adx <= c.AdxRange) return Regime.Range;
            return Regime.Transition;
        }

        private static bool IsDonchianBreak(MarketData md, int n)
        {
            var up = new PriceView(md, Side.Buy);
            var dn = new PriceView(md, Side.Sell);
            return up.C(0) > up.MaxH(1, n) || dn.C(0) > dn.MaxH(1, n);
        }
    }

    // =================================================================================
    //  VUE MIROIR : chaque setup est écrit une seule fois (côté achat). Pour la vente,
    //  les prix sont inversés (x -> -x, High <-> Low). Supprime toute duplication BUY/SELL.
    // =================================================================================
    public sealed class PriceView
    {
        private readonly MarketData _md;
        private readonly int _s;
        public Side Side { get; private set; }

        public PriceView(MarketData md, Side side) { _md = md; Side = side; _s = (int)side; }

        public double O(int a) { return _s * _md.Ago(a).C.Open; }
        public double C(int a) { return _s * _md.Ago(a).C.Close; }
        public double H(int a) { var c = _md.Ago(a).C; return _s == 1 ? c.High : -c.Low; }
        public double L(int a) { var c = _md.Ago(a).C; return _s == 1 ? c.Low : -c.High; }
        public double EmaF(int a) { return _s * _md.Ago(a).EmaFast; }
        public double EmaS(int a) { return _s * _md.Ago(a).EmaSlow; }
        public double Atr(int a) { return _md.Ago(a).Atr; }
        public double Range(int a) { return H(a) - L(a); }
        public double ToReal(double v) { return _s * v; }

        public double MaxH(int from, int to)
        {
            double m = double.MinValue;
            for (int i = from; i <= to && _md.Has(i); i++) m = Math.Max(m, H(i));
            return m;
        }

        public double MinL(int from, int to, out int argAgo)
        {
            double m = double.MaxValue;
            argAgo = -1;
            for (int i = from; i <= to && _md.Has(i); i++)
            {
                if (L(i) < m) { m = L(i); argAgo = i; }
            }
            return m;
        }

        public double MinL(int from, int to) { int unused; return MinL(from, to, out unused); }

        /// <summary>Position de la clôture dans la bougie (1 = au plus haut, sens du trade).</summary>
        public double ClosePos(int a) { double r = Range(a); return r > 0 ? (C(a) - L(a)) / r : 0.5; }

        public double Body(int a) { return C(a) - O(a); }
    }

    // =================================================================================
    //  SETUPS
    // =================================================================================
    public sealed class SetupSignal
    {
        public SetupType Type;
        public Side Side;
        public double StopLevel;      // niveau structurel en prix BID
        public bool LiquidityEvent;
        public bool VolumeConfirm;
        public string Reason;
    }

    public interface ISetup
    {
        SetupType Type { get; }
        bool Enabled(EngineConfig c);
        SetupSignal Detect(PriceView v, MarketData md, RegimeState r, EngineConfig c);
    }

    internal static class SetupHelpers
    {
        public static SetupSignal Make(SetupType t, PriceView v, double viewStop, string reason)
        {
            return new SetupSignal { Type = t, Side = v.Side, StopLevel = v.ToReal(viewStop), Reason = reason };
        }

        public static bool VolumeAboveAverage(MarketData md)
        {
            double avg = md.Ago(1).VolAvg;
            return Num.Ok(avg) && avg > 0 && md.Ago(0).C.Volume >= 1.3 * avg;
        }
    }

    /// <summary>A — Balayage d'un plus bas/haut récent puis réintégration rapide avec rejet.</summary>
    public sealed class LiquiditySweepSetup : ISetup
    {
        public SetupType Type { get { return SetupType.LiquiditySweep; } }
        public bool Enabled(EngineConfig c) { return c.EnableSweep; }

        public SetupSignal Detect(PriceView v, MarketData md, RegimeState r, EngineConfig c)
        {
            int levelAgo;
            double level = v.MinL(1, c.StructureLookback, out levelAgo);
            if (levelAgo < 3) return null; // niveau trop récent : pas une vraie liquidité
            double atr = v.Atr(1), range = v.Range(0);
            if (range <= 0) return null;

            double penetration = level - v.L(0);
            if (penetration < 0.05 * atr || penetration > 1.0 * atr) return null;
            if (v.C(0) <= level) return null;                                        // réintégration
            double wick = Math.Min(v.O(0), v.C(0)) - v.L(0);
            if (wick < 0.4 * range || v.ClosePos(0) < 0.6) return null;              // rejet

            var s = SetupHelpers.Make(Type, v, v.L(0) - c.SlBufferAtr * atr,
                "sweep " + Num.F(penetration / atr, 2) + " ATR sous le niveau " + levelAgo + " bougies, réintégré");
            s.LiquidityEvent = true;
            s.VolumeConfirm = SetupHelpers.VolumeAboveAverage(md);
            return s;
        }
    }

    /// <summary>B — Cassure d'une consolidation compressée, non étendue.</summary>
    public sealed class BreakoutSetup : ISetup
    {
        public SetupType Type { get { return SetupType.BreakoutContinuation; } }
        public bool Enabled(EngineConfig c) { return c.EnableBreakout; }

        public SetupSignal Detect(PriceView v, MarketData md, RegimeState r, EngineConfig c)
        {
            double atr = v.Atr(1), range = v.Range(0);
            double boxHigh = v.MaxH(1, c.BoxBars), boxLow = v.MinL(1, c.BoxBars);
            double width = boxHigh - boxLow;
            if (range <= 0 || width < 0.5 * atr || width > c.BoxMaxAtr * atr) return null;
            double preRatio = md.Ago(1).AtrRatio;
            if (!Num.Ok(preRatio) || preRatio > 1.0) return null;                    // compression préalable

            if (v.C(0) <= boxHigh || v.Body(0) < 0.5 * range) return null;
            double extension = v.C(0) - boxHigh;
            if (extension > 0.8 * atr) return null;                                  // déjà trop étendu

            double boxMid = (boxHigh + boxLow) / 2;
            var s = SetupHelpers.Make(Type, v, Math.Min(boxMid, v.L(0)) - c.SlBufferAtr * atr,
                "cassure d'une box de " + c.BoxBars + " bougies (" + Num.F(width / atr, 1) + " ATR), extension " + Num.F(extension / atr, 2) + " ATR");
            s.LiquidityEvent = true;
            s.VolumeConfirm = SetupHelpers.VolumeAboveAverage(md);
            return s;
        }
    }

    /// <summary>C — Pullback vers l'EMA rapide dans une tendance propre, entrée sur reprise.</summary>
    public sealed class TrendPullbackSetup : ISetup
    {
        public SetupType Type { get { return SetupType.TrendPullback; } }
        public bool Enabled(EngineConfig c) { return c.EnablePullback; }

        public SetupSignal Detect(PriceView v, MarketData md, RegimeState r, EngineConfig c)
        {
            Regime wanted = v.Side == Side.Buy ? Regime.TrendUp : Regime.TrendDown;
            if (r.Regime != wanted) return null;
            double atr = v.Atr(1);

            bool touched = false;
            for (int k = 1; k <= c.PullbackBars && md.Has(k); k++)
            {
                if (v.L(k) <= v.EmaF(k) + 0.25 * atr) { touched = true; break; }
            }
            if (!touched) return null;
            double pullbackLow = v.MinL(0, c.PullbackBars);
            if (pullbackLow < v.EmaS(0) - 0.5 * atr) return null;                    // tendance cassée

            bool resumption = v.C(0) > v.H(1) && v.Body(0) > 0 && v.C(0) > v.EmaF(0);
            if (!resumption) return null;

            return SetupHelpers.Make(Type, v, pullbackLow - c.SlBufferAtr * atr,
                "pullback sur EMA" + c.EmaFast + " puis reprise au-dessus du plus haut précédent");
        }
    }

    /// <summary>D — Bougie d'expansion inhabituelle, entrée seulement si le mouvement n'est pas déjà épuisé.</summary>
    public sealed class MomentumExpansionSetup : ISetup
    {
        public SetupType Type { get { return SetupType.MomentumExpansion; } }
        public bool Enabled(EngineConfig c) { return c.EnableMomentum; }

        public SetupSignal Detect(PriceView v, MarketData md, RegimeState r, EngineConfig c)
        {
            if (!md.Has(4)) return null;
            double atr = v.Atr(1), range = v.Range(0);
            if (range < c.ExpansionAtr * atr) return null;
            if (v.Body(0) < 0.6 * range || v.ClosePos(0) < 0.75) return null;
            if (v.C(0) <= v.MaxH(1, c.StructureLookback)) return null;
            if (v.C(0) - v.EmaF(0) > c.MaxExtensionAtr * atr) return null;           // sur-extension
            if (v.C(1) - v.C(4) > 1.5 * atr) return null;                            // déjà explosé avant

            var s = SetupHelpers.Make(Type, v, v.L(0) + 0.5 * range - c.SlBufferAtr * atr,
                "bougie d'expansion " + Num.F(range / atr, 1) + " ATR cassant le plus haut de " + c.StructureLookback + " bougies");
            s.VolumeConfirm = SetupHelpers.VolumeAboveAverage(md);
            return s;
        }
    }

    // =================================================================================
    //  CONFLUENCE ENGINE — score 0..100 (poids FIXES : ne pas les optimiser)
    // =================================================================================
    public sealed class ScoreResult
    {
        public int Score;
        public readonly List<string> Items = new List<string>();

        public void Add(bool condition, int points, string label)
        {
            if (!condition) return;
            Score += points;
            Items.Add((points >= 0 ? "+" : "") + points + " " + label);
        }

        public override string ToString() { return string.Join(", ", Items); }
    }

    public static class ConfluenceEngine
    {
        public static ScoreResult Score(SetupSignal s, PriceView v, MarketData md, RegimeState r, SessionState sess,
                                        double spread, double spreadLimit, double stopDist, EngineConfig c)
        {
            int d = Num.Dir(s.Side);
            double atr = md.Ago(1).Atr;
            var res = new ScoreResult();
            res.Add(true, 20, "setup " + s.Type);
            res.Add(r.TrendDir == d, 15, "tendance alignée");
            res.Add(r.TrendDir == -d, -15, "contre-tendance");
            res.Add(c.UseHtfScore && r.HtfBias == d, 15, "M" + c.HtfMinutes + " aligné");
            res.Add(c.UseHtfScore && r.HtfBias == -d, -10, "M" + c.HtfMinutes + " opposé");
            res.Add(r.Structure == d, 10, "structure HH/HL");
            res.Add(r.Structure == -d, -5, "structure opposée");
            res.Add(v.ClosePos(0) >= 0.6 && v.Body(0) >= 0.4 * v.Range(0), 10, "momentum de clôture");
            bool normalVol = r.AtrRatio >= 0.7 && r.AtrRatio <= 1.8;
            res.Add(normalVol, 10, "volatilité normale");
            res.Add(r.AtrRatio < c.LowVolRatio, -10, "volatilité faible");
            res.Add(r.AtrRatio > 1.8, -10, "volatilité anormale");
            res.Add(s.LiquidityEvent, 5, "événement de liquidité");
            res.Add(s.VolumeConfirm, 5, "tick volume > moyenne");
            res.Add(sess.Overlap, 10, "overlap Londres/NY");
            res.Add(!sess.Overlap && (sess.London || sess.NewYork), 5, "session " + sess.Name);
            res.Add(spread <= 0.5 * spreadLimit, 5, "spread serré");
            res.Add(Math.Abs(v.C(0) - v.EmaF(0)) > 2.0 * atr, -15, "sur-extension vs EMA" + c.EmaFast);
            res.Add(stopDist > 0 && spread / stopDist > 0.10, -10, "coût/risque élevé");
            res.Score = Math.Max(0, Math.Min(100, res.Score));
            return res;
        }
    }

    // =================================================================================
    //  RISK ENGINE
    // =================================================================================
    public sealed class SymbolSpec
    {
        public string Name = "XAUUSD", AccountCurrency = "USD";
        public double TickSize = 0.01, TickValue = 0.01, PipSize = 0.01;
        public double VolumeMin = 1, VolumeMax = 10000, VolumeStep = 1;
        public int Digits = 2;

        /// <summary>Valeur (devise du compte) d'un mouvement de 1.0 du prix pour 1 unité.</summary>
        public double ValuePerPriceUnit { get { return TickSize > 0 ? TickValue / TickSize : double.NaN; } }

        public double RoundPrice(double p) { return Math.Round(p, Digits); }

        public double NormalizeDown(double units)
        {
            if (!Num.Ok(units) || units <= 0 || VolumeStep <= 0) return 0;
            double steps = Math.Floor(units / VolumeStep + 1e-9);
            return Math.Round(steps * VolumeStep, 8);
        }

        public List<string> Validate()
        {
            var e = new List<string>();
            if (!(TickSize > 0) || !(TickValue > 0)) e.Add("TickSize/TickValue invalides");
            if (!(PipSize > 0)) e.Add("PipSize invalide");
            if (!(VolumeMin > 0) || !(VolumeStep > 0) || VolumeMax < VolumeMin) e.Add("Contraintes de volume invalides");
            return e;
        }
    }

    public sealed class SizingResult
    {
        public double Units;
        public double RiskMoney;
        public string Reason;
        public bool Ok { get { return Units > 0; } }
    }

    public static class RiskEngine
    {
        public static SizingResult Size(double equity, double stopDistance, double openRiskMoney, SymbolSpec s, EngineConfig c)
        {
            double vpu = s.ValuePerPriceUnit;
            if (!Num.Ok(equity) || equity <= 0) return Fail("equity invalide");
            if (!Num.Ok(stopDistance) || stopDistance <= 0) return Fail("distance de stop invalide");
            if (!Num.Ok(vpu) || vpu <= 0) return Fail("valeur du tick invalide");

            double target = equity * c.RiskPercent / 100.0;
            double units = s.NormalizeDown(target / (stopDistance * vpu));
            if (units < s.VolumeMin) return Fail("volume min broker > risque autorisé (" + Num.F(s.VolumeMin * stopDistance * vpu) + " " + s.AccountCurrency + ")");
            units = Math.Min(units, s.NormalizeDown(s.VolumeMax));

            double risk = units * stopDistance * vpu;
            if (openRiskMoney + risk > equity * c.MaxOpenRiskPercent / 100.0 + 1e-9)
                return Fail("risque ouvert max atteint");
            return new SizingResult { Units = units, RiskMoney = risk };
        }

        private static SizingResult Fail(string reason) { return new SizingResult { Units = 0, Reason = reason }; }
    }

    // =================================================================================
    //  POSITION MANAGEMENT — TP1/TP2 partiels, profit lock progressif, trailing ATR, time stop
    //  L'état (TP déjà pris ?) est déduit du volume restant ET du niveau du stop :
    //  idempotent, survit aux redémarrages, aucune clôture partielle répétée.
    // =================================================================================
    public sealed class ManagedPosition
    {
        public long Id;
        public Side Side;
        public SetupType Setup;
        public double Entry, RiskDistance, InitialUnits, Units;
        public double? Stop;
        public DateTime EntryUtc;
        public double BestPrice;
        public int Score;
        public string Regime = "";

        public int Dir { get { return (int)Side; } }
        public double R(double price) { return RiskDistance > 0 ? (price - Entry) * Dir / RiskDistance : 0; }
        public double PriceAtR(double r) { return Entry + Dir * r * RiskDistance; }

        public void UpdateBest(double price)
        {
            if (BestPrice == 0 || (price - BestPrice) * Dir > 0) BestPrice = price;
        }

        public int Stage(EngineConfig c, SymbolSpec s)
        {
            double half = s.VolumeStep * 0.5;
            int volStage = 0;
            if (c.Tp1ClosePct > 0 && Units <= InitialUnits * (1 - c.Tp1ClosePct / 100) + half) volStage = 1;
            if (c.Tp2ClosePct > 0 && Units <= InitialUnits * (1 - (c.Tp1ClosePct + c.Tp2ClosePct) / 100) + half) volStage = 2;
            int stopStage = 0;
            if (Stop.HasValue && RiskDistance > 0)
            {
                double lockR = R(Stop.Value);
                if (lockR >= c.StopAfterTp2R - 1e-6) stopStage = 2;
                else if (lockR >= c.StopAfterTp1R - 1e-6) stopStage = 1;
            }
            return Math.Max(volStage, stopStage);
        }

        public double OpenRiskMoney(SymbolSpec s)
        {
            if (!Stop.HasValue) return RiskDistance * Units * s.ValuePerPriceUnit;
            double loss = (Entry - Stop.Value) * Dir;
            return Math.Max(0, loss) * Units * s.ValuePerPriceUnit;
        }
    }

    public enum ExitKind { PartialClose, MoveStop, CloseAll }

    public sealed class ExitAction
    {
        public ExitKind Kind;
        public double Units;
        public double Price;   // prix déclencheur (TP) ou nouveau stop
        public string Reason;

        public override string ToString() { return Kind + " " + Reason + " @" + Num.F(Price); }
    }

    public static class ExitEngine
    {
        /// <summary>Appelé à chaque tick (live) ou avec l'extrême favorable de la bougie (simulation).</summary>
        public static List<ExitAction> OnPrice(ManagedPosition p, double exitPrice, EngineConfig c, SymbolSpec s, double minGap)
        {
            var actions = new List<ExitAction>();
            p.UpdateBest(exitPrice);
            int stage = p.Stage(c, s);
            double r = p.R(exitPrice);
            double remaining = p.Units;

            if (stage < 1 && r >= c.Tp1R)
            {
                remaining = AddPartial(actions, p, remaining, c.Tp1ClosePct, c.Tp1R, "TP1", s);
                stage = 1;
            }
            if (stage < 2 && r >= c.Tp2R)
            {
                AddPartial(actions, p, remaining, c.Tp2ClosePct, c.Tp2R, "TP2", s);
                stage = 2;
            }
            // Réappliqué à chaque appel : si un déplacement de stop a échoué, il est retenté (jamais desserré).
            if (stage >= 2) TryMoveStop(actions, p, p.PriceAtR(c.StopAfterTp2R), exitPrice, "profit lock après TP2", minGap);
            else if (stage == 1) TryMoveStop(actions, p, p.PriceAtR(c.StopAfterTp1R), exitPrice, "profit lock après TP1", minGap);
            return actions;
        }

        /// <summary>Appelé à la clôture de chaque bougie du timeframe de signal.</summary>
        public static List<ExitAction> OnBarClosed(ManagedPosition p, MarketData md, EngineConfig c, SymbolSpec s,
                                                   double exitPriceNow, double minGap)
        {
            var actions = new List<ExitAction>();
            var bar = md.Ago(0);
            p.UpdateBest(p.Side == Side.Buy ? bar.C.High : bar.C.Low);
            double atr = bar.Atr;
            int stage = p.Stage(c, s);

            if (Num.Ok(atr) && p.R(p.BestPrice) >= c.TrailStartR)
            {
                double trail = p.BestPrice - p.Dir * c.TrailAtr * atr;
                double floor = p.PriceAtR(c.StopAfterTp2R);
                if ((trail - floor) * p.Dir < 0) trail = floor;
                TryMoveStop(actions, p, trail, exitPriceNow, "trailing ATR", minGap);
            }

            int barsHeld = (int)Math.Floor((md.LastCloseTime - p.EntryUtc).TotalMinutes / c.SignalTfMinutes);
            if (stage == 0 && barsHeld >= c.MaxBarsInTrade && p.R(exitPriceNow) < 0.3)
                actions.Add(new ExitAction { Kind = ExitKind.CloseAll, Price = exitPriceNow, Reason = "time stop (" + barsHeld + " bougies sans progrès)" });
            return actions;
        }

        private static double AddPartial(List<ExitAction> actions, ManagedPosition p, double remaining, double pct, double atR, string label, SymbolSpec s)
        {
            if (pct <= 0) return remaining;
            double units = s.NormalizeDown(p.InitialUnits * pct / 100.0);
            if (units < s.VolumeMin || remaining - units < s.VolumeMin) return remaining; // volume trop petit : on verrouille seulement
            actions.Add(new ExitAction { Kind = ExitKind.PartialClose, Units = units, Price = p.PriceAtR(atR), Reason = label });
            return remaining - units;
        }

        private static void TryMoveStop(List<ExitAction> actions, ManagedPosition p, double newStop, double exitPrice, string reason, double minGap)
        {
            if (p.Stop.HasValue && (newStop - p.Stop.Value) * p.Dir <= 0) return; // jamais desserrer
            if ((exitPrice - newStop) * p.Dir <= minGap)
            {
                actions.Add(new ExitAction { Kind = ExitKind.CloseAll, Price = exitPrice, Reason = reason + " (prix déjà au niveau du stop)" });
                return;
            }
            actions.Add(new ExitAction { Kind = ExitKind.MoveStop, Price = newStop, Reason = reason });
        }
    }

    // =================================================================================
    //  SAFETY ENGINE
    // =================================================================================
    public sealed class RealizedDeal
    {
        public long PositionId;
        public DateTime CloseUtc;
        public double NetProfit;
    }

    public sealed class SafetyInput
    {
        public DateTime NowUtc;
        public double Balance, OpenPnL;
        public IReadOnlyList<RealizedDeal> Deals = new List<RealizedDeal>();
        public ISet<long> OpenPositionIds = new HashSet<long>();
        public int ExecutionFailures;
    }

    public sealed class SafetyDecision
    {
        public bool Allowed = true;
        public string Reason = "";
        public static SafetyDecision Block(string r) { return new SafetyDecision { Allowed = false, Reason = r }; }
    }

    public static class SafetyEngine
    {
        public static SafetyDecision Check(SafetyInput x, EngineConfig c)
        {
            if (c.EmergencyStop) return SafetyDecision.Block("EMERGENCY STOP actif");
            if (x.ExecutionFailures >= c.MaxExecutionFailures)
                return SafetyDecision.Block(x.ExecutionFailures + " échecs d'exécution consécutifs : redémarrage manuel requis");

            DateTime day = x.NowUtc.Date;
            DateTime week = day.AddDays(-(((int)day.DayOfWeek + 6) % 7));
            double realizedDay = x.Deals.Where(d => d.CloseUtc >= day).Sum(d => d.NetProfit);
            double realizedWeek = x.Deals.Where(d => d.CloseUtc >= week).Sum(d => d.NetProfit);

            if (LossExceeded(realizedDay + x.OpenPnL, x.Balance - realizedDay, c.MaxDailyLossPercent))
                return SafetyDecision.Block("perte journalière max atteinte (" + c.MaxDailyLossPercent + " %) : plus d'entrée aujourd'hui");
            if (LossExceeded(realizedWeek + x.OpenPnL, x.Balance - realizedWeek, c.MaxWeeklyLossPercent))
                return SafetyDecision.Block("perte hebdomadaire max atteinte (" + c.MaxWeeklyLossPercent + " %) : plus d'entrée cette semaine");

            int streak = ConsecutiveLossesToday(x, day);
            if (streak >= c.MaxConsecutiveLosses)
                return SafetyDecision.Block(streak + " pertes consécutives aujourd'hui : pause jusqu'à demain");
            return new SafetyDecision();
        }

        private static bool LossExceeded(double pnl, double reference, double pct)
        {
            return reference > 0 && pnl <= -reference * pct / 100.0;
        }

        private static int ConsecutiveLossesToday(SafetyInput x, DateTime day)
        {
            var closed = x.Deals
                .Where(d => !x.OpenPositionIds.Contains(d.PositionId))
                .GroupBy(d => d.PositionId)
                .Select(g => new { Close = g.Max(d => d.CloseUtc), Net = g.Sum(d => d.NetProfit) })
                .Where(t => t.Close >= day)
                .OrderBy(t => t.Close)
                .ToList();
            int streak = 0;
            foreach (var t in closed) streak = t.Net <= 0 ? streak + 1 : 0;
            return streak;
        }
    }

    // =================================================================================
    //  ENGINE (orchestration de l'entrée)
    // =================================================================================
    public sealed class EntryContext
    {
        public double Bid, Ask;
        public SymbolSpec Symbol;
        public IReadOnlyList<ManagedPosition> OpenPositions = new List<ManagedPosition>();
        public SafetyDecision Safety = new SafetyDecision();
        public int TradesToday;
        public DateTime? LastExitUtc;
    }

    public sealed class EntryDecision
    {
        public bool Take;
        public string Reason = "";
        public SetupSignal Signal;
        public RegimeState Regime;
        public ScoreResult Score;
        public SessionState Session;
        public double Atr, Spread;

        public static EntryDecision No(string reason) { return new EntryDecision { Take = false, Reason = reason }; }
    }

    public sealed class GoldEngine
    {
        private readonly List<ISetup> _setups = new List<ISetup>
        {
            new TrendPullbackSetup(), new LiquiditySweepSetup(), new BreakoutSetup(), new MomentumExpansionSetup(),
        };
        private long _lastEntrySeq = -1;
        private long _pauseUntilSeq = -1;

        public EngineConfig Config { get; private set; }
        public MarketData Data { get; private set; }
        public SessionClock Clock { get; private set; }

        public GoldEngine(EngineConfig cfg)
        {
            Config = cfg;
            Data = new MarketData(cfg);
            Clock = new SessionClock();
        }

        public void MarkEntryAttempt() { _lastEntrySeq = Data.LastSeq; }

        /// <summary>Vrai quand les positions doivent être fermées avant le gap du week-end (vendredi 16:30 New York).</summary>
        public bool MustFlattenForWeekend()
        {
            return Config.FlattenBeforeWeekend && Data.Count > 0 && Clock.At(Data.LastCloseTime).WeekendFlatten;
        }

        public EntryDecision Evaluate(EntryContext ctx)
        {
            var c = Config;
            if (!Data.IsReady) return EntryDecision.No("données insuffisantes (warm-up)");
            double atr = Data.Ago(1).Atr;
            if (Data.Ago(0).C.Range > EngineConfig.NewsSpikeAtr * atr) _pauseUntilSeq = Data.LastSeq + EngineConfig.NewsPauseBars;
            if (!ctx.Safety.Allowed) return EntryDecision.No("SAFETY : " + ctx.Safety.Reason);

            string gate = OvertradingGate(ctx);
            if (gate != null) return EntryDecision.No(gate);

            var bar = Data.Ago(0);
            var session = Clock.At(Data.LastCloseTime);
            gate = SessionGate(session, bar);
            if (gate != null) return EntryDecision.No(gate);

            double spread = ctx.Ask - ctx.Bid;
            double spreadLimit = SpreadLimit(atr, ctx.Symbol);
            if (!Num.Ok(spread) || spread <= 0 || spread > spreadLimit)
                return EntryDecision.No("spread " + Num.F(spread) + " > limite " + Num.F(spreadLimit));

            if (Data.LastSeq <= _pauseUntilSeq) return EntryDecision.No("pause après bougie anormale (news probable)");

            var regime = RegimeDetector.Detect(Data, c);
            if (regime.Regime == Regime.HighVolatility) return EntryDecision.No("régime HIGH VOLATILITY : pas de trade");

            return BestCandidate(ctx, regime, session, atr, spread, spreadLimit);
        }

        private string OvertradingGate(EntryContext ctx)
        {
            var c = Config;
            if (_lastEntrySeq == Data.LastSeq) return "déjà une entrée sur cette bougie";
            if (ctx.OpenPositions.Count >= c.MaxConcurrentPositions) return "positions max ouvertes";
            if (ctx.TradesToday >= c.MaxTradesPerDay) return "trades max du jour atteints";
            if (ctx.LastExitUtc.HasValue && Data.LastCloseTime < ctx.LastExitUtc.Value + TimeSpan.FromMinutes(c.CooldownBars * c.SignalTfMinutes))
                return "cooldown après sortie";
            return null;
        }

        private string SessionGate(SessionState s, BarState bar)
        {
            var c = Config;
            if (c.AvoidRollover && s.Rollover) return "rollover (spreads larges)";
            if (c.AvoidFridayClose && s.FridayClose) return "clôture du vendredi";
            if (bar.BarsSinceGap < c.ReopenSkipBars) return "réouverture du marché récente";
            bool allowed = (c.TradeLondon && s.London) || (c.TradeNewYork && s.NewYork) || (c.TradeAsia && s.Asia);
            return allowed ? null : "hors sessions actives (" + s.Name + ")";
        }

        public double SpreadLimit(double atr, SymbolSpec s)
        {
            double limit = Config.MaxSpreadAtr * atr;
            if (Config.MaxSpreadPips > 0) limit = Math.Min(limit, Config.MaxSpreadPips * s.PipSize);
            return limit;
        }

        private EntryDecision BestCandidate(EntryContext ctx, RegimeState regime, SessionState session, double atr, double spread, double spreadLimit)
        {
            var c = Config;
            EntryDecision best = null;
            string lastReject = "aucun setup détecté";
            foreach (Side side in new[] { Side.Buy, Side.Sell })
            {
                var view = new PriceView(Data, side);
                foreach (var setup in _setups)
                {
                    if (!setup.Enabled(c)) continue;
                    var sig = setup.Detect(view, Data, regime, c);
                    if (sig == null) continue;
                    if (ctx.OpenPositions.Any(p => p.Side == side && p.Setup == sig.Type)) { lastReject = "setup déjà en position"; continue; }

                    string stopReject = NormalizeStop(sig, view, atr);
                    if (stopReject != null) { lastReject = sig.Type + " : " + stopReject; continue; }

                    double stopDist = Math.Abs(Data.Ago(0).C.Close - sig.StopLevel) + spread;
                    var score = ConfluenceEngine.Score(sig, view, Data, regime, session, spread, spreadLimit, stopDist, c);
                    if (score.Score < c.MinScore) { lastReject = sig.Type + " " + Num.Name(side) + " score " + score.Score + " < " + c.MinScore; continue; }
                    if (best == null || score.Score > best.Score.Score)
                        best = new EntryDecision { Take = true, Signal = sig, Regime = regime, Score = score, Session = session, Atr = atr, Spread = spread, Reason = sig.Reason };
                }
            }
            return best ?? EntryDecision.No(lastReject);
        }

        /// <summary>SL structurel borné entre MinSlAtr et MaxSlAtr (distance mesurée sur la clôture BID).</summary>
        private string NormalizeStop(SetupSignal sig, PriceView v, double atr)
        {
            double close = v.C(0);
            double viewStop = v.ToReal(sig.StopLevel); // conversion réel -> vue (symétrique)
            double dist = close - viewStop;
            if (dist > Config.MaxSlAtr * atr) return "SL structurel trop large (" + Num.F(dist / atr, 1) + " ATR)";
            if (dist < Config.MinSlAtr * atr) viewStop = close - Config.MinSlAtr * atr;
            sig.StopLevel = v.ToReal(viewStop);
            return null;
        }
    }

    // =================================================================================
    //  STATISTIQUES (journal + résumé)
    // =================================================================================
    public sealed class ClosedTrade
    {
        public long PositionId;
        public DateTime EntryUtc, CloseUtc;
        public Side Side;
        public SetupType Setup;
        public double NetProfit, RiskMoney;
        public double RMultiple { get { return RiskMoney > 0 ? NetProfit / RiskMoney : 0; } }
    }

    public sealed class PerformanceStats
    {
        public int Trades, Wins, Losses, MaxConsecutiveLosses;
        public double NetProfit, GrossWin, GrossLoss, AvgWin, AvgLoss, ExpectancyMoney, ExpectancyR, StdR, MaxDrawdownMoney, MaxDrawdownPct;
        public double WinRate { get { return Trades > 0 ? 100.0 * Wins / Trades : 0; } }
        public double ProfitFactor { get { return GrossLoss > 0 ? GrossWin / GrossLoss : (GrossWin > 0 ? double.PositiveInfinity : 0); } }
        public double RecoveryFactor { get { return MaxDrawdownMoney > 0 ? NetProfit / MaxDrawdownMoney : 0; } }
        public double TStat { get { return Trades > 1 && StdR > 0 ? ExpectancyR / (StdR / Math.Sqrt(Trades)) : 0; } }

        public static PerformanceStats From(IEnumerable<ClosedTrade> trades, double startEquity)
        {
            var list = trades.OrderBy(t => t.CloseUtc).ToList();
            var st = new PerformanceStats { Trades = list.Count };
            double equity = startEquity, peak = startEquity;
            int streak = 0;
            foreach (var t in list)
            {
                st.NetProfit += t.NetProfit;
                if (t.NetProfit > 0) { st.Wins++; st.GrossWin += t.NetProfit; streak = 0; }
                else { st.Losses++; st.GrossLoss -= t.NetProfit; streak++; }
                st.MaxConsecutiveLosses = Math.Max(st.MaxConsecutiveLosses, streak);
                equity += t.NetProfit;
                peak = Math.Max(peak, equity);
                st.MaxDrawdownMoney = Math.Max(st.MaxDrawdownMoney, peak - equity);
                if (peak > 0) st.MaxDrawdownPct = Math.Max(st.MaxDrawdownPct, 100 * (peak - equity) / peak);
            }
            if (st.Trades == 0) return st;
            st.AvgWin = st.Wins > 0 ? st.GrossWin / st.Wins : 0;
            st.AvgLoss = st.Losses > 0 ? st.GrossLoss / st.Losses : 0;
            st.ExpectancyMoney = st.NetProfit / st.Trades;
            st.ExpectancyR = list.Average(t => t.RMultiple);
            double mean = st.ExpectancyR;
            st.StdR = st.Trades > 1 ? Math.Sqrt(list.Sum(t => (t.RMultiple - mean) * (t.RMultiple - mean)) / (st.Trades - 1)) : 0;
            return st;
        }

        public string Summary(string currency)
        {
            var sb = new StringBuilder();
            sb.AppendLine("==================== RÉSUMÉ GoldLiveEngine ====================");
            sb.AppendLine("TOTAL TRADES          : " + Trades);
            sb.AppendLine("WINS / LOSSES         : " + Wins + " / " + Losses);
            sb.AppendLine("WIN RATE              : " + Num.F(WinRate, 1) + " %");
            sb.AppendLine("NET PROFIT            : " + Num.F(NetProfit) + " " + currency);
            sb.AppendLine("PROFIT FACTOR         : " + Num.F(ProfitFactor, 2));
            sb.AppendLine("AVG WIN / AVG LOSS    : " + Num.F(AvgWin) + " / " + Num.F(AvgLoss) + " " + currency);
            sb.AppendLine("EXPECTANCY            : " + Num.F(ExpectancyMoney) + " " + currency + " (" + Num.F(ExpectancyR, 3) + " R)");
            sb.AppendLine("MAX DRAWDOWN (clôturé): " + Num.F(MaxDrawdownMoney) + " " + currency + " (" + Num.F(MaxDrawdownPct, 2) + " %)");
            sb.AppendLine("MAX CONSECUTIVE LOSSES: " + MaxConsecutiveLosses);
            sb.Append("===============================================================");
            return sb.ToString();
        }
    }

    /// <summary>Encode dans le commentaire de la position ce qu'il faut pour la reprendre après un redémarrage.</summary>
    public static class PositionTag
    {
        private const string Prefix = "GLE1";

        public static string Encode(SetupType setup, int score, double riskDistance, double initialUnits)
        {
            return string.Format(CultureInfo.InvariantCulture, "{0}|{1}|{2}|{3:R}|{4:R}", Prefix, (int)setup, score, riskDistance, initialUnits);
        }

        public static bool TryDecode(string comment, out SetupType setup, out int score, out double riskDistance, out double initialUnits)
        {
            setup = SetupType.LiquiditySweep; score = 0; riskDistance = 0; initialUnits = 0;
            if (string.IsNullOrEmpty(comment)) return false;
            var p = comment.Split('|');
            int setupInt;
            if (p.Length != 5 || p[0] != Prefix) return false;
            if (!int.TryParse(p[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out setupInt) || !Enum.IsDefined(typeof(SetupType), setupInt)) return false;
            if (!int.TryParse(p[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out score)) return false;
            if (!double.TryParse(p[3], NumberStyles.Float, CultureInfo.InvariantCulture, out riskDistance) || !(riskDistance > 0)) return false;
            if (!double.TryParse(p[4], NumberStyles.Float, CultureInfo.InvariantCulture, out initialUnits) || !(initialUnits > 0)) return false;
            setup = (SetupType)setupInt;
            return true;
        }
    }
}

#if !GLE_OFFLINE
// =====================================================================================
//  ADAPTATEUR cTrader (EXECUTION ENGINE + intégration live)
// =====================================================================================
namespace cAlgo.Robots
{
    using System;
    using System.Collections.Generic;
    using System.Linq;
    using cAlgo.API;
    using cAlgo.API.Internals;
    using GoldLive.Core;

    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None, AddIndicators = false)]
    public class GoldLiveEngine : Robot
    {
        // ---------------- GENERAL ----------------
        [Parameter("Instance tag (label unique)", DefaultValue = "1", Group = "GENERAL")]
        public string InstanceTag { get; set; }

        // ---------------- RISK ----------------
        [Parameter("Risk per trade (%)", DefaultValue = 0.35, MinValue = 0.05, MaxValue = 2.0, Step = 0.05, Group = "RISK")]
        public double RiskPercent { get; set; }

        [Parameter("Max open risk (%)", DefaultValue = 1.0, MinValue = 0.05, MaxValue = 5.0, Step = 0.05, Group = "RISK")]
        public double MaxOpenRiskPercent { get; set; }

        // ---------------- SESSIONS ----------------
        [Parameter("Trade Asia", DefaultValue = false, Group = "SESSIONS")]
        public bool TradeAsia { get; set; }

        [Parameter("Trade London", DefaultValue = true, Group = "SESSIONS")]
        public bool TradeLondon { get; set; }

        [Parameter("Trade New York", DefaultValue = true, Group = "SESSIONS")]
        public bool TradeNewYork { get; set; }

        [Parameter("Avoid rollover", DefaultValue = true, Group = "SESSIONS")]
        public bool AvoidRollover { get; set; }

        [Parameter("Avoid Friday close", DefaultValue = true, Group = "SESSIONS")]
        public bool AvoidFridayClose { get; set; }

        // ---------------- REGIME ----------------
        [Parameter("ADX trend threshold", DefaultValue = 22, MinValue = 10, MaxValue = 40, Step = 1, Group = "REGIME")]
        public double AdxTrend { get; set; }

        [Parameter("ADX range threshold", DefaultValue = 18, MinValue = 5, MaxValue = 35, Step = 1, Group = "REGIME")]
        public double AdxRange { get; set; }

        [Parameter("High volatility ratio (ATR/ATR200)", DefaultValue = 2.2, MinValue = 1.2, MaxValue = 5, Step = 0.1, Group = "REGIME")]
        public double HighVolRatio { get; set; }

        [Parameter("Low volatility ratio (ATR/ATR200)", DefaultValue = 0.65, MinValue = 0.2, MaxValue = 0.95, Step = 0.05, Group = "REGIME")]
        public double LowVolRatio { get; set; }

        // ---------------- SETUPS ----------------
        [Parameter("A - Liquidity sweep", DefaultValue = true, Group = "SETUPS")]
        public bool EnableSweep { get; set; }

        [Parameter("B - Breakout continuation", DefaultValue = true, Group = "SETUPS")]
        public bool EnableBreakout { get; set; }

        [Parameter("C - Trend pullback", DefaultValue = true, Group = "SETUPS")]
        public bool EnablePullback { get; set; }

        [Parameter("D - Momentum expansion", DefaultValue = true, Group = "SETUPS")]
        public bool EnableMomentum { get; set; }

        [Parameter("Min confluence score", DefaultValue = 55, MinValue = 0, MaxValue = 100, Step = 5, Group = "SETUPS")]
        public int MinScore { get; set; }

        // ---------------- EXECUTION ----------------
        [Parameter("Max spread (x ATR)", DefaultValue = 0.20, MinValue = 0.02, MaxValue = 1.0, Step = 0.01, Group = "EXECUTION")]
        public double MaxSpreadAtr { get; set; }

        [Parameter("Max spread (pips, 0 = off)", DefaultValue = 0, MinValue = 0, Group = "EXECUTION")]
        public double MaxSpreadPips { get; set; }

        [Parameter("Max slippage (x ATR)", DefaultValue = 0.15, MinValue = 0.01, MaxValue = 1.0, Step = 0.01, Group = "EXECUTION")]
        public double MaxSlippageAtr { get; set; }

        [Parameter("SL buffer (x ATR)", DefaultValue = 0.25, MinValue = 0, MaxValue = 1.5, Step = 0.05, Group = "EXECUTION")]
        public double SlBufferAtr { get; set; }

        [Parameter("Min SL (x ATR)", DefaultValue = 0.8, MinValue = 0.2, MaxValue = 3, Step = 0.1, Group = "EXECUTION")]
        public double MinSlAtr { get; set; }

        [Parameter("Max SL (x ATR)", DefaultValue = 3.5, MinValue = 1, MaxValue = 10, Step = 0.1, Group = "EXECUTION")]
        public double MaxSlAtr { get; set; }

        [Parameter("Cooldown bars", DefaultValue = 3, MinValue = 0, MaxValue = 50, Group = "EXECUTION")]
        public int CooldownBars { get; set; }

        [Parameter("Max trades per day", DefaultValue = 12, MinValue = 1, MaxValue = 100, Group = "EXECUTION")]
        public int MaxTradesPerDay { get; set; }

        [Parameter("Max concurrent positions", DefaultValue = 1, MinValue = 1, MaxValue = 5, Group = "EXECUTION")]
        public int MaxConcurrentPositions { get; set; }

        // ---------------- EXITS ----------------
        [Parameter("TP1 (R)", DefaultValue = 0.8, MinValue = 0.2, MaxValue = 3, Step = 0.1, Group = "EXITS")]
        public double Tp1R { get; set; }

        [Parameter("TP1 close (%)", DefaultValue = 40, MinValue = 0, MaxValue = 90, Step = 5, Group = "EXITS")]
        public double Tp1ClosePct { get; set; }

        [Parameter("TP2 (R)", DefaultValue = 1.5, MinValue = 0.3, MaxValue = 5, Step = 0.1, Group = "EXITS")]
        public double Tp2R { get; set; }

        [Parameter("TP2 close (%)", DefaultValue = 30, MinValue = 0, MaxValue = 90, Step = 5, Group = "EXITS")]
        public double Tp2ClosePct { get; set; }

        [Parameter("TP3 runner (R)", DefaultValue = 3.0, MinValue = 0.5, MaxValue = 10, Step = 0.1, Group = "EXITS")]
        public double Tp3R { get; set; }

        [Parameter("Stop after TP1 (R)", DefaultValue = -0.3, MinValue = -0.9, MaxValue = 1, Step = 0.05, Group = "EXITS")]
        public double StopAfterTp1R { get; set; }

        [Parameter("Stop after TP2 (R)", DefaultValue = 0.4, MinValue = -0.5, MaxValue = 2, Step = 0.05, Group = "EXITS")]
        public double StopAfterTp2R { get; set; }

        [Parameter("Trail start (R)", DefaultValue = 1.8, MinValue = 0.5, MaxValue = 6, Step = 0.1, Group = "EXITS")]
        public double TrailStartR { get; set; }

        [Parameter("Trail distance (x ATR)", DefaultValue = 2.0, MinValue = 0.5, MaxValue = 6, Step = 0.1, Group = "EXITS")]
        public double TrailAtr { get; set; }

        [Parameter("Max bars in trade (time stop)", DefaultValue = 36, MinValue = 3, MaxValue = 1000, Group = "EXITS")]
        public int MaxBarsInTrade { get; set; }

        // ---------------- SAFETY ----------------
        [Parameter("Max daily loss (%)", DefaultValue = 2.0, MinValue = 0.25, MaxValue = 10, Step = 0.25, Group = "SAFETY")]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Max weekly loss (%)", DefaultValue = 4.0, MinValue = 0.5, MaxValue = 20, Step = 0.5, Group = "SAFETY")]
        public double MaxWeeklyLossPercent { get; set; }

        [Parameter("Max consecutive losses (per day)", DefaultValue = 5, MinValue = 1, MaxValue = 30, Group = "SAFETY")]
        public int MaxConsecutiveLosses { get; set; }

        [Parameter("Flatten before weekend", DefaultValue = true, Group = "SAFETY")]
        public bool FlattenBeforeWeekend { get; set; }

        [Parameter("EMERGENCY STOP (no new trades)", DefaultValue = false, Group = "SAFETY")]
        public bool EmergencyStop { get; set; }

        [Parameter("Close all on emergency stop", DefaultValue = false, Group = "SAFETY")]
        public bool CloseAllOnEmergency { get; set; }

        // ---------------- DEBUG ----------------
        [Parameter("Enable debug logs", DefaultValue = false, Group = "DEBUG")]
        public bool EnableDebugLogs { get; set; }

        private const int RetryDelaySeconds = 10;
        private GoldEngine _engine;
        private EngineConfig _cfg;
        private SymbolSpec _spec;
        private string _label;
        private readonly Dictionary<long, ManagedPosition> _managed = new Dictionary<long, ManagedPosition>();
        private readonly Dictionary<long, string> _exitReasons = new Dictionary<long, string>();
        private readonly Dictionary<long, DateTime> _retryAfter = new Dictionary<long, DateTime>();
        private readonly List<ClosedTrade> _sessionTrades = new List<ClosedTrade>();
        private int _executionFailures;
        private string _lastDebug;

        // =============================== CYCLE DE VIE ===============================
        protected override void OnStart()
        {
            _label = "GLE_" + SymbolName + "_" + InstanceTag;
            _cfg = BuildConfig();
            _spec = BuildSymbolSpec();

            var errors = _cfg.Validate().Concat(_spec.Validate()).ToList();
            if (errors.Count > 0)
            {
                foreach (var e in errors) Print("ERREUR DE PARAMÈTRE : " + e);
                Stop();
                return;
            }

            _engine = new GoldEngine(_cfg);
            LogStartup();
            WarmUp();
            RecoverPositions();
            Positions.Closed += OnPositionClosed;

            if (EmergencyStop && CloseAllOnEmergency) CloseAllBotPositions("EMERGENCY STOP");
        }

        protected override void OnBar()
        {
            try
            {
                SyncClosedBars();
                ReconcilePositions();
                ManageOnBarClose();
                TryEnter();
            }
            catch (Exception ex)
            {
                Print("ERREUR OnBar : " + ex.GetType().Name + " " + ex.Message);
            }
        }

        protected override void OnTick()
        {
            if (_managed.Count == 0) return;
            try
            {
                ManageOnTick();
            }
            catch (Exception ex)
            {
                Print("ERREUR OnTick : " + ex.GetType().Name + " " + ex.Message);
            }
        }

        protected override void OnStop()
        {
            if (_spec == null) return;
            var all = LoadClosedTrades();
            Print(PerformanceStats.From(all, Account.Balance - all.Sum(t => t.NetProfit)).Summary(_spec.AccountCurrency));
        }

        // =============================== CONFIGURATION ===============================
        private EngineConfig BuildConfig()
        {
            return new EngineConfig
            {
                SignalTfMinutes = TimeframeMinutes(),
                RiskPercent = RiskPercent, MaxOpenRiskPercent = MaxOpenRiskPercent,
                TradeAsia = TradeAsia, TradeLondon = TradeLondon, TradeNewYork = TradeNewYork,
                AvoidRollover = AvoidRollover, AvoidFridayClose = AvoidFridayClose,
                AdxTrend = AdxTrend, AdxRange = AdxRange, HighVolRatio = HighVolRatio, LowVolRatio = LowVolRatio,
                EnableSweep = EnableSweep, EnableBreakout = EnableBreakout, EnablePullback = EnablePullback, EnableMomentum = EnableMomentum,
                MinScore = MinScore,
                MaxSpreadAtr = MaxSpreadAtr, MaxSpreadPips = MaxSpreadPips, MaxSlippageAtr = MaxSlippageAtr,
                SlBufferAtr = SlBufferAtr, MinSlAtr = MinSlAtr, MaxSlAtr = MaxSlAtr,
                CooldownBars = CooldownBars, MaxTradesPerDay = MaxTradesPerDay, MaxConcurrentPositions = MaxConcurrentPositions,
                Tp1R = Tp1R, Tp1ClosePct = Tp1ClosePct, Tp2R = Tp2R, Tp2ClosePct = Tp2ClosePct, Tp3R = Tp3R,
                StopAfterTp1R = StopAfterTp1R, StopAfterTp2R = StopAfterTp2R, TrailStartR = TrailStartR, TrailAtr = TrailAtr,
                MaxBarsInTrade = MaxBarsInTrade,
                MaxDailyLossPercent = MaxDailyLossPercent, MaxWeeklyLossPercent = MaxWeeklyLossPercent,
                MaxConsecutiveLosses = MaxConsecutiveLosses, EmergencyStop = EmergencyStop,
                FlattenBeforeWeekend = FlattenBeforeWeekend,
            };
        }

        private int TimeframeMinutes()
        {
            if (TimeFrame == TimeFrame.Minute) return 1;
            if (TimeFrame == TimeFrame.Minute2) return 2;
            if (TimeFrame == TimeFrame.Minute3) return 3;
            if (TimeFrame == TimeFrame.Minute5) return 5;
            if (TimeFrame == TimeFrame.Minute15) return 15;
            return 0; // rejeté par Validate()
        }

        private SymbolSpec BuildSymbolSpec()
        {
            return new SymbolSpec
            {
                Name = SymbolName,
                AccountCurrency = Account.Asset.Name,
                TickSize = Symbol.TickSize, TickValue = Symbol.TickValue, PipSize = Symbol.PipSize,
                VolumeMin = Symbol.VolumeInUnitsMin, VolumeMax = Symbol.VolumeInUnitsMax, VolumeStep = Symbol.VolumeInUnitsStep,
                Digits = Symbol.Digits,
            };
        }

        private void LogStartup()
        {
            Print("GoldLiveEngine démarré | label " + _label + " | compte " + (Account.IsLive ? "LIVE" : "DEMO") + " " + Account.BrokerName
                  + " | devise " + _spec.AccountCurrency + " | TF M" + _cfg.SignalTfMinutes);
            Print("Symbole " + SymbolName + " : TickSize " + Symbol.TickSize + ", TickValue " + Symbol.TickValue + ", PipSize " + Symbol.PipSize
                  + ", PipValue " + Symbol.PipValue + ", Vol min/step/max " + Symbol.VolumeInUnitsMin + "/" + Symbol.VolumeInUnitsStep + "/" + Symbol.VolumeInUnitsMax
                  + ", LotSize " + Symbol.LotSize + ", Digits " + Symbol.Digits);
            double viaPip = Symbol.PipValue / Symbol.PipSize, viaTick = _spec.ValuePerPriceUnit;
            if (viaTick > 0 && Math.Abs(viaPip - viaTick) / viaTick > 0.01)
                Print("ATTENTION : PipValue/PipSize (" + viaPip + ") et TickValue/TickSize (" + viaTick + ") divergent. Vérifier le sizing sur démo.");
            if (!SymbolName.ToUpperInvariant().Contains("XAU") && !SymbolName.ToUpperInvariant().Contains("GOLD"))
                Print("ATTENTION : ce moteur est conçu pour XAUUSD, symbole actuel " + SymbolName);
            if (_engine.Clock.UsingFallback)
                Print("ATTENTION : fuseaux Londres/New York introuvables, horaires de session approximatifs (heure d'hiver).");
        }

        // =============================== DONNÉES ===============================
        private void WarmUp()
        {
            int attempts = 0;
            while (Bars.Count - 1 < _cfg.WarmupBars && attempts++ < 20)
            {
                if (Bars.LoadMoreHistory() <= 0) break;
            }
            SyncClosedBars();
            Print("Warm-up : " + (Bars.Count - 1) + " bougies clôturées chargées (" + _cfg.WarmupBars + " requises). Prêt : " + _engine.Data.IsReady);
        }

        /// <summary>Ajoute toutes les bougies clôturées non encore vues (gère les reconnexions).</summary>
        private void SyncClosedBars()
        {
            int lastClosed = Bars.Count - 2;
            if (lastClosed < 0) return;
            DateTime known = _engine.Data.LastOpenTime;
            int start = lastClosed;
            while (start > 0 && Bars.OpenTimes[start - 1] > known) start--;
            for (int i = start; i <= lastClosed; i++)
            {
                var b = Bars[i];
                if (b.OpenTime <= known) continue;
                _engine.Data.Append(new Candle(b.OpenTime, b.Open, b.High, b.Low, b.Close, b.TickVolume));
            }
        }

        // =============================== POSITIONS / RESTART ===============================
        private IEnumerable<Position> BotPositions()
        {
            return Positions.Where(p => p.Label == _label && p.SymbolName == SymbolName);
        }

        private void RecoverPositions()
        {
            foreach (var p in BotPositions()) Track(p, true);
            if (_managed.Count > 0) Print("Reprise de " + _managed.Count + " position(s) existante(s) après redémarrage.");
        }

        private void ReconcilePositions()
        {
            var live = BotPositions().ToList();
            foreach (var p in live)
            {
                if (!_managed.ContainsKey(p.Id)) Track(p, true);
                else Refresh(_managed[p.Id], p);
            }
            foreach (var id in _managed.Keys.Where(id => live.All(p => p.Id != id)).ToList()) _managed.Remove(id);
        }

        private void Track(Position p, bool recovered)
        {
            SetupType setup; int score; double riskDist, initialUnits;
            var mp = new ManagedPosition
            {
                Id = p.Id, Side = p.TradeType == TradeType.Buy ? Side.Buy : Side.Sell,
                Entry = p.EntryPrice, EntryUtc = DateTime.SpecifyKind(p.EntryTime, DateTimeKind.Utc),
            };
            if (PositionTag.TryDecode(p.Comment, out setup, out score, out riskDist, out initialUnits))
            {
                mp.Setup = setup; mp.Score = score; mp.RiskDistance = riskDist; mp.InitialUnits = initialUnits;
            }
            else
            {
                mp.RiskDistance = p.StopLoss.HasValue ? Math.Abs(p.EntryPrice - p.StopLoss.Value) : 0;
                mp.InitialUnits = p.VolumeInUnits;
                Print("ATTENTION : commentaire illisible sur la position " + p.Id + ", R reconstruit depuis le SL (" + mp.RiskDistance + ").");
            }
            Refresh(mp, p);
            if (recovered) RecomputeBestPrice(mp);
            _managed[p.Id] = mp;
            EnsureStopLoss(mp, p);
        }

        private static void Refresh(ManagedPosition mp, Position p)
        {
            mp.Units = p.VolumeInUnits;
            mp.Stop = p.StopLoss;
        }

        private void RecomputeBestPrice(ManagedPosition mp)
        {
            mp.BestPrice = mp.Entry;
            for (int i = Bars.Count - 1; i >= 0 && Bars.OpenTimes[i] >= mp.EntryUtc; i--)
                mp.UpdateBest(mp.Side == Side.Buy ? Bars.HighPrices[i] : Bars.LowPrices[i]);
        }

        /// <summary>Une position sans stop est un risque illimité : on le remet, sinon on ferme.</summary>
        private void EnsureStopLoss(ManagedPosition mp, Position p)
        {
            if (p.StopLoss.HasValue) return;
            if (mp.RiskDistance <= 0)
            {
                Print("SÉCURITÉ : position " + p.Id + " sans SL ni R connu -> clôture.");
                CloseAndRecord(p, "sécurité : aucun stop");
                return;
            }
            double sl = _spec.RoundPrice(mp.PriceAtR(-1));
            var res = p.ModifyStopLossPrice(sl);
            if (!res.IsSuccessful)
            {
                Print("SÉCURITÉ : impossible de poser le SL sur " + p.Id + " (" + res.Error + ") -> clôture.");
                CloseAndRecord(p, "sécurité : SL impossible");
            }
        }

        // =============================== ENTRÉE ===============================
        private void TryEnter()
        {
            if (!_engine.Data.IsReady) { Debug("warm-up en cours"); return; }
            if (!Symbol.IsTradingEnabled || !Symbol.MarketHours.IsOpened()) { Debug("marché fermé"); return; }

            var deals = LoadRealizedDeals();
            var ctx = new EntryContext
            {
                Bid = Symbol.Bid, Ask = Symbol.Ask, Symbol = _spec,
                OpenPositions = _managed.Values.ToList(),
                Safety = SafetyEngine.Check(new SafetyInput
                {
                    NowUtc = Server.Time, Balance = Account.Balance,
                    OpenPnL = BotPositions().Sum(p => p.NetProfit),
                    Deals = deals, OpenPositionIds = new HashSet<long>(_managed.Keys),
                    ExecutionFailures = _executionFailures,
                }, _cfg),
                TradesToday = CountTradesToday(deals),
                LastExitUtc = deals.Count > 0 ? deals.Max(d => d.CloseUtc) : (DateTime?)null,
            };

            var decision = _engine.Evaluate(ctx);
            if (!decision.Take) { Debug(decision.Reason); return; }
            Execute(decision, ctx);
        }

        private void Execute(EntryDecision d, EntryContext ctx)
        {
            var side = d.Signal.Side;
            double fillRef = side == Side.Buy ? Symbol.Ask : Symbol.Bid;
            // Buy : SL touché au BID -> distance = ask - stop. Sell : SL touché à l'ASK -> distance = stop + spread - bid.
            double stopDist = side == Side.Buy ? Symbol.Ask - d.Signal.StopLevel : d.Signal.StopLevel + Symbol.Spread - Symbol.Bid;
            if (stopDist <= 0 || stopDist > _cfg.MaxSlAtr * d.Atr * 1.2)
            {
                Print("Entrée annulée : le prix a dépassé le stop structurel avant exécution.");
                return;
            }

            RefreshTickValue();
            double openRisk = _managed.Values.Sum(p => p.OpenRiskMoney(_spec));
            var size = RiskEngine.Size(Account.Equity, stopDist, openRisk, _spec, _cfg);
            if (!size.Ok) { Print("Signal " + d.Signal.Type + " ignoré : " + size.Reason); return; }

            double slPips = stopDist / Symbol.PipSize;
            double tpPips = _cfg.Tp3R * stopDist / Symbol.PipSize;
            double rangePips = Math.Max(1, _cfg.MaxSlippageAtr * d.Atr / Symbol.PipSize);
            string comment = PositionTag.Encode(d.Signal.Type, d.Score.Score, stopDist, size.Units);
            var type = side == Side.Buy ? TradeType.Buy : TradeType.Sell;

            _engine.MarkEntryAttempt(); // avant l'envoi : même un timeout ne peut pas provoquer un doublon sur cette bougie
            var result = ExecuteMarketRangeOrder(type, SymbolName, size.Units, rangePips, fillRef, _label, slPips, tpPips, comment);
            if (!result.IsSuccessful || result.Position == null)
            {
                _executionFailures++;
                Print("ORDRE REFUSÉ (" + _executionFailures + "/" + _cfg.MaxExecutionFailures + ") : " + result.Error);
                return;
            }
            _executionFailures = 0;
            Track(result.Position, false);
            _managed[result.Position.Id].BestPrice = result.Position.EntryPrice;
            _managed[result.Position.Id].Regime = d.Regime.Regime.ToString();
            LogEntry(result.Position, d, size, stopDist);
        }

        /// <summary>
        /// Symbol.TickValue est figé au démarrage du cBot : sur un compte non-USD il dérive avec le taux de change.
        /// On reconvertit donc la valeur d'un tick (devise de cotation -> devise du compte) juste avant chaque ordre.
        /// </summary>
        private void RefreshTickValue()
        {
            double live = double.NaN;
            try { live = Symbol.QuoteAsset.Convert(Account.Asset, Symbol.TickSize); }
            catch (Exception ex) { Debug("conversion QuoteAsset impossible : " + ex.Message); }
            if (!(live > 0) || double.IsInfinity(live)) { _spec.TickValue = Symbol.TickValue; return; }
            if (Math.Abs(live / Symbol.TickValue - 1) > 0.25)
                Print("ATTENTION : TickValue converti (" + live + ") très différent de Symbol.TickValue (" + Symbol.TickValue + "), valeur prudente retenue.");
            _spec.TickValue = Math.Abs(live / Symbol.TickValue - 1) > 0.25 ? Math.Max(live, Symbol.TickValue) : live;
        }

        private int CountTradesToday(List<RealizedDeal> deals)
        {
            DateTime day = Server.Time.Date;
            var ids = new HashSet<long>(BotPositions().Where(p => p.EntryTime >= day).Select(p => (long)p.Id));
            foreach (var t in History.Where(h => h.Label == _label && h.EntryTime >= day)) ids.Add(t.PositionId);
            return ids.Count;
        }

        // =============================== GESTION DES POSITIONS ===============================
        private void ManageOnTick()
        {
            foreach (var p in BotPositions().ToList())
            {
                ManagedPosition mp;
                if (!_managed.TryGetValue(p.Id, out mp) || !CanActNow(p.Id)) continue;
                Refresh(mp, p);
                double exitPrice = mp.Side == Side.Buy ? Symbol.Bid : Symbol.Ask;
                Apply(p, mp, ExitEngine.OnPrice(mp, exitPrice, _cfg, _spec, MinStopGap()));
            }
        }

        private void ManageOnBarClose()
        {
            if (_engine.MustFlattenForWeekend())
            {
                if (_managed.Count > 0) CloseAllBotPositions("clôture avant le week-end");
                return;
            }
            foreach (var p in BotPositions().ToList())
            {
                ManagedPosition mp;
                if (!_managed.TryGetValue(p.Id, out mp)) continue;
                Refresh(mp, p);
                EnsureStopLoss(mp, p);
                double exitPrice = mp.Side == Side.Buy ? Symbol.Bid : Symbol.Ask;
                Apply(p, mp, ExitEngine.OnBarClosed(mp, _engine.Data, _cfg, _spec, exitPrice, MinStopGap()));
            }
        }

        private double MinStopGap() { return Math.Max(Symbol.Spread, 2 * Symbol.TickSize); }

        private bool CanActNow(long id)
        {
            DateTime until;
            return !_retryAfter.TryGetValue(id, out until) || Server.Time >= until;
        }

        private void Apply(Position p, ManagedPosition mp, List<ExitAction> actions)
        {
            foreach (var a in actions)
            {
                TradeResult res;
                if (a.Kind == ExitKind.PartialClose)
                {
                    res = ClosePosition(p, a.Units);
                    if (res.IsSuccessful) Print("PARTIAL | #" + p.Id + " | " + a.Reason + " | " + a.Units + " unités @ " + (mp.Side == Side.Buy ? Symbol.Bid : Symbol.Ask));
                }
                else if (a.Kind == ExitKind.MoveStop)
                {
                    res = p.ModifyStopLossPrice(_spec.RoundPrice(a.Price));
                    if (res.IsSuccessful) Debug("SL #" + p.Id + " -> " + _spec.RoundPrice(a.Price) + " (" + a.Reason + ")");
                }
                else
                {
                    res = CloseAndRecord(p, a.Reason);
                }

                if (!res.IsSuccessful)
                {
                    _retryAfter[p.Id] = Server.Time.AddSeconds(RetryDelaySeconds);
                    Print("Action " + a.Kind + " échouée sur #" + p.Id + " : " + res.Error + " (nouvel essai dans " + RetryDelaySeconds + " s)");
                    return;
                }
                if (a.Kind == ExitKind.CloseAll) return;
                Refresh(mp, p);
            }
        }

        private TradeResult CloseAndRecord(Position p, string reason)
        {
            _exitReasons[p.Id] = reason;
            return ClosePosition(p);
        }

        private void CloseAllBotPositions(string reason)
        {
            foreach (var p in BotPositions().ToList()) CloseAndRecord(p, reason);
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var p = args.Position;
            if (p.Label != _label || p.SymbolName != SymbolName) return;
            ManagedPosition mp;
            _managed.TryGetValue(p.Id, out mp);
            string reason;
            if (!_exitReasons.TryGetValue(p.Id, out reason)) reason = DescribeCloseReason(args.Reason, mp);

            var trade = BuildClosedTrade(p.Id, mp);
            if (trade != null)
            {
                _sessionTrades.Add(trade);
                Print("EXIT  | #" + p.Id + " | " + trade.Setup + " " + Num.Name(trade.Side) + " | raison : " + reason
                      + " | PnL net " + Num.F(trade.NetProfit) + " " + _spec.AccountCurrency + " | " + Num.F(trade.RMultiple, 2) + " R");
            }
            _managed.Remove(p.Id);
            _exitReasons.Remove(p.Id);
            _retryAfter.Remove(p.Id);
        }

        private string DescribeCloseReason(PositionCloseReason reason, ManagedPosition mp)
        {
            if (reason == PositionCloseReason.TakeProfit) return "TP3 (runner)";
            if (reason == PositionCloseReason.StopOut) return "STOP OUT du broker";
            if (reason == PositionCloseReason.StopLoss)
                return mp != null && mp.Stop.HasValue && mp.R(mp.Stop.Value) > -0.99 ? "stop verrouillé / trailing" : "stop loss initial";
            return "clôture externe (manuelle ou autre)";
        }

        // =============================== HISTORIQUE ===============================
        private List<RealizedDeal> LoadRealizedDeals()
        {
            return History.Where(h => h.Label == _label && h.SymbolName == SymbolName)
                .Select(h => new RealizedDeal { PositionId = h.PositionId, CloseUtc = DateTime.SpecifyKind(h.ClosingTime, DateTimeKind.Utc), NetProfit = h.NetProfit })
                .ToList();
        }

        private List<ClosedTrade> LoadClosedTrades()
        {
            var open = new HashSet<long>(BotPositions().Select(p => (long)p.Id));
            return History.Where(h => h.Label == _label && h.SymbolName == SymbolName && !open.Contains(h.PositionId))
                .GroupBy(h => (long)h.PositionId)
                .Select(g => BuildClosedTrade(g.Key, null))
                .Where(t => t != null)
                .ToList();
        }

        private ClosedTrade BuildClosedTrade(long positionId, ManagedPosition mp)
        {
            var chunks = History.Where(h => h.PositionId == positionId && h.Label == _label).ToList();
            if (chunks.Count == 0) return null;
            var first = chunks[0];
            SetupType setup; int score; double riskDist, initialUnits;
            bool tagged = PositionTag.TryDecode(first.Comment, out setup, out score, out riskDist, out initialUnits);
            if (!tagged && mp != null) { setup = mp.Setup; riskDist = mp.RiskDistance; initialUnits = mp.InitialUnits; }
            return new ClosedTrade
            {
                PositionId = positionId,
                EntryUtc = first.EntryTime, CloseUtc = chunks.Max(h => h.ClosingTime),
                Side = first.TradeType == TradeType.Buy ? Side.Buy : Side.Sell,
                Setup = setup,
                NetProfit = chunks.Sum(h => h.NetProfit),
                RiskMoney = riskDist * initialUnits * _spec.ValuePerPriceUnit,
            };
        }

        // =============================== JOURNAL ===============================
        private void LogEntry(Position p, EntryDecision d, SizingResult size, double stopDist)
        {
            var mp = _managed[p.Id];
            Print(string.Join(" | ", new[]
            {
                "ENTRY #" + p.Id, Server.Time.ToString("yyyy-MM-dd HH:mm"), d.Signal.Type.ToString(), Num.Name(d.Signal.Side),
                "entry " + p.EntryPrice, "SL " + (p.StopLoss.HasValue ? p.StopLoss.Value.ToString() : "?"),
                "TP1 " + _spec.RoundPrice(mp.PriceAtR(_cfg.Tp1R)) + " TP2 " + _spec.RoundPrice(mp.PriceAtR(_cfg.Tp2R)) + " TP3 " + (p.TakeProfit.HasValue ? p.TakeProfit.Value.ToString() : "?"),
                "risque " + Num.F(size.RiskMoney) + " " + _spec.AccountCurrency + " (" + _cfg.RiskPercent + " %, R=" + Num.F(stopDist, 2) + ")",
                "volume " + size.Units + " (" + Symbol.VolumeInUnitsToQuantity(size.Units) + " lots)",
                "spread " + Num.F(d.Spread, 2), "ATR " + Num.F(d.Atr, 2), "ADX " + Num.F(d.Regime.Adx, 1),
                "régime " + d.Regime, "session " + d.Session.Name, "score " + d.Score.Score,
                "confluences [" + d.Score + "]", "raison : " + d.Reason,
            }));
        }

        private void Debug(string message)
        {
            if (!EnableDebugLogs || message == _lastDebug) return;
            _lastDebug = message;
            Print("[debug] " + message);
        }
    }
}
#endif
