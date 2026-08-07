# Addendum Phase 0 — Oracle, estimand séquentiel et coût plancher

> Statut : **figé et implémenté**. Code : `feasibility/passive_campaign.py`,
> `feasibility/sequential.py`. 15 tests d'oracle, 15 tests de stress hors hypothèses.
>
> Une correction bloquante, et deux distinctions qui protègent le projet contre
> lui-même.

---

# Partie A — un percentile oracle n'exclut jamais

## 1. Ce qui était faux

La règle précédente était :

```
Q₀.₉₀(Capture_oracle) ≤ C_floor   ⇒   PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY
```

Elle ne permet de conclure qu'une chose :

> au moins 90 % de la population étudiée ne possède pas assez de mouvement,
> selon cette définition de l'oracle

Les 10 % restants peuvent contenir exactement la stratégie recherchée.

## 2. L'exemple qui tranche

```
92 % des événements :  capture oracle = 0,20
 8 % des événements :  capture oracle = 3,00
plancher de coûts   :  0,35
```

`Q₀.₉₀ = 0,20 ≤ 0,35` est vrai. Et pourtant **80 opportunités sur 1 000 dégagent un
surplus, la plus favorable de 2,65**. Un moteur qui ne trade que ces 8 % conserve toute sa
valeur.

C'est le profil d'une stratégie sélective — rare, mais réelle. C'est précisément ce que le
projet cherche, et le raccourci l'aurait supprimé. `python3 -m feasibility.passive_demo`
affiche ce contre-exemple à chaque exécution.

## 3. La variable fondamentale

Pour chaque opportunité `i` :

```
G_i^oracle  = capture brute maximale après latence
S_i^oracle  = G_i^oracle − C_floor,i          (surplus)
I_i         = 1[ S_i^oracle > δ_MEU ]         (oracle-rentable)
```

`G` est construite en offrant au système la direction parfaite, la meilleure sortie de la
fenêtre et aucune erreur prédictive. Elle **conserve** en revanche ce qu'aucun oracle ne
peut contourner : latence déjà subie, marché fermé, prix réellement disponibles, type
d'ordre, taille, capital, concurrence des positions, coûts irréductibles. Sans ces
contraintes elle cesserait d'être une borne supérieure *du système étudié*.

## 4. Trois niveaux d'exclusion

| Niveau | Condition | Verdict |
| --- | --- | --- |
| **A** — impossibilité universelle | `sup_i S_i ≤ δ_MEU` | `ORACLE_UNIVERSALLY_NON_VIABLE` |
| **B** — impossibilité par fréquence | `f_oracle-rentable < f_min` | `ORACLE_FREQUENCY_NON_VIABLE` |
| **C** — impossibilité économique | `V_oracle_max < J_min` | `ORACLE_ECONOMIC_CAPACITY_NON_VIABLE` |

Le niveau A n'affirme **jamais** que le taux d'opportunités rentables est nul. Avec zéro
succès sur `n` tirages, la borne de Clopper-Pearson vaut `1 − α^(1/n)` — elle ne descend
pas à zéro. Le rapport l'affiche : *« le taux réel reste borné par 0,15 %, non nul par
construction »*.

Le niveau B utilise la borne **supérieure** du taux, pour que l'exclusion reste
conservatrice.

## 5. Les quantiles restent, comme diagnostics

`p50`, `p75`, `p90`, `p95`, `p99` continuent d'être publiés — et le rapport les étiquette :
*« diagnostics, aucun n'exclut à lui seul »*. Un quantile ne produit une exclusion que
rattaché explicitement à une exigence de fréquence. Le quantile pertinent est alors lié à

```
r_min ≈ f_min / λ_opp        →       quantile 1 − r_min
```

et non choisi arbitrairement à `p90`.

---

# Partie B — un mouvement ne compte qu'une fois

## 6. Le piège

Interdit de traiter chaque tick comme une opportunité indépendante puis de sommer les
profits oracle. Un seul mouvement peut produire 500 horodatages, 500 fenêtres et 500
« opportunités » alors qu'un système réel n'aurait pris qu'une position. Cela gonflerait
`V_oracle_max` **et** `f_oracle-rentable`.

Un test le vérifie : 500 départs espacés d'une milliseconde sur une fenêtre de 500 ms
donnent **une** opportunité admissible.

## 7. `OpportunitySet`

Déclare `start`, `horizon`, `cooldown`, `max_concurrent_positions`, contrainte de capital,
politique de recouvrement, séance et cellule.

**`DISJOINT_WINDOWS`** — aucune nouvelle opportunité tant que la fenêtre précédente est
active. Résolu exactement par ordonnancement pondéré d'intervalles. Très conservateur.

**`CAPACITY_CONSTRAINED_ORACLE`** — toutes les opportunités existent, mais l'oracle
sélectionne un ensemble compatible avec la concurrence, le capital et le cooldown. Plafond :

```
capacité = concurrence × ⌊ durée / (horizon + cooldown) ⌋
```

Aucune sélection ne peut le dépasser.

## 8. La sélection ne filtre pas la rentabilité

Point subtil, corrigé par un test : la sélection dit **combien de tirages indépendants** le
système obtient, pas lesquels sont rentables. Écarter les opportunités non rentables
détruirait le dénominateur — or « zéro rentable sur N admissibles » est exactement ce que
le niveau A doit pouvoir affirmer.

---

# Partie C — Q63, le plancher de coûts

## 9. Ce que le plancher n'est pas

Ni le coût central estimé, ni le coût prudent. C'est une **borne inférieure du coût
réellement inévitable**. Pour que l'exclusion tienne :

```
C_réel ≥ C_floor       doit être défendable
```

Pour une exclusion signal-agnostique, mieux vaut sous-estimer les coûts que les
surestimer. Un composant estimé entre donc par `LCB(C)`, jamais par son estimation
centrale — et le constructeur refuse une fiche qui déclare le contraire.

## 10. Le plancher dépend du type d'ordre

**Agressif.** Peuvent entrer, selon la convention : commission certaine, franchissement
déjà nécessaire et observé, frais fixes incontournables, financement inévitable si
l'horizon traverse la frontière.

**Passif.** Le spread ne peut **pas** être utilisé automatiquement : un ordre passif peut
obtenir un prix différent du scénario agressif. Son plancher se réduit aux frais réellement
certains. Le constructeur lève une erreur si un franchissement y est déclaré.

La sélection adverse appartient au coût réel, mais n'entre dans le plancher que si une
borne inférieure positive est démontrée.

## 11. Les crédits sont signés

Un swap ou une remise favorable rend un composant négatif. Le plancher retient la
convention la plus favorable compatible avec la cellule. **Transformer un crédit possible
en coût positif pour faciliter une exclusion est interdit.**

## 12. Même convention des deux côtés

Unité, taille, type d'ordre, prix de référence, aller-retour, horizon, séance, instrument.
On ne compare pas une capture en `$/oz` à une commission en `$/lot` sans conversion
contractuelle.

---

# Partie D — l'estimand n'est pas la méthode de variance

## 13. Ce que le regroupement changeait en silence

« Chaque grappe est réduite à sa fraction sous le seuil » modifie la quantité estimée.

```
CDF par grappe      (1/G) Σ_g X_g              où  X_g = (1/n_g) Σ_i 1[L_gi ≤ L*]
CDF par événement   Σ_g Σ_i 1[L_gi ≤ L*] / Σ_g n_g
```

Ce ne sont pas les mêmes quantités, et l'écart n'est pas marginal :

| | grappe A : 10 événements, 100 % sous seuil<br>grappe B : 1 000 événements, 50 % sous seuil |
| --- | --- |
| par grappe | `(1 + 0,5) / 2 = 0,75` |
| par événement | `510 / 1 010 ≈ 0,505` |

Les deux sont justes. Elles répondent à des questions différentes.

## 14. Trois estimandes nommés

```
EVENT_WEIGHTED     quelle latence subit un événement déclencheur tiré dans la population ?
CLUSTER_WEIGHTED   quelle est la performance d'un épisode de rafale typique ?
SESSION_WEIGHTED   quelle est la performance d'une séance typique ?
```

Aucune ne remplace silencieusement les autres. Pour une décision opérationnelle la grandeur
naturelle est généralement `EVENT_WEIGHTED`, conditionnée à la cellule et à l'état de
rafale — mais si les futurs signaux produisent au plus une décision par rafale,
`CLUSTER_WEIGHTED` devient plus pertinent. **La phase 0 publie les deux plutôt que de
choisir.**

## 15. Le principe

```
estimand  ≠  méthode de variance
```

Le regroupement sert à traiter la dépendance statistique. Il ne peut pas changer la
population cible au seul motif de rendre les observations indépendantes. La grappe reste
l'unité d'**indépendance** — donc la taille d'échantillon — sans devenir l'unité de
**pondération**.

La séquence par événement exige un plafond de taille de grappe déclaré à l'avance : sans
lui la variable n'est pas bornée, et la frontière sous-gaussienne ne s'applique pas.

---

# Partie E — grappe ≠ indépendance

## 16. Le second risque

Découper une série temporelle en blocs ne rend pas les blocs indépendants. Deux blocs
consécutifs peuvent partager charge processeur, file persistante, régime de marché,
connexion, événement macro, rafale prolongée, volatilité.

Une séquence de confiance valide sous hypothèse de martingale **perd sa garantie** si cette
hypothèse est fausse.

## 17. `ClusterQualification`

Publié avant que la grappe entre dans l'inférence :

```
cluster_definition · reset_rule · minimum_gap
size_distribution · duration_distribution
ACF des latences · ACF des fractions sous seuil · ACF de la charge
persistance des épisodes de connexion · dépendance de séance · persistance macro
```

Sans dépendance maîtrisée ni stationnarité vérifiée →
`SEQUENTIAL_ASSUMPTIONS_UNVERIFIED`.

## 18. Non-stationnarité

Quel paramètre constant la séquence cherche-t-elle à couvrir ? Si `F_t(L*)` change
fortement entre Asie, Londres, New York, publications macro et versions logicielles, une
moyenne globale unique n'a pas nécessairement de sens. C'est une raison supplémentaire de
conserver des cellules **homogènes et versionnées** — et les tests de stress le montrent :
sous dérive lente ou changement de régime, la couverture est franchie.

## 19. Ce que les simulations prouvent, et ce qu'elles ne prouvent pas

`0 franchissement / 800 réplications` est encourageant, mais la borne supérieure du taux
réel reste non nulle — la même borne de Clopper-Pearson que pour l'oracle. Et surtout, la
garantie théorique dépend de ses hypothèses, pas de la qualité des simulations qui les
respectent.

Les deux familles de tests sont donc **séparées**, dans deux fichiers distincts :

```
tests sous hypothèses    → conformité de l'implémentation à la théorie
stress hors hypothèses   → domaine de sécurité, jamais une preuve
```

Le second groupe couvre : tailles de grappes très inégales, masse près du seuil, queues
extrêmes, dérive lente, changement de régime, autocorrélation positive, rafales
persistantes, arrêt agressif, suréchantillonnage.

## 20. Q59-A devient une architecture, pas un choix global

```
mode disponible : ANYTIME_VALID
repli           : FIXED_HORIZON
```

Le label `ANYTIME_VALID` n'est accordé qu'aux cellules dont les hypothèses sont
défendables. Une cellule dont la dépendance ne permet pas encore de défendre la séquence
**n'est pas perdue** : elle utilise le protocole fixe.

Trois statuts séquentiels, **orthogonaux** à la validité de la mesure :

```
SEQUENTIAL_VALID · SEQUENTIAL_ASSUMPTIONS_UNVERIFIED · SEQUENTIAL_INVALID
```

Une excellente mesure peut porter une inférence séquentielle non qualifiée.

---

# La phase 0 corrigée

Pour chaque cellule :

1. calculer la borne de latence ;
2. calculer la capture oracle ;
3. appliquer le véritable plancher de coûts ;
4. construire les opportunités **sous contraintes** ;
5. calculer taux, fréquence, surplus maximal, capacité économique ;
6. comparer à `f_min`, `δ_MEU`, `J_min`.

```
D_feasible^phase0 = D_cost ∩ D_passive_latency ∩ D_capturability
```

`PHASE0_NOT_EXCLUDED` ne signifie jamais qu'un bon trade est possible. Il signifie qu'il
reste physiquement et économiquement assez d'espace pour justifier la recherche d'un
signal.

---

## Ce qui reste à trancher avant le premier tick

**Bloquant :**

1. **Q59-A** — les tolérances de qualification des grappes (ACF, stationnarité), et les
   valeurs de couverture ;
2. **Q63** — le plancher de coûts par cellule et par type d'ordre ;
3. **Q64** — `δ_MEU`, `f_min` et `J_min` par cellule. Sans eux, aucun des trois niveaux
   d'exclusion oracle ne se calcule ;
4. **Q65** — politique de chevauchement, cooldown, concurrence et capital.

**Non bloquant pour la collecte :** sensibilité au découpage sur données réelles, banc
d'effet observateur sur l'hôte réel, protocole apparié Q43.

Q61-B — le budget propre à un moteur — reste hors du chemin critique de la phase 0.
