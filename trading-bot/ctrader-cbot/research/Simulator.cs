using System;
using System.Collections.Generic;
using System.Linq;
using GoldLive.Core;

namespace GoldLive.Research
{
    /// <summary>Coûts de transaction simulés (en unités de prix / devise du compte, compte en USD).</summary>
    public sealed class SimCosts
    {
        public double Spread = 0.25;             // spread moyen XAUUSD en $ (à adapter à TON broker)
        public double Slippage = 0.03;           // glissement défavorable sur ordres au marché et stops
        public double CommissionPerUnit = 0.07;  // aller-retour par once (7 $ par lot de 100 oz)

        public SimCosts Scaled(double spreadFactor, double slippage)
        {
            return new SimCosts { Spread = Spread * spreadFactor, Slippage = slippage, CommissionPerUnit = CommissionPerUnit };
        }
    }

    public sealed class SimResult
    {
        public List<ClosedTrade> Trades = new List<ClosedTrade>();
        public List<string> EntryLog = new List<string>();
        public double StartEquity, EndEquity, MaxDrawdownPct;
    }

    /// <summary>
    /// Broker simulé volontairement pessimiste :
    ///  - bougies = prix BID ; achat au ASK (bid + spread), vente clôturée au ASK ;
    ///  - entrée à l'ouverture de la bougie SUIVANT le signal (+ slippage) ;
    ///  - si le stop et un TP sont atteints dans la même bougie : le STOP est supposé touché d'abord ;
    ///  - après un TP partiel, si la bougie a aussi touché le nouveau stop verrouillé : on le suppose touché ;
    ///  - gaps : un stop dépassé à l'ouverture est exécuté au prix d'ouverture.
    /// </summary>
    public sealed class Simulator
    {
        private sealed class SimPosition
        {
            public ManagedPosition P;
            public double Realized, RiskMoney, Tp3;
        }

        private readonly EngineConfig _cfg;
        private readonly SimCosts _costs;
        private readonly SymbolSpec _spec;
        private readonly GoldEngine _engine;
        private readonly List<SimPosition> _open = new List<SimPosition>();
        private readonly List<RealizedDeal> _deals = new List<RealizedDeal>();
        private readonly SimResult _result = new SimResult();
        private double _balance;
        private long _nextId = 1;
        private int _dealsFrom;

        public Simulator(EngineConfig cfg, SimCosts costs, double startEquity)
        {
            _cfg = cfg;
            _costs = costs;
            _spec = new SymbolSpec { TickSize = 0.01, TickValue = 0.01, PipSize = 0.01, VolumeMin = 1, VolumeStep = 1, VolumeMax = 100000, Digits = 2 };
            _engine = new GoldEngine(cfg);
            _balance = startEquity;
            _result.StartEquity = startEquity;
        }

        public static SimResult Run(IReadOnlyList<Candle> bars, EngineConfig cfg, SimCosts costs, DateTime from, DateTime to,
                                    double startEquity = 10000, int maxBars = int.MaxValue)
        {
            return new Simulator(cfg, costs, startEquity).RunInternal(bars, from, to, maxBars);
        }

        private SimResult RunInternal(IReadOnlyList<Candle> bars, DateTime from, DateTime to, int maxBars)
        {
            EntryDecision pending = null;
            double peak = _balance;
            int n = Math.Min(bars.Count, maxBars);
            for (int j = 0; j < n; j++)
            {
                var bar = bars[j];
                if (bar.OpenTimeUtc >= to && _open.Count == 0 && pending == null) break;
                if (pending != null) { Fill(pending, bar); pending = null; }
                foreach (var sp in _open.ToList()) Intrabar(sp, bar);
                if (!_engine.Data.Append(bar)) continue;
                if (_engine.MustFlattenForWeekend())
                    foreach (var sp in _open.ToList()) CloseChunk(sp, sp.P.Units, ExitPrice(sp.P, bar.Close) - sp.P.Dir * _costs.Slippage, bar.OpenTimeUtc);
                foreach (var sp in _open.ToList()) OnBarClosed(sp, bar);

                double equity = Equity(bar);
                peak = Math.Max(peak, equity);
                _result.MaxDrawdownPct = Math.Max(_result.MaxDrawdownPct, 100 * (peak - equity) / peak);

                bool inWindow = bar.OpenTimeUtc >= from && bar.OpenTimeUtc < to;
                if (inWindow) pending = Decide(bar);
            }
            if (n > 0) foreach (var sp in _open.ToList()) CloseChunk(sp, sp.P.Units, ExitPrice(sp.P, bars[n - 1].Close), bars[n - 1].OpenTimeUtc);
            _result.EndEquity = _balance;
            return _result;
        }

        private EntryDecision Decide(Candle bar)
        {
            var md = _engine.Data;
            DateTime now = md.LastCloseTime;
            var ctx = new EntryContext
            {
                Bid = bar.Close, Ask = bar.Close + _costs.Spread, Symbol = _spec,
                OpenPositions = _open.Select(o => o.P).ToList(),
                Safety = SafetyEngine.Check(new SafetyInput
                {
                    NowUtc = now, Balance = _balance, OpenPnL = Equity(bar) - _balance,
                    Deals = RecentDeals(now), OpenPositionIds = new HashSet<long>(_open.Select(o => o.P.Id)),
                }, _cfg),
                TradesToday = CountTradesToday(now.Date),
                LastExitUtc = _deals.Count > 0 ? _deals[_deals.Count - 1].CloseUtc : (DateTime?)null,
            };
            var d = _engine.Evaluate(ctx);
            if (!d.Take) return null;
            _engine.MarkEntryAttempt();
            _result.EntryLog.Add(md.LastOpenTime.ToString("u") + " " + d.Signal.Type + " " + d.Signal.Side + " " + d.Score.Score);
            return d;
        }

        /// <summary>Seules les transactions de la semaine en cours influencent le Safety Engine : évite un coût O(n²).</summary>
        private List<RealizedDeal> RecentDeals(DateTime now)
        {
            DateTime day = now.Date;
            DateTime weekStart = day.AddDays(-(((int)day.DayOfWeek + 6) % 7)).AddDays(-1);
            while (_dealsFrom < _deals.Count && _deals[_dealsFrom].CloseUtc < weekStart) _dealsFrom++;
            return _deals.GetRange(_dealsFrom, _deals.Count - _dealsFrom);
        }

        private int CountTradesToday(DateTime day)
        {
            int count = _open.Count(o => o.P.EntryUtc >= day);
            for (int i = _result.Trades.Count - 1; i >= 0 && _result.Trades[i].CloseUtc >= day; i--)
                if (_result.Trades[i].EntryUtc >= day) count++;
            return count;
        }

        private void Fill(EntryDecision d, Candle bar)
        {
            int dir = (int)d.Signal.Side;
            double fill = d.Signal.Side == Side.Buy ? bar.Open + _costs.Spread + _costs.Slippage : bar.Open - _costs.Slippage;
            double stopDist = d.Signal.Side == Side.Buy ? fill - d.Signal.StopLevel : d.Signal.StopLevel + _costs.Spread - fill;
            if (stopDist <= 0 || stopDist > _cfg.MaxSlAtr * d.Atr * 1.2) return; // gap au-delà du stop : entrée annulée

            double openRisk = _open.Sum(o => o.P.OpenRiskMoney(_spec));
            var size = RiskEngine.Size(_balance, stopDist, openRisk, _spec, _cfg);
            if (!size.Ok) return;

            var p = new ManagedPosition
            {
                Id = _nextId++, Side = d.Signal.Side, Setup = d.Signal.Type, Entry = fill, RiskDistance = stopDist,
                InitialUnits = size.Units, Units = size.Units, Stop = fill - dir * stopDist, EntryUtc = bar.OpenTimeUtc,
                BestPrice = fill, Score = d.Score.Score, Regime = d.Regime.Regime.ToString(),
            };
            _open.Add(new SimPosition { P = p, RiskMoney = size.RiskMoney, Tp3 = p.PriceAtR(_cfg.Tp3R) });
        }

        /// <summary>Prix de sortie côté position : BID pour un achat, ASK pour une vente.</summary>
        private double ExitPrice(ManagedPosition p, double bid) { return p.Side == Side.Buy ? bid : bid + _costs.Spread; }

        private void Intrabar(SimPosition sp, Candle bar)
        {
            var p = sp.P;
            int d = p.Dir;
            double open = ExitPrice(p, bar.Open);
            double adverse = ExitPrice(p, d == 1 ? bar.Low : bar.High);
            double favorable = ExitPrice(p, d == 1 ? bar.High : bar.Low);
            DateTime t = bar.OpenTimeUtc;

            if (p.Stop.HasValue && (open - p.Stop.Value) * d <= 0) { CloseChunk(sp, p.Units, open - d * _costs.Slippage, t); return; }
            if ((open - sp.Tp3) * d >= 0) { CloseChunk(sp, p.Units, open, t); return; }
            if (p.Stop.HasValue && (adverse - p.Stop.Value) * d <= 0) { CloseChunk(sp, p.Units, p.Stop.Value - d * _costs.Slippage, t); return; }

            double? stopBefore = p.Stop;
            foreach (var a in ExitEngine.OnPrice(p, favorable, _cfg, _spec, _costs.Spread))
            {
                if (a.Kind == ExitKind.PartialClose) CloseChunk(sp, a.Units, a.Price - d * _costs.Slippage, t);
                else if (a.Kind == ExitKind.MoveStop) p.Stop = a.Price;
                else { CloseChunk(sp, p.Units, WorseOf(p, a.Price, p.Stop ?? a.Price), t); return; }
                if (!_open.Contains(sp)) return;
            }
            if ((favorable - sp.Tp3) * d >= 0) { CloseChunk(sp, p.Units, sp.Tp3, t); return; }
            bool stopMoved = p.Stop != stopBefore;
            if (stopMoved && p.Stop.HasValue && (adverse - p.Stop.Value) * d <= 0) CloseChunk(sp, p.Units, p.Stop.Value - d * _costs.Slippage, t);
        }

        private static double WorseOf(ManagedPosition p, double a, double b)
        {
            return p.Side == Side.Buy ? Math.Min(a, b) : Math.Max(a, b);
        }

        private void OnBarClosed(SimPosition sp, Candle bar)
        {
            if (!_open.Contains(sp)) return;
            double exitNow = ExitPrice(sp.P, bar.Close);
            foreach (var a in ExitEngine.OnBarClosed(sp.P, _engine.Data, _cfg, _spec, exitNow, _costs.Spread))
            {
                if (a.Kind == ExitKind.MoveStop) sp.P.Stop = a.Price;
                else if (a.Kind == ExitKind.CloseAll) { CloseChunk(sp, sp.P.Units, exitNow - sp.P.Dir * _costs.Slippage, bar.OpenTimeUtc); return; }
            }
        }

        private void CloseChunk(SimPosition sp, double units, double price, DateTime barOpen)
        {
            var p = sp.P;
            units = Math.Min(units, p.Units);
            double pnl = (price - p.Entry) * p.Dir * units * _spec.ValuePerPriceUnit - units * _costs.CommissionPerUnit;
            DateTime closeTime = barOpen + _engine.Data.Timeframe;
            _balance += pnl;
            sp.Realized += pnl;
            p.Units -= units;
            _deals.Add(new RealizedDeal { PositionId = p.Id, CloseUtc = closeTime, NetProfit = pnl });
            if (p.Units > _spec.VolumeStep * 0.5) return;

            _open.Remove(sp);
            _result.Trades.Add(new ClosedTrade
            {
                PositionId = p.Id, EntryUtc = p.EntryUtc, CloseUtc = closeTime, Side = p.Side, Setup = p.Setup,
                NetProfit = sp.Realized, RiskMoney = sp.RiskMoney,
            });
        }

        private double Equity(Candle bar)
        {
            double floating = _open.Sum(o => (ExitPrice(o.P, bar.Close) - o.P.Entry) * o.P.Dir * o.P.Units * _spec.ValuePerPriceUnit);
            return _balance + floating;
        }
    }
}
