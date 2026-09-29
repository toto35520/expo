using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using GoldLive.Core;

namespace GoldLive.Research
{
    public sealed class Variant
    {
        public string Name;
        public EngineConfig Config;
        public SimCosts Costs;
        public Variant(string name, EngineConfig cfg, SimCosts costs) { Name = name; Config = cfg; Costs = costs; }
    }

    /// <summary>Découpage temporel : TRAIN (développement) / VALIDATION / OUT-OF-SAMPLE.</summary>
    public sealed class Splits
    {
        public DateTime Start, TrainEnd, ValEnd, End;

        public static Splits From(IReadOnlyList<Candle> bars, int valMonths, int oosMonths)
        {
            var s = new Splits { Start = bars[0].OpenTimeUtc, End = bars[bars.Count - 1].OpenTimeUtc.AddMinutes(1) };
            s.ValEnd = s.End.AddMonths(-oosMonths);
            s.TrainEnd = s.ValEnd.AddMonths(-valMonths);
            if (s.TrainEnd <= s.Start.AddMonths(6))
            {
                long span = (s.End - s.Start).Ticks;
                s.TrainEnd = s.Start.AddTicks(span / 2);
                s.ValEnd = s.Start.AddTicks(span * 3 / 4);
            }
            return s;
        }

        public override string ToString()
        {
            return "TRAIN " + D(Start) + " -> " + D(TrainEnd) + " | VALIDATION " + D(TrainEnd) + " -> " + D(ValEnd) + " | OOS " + D(ValEnd) + " -> " + D(End);
        }

        public static string D(DateTime t) { return t.ToString("yyyy-MM-dd"); }
    }

    public sealed class Analysis
    {
        private readonly IReadOnlyList<Candle> _bars;
        private readonly SimCosts _costs;
        private readonly double _equity;
        private readonly StringBuilder _out = new StringBuilder();
        private readonly ConcurrentDictionary<string, SimResult> _cache = new ConcurrentDictionary<string, SimResult>();
        public int VariantsTested { get { return _cache.Count; } }

        public Analysis(IReadOnlyList<Candle> bars, SimCosts costs, double equity)
        {
            _bars = bars; _costs = costs; _equity = equity;
        }

        public string Report { get { return _out.ToString(); } }

        public void Line(string s = "") { _out.AppendLine(s); Console.WriteLine(s); }

        // ------------------------------------------------------------------ exécution
        public Dictionary<string, SimResult> RunAll(IEnumerable<Variant> variants, DateTime? to = null)
        {
            var list = variants.ToList();
            DateTime end = to ?? DateTime.MaxValue;
            Parallel.ForEach(list, v =>
            {
                string key = v.Name + "|" + end.Ticks;
                _cache.GetOrAdd(key, _ => Simulator.Run(_bars, v.Config, v.Costs, DateTime.MinValue, end, _equity));
            });
            return list.ToDictionary(v => v.Name, v => _cache[v.Name + "|" + end.Ticks]);
        }

        public static List<ClosedTrade> Slice(IEnumerable<ClosedTrade> trades, DateTime from, DateTime to)
        {
            return trades.Where(t => t.EntryUtc >= from && t.EntryUtc < to).ToList();
        }

        // ------------------------------------------------------------------ tableaux
        public static string Header()
        {
            return string.Format(CultureInfo.InvariantCulture, "| {0,-34} | {1,6} | {2,6} | {3,6} | {4,8} | {5,9} | {6,7} | {7,7} | {8,6} |",
                "Période / variante", "Trades", "Win %", "PF", "Exp. R", "Net $", "MaxDD%", "RecFac", "MaxCL");
        }

        public static string Row(string name, List<ClosedTrade> trades, double startEquity)
        {
            var s = PerformanceStats.From(trades, startEquity);
            return string.Format(CultureInfo.InvariantCulture, "| {0,-34} | {1,6} | {2,6:F1} | {3,6:F2} | {4,8:F3} | {5,9:F0} | {6,7:F2} | {7,7:F2} | {8,6} |",
                name, s.Trades, s.WinRate, Math.Min(s.ProfitFactor, 99), s.ExpectancyR, s.NetProfit, s.MaxDrawdownPct, s.RecoveryFactor, s.MaxConsecutiveLosses);
        }

        public void YearByYear(string title, List<ClosedTrade> trades)
        {
            Line("### " + title + " — année par année");
            Line(Header());
            double eq = _equity;
            foreach (var g in trades.GroupBy(t => t.EntryUtc.Year).OrderBy(g => g.Key))
            {
                var yearTrades = g.ToList();
                Line(Row(g.Key.ToString(), yearTrades, eq));
                eq += yearTrades.Sum(t => t.NetProfit);
            }
            Line(Row("CUMULÉ", trades, _equity));
            var months = trades.GroupBy(t => new { t.EntryUtc.Year, t.EntryUtc.Month }).Select(g => g.Sum(t => t.NetProfit)).ToList();
            if (months.Count > 0)
                Line("Mois positifs : " + months.Count(m => m > 0) + " / " + months.Count + " (" + (100.0 * months.Count(m => m > 0) / months.Count).ToString("F0") + " %)");
            Line();
        }

        public void Splits(Splits sp, List<ClosedTrade> trades)
        {
            Line("### Découpage temporel");
            Line(sp.ToString());
            Line(Header());
            Line(Row("TRAIN (développement)", Slice(trades, sp.Start, sp.TrainEnd), _equity));
            Line(Row("VALIDATION", Slice(trades, sp.TrainEnd, sp.ValEnd), _equity));
            Line(Row("OUT-OF-SAMPLE", Slice(trades, sp.ValEnd, sp.End), _equity));
            Line();
        }

        public void PerSetup(List<ClosedTrade> trades)
        {
            Line("### Par setup (+ correction de Holm-Bonferroni, H0 : espérance en R <= 0)");
            Line(Header());
            var tests = new List<KeyValuePair<string, double>>();
            foreach (SetupType st in Enum.GetValues(typeof(SetupType)))
            {
                var sub = trades.Where(t => t.Setup == st).ToList();
                Line(Row(st.ToString(), sub, _equity));
                var s = PerformanceStats.From(sub, _equity);
                if (s.Trades >= 2) tests.Add(new KeyValuePair<string, double>(st.ToString(), Stats.OneSidedP(s.TStat)));
            }
            Line();
            foreach (var r in Stats.Holm(tests, 0.05))
                Line("- " + r.Name + " : p brut " + r.P.ToString("F4") + ", seuil Holm " + r.Threshold.ToString("F4") + " -> " + (r.Rejected ? "edge significative" : "NON significative"));
            Line();
        }

        public void Table(string title, Dictionary<string, SimResult> results, DateTime from, DateTime to, string baseline = null)
        {
            Line("### " + title);
            Line(Header());
            foreach (var kv in results) Line(Row(kv.Key, Slice(kv.Value.Trades, from, to), _equity));
            Line();
        }

        // ------------------------------------------------------------------ walk-forward
        public void WalkForward(Dictionary<string, SimResult> grid, int trainMonths, int testMonths, int minTrades)
        {
            Line("### Walk-forward (" + trainMonths + " mois d'optimisation / " + testMonths + " mois de test, critère : t-stat de l'espérance en R, min " + minTrades + " trades)");
            Line("| Fenêtre de test | Paramètres choisis | Trades train | Exp. R train | Trades test | Exp. R test |");
            Line("|---|---|---|---|---|---|");
            var oos = new List<ClosedTrade>();
            var chosen = new List<string>();
            DateTime start = _bars[0].OpenTimeUtc;
            DateTime end = _bars[_bars.Count - 1].OpenTimeUtc;
            for (DateTime testStart = start.AddMonths(trainMonths); testStart < end; testStart = testStart.AddMonths(testMonths))
            {
                DateTime trainStart = testStart.AddMonths(-trainMonths), testEnd = testStart.AddMonths(testMonths);
                var best = grid
                    .Select(kv => new { kv.Key, Stats = PerformanceStats.From(Slice(kv.Value.Trades, trainStart, testStart), _equity), All = kv.Value.Trades })
                    .Where(x => x.Stats.Trades >= minTrades)
                    .OrderByDescending(x => x.Stats.TStat)
                    .FirstOrDefault();
                if (best == null) { Line("| " + Splits_D(testStart) + " | aucun jeu avec assez de trades | | | | |"); continue; }
                var test = Slice(best.All, testStart, testEnd);
                var ts = PerformanceStats.From(test, _equity);
                oos.AddRange(test);
                chosen.Add(best.Key);
                Line("| " + Splits_D(testStart) + " -> " + Splits_D(testEnd) + " | " + best.Key + " | " + best.Stats.Trades + " | " + best.Stats.ExpectancyR.ToString("F3", CultureInfo.InvariantCulture)
                     + " | " + ts.Trades + " | " + ts.ExpectancyR.ToString("F3", CultureInfo.InvariantCulture) + " |");
            }
            Line();
            Line(Header());
            Line(Row("WALK-FORWARD OOS CONCATÉNÉ", oos, _equity));
            Line("Stabilité des paramètres : " + string.Join(", ", chosen.GroupBy(c => c).Select(g => g.Key + " x" + g.Count())));
            Line();
        }

        private static string Splits_D(DateTime t) { return GoldLive.Research.Splits.D(t); }

        // ------------------------------------------------------------------ Monte Carlo
        public void MonteCarlo(List<ClosedTrade> trades, double riskPct, int iterations, int seed)
        {
            Line("### Monte Carlo (" + iterations + " tirages, risque " + riskPct + " % par R)");
            if (trades.Count < 30) { Line("Pas assez de trades (" + trades.Count + ")."); Line(); return; }
            var r = trades.Select(t => t.RMultiple).ToArray();
            Line("| Scénario | Rendement P5 | P50 | P95 | MaxDD P50 | MaxDD P95 | P(DD >= 20 %) | P(DD >= 30 %) |");
            Line("|---|---|---|---|---|---|---|---|");
            McRow("Ordre des trades mélangé", r, riskPct, iterations, seed, 1.0, 0);
            McRow("10 % des trades supprimés", r, riskPct, iterations, seed + 1, 0.9, 0);
            McRow("Coût +0,05 R par trade", r, riskPct, iterations, seed + 2, 1.0, 0.05);
            McRow("Coût +0,10 R et 10 % supprimés", r, riskPct, iterations, seed + 3, 0.9, 0.10);
            Line();
        }

        private void McRow(string name, double[] r, double riskPct, int iterations, int seed, double keep, double costR)
        {
            var rng = new Random(seed);
            var finals = new double[iterations];
            var dds = new double[iterations];
            for (int i = 0; i < iterations; i++)
            {
                var sample = r.Where(_ => rng.NextDouble() < keep).OrderBy(_ => rng.Next()).ToArray();
                double eq = 1, peak = 1, dd = 0;
                foreach (var x in sample)
                {
                    eq *= 1 + (x - costR) * riskPct / 100;
                    peak = Math.Max(peak, eq);
                    dd = Math.Max(dd, (peak - eq) / peak);
                }
                finals[i] = (eq - 1) * 100;
                dds[i] = dd * 100;
            }
            Array.Sort(finals); Array.Sort(dds);
            Func<double[], double, double> q = (a, p) => a[Math.Min(a.Length - 1, (int)(p * a.Length))];
            Line(string.Format(CultureInfo.InvariantCulture, "| {0} | {1:F1} % | {2:F1} % | {3:F1} % | {4:F1} % | {5:F1} % | {6:F1} % | {7:F1} % |",
                name, q(finals, 0.05), q(finals, 0.5), q(finals, 0.95), q(dds, 0.5), q(dds, 0.95),
                100.0 * dds.Count(d => d >= 20) / iterations, 100.0 * dds.Count(d => d >= 30) / iterations));
        }
    }

    public static class Stats
    {
        public sealed class HolmResult { public string Name; public double P, Threshold; public bool Rejected; }

        /// <summary>p-value unilatérale (approximation normale, valable pour n grand).</summary>
        public static double OneSidedP(double t) { return 0.5 * Erfc(t / Math.Sqrt(2)); }

        public static List<HolmResult> Holm(List<KeyValuePair<string, double>> tests, double alpha)
        {
            var sorted = tests.OrderBy(t => t.Value).ToList();
            var res = new List<HolmResult>();
            bool stillRejecting = true;
            for (int i = 0; i < sorted.Count; i++)
            {
                double threshold = alpha / (sorted.Count - i);
                stillRejecting = stillRejecting && sorted[i].Value <= threshold;
                res.Add(new HolmResult { Name = sorted[i].Key, P = sorted[i].Value, Threshold = threshold, Rejected = stillRejecting });
            }
            return res;
        }

        // Numerical Recipes erfc (erreur < 1.2e-7)
        public static double Erfc(double x)
        {
            double z = Math.Abs(x), t = 1 / (1 + 0.5 * z);
            double r = t * Math.Exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807
                       + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
            return x >= 0 ? r : 2 - r;
        }
    }
}
