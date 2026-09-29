using System;
using System.Collections.Generic;
using System.Linq;
using GoldLive.Core;

namespace GoldLive.Research
{
    /// <summary>Tests de la mécanique du moteur (pas de sa rentabilité).</summary>
    public static class SelfTest
    {
        private static int _failed;

        public static int Run()
        {
            Check("Configuration par défaut valide", new EngineConfig().Validate().Count == 0);
            TestSizing();
            TestPartialIdempotence();
            TestSessionsDst();
            TestPositionTag();
            TestSafety();
            TestNoLookAhead();
            TestRandomWalkHasNoEdge();
            Console.WriteLine(_failed == 0 ? "\nTOUS LES TESTS PASSENT" : "\n" + _failed + " TEST(S) EN ÉCHEC");
            return _failed == 0 ? 0 : 1;
        }

        private static void Check(string name, bool ok, string detail = "")
        {
            Console.WriteLine((ok ? "[OK]   " : "[FAIL] ") + name + (detail.Length > 0 ? " — " + detail : ""));
            if (!ok) _failed++;
        }

        private static SymbolSpec Gold() { return new SymbolSpec { TickSize = 0.01, TickValue = 0.01, PipSize = 0.01, VolumeMin = 1, VolumeStep = 1, VolumeMax = 10000 }; }

        private static void TestSizing()
        {
            var cfg = new EngineConfig { RiskPercent = 0.35 };
            var s = RiskEngine.Size(10000, 5.0, 0, Gold(), cfg);
            Check("Sizing : 0,35 % de 10 000 $ avec stop à 5 $ = 7 onces", s.Units == 7 && Math.Abs(s.RiskMoney - 35) < 1e-9, s.Units + " unités, risque " + s.RiskMoney);
            var tiny = RiskEngine.Size(100, 5.0, 0, Gold(), cfg);
            Check("Sizing : jamais d'arrondi vers le haut du risque", !tiny.Ok, tiny.Reason);
            var capped = RiskEngine.Size(10000, 5.0, 70, Gold(), cfg);
            Check("Sizing : risque ouvert max respecté", !capped.Ok, capped.Reason);
            var lots = new SymbolSpec { TickSize = 0.01, TickValue = 0.01, PipSize = 0.01, VolumeMin = 100, VolumeStep = 100, VolumeMax = 1e6 };
            var l = RiskEngine.Size(100000, 3.0, 0, lots, cfg);
            Check("Sizing : arrondi au pas du broker (100 unités)", l.Units == 100, l.Units + " unités");
        }

        private static void TestPartialIdempotence()
        {
            var cfg = new EngineConfig();
            var spec = Gold();
            var p = new ManagedPosition { Id = 1, Side = Side.Buy, Entry = 2000, RiskDistance = 5, InitialUnits = 100, Units = 100, Stop = 1995, BestPrice = 2000 };
            var a1 = ExitEngine.OnPrice(p, 2004.1, cfg, spec, 0.3);
            Check("TP1 déclenché à 0,8 R", a1.Count(a => a.Kind == ExitKind.PartialClose) == 1 && a1.Any(a => a.Kind == ExitKind.MoveStop));
            foreach (var a in a1)
            {
                if (a.Kind == ExitKind.PartialClose) p.Units -= a.Units;
                if (a.Kind == ExitKind.MoveStop) p.Stop = a.Price;
            }
            Check("Stop après TP1 = entrée - 0,3 R", Math.Abs(p.Stop.Value - 1998.5) < 1e-9, p.Stop.ToString());
            var a2 = ExitEngine.OnPrice(p, 2004.2, cfg, spec, 0.3);
            Check("TP1 jamais répété (idempotent)", a2.Count == 0);
            var restarted = new ManagedPosition { Id = 1, Side = Side.Buy, Entry = 2000, RiskDistance = 5, InitialUnits = 100, Units = 100, Stop = 1998.5 };
            Check("Après redémarrage : stade TP1 déduit du stop même si le partiel a échoué", restarted.Stage(cfg, spec) == 1);
            var lockFailed = new ManagedPosition { Id = 4, Side = Side.Buy, Entry = 2000, RiskDistance = 5, InitialUnits = 100, Units = 60, Stop = 1995 };
            var lf = ExitEngine.OnPrice(lockFailed, 2003, cfg, spec, 0.3);
            Check("Stop de verrouillage retenté si le déplacement avait échoué", lf.Count == 1 && lf[0].Kind == ExitKind.MoveStop && Math.Abs(lf[0].Price - 1998.5) < 1e-9);
            var sell = new ManagedPosition { Id = 2, Side = Side.Sell, Entry = 2000, RiskDistance = 5, InitialUnits = 100, Units = 100, Stop = 2005 };
            var s1 = ExitEngine.OnPrice(sell, 1992.4, cfg, spec, 0.3);
            Check("Vente : TP1 + TP2 déclenchés sur un gap à 1,52 R", s1.Count(a => a.Kind == ExitKind.PartialClose) == 2);
            var loosen = new ManagedPosition { Id = 3, Side = Side.Buy, Entry = 2000, RiskDistance = 5, InitialUnits = 100, Units = 60, Stop = 2003 };
            var l1 = ExitEngine.OnPrice(loosen, 2004.5, cfg, spec, 0.3);
            Check("Un stop n'est jamais desserré", l1.All(a => a.Kind != ExitKind.MoveStop || a.Price > 2003));
        }

        private static void TestSessionsDst()
        {
            var clock = new SessionClock();
            Check("Fuseaux Londres/New York disponibles", !clock.UsingFallback);
            Check("Londres ouverte à 07:30 UTC en été (08:30 BST)", clock.At(new DateTime(2024, 7, 1, 7, 30, 0, DateTimeKind.Utc)).London);
            Check("Londres fermée à 07:30 UTC en hiver (07:30 GMT)", !clock.At(new DateTime(2024, 1, 15, 7, 30, 0, DateTimeKind.Utc)).London);
            Check("New York ouverte à 12:30 UTC en été (08:30 EDT)", clock.At(new DateTime(2024, 7, 1, 12, 30, 0, DateTimeKind.Utc)).NewYork);
            Check("New York fermée à 12:30 UTC en hiver (07:30 EST)", !clock.At(new DateTime(2024, 1, 15, 12, 30, 0, DateTimeKind.Utc)).NewYork);
            Check("Flatten week-end vendredi 20:45 UTC en été (16:45 NY)", clock.At(new DateTime(2024, 7, 5, 20, 45, 0, DateTimeKind.Utc)).WeekendFlatten);
            Check("Pas de flatten jeudi", !clock.At(new DateTime(2024, 7, 4, 20, 45, 0, DateTimeKind.Utc)).WeekendFlatten);
            Check("Rollover 21:30 UTC en été (17:30 NY)", clock.At(new DateTime(2024, 7, 1, 21, 30, 0, DateTimeKind.Utc)).Rollover);
        }

        private static void TestPositionTag()
        {
            string tag = PositionTag.Encode(SetupType.TrendPullback, 72, 3.4567891, 12);
            SetupType st; int score; double r, v;
            bool ok = PositionTag.TryDecode(tag, out st, out score, out r, out v);
            Check("Tag de position : aller-retour exact", ok && st == SetupType.TrendPullback && score == 72 && r == 3.4567891 && v == 12, tag);
            Check("Tag de position : commentaire étranger rejeté", !PositionTag.TryDecode("manuel", out st, out score, out r, out v));
        }

        private static void TestSafety()
        {
            var cfg = new EngineConfig();
            var now = new DateTime(2024, 3, 6, 15, 0, 0, DateTimeKind.Utc);
            var deals = new List<RealizedDeal>
            {
                new RealizedDeal { PositionId = 1, CloseUtc = now.AddHours(-3), NetProfit = -120 },
                new RealizedDeal { PositionId = 2, CloseUtc = now.AddHours(-2), NetProfit = -90 },
            };
            var d = SafetyEngine.Check(new SafetyInput { NowUtc = now, Balance = 9790, Deals = deals }, cfg);
            Check("Perte journalière de 2,06 % -> entrées bloquées", !d.Allowed, d.Reason);
            var nextDay = SafetyEngine.Check(new SafetyInput { NowUtc = now.AddDays(1), Balance = 9790, Deals = deals }, cfg);
            Check("Nouveau jour -> reprise autorisée", nextDay.Allowed, nextDay.Reason);
            var streak = Enumerable.Range(1, 5).Select(i => new RealizedDeal { PositionId = i, CloseUtc = now.AddMinutes(-i), NetProfit = -10 }).ToList();
            var s = SafetyEngine.Check(new SafetyInput { NowUtc = now, Balance = 10000, Deals = streak }, cfg);
            Check("5 pertes consécutives -> pause", !s.Allowed, s.Reason);
            Check("Emergency stop", !SafetyEngine.Check(new SafetyInput { NowUtc = now, Balance = 10000 }, new EngineConfig { EmergencyStop = true }).Allowed);
        }

        /// <summary>
        /// Test anti look-ahead : les décisions prises jusqu'à la bougie k doivent être IDENTIQUES
        /// que le simulateur connaisse ou non les bougies suivantes.
        /// </summary>
        private static void TestNoLookAhead()
        {
            var bars = Synthetic.Generate(1, 3, 5);
            var cfg = new EngineConfig();
            var full = Simulator.Run(bars, cfg, new SimCosts(), DateTime.MinValue, DateTime.MaxValue);
            bool identical = true;
            foreach (int cut in new[] { bars.Count / 3, bars.Count / 2, 2 * bars.Count / 3 })
            {
                var partial = Simulator.Run(bars, cfg, new SimCosts(), DateTime.MinValue, DateTime.MaxValue, 10000, cut);
                var prefix = full.EntryLog.Take(partial.EntryLog.Count).ToList();
                identical &= partial.EntryLog.SequenceEqual(prefix) && partial.EntryLog.Count > 0;
            }
            Check("Aucun look-ahead : décisions identiques avec historique tronqué", identical, full.EntryLog.Count + " signaux sur la série complète");
        }

        /// <summary>
        /// Sur une marche aléatoire, un moteur sain ne doit PAS montrer d'edge significative
        /// (une t-stat élevée trahirait un biais de simulation ou du look-ahead).
        /// </summary>
        private static void TestRandomWalkHasNoEdge()
        {
            var tStats = new List<double>();
            foreach (int seed in new[] { 11, 12, 13 })
            {
                var r = Simulator.Run(Synthetic.Generate(2, seed, 5), new EngineConfig(), new SimCosts(), DateTime.MinValue, DateTime.MaxValue);
                var st = PerformanceStats.From(r.Trades, 10000);
                tStats.Add(st.TStat);
                Console.WriteLine("       seed " + seed + " : " + st.Trades + " trades, win " + st.WinRate.ToString("F1") + " %, exp " + st.ExpectancyR.ToString("F3") + " R, t = " + st.TStat.ToString("F2"));
            }
            Check("Marche aléatoire : pas d'edge significative (t < 2.5 sur chaque seed)", tStats.All(t => t < 2.5), string.Join(", ", tStats.Select(t => t.ToString("F2"))));
        }
    }
}
