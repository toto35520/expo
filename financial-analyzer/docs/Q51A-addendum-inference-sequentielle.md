# Addendum pré-collecte Q51-A — Inférence séquentielle, ancrage, budget

> Statut : **figé et implémenté**. Code : `feasibility/sequential.py`, extensions de
> `feasibility/passive_campaign.py`. 46 tests ajoutés.
>
> Trois corrections avant la première observation normative. Deux étaient bloquantes.

---

# Partie A — Q59-A · l'arrêt doit être statistiquement valide

## 1. Ce qui était insuffisant

La politique précédente était :

```
arrêter lorsque l'intervalle devient suffisamment étroit
→ afficher confidence_interval_is_optimistic
```

Le diagnostic décrivait mal le problème. Si la décision d'arrêt dépend de l'intervalle
observé, un intervalle classique calculé après l'arrêt **ne conserve pas sa couverture
nominale**. Ce n'est pas :

```
intervalle potentiellement optimiste
```

mais :

```
garantie statistique non valide sous cette règle d'arrêt
```

La différence est vérifiable, et elle est brutale. Un adversaire qui surveille en continu et
s'arrête dès que l'intervalle exclut la vraie valeur obtient, sur 800 réplications :

| méthode | franchissements | niveau annoncé |
| --- | --- | --- |
| séquence de confiance | **0 %** | 5 % |
| Hoeffding à horizon fixe | 0,03 % *(survit par excès de conservatisme)* | 5 % |
| intervalle normal recalculé en continu | **48 %** | 5 % |

Un avertissement à côté d'un chiffre franchi une fois sur deux ne le rattrape pas.

## 2. Deux modes, déclarés avant la première observation

### `FIXED_HORIZON`

La durée est gelée d'avance — période calendaire, nombre de séances, ou nombre de grappes.
La campagne ne s'arrête **ni** parce que le résultat est favorable, **ni** parce qu'il est
défavorable, **ni** parce que le p95 semble stable, **ni** parce que l'intervalle est devenu
étroit.

Une largeur atteinte est un **diagnostic**. Le module l'affiche et refuse qu'elle déclenche
l'arrêt. Symétriquement, un intervalle trop large ne peut pas **prolonger** la campagne : ce
serait un arrêt dépendant des données par l'autre bout.

### `ANYTIME_VALID`

L'arrêt peut dépendre de l'incertitude, parce que la garantie est simultanée dans le temps :

```
P( ∀n, θ ∈ CS_n ) ≥ 1 − α
```

La campagne peut alors s'arrêter à un temps aléatoire `τ` sans invalider la garantie.

`StoppingPolicy` refuse de se construire si `ANYTIME_VALID` n'a pas de `ρ` déclaré, ou si
`FIXED_HORIZON` n'a pas de durée gelée.

## 3. La construction retenue

Mélange normal de Robbins, appliqué **au niveau des grappes** :

```
P( ∃n : |S_n| ≥ √( 2 (V_n + ρ) · log( √((V_n + ρ)/ρ) / α ) ) ) ≤ α
```

Chaque grappe est réduite à une valeur unique — la fraction d'observations sous le seuil —
ce qui fait du **nombre de grappes**, et non du nombre d'observations, la taille
d'échantillon de l'inférence. Une rafale de 300 ticks et un bloc calme de 30 produisent
chacun une observation d'inférence.

L'estimande est donc explicitement `EQUAL_PER_CLUSTER`, distinct du quantile empirique usuel
qui pondère par observation. Les deux répondent à des questions différentes et le type le
déclare.

**Un seul seuil, donc aucune correction d'union.** La décision porte sur la latence
admissible, qui est fixe : `Q_q > seuil` équivaut à `F(seuil) < q`. Aucune inversion sur une
grille de quantiles n'est nécessaire, donc aucune borne d'union n'est due.

## 4. Le conservatisme, et son asymétrie utile

`σ² = 1/4` (Hoeffding sur [0, 1]) est volontairement lâche — les fractions intra-grappe ont
une variance bien moindre. Le coût est très asymétrique, et l'asymétrie tombe du bon côté :

| pour conclure | marge à franchir | grappes nécessaires |
| --- | --- | --- |
| **exclure** (`F ≈ 0,50` contre `q = 0,95`) | 0,45 | **69** |
| marge intermédiaire | 0,20 | 176 |
| **« non exclu »** (`F ≈ 1,00` contre `q = 0,95`) | 0,05 | **1 106** |

Exclure est bon marché ; conclure « non exclu » est cher. C'est cohérent avec le statut des
deux verdicts — l'exclusion conclut, la non-exclusion autorise seulement à continuer de
chercher. `clusters_for_separation()` rend ce coût chiffrable **avant** de geler un horizon.

## 5. Le faux garde-fou est supprimé

`confidence_interval_is_optimistic` subsiste comme diagnostic historique et n'a plus aucune
valeur de protection. Un run portant :

```
data_dependent_stop = TRUE
inference = ORDINARY_CI
```

reçoit `SEQUENTIAL_INFERENCE_INVALID`. Il n'y a pas de chiffre à publier assorti d'une
réserve : il y a une procédure à refaire.

## 6. Q59 se décompose

```
Q59-A — méthode d'inférence      ← à trancher en premier
Q59-B — couverture minimale
Q59-C — précision utile
Q59-D — règle d'arrêt
```

Recommandation retenue : `ANYTIME_VALID` si l'implémentation statistique est jugée
suffisamment robuste — elle l'est, elle est testée par simulation adverse — sinon
`FIXED_HORIZON` pour la première campagne. **Un protocole plus simple mais valide vaut mieux
qu'un protocole sophistiqué mal calibré.**

---

# Partie B — Q61 · deux budgets, pas un seul

## 7. Q61-A — la borne oracle, indépendante de tout signal

Avant qu'un signal existe, `edge_j(L, h, c)` est inconnu pour tout moteur `j`. Inventer un
`Lmax` à partir d'un avantage prédictif supposé réintroduirait une croyance sur l'alpha dans
un test conçu pour en être indépendant.

Ce qui **peut** se calculer sans signal est une borne optimiste du mouvement encore
capturable :

```
U_capture(L, h, c)
```

Construite en offrant gratuitement au système ce qu'aucun moteur réel ne possède : la
direction connue à l'avance et l'instant de sortie parfait dans la fenêtre restante. Aucun
détecteur ne peut faire mieux.

```
U_capture ≤ C_floor   ⇒   LATENCY_COST_ORACLE_EXCLUDED
```

L'argument est plus fort qu'un `Lmax` arbitraire : même un détecteur extrêmement favorable ne
dispose plus d'un mouvement suffisant après la latence observée. Si `L ≥ h`, la capture vaut
zéro et l'événement **reste dans l'échantillon** — le retirer ne conserverait que les cas où
l'on avait eu le temps d'agir.

## 8. Q61-B — le budget d'un moteur validé

Plus tard, lorsqu'un moteur `j` existe et a passé ses gates :

```
L_max,j(h, c) = sup { L : edge_net,j(L, h, c) > δ_MEU }
```

Ce budget est spécifique au moteur, à l'horizon, à la cellule, au régime et au type d'ordre,
et se fige dans le protocole du moteur avant son évaluation finale.

`AdmissibleLatency` exige désormais un `engine_id` nommé : un budget anonyme ne se construit
pas.

## 9. Conséquence sur le calendrier

**Q61-B ne bloque pas le premier verdict réel.** La phase 0 doit précisément pouvoir éliminer
des horizons avant qu'un signal soit inventé. Le premier verdict peut déjà être
`PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY` si les bornes physiques — coûts et latence —
suffisent.

Q61-B ne devient nécessaire que pour décider : *un moteur prédictif particulier reste-t-il
exploitable avec cette latence ?*

---

# Partie C — l'ancrage est un type

## 10. Trois ancres, trois estimandes

| Ancre | `t₀` | Ce qu'elle ignore |
| --- | --- | --- |
| `MARKET_EVENT_ANCHOR` | instant de l'événement de marché | rien — référence économique idéale |
| `PROVIDER_EVENT_ANCHOR` | horodatage fournisseur | appariement, agrégation, délai interne avant publication |
| `LOCAL_RECEIVE_ANCHOR` | `B1` | tout ce qui précède la réception locale |

Les portées correspondantes — `END_TO_END_MARKET`, `PROVIDER_TO_ACTION`,
`POST_RECEIVE_ONLY` — **ne se fusionnent jamais** dans une même distribution.

Chaque portée impose son nom de publication. « Capturabilité » tout court est interdit : il
se lirait comme une mesure de bout en bout.

```
END_TO_END_CAPTURABILITY
PROVIDER_ANCHORED_CAPTURABILITY
POST_RECEIVE_CAPTURABILITY
```

## 11. Correction apportée à l'ADR-180

L'ADR-180 affirmait qu'une qualification Q57 de `B0 → B1` donnait l'ancre marché et retirait
l'optimisme. C'est faux : elle donne l'ancre **fournisseur**. L'horodatage fournisseur reste
une borne optimiste — moins lâche, pas exacte — parce qu'il ignore ce qui s'est passé entre
l'appariement et la publication.

## 12. La fin de l'horizon ne se déplace pas en silence

Déplacer l'ancre sans fixer la fin de l'horizon créerait deux estimandes sous le même nom :

```
horizon économique   [ t_marché  , t_marché  + h ]
horizon glissé       [ t_réception, t_réception + h ]
```

Le second va plus loin dans le futur de `t_réception − t_marché`, et peut donc **fabriquer**
du mouvement capturable. `HorizonEndPolicy` est explicite —`FIXED_MARKET_END` ou
`ANCHORED_TO_ORIGIN` — et `creates_extended_window` signale la combinaison à risque.

## 13. L'asymétrie de `POST_RECEIVE_ONLY`

Si, même après avoir donné gratuitement au système toute la dissémination, tout le trajet
fournisseur et tout le réseau entrant, la latence interne suffit à éliminer l'horizon, alors
**l'exclusion est forte**.

Mais une non-exclusion sous cette portée ne dit strictement rien du chemin de bout en bout.
`interpret()` produit deux phrases distinctes selon le sens du résultat, et la non-exclusion
nomme systématiquement la portée dont elle relève.

---

# Partie D — corrections non bloquantes

## 14. Le découpage du régime calme est versionné

`BlockingChoice` porte durée, source et version. L'inférence est refaite sur `{b/2, b, 2b}`
et `blocking_is_robust()` vérifie que tous les découpages placent le seuil du même côté de
l'intervalle. Un verdict qui bascule entre `b/2` et `2b` décrit le découpage autant que la
latence.

À terme, la durée devra être confrontée à l'autocorrélation des latences et du débit de
ticks, aux épisodes de file et de connexion, et à la durée des régimes de charge : les blocs
doivent être assez longs pour ne pas présenter comme indépendantes des observations qui ne le
sont pas.

## 15. L'effet observateur est un banc apparié

```
O = L_instrumenté − L_baseline
```

publié en p50, p95, p99. Sérialiser hors du chemin critique ne supprime ni la lecture
d'horloge, ni la création d'objet, ni l'allocation, ni la mise en file, ni la contention. Un
surcoût arrondi à zéro alors que l'horloge a avancé lève une erreur — et deux séries de
tailles différentes sont refusées, comparer les mesurerait aussi la différence d'échantillon.

## 16. Q43 exige un flux apparié

« Event-driven lundi contre periodic mardi » ne permet pas d'attribuer l'écart à la cadence :
les marchés n'étaient pas les mêmes. `PAIRED_REPLAY` et `SHADOW_EVALUATION` autorisent
l'attribution ; `UNPAIRED_DAYS` ne produit qu'un diagnostic et le dit.

---

# La première chaîne réelle

```
Q50    → vraie chronologie marché
Q51-A  → vraie borne locale
Q57    → domaine d'horloge réellement qualifié
Q40    → vraie surface de coûts
Q19-0  → capturabilité signal-agnostique
```

puis

```
D_feasible = D_cost ∩ D_passive_latency ∩ D_capturability
```

avec six états possibles :

```
PHASE0_EXCLUDED_BY_COST
PHASE0_EXCLUDED_BY_PASSIVE_LATENCY
PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY
PHASE0_NOT_EXCLUDED
PHASE0_INDETERMINATE
PHASE0_MEASUREMENT_INVALID
```

`PHASE0_NOT_EXCLUDED` ne signifie **jamais** qu'un bon trade est possible. Il signifie
seulement qu'il reste physiquement et économiquement assez d'espace pour justifier la
recherche d'un signal.

---

## Ce qui reste à trancher avant le premier tick

**Bloquant** — trois décisions, pas du code :

1. `FIXED_HORIZON` ou `ANYTIME_VALID` pour Q59-A, et les valeurs qui vont avec ;
2. la latence admissible de Q61-B, **seulement si** un moteur existe — sinon la phase 0
   s'exécute sans elle ;
3. le plancher de coûts `C_floor` de Q40, sans lequel l'exclusion oracle ne se calcule pas.

Le point 2 n'est plus bloquant : c'était l'erreur de la conclusion précédente.

**Avant le verdict final**, non bloquant pour la collecte :

4. la sensibilité au découpage des grappes calmes, sur données réelles ;
5. le banc d'effet observateur sur l'hôte réel ;
6. le protocole apparié pour Q43.
