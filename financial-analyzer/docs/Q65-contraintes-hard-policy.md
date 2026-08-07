# Q65 — `HARD` contre `POLICY` (`Q65-GOLD-RECOMMENDATION-V1`)

**Empreinte** : `d712142fbf1603bb` · **Statut** : figé · **Code** :
`feasibility/constraints.py`

```
PHYSICAL_ORACLE = HARD uniquement
POLICY_ORACLE   = HARD + POLICY
```

Une contrainte mal classée ne change pas un chiffre, elle change le **sens** d'une
exclusion. Un cooldown que nous avons choisi, s'il entre dans le `PHYSICAL_ORACLE`, réduit
la capture maximale atteignable et peut produire « aucun moteur XAUUSD possible ne peut
être viable » — alors que la phrase vraie était « aucun moteur *tel que nous avons décidé
de le construire* ».

---

## HARD — 17 contraintes

Elles entrent dans le `PHYSICAL_ORACLE`. Aucune n'est choisie par l'analyseur.

| contrainte | identifiant |
|---|---|
| instrument réellement coté | `quoted_instrument` |
| horaires réels de cotation | `quoting_hours` |
| prix réellement disponibles | `available_prices` |
| bid / ask réellement observés | `observed_bid_ask` |
| tick size / point size | `tick_size` |
| contract size | `contract_size` |
| minimum lot | `minimum_lot` |
| lot step | `lot_step` |
| maximum lot courtier | `broker_maximum_lot` |
| margin / leverage imposés au compte | `margin_and_leverage` |
| latence déjà effectivement subie | `suffered_latency` |
| market closure / trading halt | `market_closure` |
| règles contractuelles du courtier | `broker_contractual_rules` |
| frais contractuellement inévitables | `contractually_inevitable_fees` |
| financement inévitable au rollover | `inevitable_financing` |
| types d'ordre proposés par le courtier | `broker_offered_order_types` |
| capital réellement disponible | `available_capital` — **conditionnelle**, voir §4 |

## POLICY — 12 contraintes

Elles n'entrent jamais dans une exclusion de *tout moteur*. Elles appartiennent au
`POLICY_ORACLE`.

| contrainte | identifiant |
|---|---|
| risque planifié = 0,50 % equity par trade | `planned_risk_per_trade` |
| risque ouvert maximal = 2R | `max_open_risk` |
| drawdown maximal de validation = 12R | `max_validation_drawdown` |
| nombre maximal de trades simultanés | `max_concurrent_trades` |
| cooldown | `cooldown` |
| séances que nous choisissons de trader | `selected_sessions` |
| interdiction volontaire de types d'ordre | `self_restricted_order_types` |
| filtres macro | `macro_filters` |
| seuil de confiance | `confidence_threshold` |
| seuil de qualité | `quality_threshold` |
| politique NO_TRADE | `no_trade_policy` |
| limites d'exposition de l'architecture | `architecture_exposure_limits` |

> **La confusion la plus facile** : `quoting_hours` est `HARD`, `selected_sessions` est
> `POLICY`. Les heures d'ouverture ne se négocient pas ; les séances que nous retenons, si.

---

## 3. Le registre est fermé

Une contrainte absente n'est **ni** supposée dure **ni** supposée politique.

```python
Q65_V1.get("filtre_maison_v3")
# CampaignError: le registre est fermé…

Q65_V1.universal_claim(("quoting_hours", "filtre_maison_v3"))
# BLOCKED_BY_UNCLASSIFIED
```

Classer l'inconnu en `POLICY` par défaut irait pourtant dans le sens sûr — l'écarter de la
borne physique la rend plus favorable, donc n'exclut rien à tort. Le choix a été écarté
parce qu'une valeur par défaut sûre finit toujours par être lue comme une classification
(ADR-251).

---

## 4. Cas particulier — le capital

Le capital n'est `HARD` que lorsqu'une contrainte contractuelle rend l'exécution réellement
impossible :

```
lot minimum du courtier + distance au stop
    → risque minimal possible = 1,8R  >  1R planifié
    → EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL
```

```python
preuve = Q65_V1.capital_constraint(
    smallest_lot_risk_r=1.8, planned_risk_r=1.0,
    source="MT5 volume_min + distance au stop",
)
Q65_V1.universal_claim(("available_capital", "tick_size"), [preuve]).scope
# "tout moteur XAUUSD possible **sur ce compte** — une contrainte de capital prouvée
#  limite la portée au compte, jamais au marché"
```

Sans preuve, le capital est **écarté** de la borne physique — ce qui la rend plus favorable
et ne peut donc rien exclure à tort. Avec preuve, il entre, mais la portée du verdict
devient explicitement le compte.

Et dans les deux cas : **cela ne transforme jamais le signal en mauvais signal**. La qualité
se mesure en `R` (Q1-v1) ; l'exécution décide séparément si ce capital peut la financer.

---

## 5. Cas particulier — les types d'ordre

| fait | classe |
|---|---|
| le courtier propose ou non un type d'ordre | `HARD` |
| « nous n'utiliserons que des market orders » | `POLICY` |

```python
Q65_V1.physical_order_types(
    broker_offered=("MARKET", "LIMIT", "STOP"), self_allowed=("MARKET",)
)
# ("MARKET", "LIMIT", "STOP")
```

Le `PHYSICAL_ORACLE` reçoit **tous** les modes réellement disponibles. Ne lui laisser que le
nôtre rendrait l'exécution artificiellement coûteuse et pourrait éliminer une famille de
stratégies au motif que *nous* refusons l'ordre qui la rendait viable.

---

## 6. La règle normative, exécutable

```python
verdict = Q65_V1.universal_claim(applied_constraints)
if not verdict.admissible:
    ...  # la borne ne porte pas sur « tout moteur possible »
```

| verdict | ce qui l'a produit |
|---|---|
| `ADMISSIBLE` | uniquement du `HARD`, conditionnelles prouvées |
| `BLOCKED_BY_POLICY` | une contrainte que nous avons choisie |
| `BLOCKED_BY_UNPROVEN_CONDITIONAL` | le capital, sans preuve |
| `BLOCKED_BY_UNCLASSIFIED` | une contrainte hors registre |

L'énoncé universel n'est plus une formulation choisie au moment d'écrire le rapport : c'est
une propriété calculée depuis les contraintes réellement appliquées.
