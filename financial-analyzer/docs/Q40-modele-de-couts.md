# Q40 — Modèle de coûts et effet minimal économiquement utile

> Statut : **exécutable**. Second protocole du projet, après `Q19-protocole-latence.md`.
> Produit `δ_MEU`, dont dépend **chaque** gate. Sans lui, aucun verdict n'est prononçable.

## 1. Pourquoi cette pièce vient avant les moteurs

`δ_MEU` n'est pas un paramètre de réglage. C'est ce qui rend les trois autres verdicts possibles :

- sans lui, on ne peut pas dire qu'un effet est **utile** ;
- sans lui, on ne peut pas dire qu'un effet est **négligeable** — le test d'équivalence (ADR-094)
  a besoin de bornes ;
- sans lui, on ne peut pas calculer la **puissance** requise (ADR-093), qui se définit par rapport
  à une taille d'effet.

Il est donc antérieur à tout moteur, et il se calcule **sans aucun modèle de marché** : uniquement
à partir de frais observables et de volatilité mesurée.

## 2. Un double comptage à corriger dans la formule

La formule de l'addendum s'écrit :

```
C_total = C_spread + C_commission + C_slippage + C_latence + C_base + C_financement
```

`C_slippage` et `C_latence` ne sont pas additifs : **le glissement mesuré de bout en bout contient
déjà l'effet de la latence.** Les additionner compte la même chose deux fois et surestime le
seuil, donc rejette des effets réels.

**Deux formulations valides, jamais mélangées :**

| Formulation | Composition | Usage |
| --- | --- | --- |
| **Mesurée** | `C_spread + C_commission + C_slippage_observé + C_base + C_financement` | quand la phase 2B de Q19 a fourni un glissement réel |
| **Modélisée** | `C_spread + C_commission + f(L, σ, type d'ordre) + C_base + C_financement` | avant la campagne de mesure, avec `f` explicitement déclaré comme modèle |

La formulation mesurée est préférée dès qu'elle existe. La formulation modélisée porte une
incertitude qui entre dans `M_sécurité`.

## 3. Décomposition retenue

| Terme | Nature | Dépend de | Observable |
| --- | --- | --- | --- |
| **Spread** | payé à l'entrée et à la sortie | session, régime de volatilité, fournisseur | oui, en continu |
| **Commission** | fixe ou proportionnelle | courtier, taille | oui |
| **Glissement** | écart prix de décision / prix d'exécution | latence, taille, état de marché | phase 2B de Q19 |
| **Financement** | portage overnight | **horizon**, sens, taux | oui, publié par le courtier |
| **Base** | écart et incertitude listé ↔ spot | fraîcheur de la base | ADR-079 |
| **Sélection adverse** | asymétrie des exécutions passives | type d'ordre | §7 |
| **Non-exécution** | occasion manquée sur ordre limité | type d'ordre | censurée (ADR-103) |
| **Capital immobilisé** | coût d'opportunité | horizon, taille | oui |
| **Fiscalité** | selon juridiction | hors périmètre de ce document | à obtenir |

Deux remarques.

**Le spread se compte deux fois** dans un aller-retour, ou une fois si l'on convient de mesurer
les rendements de mi-prix à mi-prix. La convention doit être déclarée et tenue — les deux se
défendent, les mélanger fausse tout.

**Le financement est le seul terme proportionnel à la durée.** C'est lui qui rend `C_total`
dépendant de l'horizon, donc qui fait que Q36 bloque Q40. Sur l'or, une position portée plusieurs
jours paie plusieurs fois ce terme, et certains courtiers appliquent un portage multiplié un jour
par semaine pour couvrir le week-end. À vérifier auprès du courtier retenu plutôt qu'à supposer.

## 4. Le coût n'est pas un scalaire, c'est une surface

`C_total` dépend simultanément de :

```
horizon de détention  ·  type d'ordre  ·  tranche de session  ·  taille  ·  régime de volatilité
```

Il n'existe donc **pas un `δ_MEU`, mais une surface `δ_MEU(h, type, session, taille, régime)`**.

Conséquences directes :

- un gate ne peut pas rendre un verdict global : il rend un verdict **par cellule** de cette
  surface, ou déclare explicitement la cellule sur laquelle il conclut ;
- un moteur peut être `PASS` en séance liquide et `FAIL_EQUIVALENT_TO_ZERO` en creux asiatique.
  C'est un résultat normal, pas une contradiction ;
- fixer les horizons (Q36) revient à **choisir la tranche de la surface** sur laquelle le projet
  se prononce. C'est pour cela que Q36 est bloquante, et non parce qu'il manquerait une préférence.

## 5. Le calcul décisif : l'horizon minimal viable

Il existe ici l'équivalent de la phase 0 de Q19 — un calcul **immédiat, sans modèle et sans
signal**, qui borne le domaine du possible.

### 5.1 Le raisonnement

Les coûts de transaction sont **approximativement fixes** par aller-retour. La volatilité, elle,
croît avec la durée de détention — approximativement en racine carrée du temps sous les
hypothèses usuelles.

Le rapport qui décide de tout est :

```
κ(h) = C_total(h) / σ(h)
```

C'est le nombre d'écarts-types de mouvement qu'il faut capturer **rien que pour rentrer dans ses
frais**. Comme le numérateur est presque constant et le dénominateur croît en `√h`, **κ décroît en
`1/√h`**.

### 5.2 Ce que cela implique

Un signal doit produire un avantage supérieur à `κ(h)` écarts-types. Or les avantages
prédictifs réalistes, en unités de volatilité, sont **petits** — c'est une propriété générale des
marchés liquides, pas une hypothèse sur celui-ci.

Il existe donc un **horizon minimal `h_min` en dessous duquel aucun signal, même parfait dans les
limites du réalisme, ne peut couvrir ses frais.** Cet horizon se calcule à partir de deux
grandeurs mesurables aujourd'hui :

1. le coût aller-retour effectif chez le courtier retenu, par tranche de session ;
2. la volatilité réalisée de l'or à différentes échelles de temps.

### 5.3 Procédure

1. mesurer le spread effectif par tranche de session sur le flux réel — pas le spread annoncé ;
2. y ajouter commission et une estimation initiale de glissement ;
3. estimer `σ(h)` sur l'historique, pour une grille d'horizons allant de la seconde à plusieurs
   jours, **par tranche de session** ;
4. tracer `κ(h)` ;
5. superposer une bande d'avantages prédictifs plausibles, déclarée à l'avance ;
6. lire `h_min` — l'horizon où `κ(h)` descend sous cette bande.

### 5.4 Lecture

| Résultat | Conséquence |
| --- | --- |
| `h_min` très supérieur aux horizons de microstructure | la famille `03a`–`03f` ne peut pas déclencher d'entrée **par pur argument de coût**, indépendamment de la latence. Résultat cumulatif avec la phase 0 de Q19 |
| `h_min` compatible avec l'intraday | le domaine est ouvert, les gates ont un sens sur cette plage |
| `h_min` dépendant fortement de la session | les horizons supportés doivent être déclarés **par session**, ce qui contraint Q36 |

Ce calcul ne demande **ni signal, ni étiquette, ni modèle, ni compte réel** — seulement le flux du
courtier et de l'historique de prix. Il devrait être le premier chiffre produit par le projet.

### 5.5 Ce qu'il ne dit pas

Il donne une borne, pas une garantie. Un horizon supérieur à `h_min` n'a rien de rentable en
soi ; il est simplement **non exclu par les coûts**. Et l'approximation en `√h` se dégrade en
présence de tendance, d'autocorrélation ou de sauts — elle sert à ordonner des grandeurs, pas à
produire un seuil au centime.

## 6. Coûts propres à ce montage

**Spot XAU/USD chez un courtier.** Le spread est le terme dominant et il est **conditionnel** :
il s'élargit au rollover quotidien, à l'ouverture du dimanche et sur publication (ADR-007). Le
mesurer en moyenne sur la journée sous-estime massivement le coût aux instants où les signaux se
déclenchent — c'est le pendant exact de la latence conditionnelle (ADR-102).

**Règle** : le coût entrant dans `δ_MEU` est le coût **conditionnel à l'état de marché où le
signal se déclenche**, jamais le coût moyen.

**Détection sur le listé, exécution sur le spot.** Deux termes supplémentaires : le niveau de la
base, qui est un décalage systématique et non un aléa, et son **incertitude**, qui est un coût de
risque (ADR-079). Une zone dont l'incertitude de traduction représente une fraction importante de
la largeur porte un coût implicite considérable — c'est déjà traité comme une suspension
d'éligibilité, mais cela doit aussi apparaître dans le calcul de rentabilité.

## 7. La sélection adverse

Terme le plus souvent oublié, et il peut dominer pour toute stratégie passive.

Un ordre à cours limité n'est pas exécuté au hasard : **il est exécuté préférentiellement quand le
marché vient vers vous**, c'est-à-dire quand vous avez tort. Le rendement conditionnel à
l'exécution est donc systématiquement moins bon que le rendement inconditionnel.

**Mesure** : comparer le résultat des ordres exécutés au résultat qu'aurait produit une exécution
garantie au même prix. L'écart est le coût de sélection adverse. Il n'apparaît dans aucun relevé
de frais et ne se déduit d'aucun barème — il faut le mesurer.

Conséquence pratique : **un backtest supposant une exécution à cours limité systématique est
optimiste**, et l'ampleur du biais est précisément ce terme. C'est aussi pourquoi la
non-exécution doit être traitée en observation censurée (ADR-103) plutôt qu'en simple absence.

## 8. De `C_total` à `δ_MEU`

```
δ_MEU = C_total + M_sécurité
```

`M_sécurité` couvre trois écarts distincts, à estimer séparément plutôt qu'en bloc :

| Composante | Origine |
| --- | --- |
| Incertitude d'estimation des coûts eux-mêmes | échantillon fini, conditions non couvertes |
| Dégradation recherche → production | conditions non reproduites, exécution réelle |
| Décroissance de l'avantage dans le temps | un effet mesuré sur le passé se dégrade |

Publier `M_sécurité` comme un chiffre unique masque le fait que la troisième composante est la
plus grande et la moins connue.

**Accompagnement obligatoire** : `f_min`, le plancher de fréquence (ADR-093). Le critère de
passage porte sur `EV_net × f`, l'espérance **par unité de temps**, et non sur `EV_net` seul.

## 9. Ce qui se mesure, et comment

| Grandeur | Source | Disponible |
| --- | --- | --- |
| Spread effectif conditionnel | flux du courtier, par tranche de session | **immédiatement** |
| Commission | barème du courtier | **immédiatement** |
| Volatilité réalisée multi-échelle | historique de prix | **immédiatement** |
| `κ(h)` et `h_min` | les trois précédents | **immédiatement** |
| Financement | barème du courtier, à vérifier | immédiatement |
| Glissement réel | phase 2B de Q19 | après campagne |
| Sélection adverse | ordres limités réels | après campagne |
| Base et son incertitude | flux listé + spot simultanés | dès que les deux flux existent |

**Les quatre premières lignes suffisent à produire `h_min`.** C'est le livrable minimal de ce
protocole, et il ne dépend d'aucune autre question ouverte.

## 10. Ce que ce document ne tranche pas

- la **fiscalité** applicable, qui affecte l'espérance nette finale et relève d'une source
  compétente, pas d'une supposition ;
- la **taille de position**, qui rétroagit sur le glissement — traitée à l'étage 8 ;
- le **choix des horizons supportés** (Q36) : ce protocole fournit la borne inférieure `h_min` et
  la surface de coûts, mais le choix reste une décision de projet.

## 11. Ordre d'exécution recommandé

```
1. spread effectif conditionnel + commission + volatilité multi-échelle   → κ(h)
2. h_min, par tranche de session                                          → borne le domaine
3. financement, par horizon candidat                                      → complète la surface
4. campagne Q19 phases 2A et 2B                                           → glissement réel
5. sélection adverse, si stratégie passive envisagée
6. δ_MEU et f_min figés, par cellule de la surface
7. seulement alors, les gates
```

Les étapes 1 et 2 peuvent être conduites **aujourd'hui**, en parallèle de la phase 0 de Q19.
Ensemble, ces deux calculs délimitent le domaine du possible avant qu'une seule ligne de moteur
ne soit écrite — l'un par la latence, l'autre par les coûts.
