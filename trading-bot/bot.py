"""Bot de trading cTrader Open API.

    python bot.py                 # lance le bot (DRY_RUN=true par défaut : aucun ordre réel)
    python bot.py --download 365  # télécharge 365 jours d'historique en CSV pour le backtest

Fonctionnement : à chaque clôture de bougie, le bot récupère l'historique, calcule le signal,
vérifie les positions ouvertes (celles portant son label) et agit.
"""
import argparse
import logging
import os
import sys
import time

import pandas as pd
from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq, ProtoOAAccountsTokenInvalidatedEvent, ProtoOAApplicationAuthReq,
    ProtoOAAssetListReq, ProtoOAClosePositionReq, ProtoOAErrorRes, ProtoOAExecutionEvent,
    ProtoOAGetTrendbarsReq, ProtoOANewOrderReq, ProtoOAOrderErrorEvent, ProtoOAReconcileReq,
    ProtoOASymbolByIdReq, ProtoOASymbolsListReq, ProtoOATraderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType, ProtoOAOrderType, ProtoOATradeSide, ProtoOATrendbarPeriod,
)
from twisted.internet import defer, reactor, task

from config import TIMEFRAME_MINUTES, Settings
from risk import DailyLossGuard, position_volume
from strategy import BUY, add_indicators, exit_at, min_bars, signal_at

log = logging.getLogger("bot")
WEEK_MS = 7 * 24 * 3600 * 1000  # plage max d'une requête de bougies


class ApiError(Exception):
    pass


class TradingBot:
    def __init__(self, settings: Settings, download_days: int = 0):
        self.s = settings
        self.download_days = download_days
        self.period_min = TIMEFRAME_MINUTES[settings.timeframe]
        self.guard = DailyLossGuard(settings.max_daily_loss_pct)
        self.last_bar_time = None
        self.busy = False
        host = EndPoints.PROTOBUF_LIVE_HOST if settings.env == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(lambda _: self._start())
        self.client.setDisconnectedCallback(lambda _, reason: log.warning("Déconnecté : %s", reason))
        self.client.setMessageReceivedCallback(self._on_message)

    # ---------- utilitaires ----------
    @defer.inlineCallbacks
    def request(self, req, timeout=15):
        msg = yield self.client.send(req, responseTimeoutInSeconds=timeout)
        res = Protobuf.extract(msg)
        if isinstance(res, (ProtoOAErrorRes, ProtoOAOrderErrorEvent)):
            raise ApiError(f"{res.errorCode}: {res.description}")
        return res

    def _acc(self, cls, **kw):
        return cls(ctidTraderAccountId=self.s.account_id, **kw)

    def _on_message(self, _client, message):
        payload = Protobuf.extract(message)
        if isinstance(payload, ProtoOAExecutionEvent) and payload.HasField("deal"):
            d = payload.deal
            side = ProtoOATradeSide.Name(d.tradeSide)
            log.info("Exécution : %s %s volume=%s prix=%s position=%s",
                     ProtoOAExecutionType.Name(payload.executionType),
                     side, d.filledVolume, d.executionPrice, d.positionId)
        elif isinstance(payload, ProtoOAOrderErrorEvent):
            log.error("Ordre refusé : %s %s", payload.errorCode, payload.description)
        elif isinstance(payload, ProtoOAAccountsTokenInvalidatedEvent):
            log.critical("Token invalidé (%s). Relance get_token.py puis le bot.", payload.reason)
            reactor.stop()

    # ---------- démarrage ----------
    @defer.inlineCallbacks
    def _start(self):
        try:
            yield self.request(ProtoOAApplicationAuthReq(
                clientId=self.s.client_id, clientSecret=self.s.client_secret))
            yield self.request(self._acc(ProtoOAAccountAuthReq, accessToken=self.s.access_token))
            log.info("Authentifié sur le compte %s (%s)", self.s.account_id, self.s.env.upper())

            trader = (yield self.request(self._acc(ProtoOATraderReq))).trader
            self.money_digits = trader.moneyDigits
            assets = {a.assetId: a.name for a in (yield self.request(self._acc(ProtoOAAssetListReq))).asset}
            self.deposit_ccy = assets[trader.depositAssetId]

            symbols = (yield self.request(self._acc(ProtoOASymbolsListReq))).symbol
            self.symbols_by_name = {x.symbolName: x for x in symbols}
            light = self.symbols_by_name.get(self.s.symbol)
            if light is None:
                raise ApiError(f"Symbole {self.s.symbol} introuvable chez ce courtier")
            self.symbol_id = light.symbolId
            self.quote_ccy = assets[light.quoteAssetId]
            self.symbol = (yield self.request(self._acc(ProtoOASymbolByIdReq, symbolId=[self.symbol_id]))).symbol[0]
            log.info("%s : id=%s, devise de cotation=%s, devise du compte=%s, lot=%s unités",
                     self.s.symbol, self.symbol_id, self.quote_ccy, self.deposit_ccy,
                     self.symbol.lotSize / 100)

            if self.download_days:
                yield self._download()
                reactor.stop()
                return

            if self.s.dry_run:
                log.warning("DRY_RUN activé : les signaux sont journalisés mais AUCUN ordre n'est envoyé.")
            task.LoopingCall(self._tick).start(30, now=True)
        except Exception as e:  # noqa: BLE001
            log.critical("Échec du démarrage : %s", e)
            reactor.stop()

    # ---------- données ----------
    @defer.inlineCallbacks
    def get_bars(self, symbol_id, from_ms, to_ms, period=None):
        period = period or self.s.timeframe
        rows, start = [], from_ms
        while start < to_ms:
            end = min(start + WEEK_MS, to_ms)
            res = yield self.request(self._acc(
                ProtoOAGetTrendbarsReq, symbolId=symbol_id, fromTimestamp=start, toTimestamp=end,
                period=ProtoOATrendbarPeriod.Value(period)), timeout=30)
            for b in res.trendbar:
                rows.append({
                    "time": pd.Timestamp(b.utcTimestampInMinutes * 60, unit="s", tz="UTC"),
                    "open": (b.low + b.deltaOpen) / 1e5, "high": (b.low + b.deltaHigh) / 1e5,
                    "low": b.low / 1e5, "close": (b.low + b.deltaClose) / 1e5,
                    "volume": b.volume,
                })
            start = end
        df = pd.DataFrame(rows).drop_duplicates("time").sort_values("time").reset_index(drop=True)
        return df

    @defer.inlineCallbacks
    def _download(self):
        now = int(time.time() * 1000)
        df = yield self.get_bars(self.symbol_id, now - self.download_days * 86400 * 1000, now)
        os.makedirs("data", exist_ok=True)
        path = f"data/{self.s.symbol}_{self.s.timeframe}.csv"
        df.to_csv(path, index=False)
        log.info("%d bougies enregistrées dans %s", len(df), path)

    @defer.inlineCallbacks
    def quote_to_account_rate(self):
        """Taux pour convertir un montant de la devise de cotation vers la devise du compte."""
        if self.quote_ccy == self.deposit_ccy:
            return 1.0
        now = int(time.time() * 1000)
        for name, invert in ((self.quote_ccy + self.deposit_ccy, False),
                             (self.deposit_ccy + self.quote_ccy, True)):
            sym = self.symbols_by_name.get(name)
            if sym:
                bars = yield self.get_bars(sym.symbolId, now - 3 * 86400 * 1000, now, "M1")
                if not bars.empty:
                    price = bars["close"].iloc[-1]
                    return 1 / price if invert else price
        raise ApiError(f"Pas de paire pour convertir {self.quote_ccy} en {self.deposit_ccy}")

    # ---------- boucle principale ----------
    @defer.inlineCallbacks
    def _tick(self):
        if self.busy:
            return
        self.busy = True
        try:
            now = pd.Timestamp.now(tz="UTC")
            period = pd.Timedelta(minutes=self.period_min)
            lookback_ms = int(min_bars(self.s.strategy) * 2.2 * period.total_seconds() * 1000) + WEEK_MS
            now_ms = int(now.timestamp() * 1000)
            bars = yield self.get_bars(self.symbol_id, now_ms - lookback_ms, now_ms)
            bars = bars[bars["time"] + period <= now].reset_index(drop=True)  # bougies clôturées seulement
            if len(bars) < min_bars(self.s.strategy):
                log.warning("Historique insuffisant (%d bougies)", len(bars))
                return
            last_time = bars["time"].iloc[-1]
            if last_time == self.last_bar_time:
                return  # rien de nouveau
            self.last_bar_time = last_time
            yield self._on_new_bar(add_indicators(bars, self.s.strategy))
        except Exception as e:  # noqa: BLE001
            log.error("Erreur pendant le tick : %s", e)
        finally:
            self.busy = False

    @defer.inlineCallbacks
    def _on_new_bar(self, df):
        i = len(df) - 1
        row = df.iloc[i]
        log.info("Bougie %s close=%.5f ema%d=%.5f ema%d=%.5f ema%d=%.5f atr=%.5f",
                 row["time"], row["close"], self.s.strategy.ema_fast, row["ema_fast"],
                 self.s.strategy.ema_slow, row["ema_slow"], self.s.strategy.ema_trend,
                 row["ema_trend"], row["atr"])

        positions = [p for p in (yield self.request(self._acc(ProtoOAReconcileReq))).position
                     if p.tradeData.label == self.s.label and p.tradeData.symbolId == self.symbol_id]

        for p in positions:
            side = BUY if p.tradeData.tradeSide == ProtoOATradeSide.BUY else -BUY
            if exit_at(df, i, side):
                log.info("Croisement inverse -> clôture de la position %s", p.positionId)
                if not self.s.dry_run:
                    yield self.request(self._acc(ProtoOAClosePositionReq, positionId=p.positionId,
                                                 volume=p.tradeData.volume))
                positions = []

        if positions:
            return  # une seule position à la fois
        sig = signal_at(df, i, self.s.strategy)
        if sig is None:
            return

        trader = (yield self.request(self._acc(ProtoOATraderReq))).trader
        balance = trader.balance / 10 ** self.money_digits
        if not self.guard.allows_trading(balance):
            log.warning("Perte journalière max atteinte : pas de nouvelle position aujourd'hui.")
            return

        rate = yield self.quote_to_account_rate()
        volume = position_volume(balance, self.s.risk_per_trade_pct, sig.sl_distance, rate,
                                 self.symbol.minVolume, self.symbol.stepVolume, self.symbol.maxVolume)
        side_name = "BUY" if sig.side == BUY else "SELL"
        if volume == 0:
            log.warning("Signal %s ignoré : même le volume minimum dépasserait le risque autorisé.", side_name)
            return

        digits = self.symbol.digits
        rel_sl = int(round(round(sig.sl_distance, digits) * 1e5))
        rel_tp = int(round(round(sig.tp_distance, digits) * 1e5))
        log.info("SIGNAL %s volume=%.2f lots (risque %.2f%% de %.2f %s) SL=%.5f TP=%.5f",
                 side_name, volume / self.symbol.lotSize, self.s.risk_per_trade_pct, balance,
                 self.deposit_ccy, sig.sl_distance, sig.tp_distance)
        if self.s.dry_run:
            return
        yield self.request(self._acc(
            ProtoOANewOrderReq, symbolId=self.symbol_id, orderType=ProtoOAOrderType.MARKET,
            tradeSide=ProtoOATradeSide.Value(side_name), volume=volume,
            relativeStopLoss=rel_sl, relativeTakeProfit=rel_tp, label=self.s.label))

    def run(self):
        self.client.startService()
        reactor.run()


def check_settings(s: Settings):
    missing = [k for k, v in {"CTRADER_CLIENT_ID": s.client_id, "CTRADER_CLIENT_SECRET": s.client_secret,
                              "CTRADER_ACCESS_TOKEN": s.access_token, "CTRADER_ACCOUNT_ID": s.account_id}.items()
               if not v]
    if missing:
        sys.exit(f"Variables manquantes dans .env : {', '.join(missing)}")
    if s.timeframe not in TIMEFRAME_MINUTES:
        sys.exit(f"TIMEFRAME invalide : {s.timeframe}")
    if s.env == "live" and not s.dry_run:
        log.warning("MODE LIVE : des ordres réels vont être envoyés avec de l'argent réel.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", type=int, default=0, metavar="JOURS",
                    help="télécharge l'historique au lieu de trader")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")])
    s = Settings()
    check_settings(s)
    TradingBot(s, args.download).run()


if __name__ == "__main__":
    main()
