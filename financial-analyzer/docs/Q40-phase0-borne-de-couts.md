# Q40 Phase 0 — Borne de coûts et horizon minimal exploitable

> Statut : **figé et implémenté**. Remplace `Q40-modele-de-couts.md` sur les points où les
> deux divergent. Code : `financial-analyzer/feasibility/`.
>
> Objet : déterminer, **avant toute définition de signal**, quelles cellules sont
> incompatibles avec les coûts observés. Ne cherche pas à démontrer une rentabilité — seulement
> à réduire l'espace où il est rationnel d'en chercher une.

---

# Partie A — Protocole normatif

## 1. Principe

```
κ(h,c) = C_total(h,c) / σ(h,c)
```

Nombre d'unités d'amplitude à capturer **uniquement pour couvrir les frais**. Les coûts variant
peu avec l'horizon et l'amplitude croissant avec lui, κ décroît — ce qui borne par le bas les
horizons où un avantage peut exister.

## 2. Cellule de décision

`c = (instrument, marché de détection, marché d'exécution, horizon, type d'ordre, session,
taille, régime)`. **Un verdict n'est valable que pour sa cellule.** Non viable en creux de
liquidité et non exclu en séance liquide n'est pas une contradiction.

## 3. Deux méthodes de coût, jamais mélangées

**Méthode A — implementation shortfall observé.** `IS_entrée = d·(P_fill − P_référence)`,
symétrique en sortie. Contient déjà spread, mouvement pendant la latence, glissement, impact,
effet de file. **Interdit d'y ajouter `C_spread`, `C_slippage` ou `C_latence`.**

**Méthode B — décomposition modélisée.** Spread explicite, glissement fonction déclarée de
`(L, σ, o, q, r)`, impact selon taille et liquidité. **Interdit d'y injecter un glissement
observé de bout en bout.**

Champs obligatoires : `reference_price_convention`, `cost_measurement_method`,
`round_trip_definition`, `spread_counting_convention`.

## 4. Composants

| Terme | Règle |
| --- | --- |
| **Spread** | celui observé **au moment où l'opération aurait été déclenchée** ; jamais le spread annoncé. Quantiles p10 à p99 par session, régime, jour, proximité de publication, taille |
| **Commission** | normalisée en devise du compte : par côté, aller-retour, minimum, palier de volume, coût de conversion |
| **Glissement** | inclus dans l'IS en méthode A ; fonction déclarée en méthode B. **Moyenne globale interdite**, queues publiées |
| **Impact** | jamais fixé arbitrairement à zéro ; déclarable `BELOW_MEASUREMENT_RESOLUTION` avec borne prudente |
| **Financement** | coût **signé**, chargé depuis la spécification réelle du compte. Le jour de portage multiplié se **vérifie**, ne se suppose pas |
| **Rollover futures** | événement distinct : commissions de sortie et réentrée, spread calendaire, glissement, changement de contrat dominant |
| **Base** | séparer `basis_actual_transaction_cost` (entre dans `C_total`) de `basis_translation_uncertainty` (entre dans la marge, l'intervalle, la suspension). Sans cette séparation, une même incertitude serait comptée deux fois |

## 5. Sélection adverse

`E[R_h | fill] < E[R_h]` pour une stratégie passive mal spécifiée.
`AS(h) = −E[d(P_{t_f+h} − P_f) | fill]`, comparé à un témoin apparié sur heure, volatilité,
direction, distance au marché, spread, régime, impulsion préalable.

Publiés : probabilité d'exécution, exécution partielle, délai, dérive post-exécution, taux
d'annulation avant exécution, incertitude de position dans la file.

**Un backtest « le prix touche la limite ⇒ ordre exécuté intégralement » est invalide** pour la
mesure économique finale.

## 6. Amplitude multi-échelle

Mesure **empirique** : `σ(h,c) = Scale(P_{t+h} − P_t | c)`, par estimateur robuste. La loi en
`√h` sert à vérifier l'ordre de grandeur et repérer les anomalies — **jamais à imposer une courbe
aux données**. Publiés : composante continue, composante de saut, composante de tendance.

Grille d'horizons fixée **avant** lecture des résultats.

## 7. Distribution de κ et verdicts

Coût et amplitude sont des distributions : publier `κ_p50`, `κ_p75`, `κ_p90`, `κ_p95`, intervalle
de confiance, nombre d'observations **et de clusters indépendants**.

| Verdict | Condition |
| --- | --- |
| `COST_NON_VIABLE` | `LCB[κ] > a_max` — même en lecture optimiste, la cellule exige plus que le plausible |
| `COST_NOT_EXCLUDED` | `LCB[κ] ≤ a_max` — **ne démontre aucune rentabilité** |
| `COST_HEADROOM` | `UCB[κ] < a_min` — marge confortable, reste soumis aux autres gates |
| `COST_INDETERMINATE` | données insuffisantes ou trop incertaines |

**Horizon minimal de coût** : franchissement **persistant**, sur plusieurs horizons consécutifs
et une majorité de blocs temporels. Un point isolé ne suffit pas.

## 8. Bande d'avantages plausibles

`A = [a_min, a_max]` en unités d'amplitude par occurrence, **déclarée avant** tout tracé de κ.
La modifier après observation revient à choisir la conclusion.

## 9. Fréquence

Deux planchers distincts, `f_min = max(f_min_econ, f_min_stat)` :

```
f_min_econ = (J_min + C_fixes_temps) / (p_fill × EV_net_par_occurrence)
```

Avant validation, une borne **optimiste** d'`EV` suffit : si même elle exige plus d'occurrences
qu'il n'en survient, `FREQUENCY_NON_VIABLE` est conclu **avant tout test prédictif**.

`f_min_stat` couvre la validabilité : occurrences, séances indépendantes, régimes, clusters,
résultats non censurés.

## 10. Enveloppe de faisabilité

```
D_feasible = D_cost ∩ D_latency ∩ D_frequency
```

Hors de cette intersection, aucune autorité de déclenchement et aucun budget de construction
important. `ELIGIBLE_FOR_PREDICTIVE_TESTING` ne signifie **jamais** rentable.

## 11. Phases

| Phase | Entrées | Sortie |
| --- | --- | --- |
| **0A** | ticks, bid/ask, commissions, financement | carte des horizons exclus / non exclus / indéterminés |
| **0B** | horodatages bruts d'occurrences d'une famille | verdict de fréquence, avant toute qualité prédictive |
| **0C** | campagne réelle | IS, latence conditionnelle, impact, taux d'exécution, sélection adverse |

Les ordres limites éloignés puis annulés mesurent le trajet de messagerie de l'infrastructure
réelle. **Ils ne mesurent ni le remplissage, ni la file, ni le glissement, ni la sélection
adverse** — ils ne remplacent pas une campagne d'exécution.

## 12. Marges, jeu réservé, asymétrie

`M_sécurité` couvre incertitudes de coût, de volatilité, de sélection adverse, de base,
dégradation recherche-production, erreur de mesure, changement de régime — estimée sur les écarts
entre coûts prédits et observés. Sans historique réel, déclarée comme **hypothèse**, jamais comme
observation.

Jeu réservé : contigu, postérieur, séparé par un tampon au moins égal à la plus longue dépendance
pertinente. Idéalement une période future n'existant pas encore au gel du protocole.

**Asymétrie des conclusions** : un résultat positif sur version grossière est informatif — un
raffinement peut améliorer. Un résultat négatif sur version grossière ne réfute pas la famille ;
il ne devient conclusif que s'il vient d'une **borne supérieure indépendante du détecteur**
(phase 0 de Q19, phase 0 de Q40, ou test d'équivalence de puissance suffisante).

---

# Partie B — Ce que l'implémentation a révélé

Le protocole est implémenté dans `feasibility/` avec 39 tests. Cinq points ne sont apparus qu'à
l'exécution — ils ne se voyaient pas dans la spécification.

## B1 — La densité de ticks conditionne la validité de σ(h)

Première exécution : σ identique — au chiffre près — pour des horizons de 1 s, 10 s et 60 s.
Valeur obtenue : `1,4826 × pas de cotation`. Autrement dit **la médiane des déplacements valait
exactement un tick**, parce que le générateur produisait un tick toutes les 29 secondes : un
horizon d'une seconde ne contenait aucun tick.

Conséquence : κ devenait plat aux horizons courts, ce qui se serait lu comme *« les coûts ne
dominent pas davantage à 1 s qu'à 60 s »* — l'inverse de la réalité, et l'inverse du mécanisme
que la phase 0 est censée mettre en évidence.

**Règle** : avant d'interpréter toute valeur de κ, publier le **nombre de ticks par horizon** et
écarter les horizons où il est trop faible. Un horizon dont l'amplitude sature sur le pas de
cotation mesure la discrétisation, pas le marché.

Ce point vaut pour les données réelles : en creux asiatique, un horizon de quelques secondes peut
être exactement dans ce régime.

## B2 — Une latence dépassant l'horizon doit compter comme consommation totale

La première version écartait les événements où l'instant d'exécution possible tombait après la
fin de la fenêtre d'évaluation. C'est un biais de sélection : **ne restaient que les événements
où l'on avait eu le temps d'agir**, donc les plus favorables.

Effet mesuré : à l'horizon d'une seconde avec une latence p95 de deux secondes, l'échantillon se
vidait et le verdict passait de `NON_VIABLE` à `INDETERMINATE`. Un résultat conclusif — *il n'y a
littéralement plus rien à capturer quand on peut enfin agir* — se transformait en absence de
conclusion.

**Règle** : ces cas comptent comme consommation totale et résiduel nul. Après correction, la
part consommée à l'horizon d'une seconde passe de 18 % à 71 %, et le verdict redevient conclusif.

## B3 — La règle de persistance mord réellement

Sur la démonstration, la borne supérieure de κ passe sous `a_max` à 3 600 s puis 7 200 s — **deux
horizons consécutifs**, là où la règle en exige trois. Le protocole rend donc « aucun horizon
minimal trouvé sur la grille étudiée ».

Une lecture ponctuelle aurait annoncé `h_min = 1 800 s`. La règle de persistance a fait
exactement ce pour quoi elle existe, sur le premier jeu de données rencontré.

## B4 — Coût et amplitude doivent être rééchantillonnés sur les mêmes blocs

Ils partagent la séance : le spread est large les jours agités, et l'amplitude aussi. Les
rééchantillonner indépendamment supprimerait cette dépendance et **resserrerait artificiellement**
l'intervalle sur κ — donc conduirait à exclure des cellules par excès de confiance.

L'implémentation tire les blocs une seule fois et recalcule les deux grandeurs dessus.

## B5 — L'interdiction de double comptage est vérifiable, pas seulement énonçable

L'interdiction d'additionner spread et implementation shortfall est appliquée par le constructeur
de conventions : une combinaison invalide lève une erreur avant tout calcul, et deux tests
vérifient que les deux sens de l'erreur se déclenchent. Ce n'est plus une consigne à respecter
mais un état inaccessible.

Le diagnostic `√h` a par ailleurs produit des rapports observé/attendu allant jusqu'à **2,6** sur
des données comportant des sauts : extrapoler l'amplitude longue depuis un horizon court par la
racine du temps l'aurait sous-estimée d'un facteur deux et demi. Confirmation concrète que la
mesure empirique doit primer.

## B6 — Ce que le code ne fait pas

- il ne lit **aucune donnée réelle** : les entrées attendues sont des tableaux horodatés, le
  générateur synthétique ne sert qu'aux tests et à la démonstration ;
- il n'estime ni la sélection adverse ni l'impact **sans campagne réelle** — les fonctions
  existent, elles retournent `nan` sans données d'exécution ;
- il ne choisit pas `a_min`, `a_max`, `f_min` ni les seuils : ils sont **exigés en entrée**, sans
  valeur par défaut, précisément pour qu'ils ne puissent pas être choisis après coup.

## 13. Exécuter

```
cd financial-analyzer
python3 -m pytest tests/ -q          # 39 tests
python3 -m feasibility.report        # carte de faisabilité sur données synthétiques
```

Pour des données réelles : construire un `ReportInputs` avec les tableaux du courtier et la
distribution de latence **conditionnelle à la rafale** mesurée en phase 2 de Q19.
