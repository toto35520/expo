# Q63 — plancher de coûts XAUUSD / IC Markets MT5

**Version** : `Q63-XAUUSD-ICMARKETS-MT5-V1` · **Statut** : `PROVISIONAL` · **Code** :
`feasibility/cost_floor_xauusd.py`

`C_floor` est la borne **inférieure** du coût réellement incontournable. Ni une estimation
centrale, ni un coût prudent : `C_réel ≥ C_floor` doit être défendable.

> On préfère **manquer une exclusion** plutôt qu'en **fabriquer une**.

---

## 1. Ce qui manque, et pourquoi cela ne se devine pas

| élément | pourquoi il bloque | où le relever |
|---|---|---|
| `ACCOUNT_TYPE` | Raw Spread a une commission contractuelle donc un plancher positif ; Standard n'en a pas — son coût passe par un mark-up de spread, qui n'est pas un plancher | MT5 → propriétés du compte |
| `ACCOUNT_BASE_CURRENCY` | le tarif diffère (7,00 USD / 6,50 EUR / 5,50 GBP par lot AR) et une commission hors USD exige un taux de change | MT5 → propriétés du compte |
| `MT5_SYMBOL_SPECIFICATION` | sans contract size ni tick size contractuels, aucune conversion `lot → oz → R` n'est légitime | MT5 → clic droit sur XAUUSD → Spécification |

Le préflight du collecteur les lit et fait passer Q63 en `VERIFIED` sans intervention :

```bash
python -m feasibility.collect_xauusd --source mt5 --preflight-only
```

**`PROVISIONAL` ne bloque pas la collecte.** Un plancher non résolu interdit une
*exclusion*, pas une *observation* (ADR-255).

---

## 2. Les composants

```
C_floor = certain_commission + mandatory_fees + observed_crossing
        + unavoidable_financing + signed_credits
```

| composant | valeur | raison |
|---|---|---|
| `certain_commission` | Raw : tarif ÷ contract size · côtés — Standard : `0` | contractuelle |
| `mandatory_fees` | `0` | aucun autre frais obligatoire documenté |
| `observed_crossing` | `0` | rien ne garantit un franchissement strictement positif ; **interdit** pour un ordre passif |
| `unavoidable_financing` | `0` ou `UNRESOLVED` | voir §4 |
| `signed_credits` | `0` | sauf crédit contractuel réellement applicable |
| `slippage_floor` | `0` | une moyenne de slippage n'est pas une borne inférieure |
| `adverse_selection_floor` | `0` | même raison — elle appartient au coût réel, pas au minimum garanti |

Le **spread moyen publié** (≈ 0,08 sur XAUUSD Raw au moment de la consultation) est un
diagnostic. Il ne devient jamais `C_floor`. Le spread observé en temps réel appartient au
modèle de coût réel **Q40**.

---

## 3. La commission

Raw Spread, compte USD, contract size 100 oz :

```
7,00 USD / lot aller-retour ÷ 100 oz = 0,070 USD/oz  (aller-retour)
                                     = 0,035 USD/oz  (entrée seule)
```

`ENTRY_ONLY` est le **défaut**. Retenir l'aller-retour quand la sortie n'est pas prouvée
dans la fenêtre mesurée mettrait en regard deux périmètres différents et gonflerait le
plancher (ADR-259).

Un compte **hors USD** rend `UNRESOLVED` : un taux de change n'est pas contractuel. Une
borne inférieure déclarée et sourcée sur la parité conviendrait ; l'inventer, non.

---

## 4. Le financement — pourquoi `0` serait faux

| exposition | financement |
|---|---|
| clôturée avant le rollover | `0` **exactement** — c'est une preuve, pas une prudence |
| pouvant traverser le rollover | `UNRESOLVED` — bloque le plancher |

L'argument n'est pas rhétorique, il est arithmétique :

```
swap défavorable  →  C_réel = commission + swap    >  commission
swap favorable    →  C_réel = commission − crédit  <  commission
```

Poser `financement = 0` donne `C_floor = commission`. Avec un swap **créditeur**,
`C_réel < C_floor` : la propriété qui fonde toute exclusion tombe. **Zéro n'est pas
conservateur ici, il est faux** (ADR-256).

Et connaître `swap_long` / `swap_short` ne suffit pas : MT5 les exprime selon `swap_mode` —
points, devise du compte par lot, pourcentage annuel. Une `SwapConversion` explicite,
sourcée, et dont le mode correspond à celui du symbole, est exigée (ADR-257) :

```python
SwapConversion("POINTS", usd_per_oz_per_swap_unit=0.001, source="MT5 spec, AAAA-MM-JJ")
```

Les swaps se relèvent **le jour de la collecte**. Les valeurs publiées varient, et la
référence est la plateforme du compte — pas une page web figée pour des mois.

---

## 5. `UNRESOLVED` n'est pas `None`, n'est pas `0`

```python
bool(UNRESOLVED)
# CampaignError: UNRESOLVED n'a pas de valeur de vérité : le tester comme un booléen
# le ferait silencieusement passer pour zéro.
```

`None` se confond avec « pas de valeur », `0.0` avec « valeur nulle prouvée ». C'est
exactement la confusion qui transforme une ignorance en plancher.

---

## 6. À quoi le plancher a le droit de servir

```python
resolution.value_for(FloorUse.ORACLE_EXCLUSION)      # ✅
resolution.value_for(FloorUse.EXPECTED_COST_MODEL)   # ❌ CampaignError → Q40
```

Le plancher **sous-estime délibérément** le coût réel : c'est ce qui le rend sûr pour
l'exclusion. Employé comme coût attendu, la même sous-estimation ferait apparaître un
avantage là où il n'y en a pas — l'erreur inverse, dans la direction défavorable (ADR-258).

---

## 7. Passer en `VERIFIED`

Il suffit du terminal :

```
MT5 → propriétés du compte      → Raw Spread ou Standard, devise de base
MT5 → clic droit XAUUSD → Spéc. → contract size, tick size, lots, swaps, swap mode
```

Le préflight lit les trois et bascule le statut. Si le libellé du compte ne contient ni
« raw » ni « standard », `ACCOUNT_TYPE` reste `UNKNOWN` — voulu : une déduction incertaine
ne doit pas devenir une commission contractuelle. Le déclarer alors à la main, avec sa
source.
