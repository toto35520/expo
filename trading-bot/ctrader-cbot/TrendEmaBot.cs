using System;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    // Suivi de tendance : croisement EMA 20/50 filtré par l'EMA 200, SL/TP basés sur l'ATR.
    // Évalué uniquement sur bougies clôturées. Une seule position à la fois par symbole.
    [Robot(AccessRights = AccessRights.None, AddIndicators = true)]
    public class TrendEmaBot : Robot
    {
        [Parameter("EMA rapide", DefaultValue = 20, MinValue = 2, Group = "Stratégie")]
        public int FastPeriod { get; set; }

        [Parameter("EMA lente", DefaultValue = 50, MinValue = 3, Group = "Stratégie")]
        public int SlowPeriod { get; set; }

        [Parameter("EMA tendance", DefaultValue = 200, MinValue = 10, Group = "Stratégie")]
        public int TrendPeriod { get; set; }

        [Parameter("Période ATR", DefaultValue = 14, MinValue = 2, Group = "Stratégie")]
        public int AtrPeriod { get; set; }

        [Parameter("Stop loss (x ATR)", DefaultValue = 2.0, MinValue = 0.5, Group = "Stratégie")]
        public double SlAtr { get; set; }

        [Parameter("Take profit (x ATR)", DefaultValue = 3.0, MinValue = 0.5, Group = "Stratégie")]
        public double TpAtr { get; set; }

        [Parameter("Risque par trade (%)", DefaultValue = 0.5, MinValue = 0.05, MaxValue = 5, Group = "Risque")]
        public double RiskPercent { get; set; }

        [Parameter("Perte journalière max (%)", DefaultValue = 2.0, MinValue = 0.5, Group = "Risque")]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Label", DefaultValue = "claude-bot", Group = "Risque")]
        public string BotLabel { get; set; }

        private ExponentialMovingAverage _fast, _slow, _trend;
        private AverageTrueRange _atr;
        private DateTime _day;
        private double _dayStartBalance;

        protected override void OnStart()
        {
            _fast = Indicators.ExponentialMovingAverage(Bars.ClosePrices, FastPeriod);
            _slow = Indicators.ExponentialMovingAverage(Bars.ClosePrices, SlowPeriod);
            _trend = Indicators.ExponentialMovingAverage(Bars.ClosePrices, TrendPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.WilderSmoothing);
            _day = Server.Time.Date;
            _dayStartBalance = Account.Balance;
        }

        // Appelé à l'ouverture d'une nouvelle bougie : Last(1) = dernière bougie clôturée.
        protected override void OnBar()
        {
            if (Bars.Count < TrendPeriod + 50)
                return;

            int cross = Cross();
            var position = Positions.Find(BotLabel, SymbolName);

            if (position != null)
            {
                int side = position.TradeType == TradeType.Buy ? 1 : -1;
                if (cross == -side)
                {
                    Print("Croisement inverse -> clôture de la position {0}", position.Id);
                    ClosePosition(position);
                    position = null;
                }
                else
                {
                    return; // une seule position à la fois
                }
            }

            double close = Bars.ClosePrices.Last(1);
            double trend = _trend.Result.Last(1);
            TradeType type;
            if (cross == 1 && close > trend)
                type = TradeType.Buy;
            else if (cross == -1 && close < trend)
                type = TradeType.Sell;
            else
                return;

            if (!DailyLossAllowsTrading())
            {
                Print("Perte journalière max atteinte : pas de nouvelle position aujourd'hui.");
                return;
            }

            double atr = _atr.Result.Last(1);
            double slPips = SlAtr * atr / Symbol.PipSize;
            double tpPips = TpAtr * atr / Symbol.PipSize;

            // Perte au stop = unités x slPips x PipValue (valeur d'un pip par unité, en devise du compte)
            double riskAmount = Account.Balance * RiskPercent / 100.0;
            double units = Symbol.NormalizeVolumeInUnits(riskAmount / (slPips * Symbol.PipValue), RoundingMode.Down);
            if (units < Symbol.VolumeInUnitsMin)
            {
                Print("Signal {0} ignoré : le volume minimum dépasserait le risque autorisé.", type);
                return;
            }

            var result = ExecuteMarketOrder(type, SymbolName, units, BotLabel, slPips, tpPips);
            if (result.IsSuccessful)
                Print("{0} {1} lots, SL {2:F1} pips, TP {3:F1} pips (risque {4}% = {5:F2} {6})",
                    type, Symbol.VolumeInUnitsToQuantity(units), slPips, tpPips,
                    RiskPercent, riskAmount, Account.Asset.Name);
            else
                Print("Ordre refusé : {0}", result.Error);
        }

        // +1 = EMA rapide croise au-dessus de la lente, -1 = en dessous, 0 = rien
        private int Cross()
        {
            bool nowAbove = _fast.Result.Last(1) > _slow.Result.Last(1);
            bool prevAbove = _fast.Result.Last(2) > _slow.Result.Last(2);
            if (nowAbove && !prevAbove) return 1;
            if (!nowAbove && prevAbove) return -1;
            return 0;
        }

        // Compare l'équité (positions ouvertes incluses) au solde du début de journée
        private bool DailyLossAllowsTrading()
        {
            if (Server.Time.Date != _day)
            {
                _day = Server.Time.Date;
                _dayStartBalance = Account.Balance;
            }
            double lossPct = (_dayStartBalance - Account.Equity) / _dayStartBalance * 100.0;
            return lossPct < MaxDailyLossPercent;
        }
    }
}
