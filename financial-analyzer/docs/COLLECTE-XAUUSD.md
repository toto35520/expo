# Collecte XAU/USD — mode d'emploi

Ce document sert à lancer la première collecte réelle. Il ne contient aucune théorie.

**Aucun ordre n'est émis. Aucun moteur prédictif n'est appelé.** Le collecteur branche les
cinq points d'instrumentation de Q51-A sur le flux du terminal et écrit un journal
append-only.

---

## 1. Valider la chaîne sans MT5 (n'importe quelle machine)

```bash
cd financial-analyzer
python - <<'PY'
from feasibility.mt5_source import synthetic_ticks, write_ticks
write_ticks("ticks-test.jsonl", synthetic_ticks(3000))
PY
python -m feasibility.collect_xauusd --source replay --file ticks-test.jsonl
```

Le rapport doit se terminer par trois avertissements. Ils sont attendus :

- `SOURCE DE REJEU` — les durées mesurées sont celles de la machine, pas du marché ;
- `l'évaluation était vide` — elles bornent par le bas celles du système final ;
- `EXPLORATORY` — aucun gel de protocole n'est posé, donc aucun verdict n'en sortira.

Si ces trois lignes s'affichent, la chaîne fonctionne de bout en bout.

---

## 2. Préflight sur le compte réel (machine Windows avec MT5)

Prérequis : terminal MT5 **ouvert**, connecté au compte IC Markets, « Algo Trading »
autorisé, et `pip install MetaTrader5`.

```bash
python -m feasibility.collect_xauusd --source mt5 --symbol XAUUSD --preflight-only
```

Le préflight lit le compte et le symbole, et **résout Q63 tout seul**. Il n'y a rien à
recopier à la main : les trois éléments manquants —

| élément | où il est lu |
|---|---|
| `ACCOUNT_TYPE` | `account_info()` — Raw Spread / Standard |
| `ACCOUNT_BASE_CURRENCY` | `account_info().currency` |
| `MT5_SYMBOL_SPECIFICATION` | `symbol_info(XAUUSD)` — contract size, tick size, lots, swaps |

— passent Q63 de `PROVISIONAL` à `VERIFIED` dès que le terminal répond.

**Le nom du symbole peut différer.** Selon le compte : `XAUUSD`, `XAUUSD.a`, `GOLD`… Le
relever dans l'Observation du marché et le passer à `--symbol`.

**Si le type de compte ressort `UNKNOWN`**, c'est normal et voulu : MT5 ne publie pas
« Raw Spread » comme champ, seul le libellé commercial le porte. Une déduction incertaine
ne doit pas devenir une commission contractuelle. Deux options :

```python
from feasibility.cost_floor_xauusd import (
    AccountIdentity, AccountType, BaseCurrency, Q63Specification,
)
compte = AccountIdentity(
    AccountType.RAW_SPREAD, BaseCurrency.USD,
    read_from="espace client IC Markets, consulté le AAAA-MM-JJ",
)
```

---

## 3. Lancer la collecte

```bash
python -m feasibility.collect_xauusd --source mt5 --symbol XAUUSD \
    --session LONDRES --out-dir collecte --minutes 240
```

`Ctrl-C` arrête proprement : le tampon est vidé sur disque avant de rendre la main.

Deux fichiers sont produits par exécution :

- `XAUUSD-<horodatage>.jsonl` — une ligne par observation, append-only, `fsync` à chaque
  vidage ;
- `XAUUSD-<horodatage>.manifest.json` — écrit **avant** la collecte, il porte les
  empreintes Q1 / Q63 / Q65, le commit logiciel, le mode d'acquisition, le biais de
  sondage et le statut des données.

> **Sauvegarder `--out-dir` hors de la machine de collecte.** Le journal est le seul
> exemplaire : `.gitignore` ne l'exclut pas, mais rien ne le copie non plus. Un disque perdu
> emporte des séances qui ne se rejouent pas.

### Options utiles

| option | effet |
|---|---|
| `--minutes N` | arrêt après N minutes |
| `--max-events N` | arrêt après N observations |
| `--poll-ms X` | intervalle de sondage (défaut 1 ms) |
| `--session NOM` | étiquette de séance, entre dans la cellule |
| `--preflight-only` | lit le compte et s'arrête |

---

## 4. Lire le rapport sans se tromper

Le rapport publie, par cellule, `p50 / p95 / p99` de la borne locale `B5 − B1` et
l'intervalle de confiance bootstrappé **par grappe**.

Quatre choses à ne pas confondre :

**`IC non calculable — n grappe(s)`** n'est pas une erreur. L'intervalle se bootstrappe sur
les grappes ; avec une seule, il n'existe pas. Un intervalle nul ferait passer une absence
d'information pour une précision parfaite.

**Le biais de sondage** est annoncé séparément. L'API MT5 se sonde, elle ne pousse pas :
B1 date l'instant où nous avons regardé, pas l'arrivée du tick. Jusqu'à `--poll-ms` s'est
écoulé avant, sans être observé. À retrancher de toute réactivité annoncée.

**B0 est enregistré mais n'entre dans aucune borne.** `time_msc` est l'horloge du serveur
du courtier ; son écart avec la nôtre contient un décalage inconnu, pas seulement un temps
de transport. Le qualifier exigerait la procédure Q57/Q58.

**Les durées mesurées bornent par le bas celles du système final**, puisque l'évaluation
est vide. Elles ne décrivent pas la latence d'un système qui déciderait vraiment.

---

## 5. Ce que cette collecte peut et ne peut pas produire

| ✅ elle peut | ❌ elle ne peut pas |
|---|---|
| mesurer la borne locale par cellule et par régime | fonder un verdict normatif (pas de gel) |
| révéler la couverture réelle des séances | prononcer une exclusion oracle (Q63 `PROVISIONAL`) |
| mesurer l'effet observateur de l'instrumentation | annoncer la réactivité du système final |
| établir la structure des grappes et des rafales | rien conclure d'un rejeu |

Le statut `EXPLORATORY` est **irréversible pour ces données** : il ne se rattrape pas en
gelant le protocole après coup. C'est voulu — et ce n'est pas une raison d'attendre. Une
séance non enregistrée aujourd'hui ne se reconstruit pas demain, tandis qu'un gel de
protocole posé demain reste possible.

---

## 6. Quand passer en normatif

Une fois les premières séances enregistrées, dans cet ordre :

1. **Q63 → `VERIFIED`** : le préflight l'a fait, vérifier le manifeste ;
2. **Q66** : campagne de calibration de couverture — un certificat, pas une déclaration ;
3. **`ProtocolFreeze`** : empreinte complète (commit, Q1, Q64, calendrier, contrat de
   données, cible de pipeline, qualification d'horloge) ;
4. À partir de cet instant, et à empreinte identique, les observations deviennent
   `NORMATIVE`. Toute divergence ouvre un **nouveau segment** — jamais une fusion.
