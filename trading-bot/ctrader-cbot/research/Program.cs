using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using GoldLive.Core;

namespace GoldLive.Research
{
    /// <summary>
    /// Usage :
    ///   dotnet run -c Release -- --csv ../../data/XAUUSD_M5.csv [--spread 0.25] [--slippage 0.03] [--commission 0.07]
    ///                            [--tf 5] [--val-months 24] [--oos-months 12] [--out report.md]
    ///   dotnet run -c Release -- --selftest
    ///   dotnet run -c Release -- --synthetic       (données ALÉATOIRES : vérifie la mécanique, ne dit RIEN sur l'edge)
    /// </summary>
    public static class Program
    {
        public static int Main(string[] args)
        {
            CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
            CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
            var opt = Options.Parse(args);
            if (opt.Has("selftest")) return SelfTest.Run();

            List<Candle> bars;
            string source;
            if (opt.Has("synthetic"))
            {
                bars = Synthetic.Generate(opt.Int("years", 3), opt.Int("seed", 42), 5);
                source = "DONNÉES SYNTHÉTIQUES (marche aléatoire à régimes, seed " + opt.Int("seed", 42) + ") — aucune valeur prédictive";
            }
            else if (opt.Has("csv"))
            {
                bars = CsvLoader.Load(opt.Str("csv"), opt.Int("tf", 5));
                source = opt.Str("csv");
            }
            else
            {
                Console.WriteLine("Précise --csv <fichier>, --synthetic ou --selftest");
                return 1;
            }
            if (bars.Count < 5000) { Console.WriteLine("Historique trop court : " + bars.Count + " bougies"); return 1; }

            var costs = new SimCosts { Spread = opt.Dbl("spread", 0.25), Slippage = opt.Dbl("slippage", 0.03), CommissionPerUnit = opt.Dbl("commission", 0.07) };
            var report = Research.Run(bars, costs, source, opt.Int("tf", 5), opt.Int("val-months", 24), opt.Int("oos-months", 12));
            string outPath = opt.Str("out", "report.md");
            File.WriteAllText(outPath, report);
            Console.WriteLine("Rapport écrit dans " + Path.GetFullPath(outPath));
            return 0;
        }
    }

    public static class Research
    {
        public static string Run(List<Candle> bars, SimCosts costs, string source, int tf, int valMonths, int oosMonths)
        {
            const double equity = 10000;
            var baseCfg = new EngineConfig { SignalTfMinutes = tf };
            var errors = baseCfg.Validate();
            if (errors.Count > 0) throw new InvalidOperationException(string.Join("; ", errors));

            var a = new Analysis(bars, costs, equity);
            var sp = Splits.From(bars, valMonths, oosMonths);
            a.Line("# GoldLiveEngine — rapport de recherche");
            a.Line();
            a.Line("- Source : " + source);
            a.Line("- Bougies : " + bars.Count + " (M" + tf + ") du " + Splits.D(bars[0].OpenTimeUtc) + " au " + Splits.D(bars[bars.Count - 1].OpenTimeUtc));
            a.Line("- Coûts : spread " + costs.Spread + " $, slippage " + costs.Slippage + " $, commission " + costs.CommissionPerUnit + " $/once aller-retour");
            a.Line("- Capital initial " + equity + " $, risque " + baseCfg.RiskPercent + " % par trade. Hypothèses d'exécution pessimistes (voir Simulator.cs).");
            a.Line();

            // 1. Configuration par défaut : aucun paramètre n'a été choisi en regardant ces données.
            var baseline = a.RunAll(new[] { new Variant("défaut", baseCfg, costs) })["défaut"];
            a.YearByYear("Configuration par défaut", baseline.Trades);
            a.Splits(sp, baseline.Trades);
            a.PerSetup(Analysis.Slice(baseline.Trades, sp.Start, sp.ValEnd));

            // 2. Ablation (sur TRAIN uniquement) : chaque filtre doit prouver son utilité.
            var ablation = new List<Variant> { new Variant("défaut", baseCfg, costs) };
            ablation.Add(V("sans score (MinScore 0)", baseCfg, c => c.MinScore = 0, costs));
            ablation.Add(V("sans contexte M15", baseCfg, c => c.UseHtfScore = false, costs));
            ablation.Add(V("toutes sessions (+Asie)", baseCfg, c => c.TradeAsia = true, costs));
            ablation.Add(V("sans TP partiels", baseCfg, c => { c.Tp1ClosePct = 0; c.Tp2ClosePct = 0; }, costs));
            ablation.Add(V("sans time stop", baseCfg, c => c.MaxBarsInTrade = 1000000, costs));
            ablation.Add(V("setup A seul (sweep)", baseCfg, c => Only(c, SetupType.LiquiditySweep), costs));
            ablation.Add(V("setup B seul (breakout)", baseCfg, c => Only(c, SetupType.BreakoutContinuation), costs));
            ablation.Add(V("setup C seul (pullback)", baseCfg, c => Only(c, SetupType.TrendPullback), costs));
            ablation.Add(V("setup D seul (momentum)", baseCfg, c => Only(c, SetupType.MomentumExpansion), costs));
            a.Table("Ablation des filtres et des setups (TRAIN uniquement)", a.RunAll(ablation, sp.TrainEnd), sp.Start, sp.TrainEnd);

            // 3. Sensibilité aux coûts (toute la période).
            var costVariants = new List<Variant>
            {
                new Variant("spread x1, slippage " + costs.Slippage, baseCfg, costs),
                new Variant("spread x1.5, slippage 0.10", baseCfg, costs.Scaled(1.5, 0.10)),
                new Variant("spread x2, slippage 0.20", baseCfg, costs.Scaled(2.0, 0.20)),
                new Variant("spread x3, slippage 0.30", baseCfg, costs.Scaled(3.0, 0.30)),
                V("x2 / 0.20, filtre spread OFF", baseCfg, c => c.MaxSpreadAtr = 10, costs.Scaled(2.0, 0.20)),
                V("x3 / 0.30, filtre spread OFF", baseCfg, c => c.MaxSpreadAtr = 10, costs.Scaled(3.0, 0.30)),
            };
            a.Table("Sensibilité aux coûts (toute la période ; filtre OFF = impact pur du coût sur les mêmes signaux)", a.RunAll(costVariants), sp.Start, sp.End);

            // 4. Plateaux de paramètres (TRAIN uniquement, un paramètre à la fois).
            Plateau(a, sp, baseCfg, costs, "MinScore", new[] { 35.0, 45, 55, 65, 75 }, (c, v) => c.MinScore = (int)v);
            Plateau(a, sp, baseCfg, costs, "SlBufferAtr", new[] { 0.10, 0.20, 0.25, 0.30, 0.40 }, (c, v) => c.SlBufferAtr = v);
            Plateau(a, sp, baseCfg, costs, "AdxTrend", new[] { 16.0, 19, 22, 25, 28 }, (c, v) => { c.AdxTrend = v; c.AdxRange = v - 4; });
            Plateau(a, sp, baseCfg, costs, "Tp1R", new[] { 0.5, 0.65, 0.8, 1.0, 1.2 }, (c, v) => c.Tp1R = v);
            Plateau(a, sp, baseCfg, costs, "MaxSpreadAtr", new[] { 0.10, 0.15, 0.20, 0.30, 0.40 }, (c, v) => c.MaxSpreadAtr = v);

            // 5. Walk-forward : grille volontairement petite (9 combinaisons).
            var grid = new List<Variant>();
            foreach (var score in new[] { 45, 55, 65 })
                foreach (var tp1 in new[] { 0.6, 0.8, 1.0 })
                    grid.Add(V("score " + score + " / TP1 " + tp1 + "R", baseCfg, c => { c.MinScore = score; c.Tp1R = tp1; }, costs));
            a.WalkForward(a.RunAll(grid), 24, 6, 60);

            // 6. Monte Carlo sur les trades hors TRAIN (validation + OOS).
            a.MonteCarlo(Analysis.Slice(baseline.Trades, sp.TrainEnd, sp.End), baseCfg.RiskPercent, 5000, 7);

            a.Line("### Data mining");
            a.Line("- Variantes simulées dans ce rapport : " + a.VariantsTested + ". Ne retiens PAS la meilleure ligne d'un tableau : cherche des plateaux,");
            a.Line("  et juge une modification uniquement sur VALIDATION puis OOS, jamais sur la période où elle a été choisie.");
            return a.Report;
        }

        private static void Plateau(Analysis a, Splits sp, EngineConfig baseCfg, SimCosts costs, string name, double[] values, Action<EngineConfig, double> set)
        {
            var variants = values.Select(v => V(name + " = " + v.ToString(CultureInfo.InvariantCulture), baseCfg, c => set(c, v), costs)).ToList();
            a.Table("Plateau " + name + " (TRAIN uniquement)", a.RunAll(variants, sp.TrainEnd), sp.Start, sp.TrainEnd);
        }

        private static Variant V(string name, EngineConfig baseCfg, Action<EngineConfig> change, SimCosts costs)
        {
            var c = baseCfg.Clone();
            change(c);
            var errors = c.Validate();
            if (errors.Count > 0) throw new InvalidOperationException(name + " : " + string.Join("; ", errors));
            return new Variant(name, c, costs);
        }

        private static void Only(EngineConfig c, SetupType t)
        {
            c.EnableSweep = t == SetupType.LiquiditySweep;
            c.EnableBreakout = t == SetupType.BreakoutContinuation;
            c.EnablePullback = t == SetupType.TrendPullback;
            c.EnableMomentum = t == SetupType.MomentumExpansion;
        }
    }

    public static class CsvLoader
    {
        /// <summary>CSV avec en-tête : time,open,high,low,close[,volume] (format produit par bot.py --download). Agrège si besoin.</summary>
        public static List<Candle> Load(string path, int targetTfMinutes)
        {
            var lines = File.ReadAllLines(path);
            var header = lines[0].ToLowerInvariant().Split(',').Select(h => h.Trim()).ToList();
            int iT = header.IndexOf("time"), iO = header.IndexOf("open"), iH = header.IndexOf("high"), iL = header.IndexOf("low"), iC = header.IndexOf("close"), iV = header.IndexOf("volume");
            if (iT < 0 || iO < 0 || iH < 0 || iL < 0 || iC < 0) throw new InvalidDataException("Colonnes attendues : time,open,high,low,close[,volume]");

            var raw = new List<Candle>();
            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                var f = lines[i].Split(',');
                var t = DateTimeOffset.Parse(f[iT], CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal).UtcDateTime;
                Func<int, double> d = k => double.Parse(f[k], CultureInfo.InvariantCulture);
                var c = new Candle(t, d(iO), d(iH), d(iL), d(iC), iV >= 0 ? d(iV) : 0);
                if (c.IsValid) raw.Add(c);
            }
            raw = raw.OrderBy(c => c.OpenTimeUtc).GroupBy(c => c.OpenTimeUtc).Select(g => g.First()).ToList();
            return Aggregate(raw, targetTfMinutes);
        }

        public static List<Candle> Aggregate(List<Candle> src, int tfMinutes)
        {
            if (src.Count < 2) return src;
            var sourceTf = src.Zip(src.Skip(1), (a, b) => b.OpenTimeUtc - a.OpenTimeUtc).Min();
            if (sourceTf >= TimeSpan.FromMinutes(tfMinutes)) return src;
            long ticks = TimeSpan.FromMinutes(tfMinutes).Ticks;
            return src.GroupBy(c => c.OpenTimeUtc.Ticks - c.OpenTimeUtc.Ticks % ticks)
                .Select(g => new Candle(new DateTime(g.Key, DateTimeKind.Utc), g.First().Open, g.Max(c => c.High), g.Min(c => c.Low), g.Last().Close, g.Sum(c => c.Volume)))
                .ToList();
        }
    }

    /// <summary>Marche aléatoire à régimes (tendances, ranges, clusters de volatilité). N'a AUCUNE edge exploitable.</summary>
    public static class Synthetic
    {
        public static List<Candle> Generate(int years, int seed, int tfMinutes)
        {
            var rng = new Random(seed);
            var bars = new List<Candle>();
            double price = 1800, drift = 0, vol = 0.35;
            var t = new DateTime(2020, 1, 6, 0, 0, 0, DateTimeKind.Utc);
            DateTime end = t.AddYears(years);
            int regimeLeft = 0;
            while (t < end)
            {
                if (t.DayOfWeek == DayOfWeek.Saturday || (t.DayOfWeek == DayOfWeek.Friday && t.Hour >= 21) || (t.DayOfWeek == DayOfWeek.Sunday && t.Hour < 23))
                {
                    t = t.AddMinutes(tfMinutes);
                    continue;
                }
                if (regimeLeft-- <= 0)
                {
                    regimeLeft = rng.Next(50, 600);
                    drift = rng.NextDouble() < 0.5 ? 0 : (rng.NextDouble() - 0.5) * 0.08;
                    vol = 0.2 + rng.NextDouble() * 0.5;
                }
                double sessionVol = t.Hour >= 7 && t.Hour < 17 ? 1.4 : 0.7;
                double o = price, h = price, l = price;
                for (int k = 0; k < tfMinutes; k++)
                {
                    price += drift + Gauss(rng) * vol * sessionVol;
                    h = Math.Max(h, price); l = Math.Min(l, price);
                }
                bars.Add(new Candle(t, Math.Round(o, 2), Math.Round(h, 2), Math.Round(l, 2), Math.Round(price, 2), 100 + rng.Next(400) * sessionVol));
                t = t.AddMinutes(tfMinutes);
            }
            return bars;
        }

        private static double Gauss(Random r)
        {
            return Math.Sqrt(-2 * Math.Log(1 - r.NextDouble())) * Math.Cos(2 * Math.PI * r.NextDouble());
        }
    }

    public sealed class Options
    {
        private readonly Dictionary<string, string> _v = new Dictionary<string, string>();

        public static Options Parse(string[] args)
        {
            var o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                if (!args[i].StartsWith("--")) continue;
                string key = args[i].Substring(2);
                string val = i + 1 < args.Length && !args[i + 1].StartsWith("--") ? args[++i] : "true";
                o._v[key] = val;
            }
            return o;
        }

        public bool Has(string k) { return _v.ContainsKey(k); }
        public string Str(string k, string def = null) { return _v.TryGetValue(k, out var v) ? v : def; }
        public int Int(string k, int def) { return _v.TryGetValue(k, out var v) ? int.Parse(v, CultureInfo.InvariantCulture) : def; }
        public double Dbl(string k, double def) { return _v.TryGetValue(k, out var v) ? double.Parse(v, CultureInfo.InvariantCulture) : def; }
    }
}
