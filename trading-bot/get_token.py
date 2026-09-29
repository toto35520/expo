"""Obtenir un access token cTrader et la liste de tes comptes (ctidTraderAccountId).

1. Crée une application sur https://openapi.ctrader.com/apps (redirect URI : https://spotware.com par ex.)
2. Mets CTRADER_CLIENT_ID et CTRADER_CLIENT_SECRET dans .env
3. python get_token.py            -> ouvre le lien, connecte-toi, copie le "code=" de l'URL de retour
   python get_token.py --refresh  -> renouvelle le token avec CTRADER_REFRESH_TOKEN
"""
import argparse
import os
import sys

from ctrader_open_api import Auth, Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAGetAccountListByAccessTokenReq,
)
from dotenv import load_dotenv
from twisted.internet import defer, reactor

load_dotenv()
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("CTRADER_REDIRECT_URI", "https://spotware.com")


def list_accounts(token: str):
    client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)

    @defer.inlineCallbacks
    def on_connected(_):
        try:
            yield client.send(ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET))
            res = Protobuf.extract((yield client.send(ProtoOAGetAccountListByAccessTokenReq(accessToken=token))))
            print("\nComptes accessibles avec ce token :")
            for a in res.ctidTraderAccount:
                print(f"  CTRADER_ACCOUNT_ID={a.ctidTraderAccountId}  (login {a.traderLogin}, "
                      f"{'LIVE' if a.isLive else 'DEMO'})")
        finally:
            reactor.stop()

    client.setConnectedCallback(on_connected)
    client.startService()
    reactor.run()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Renseigne CTRADER_CLIENT_ID et CTRADER_CLIENT_SECRET dans .env")
    auth = Auth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)

    if args.refresh:
        res = auth.refreshToken(os.getenv("CTRADER_REFRESH_TOKEN", ""))
    else:
        print("Ouvre ce lien, connecte-toi avec ton cTrader ID et autorise l'application :\n")
        print(auth.getAuthUri())
        code = input("\nColle ici la valeur de 'code=' présente dans l'URL de redirection : ").strip()
        res = auth.getToken(code)

    if "accessToken" not in res or not res["accessToken"]:
        sys.exit(f"Erreur : {res}")
    print("\nAjoute ces lignes dans ton .env (ne les partage jamais) :")
    print(f"CTRADER_ACCESS_TOKEN={res['accessToken']}")
    print(f"CTRADER_REFRESH_TOKEN={res['refreshToken']}")
    print(f"(le token expire dans {int(res.get('expiresIn', 0)) // 86400} jours)")
    list_accounts(res["accessToken"])


if __name__ == "__main__":
    main()
