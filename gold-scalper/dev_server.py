#!/usr/bin/env python3
"""Serveur local reproduisant le routage Vercel, pour tester avant de deployer.

    python3 dev_server.py           puis http://127.0.0.1:8000

Sert `public/` en statique et route `/api/*` vers la fonction `api/index.py`,
exactement comme le fait la reecriture declaree dans vercel.json.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("GOLDSCALP_HOME", "/tmp/goldscalp-dev")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location("goldscalp_api", os.path.join(ROOT, "api", "index.py"))
_api = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_api)


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(ROOT, "public"), **kwargs)

    def _is_api(self) -> bool:
        return urlparse(self.path).path.startswith("/api/")

    def _rewrite(self) -> None:
        """Reproduit le rewrite de vercel.json : /api/(.*) -> /api/index.

        Sans ça, le serveur local voit /api/calibrate alors que la fonction
        deployee voit /api/index : un bug de routage passait vert en local et
        cassait en production. Le serveur de dev doit mentir comme Vercel.
        """
        parsed = urlparse(self.path)
        self.path = "/api/index" + (f"?{parsed.query}" if parsed.query else "")

    def do_GET(self):  # noqa: N802
        if self._is_api():
            self._rewrite()
            _api.handler.do_GET(self)  # type: ignore[arg-type]
            return
        super().do_GET()

    def do_OPTIONS(self):  # noqa: N802
        if self._is_api():
            _api.handler.do_OPTIONS(self)  # type: ignore[arg-type]
            return
        self.send_response(405)
        self.end_headers()

    # Les methodes internes de la fonction attendent ces attributs.
    def _send(self, status, payload):
        _api.handler._send(self, status, payload)  # type: ignore[arg-type]

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"goldscalp dev  ->  http://127.0.0.1:{port}")
    print(f"  statique : {os.path.join(ROOT, 'public')}")
    print(f"  api      : /api/analyse, /api/health")
    HTTPServer(("127.0.0.1", port), DevHandler).serve_forever()
