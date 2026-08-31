"""Le routage de la fonction serverless, tel que Vercel l'appelle vraiment.

Bug observe en production : `vercel.json` reecrit /api/(.*) vers /api/index,
donc la fonction ne recoit jamais le chemin demande par le navigateur. Router
sur le chemin seul renvoyait une ANALYSE a qui demandait un CALIBRAGE, avec un
HTTP 200 — l'interface affichait « undefined » et la calibration n'etait jamais
appliquee. Ces tests figent le contrat : c'est le parametre `route` qui decide.
"""

from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_api():
    os.environ.setdefault("GOLDSCALP_HOME", "/tmp/goldscalp-tests")
    spec = importlib.util.spec_from_file_location(
        "goldscalp_api_routing", os.path.join(ROOT, "api", "index.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = _load_api()


def route(path: str, **params) -> str:
    qs = {k: [str(v)] for k, v in params.items()}
    return api.resolve_route(path, qs)


class TestRouteSurvivesTheVercelRewrite(unittest.TestCase):
    """Le chemin est perdu par la reecriture : seul `route` traverse."""

    def test_rewritten_path_still_reaches_calibration(self):
        # Ce que la fonction voit reellement sur Vercel.
        self.assertEqual(route("/api/index", route="calibrate"), "calibrate")

    def test_rewritten_path_without_hint_falls_back_to_analysis(self):
        self.assertEqual(route("/api/index"), "analyse")

    def test_health_survives_the_rewrite(self):
        self.assertEqual(route("/api/index", route="health"), "health")

    def test_explicit_route_wins_over_the_path(self):
        """Le chemin ment apres reecriture : il ne doit pas primer."""
        self.assertEqual(route("/api/analyse", route="calibrate"), "calibrate")

    def test_direct_path_still_works_without_rewrite(self):
        """Serveur local ou appel direct : le chemin reste un secours valide."""
        self.assertEqual(route("/api/calibrate"), "calibrate")
        self.assertEqual(route("/api/health"), "health")
        self.assertEqual(route("/api/analyse"), "analyse")

    def test_french_aliases(self):
        self.assertEqual(route("/api/index", route="calibrage"), "calibrate")
        self.assertEqual(route("/api/sante"), "health")

    def test_unknown_route_is_analysis(self):
        self.assertEqual(route("/api/index", route="n_importe_quoi"), "analyse")
        self.assertEqual(route("/api/pouet"), "analyse")

    def test_query_string_does_not_leak_into_the_path(self):
        self.assertEqual(route("/api/index?bid=4432&ask=4433", route="calibrate"),
                         "calibrate")


class TestCalibrationPayloadContract(unittest.TestCase):
    """L'interface lit `message` et `alpha` : ils font partie du contrat."""

    def test_calibration_rejects_a_missing_price(self):
        with self.assertRaises(ValueError):
            api.run_calibration({})

    def test_calibration_rejects_a_negative_price(self):
        with self.assertRaises(ValueError):
            api.run_calibration({"mt5": ["-1"]})


class TestDevServerMirrorsVercel(unittest.TestCase):
    """Le serveur de dev doit reecrire comme Vercel, sinon il cache le bug."""

    def test_dev_server_rewrites_api_paths(self):
        with open(os.path.join(ROOT, "dev_server.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("/api/index", source,
                      "dev_server.py doit reproduire le rewrite de vercel.json")


if __name__ == "__main__":
    unittest.main()
