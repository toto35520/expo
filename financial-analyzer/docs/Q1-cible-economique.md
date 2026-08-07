# Q1-v1 — Cible économique normative du Gold Analyzer

> Statut : **figée**. `Q1-GOLD-RECOMMENDATION-V1`, empreinte `c1127d72f9fcced6`.
> Code : `feasibility/mandate.py`, 17 tests dédiés.
>
> Toute modification de `J_min`, `δ_MEU`, du risque par trade, de la limite de perte, de
> l'horizon d'évaluation, du rôle ou de l'unité de performance crée **V2**, non
> applicable rétroactivement au holdout précédent.

---

## 0. Les valeurs

| | | |
| --- | --- | --- |
| rôle | `RECOMMENDATION` | n'émet aucun ordre |
| unité primaire | `R` | risque planifié jusqu'à l'invalidation |
| `1R` | 0,50 % de l'equity | jamais un montant fixe |
| `J_min` | **+0,10 R / séance** | soit +6 R sur 60 séances |
| `δ_MEU` | **+0,20 R / trade** | plancher de matérialité |
| horizon | **60 séances** | une journée n'est pas l'unité économique |
| risque / trade | ≤ 1R | l'EV se juge avant la taille |
| risque simultané | ≤ 2R | **contrainte de politique** |
| perte de validation | ≤ 12R | *risk gate* |

Deux lectures dérivées, publiées parce qu'elles sont faciles à subir sans les avoir
choisies :

```
si chaque trade vaut exactement δ_MEU  →  0,5 trade par séance suffit
budget de perte / cible sur l'horizon  →  12R / 6R = 2,0 ×
```

La première est ce qui rend la cible **atteignable par un système très sélectif** : un
trade qualifiant toutes les deux séances. La seconde dit que le budget de perte vaut le
double de la cible atteignable — exigeant, mais assumé.

---

## 0 bis. Le rôle, et ce qu'il retire du chemin critique

```
ROLE = RECOMMENDATION
```

Le verdict scientifique de v1 porte sur :

```
information disponible → analyse → décision prête
→ trade théorique exécutable selon le modèle d'exécution gelé
```

et **pas encore** sur `ordre réel → ACK → fill réel`.

Conséquence directe : **Q42 n'est pas nécessaire pour qualifier la capacité du moteur à
produire une décision.** Elle le reste pour affirmer qu'un signal est exécutable
automatiquement avec cette EV nette. Les deux gates sont séparés :

```
SIGNAL QUALITY   ≠   AUTOMATED EXECUTION QUALITY
```

`AUTO_EXECUTION` est un rôle différent, qui exigera Q1-V2 et la qualification Q42
correspondante.

---

## 0 ter. Pourquoi l'unité est R et non l'euro

Un même signal ne doit pas paraître meilleur parce que le compte est plus gros.

```
capital    100 €  →  1R = 0,50 €
capital  1 000 €  →  1R = 5 €
capital 10 000 €  →  1R = 50 €
```

Aucun de ces montants n'entre dans un seuil. Les grandeurs microstructurelles restent
dans leur unité native — `USD/oz` pour prix et spread, `USD/lot` pour la commission,
`ns` pour la latence — et la conversion en R n'intervient que lorsque le trade possède
entrée, stop, dimensionnement et spécification de contrat.

Si le lot minimum du courtier empêche de respecter le risque :

```
SIGNAL_VALID  +  EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL
```

et **jamais** `BAD_SIGNAL`. Le constructeur du mandat le distingue par type.

---

---

## 1. La règle centrale

L'objectif primaire du système **n'est pas** :

```
le taux de réussite  ·  le nombre de trades  ·  le profit brut
```

Il est :

> **maximiser la valeur nette ajustée du risque**, sous contraintes de qualité par trade,
> avec `NO TRADE` comme décision de première classe.

`NO TRADE` n'est pas l'absence de décision. Le système doit pouvoir la produire massivement
sans que cela compte comme un échec.

**Mais elle ne reçoit aucune récompense positive.** La convention est :

```
U(NO TRADE) = 0                    avant coûts fixes du système
U(TRADE)    = PnL_net − pénalité de risque
```

Sa valeur vient de l'**évitement d'espérances négatives**, pas de l'abstention elle-même.
Récompenser le fait de s'abstenir rendrait « toujours `NO TRADE` » optimal — ce qui est sûr
et économiquement inutile. Avec cette convention, s'abstenir est sûr mais insuffisant : le
système doit dépasser `J_min > 0` sur l'horizon d'évaluation pour justifier son existence.

## 2. Ce que cette règle permet de refuser

C'est la formulation qui rend les deux jugements suivants cohérents :

```
2 configurations aujourd'hui, EV net moyen élevé          → accepté
17 configurations faiblement positives                    → NO TRADE
```

Le second cas produit **davantage de signaux** et serait retenu par tout critère fondé sur
le nombre d'occurrences ou le taux de réussite. Il est refusé ici parce qu'il n'ajoute pas
de valeur nette ajustée du risque à hauteur de ce qu'il coûte en exposition, en attention
et en risque de modèle.

C'est aussi ce qui protège le projet contre sa propre mécanique de phase 0 : un moteur
rare et sélectif ne doit jamais être éliminé pour sa rareté, seulement pour son absence de
valeur.

## 2 bis. Ce que le rapport doit démontrer

Puisque l'objectif est *peu de trades, mais excellents*, l'intuition doit être **testée**, pas
inscrite. Le rapport final publie une courbe

```
Qualité(Couverture)
```

où la couverture est la part d'opportunités que le système accepte de trader, contre :
espérance nette conditionnelle, perte maximale, calibration, R moyen, risque de queue.

Le système doit **démontrer** que réduire la couverture augmente réellement la qualité. Sans
cette courbe, « 2 excellents trades valent mieux que 17 médiocres » resterait une philosophie.

---

## 3. Quatre grandeurs, quatre rôles distincts

La redondance de Q64 vient de grandeurs qui codent la même exigence sous trois noms. Elle
se dissout en leur donnant des rôles séparés.

| Grandeur | Rôle | Nature |
| --- | --- | --- |
| `J_min` | **cible économique primaire** du produit, par unité de temps | déclarée |
| `δ_MEU` | **plancher de matérialité** par trade accepté | déclarée |
| `f_stat_min` | condition de **validabilité statistique** | déclarée |
| `f_econ_min` | fréquence qu'implique la cible temporelle | **dérivée** |

### `J_min` — la cible primaire

Ce que le système doit rapporter par unité de temps pour justifier son existence :
infrastructure, données, capital immobilisé, attention. C'est la seule grandeur qui exprime
l'objectif ; les autres le contraignent ou le rendent mesurable.

### `δ_MEU` — le plancher de matérialité

Empêche le système d'accumuler des micro-avantages sans intérêt. Un trade dont l'espérance
nette est positive mais négligeable consomme du risque d'exécution, du risque de modèle et
de la capacité, pour un gain qui ne se distingue pas du bruit.

**`δ_MEU` n'est pas l'espérance du système**, et ne s'y substitue **jamais** (ADR-234).
C'est un minimum pour *accepter* un trade, pas un majorant de ce qu'il peut rapporter.

Avec `δ_MEU = +0,10 R`, un moteur produisant un trade par jour à +2,0 R serait déclaré
trop peu fréquent — l'élimination exacte que ce document existe pour empêcher. En
l'absence d'espérance estimée, la fréquence économique est donc **indéterminée**, et
exclure un moteur rare exige une borne **supérieure** de son espérance :

```
f_nécessaire = (J_min + C) / EV_U
```

C'est la construction symétrique de `S_U` du perfect oracle : sans majorant, la rareté ne
peut pas être opposée à la qualité.

### `f_stat_min` — une condition, pas un objectif

Le nombre minimal d'occurrences permettant de **valider** quoi que ce soit. Elle ne dit
rien de ce qu'il faut gagner. La confondre avec un objectif de trading pousserait le
système à produire des signaux pour satisfaire une exigence statistique — exactement
l'inversion que ce document existe pour empêcher.

### `f_econ_min` — dérivée, jamais fixée

```
J(f) = f · P(fill) · EV_filled − C_fixes − C_capital

f_econ_min = (J_min + C_fixes + C_capital) / (P(fill) · EV_filled)
```

La base de l'espérance est **typée** : sous `EV_PER_TRIGGER` la probabilité d'exécution est
déjà incluse et ne doit pas être remultipliée ; sous `EV_PER_FILLED_EXECUTION` elle reste à
appliquer. Les mélanger compterait le fill deux fois.

La fréquence économique se lit dans cette relation. La fixer indépendamment reviendrait à
déclarer trois fois la même chose et à ne plus savoir laquelle mord.

**Les deux ne se fusionnent jamais en un seul plancher** (ADR-235). Ce sont deux axes
orthogonaux :

```
viabilité économique     ←  f_econ_min      ECONOMICALLY_NON_VIABLE
validabilité statistique ←  f_stat_min      STATISTICALLY_INDETERMINATE
```

Une stratégie peut être économiquement excellente et trop rare pour être validée avec
l'historique disponible. Prendre le maximum transformerait un manque de données en échec
économique — et supprimerait exactement les stratégies rares mais fortes recherchées.

## 4. La relation économique, et ce qui la rend fausse

L'identité naïve `J = f × EV` est trop optimiste. Trois termes la corrigent :

- **probabilité d'exécution** — une occurrence non exécutée ne contribue pas ;
- **coûts fixes** — ils courent sans occurrence ;
- **capital immobilisé** — il a un coût d'opportunité même sans position.

`EconomicThresholds.redundancy_report()` s'appuie sur cette relation, et non sur une
proximité numérique : `f_min` en `1/s` ne se compare pas à `J_min` en `$/s`. Il indique
laquelle des grandeurs contraint réellement le verdict.

---

## 5. Ce que Q1 doit déclarer

```
objectif économique du système       ← J_min en découle
unité de performance                 ← $/oz, R, % du capital…
capital de référence
tolérance de risque                  ← ce que « ajusté du risque » signifie ici
horizon d'évaluation                 ← trimestre, année…
rôle du système                      ← alerte / recommandation / exécution
```

Le **rôle** est celui qui change le plus de choses en aval : il détermine si l'étage 10
émet une alerte ou un ordre, donc ce que Q42 doit mesurer, donc si la partie courtier
appartient au chemin critique.

## 6. Ce que Q1 ne doit pas décider maintenant

- la pile technique et l'emplacement du code — question distincte, sans effet sur les
  seuils ;
- l'estimand principal (Q59-E) — il dépend de la sémantique des moteurs, qui n'existent
  pas ;
- les familles de moteurs à construire.

## 7. Ordre

```
Q1  ──►  Q64 dérivée        (δ_MEU, J_min, f_stat_min, f_econ_min)
    ──►  Q63 prend son sens économique
    ──►  Q65 se classe HARD / POLICY en fonction du rôle déclaré
```

La collecte exploratoire Q50 / Q51-A / Q57 **n'attend rien de tout cela** : `DataStatus`
sépare la collecte du verdict, et seule la période postérieure au gel soutient la première
conclusion normative.

> Q1 étant figée, la première campagne normative a désormais un critère de réussite qui
> ne peut plus être choisi après avoir vu les résultats.

---

## 8. Le critère final

```
max  EV_net,R

sous    perte ≤ 12R
        risque par trade ≤ 1R
        EV du trade accepté suffisamment matérielle devant δ_MEU = 0,20R
        J sur 60 séances ≥ 6R
        NO TRADE autorisé sans pénalité
```

## 9. Ce que ces nombres ne signifient pas

Ils ne disent pas que le système gagnera 6R par trimestre, qu'il doit trader chaque jour,
qu'un trade à +0,20R est garanti, ni qu'une perte de 12R surviendra.

Ils définissent **la barre minimale exigée avant de considérer qu'une complexité
supplémentaire vaut la peine d'exister.**

## 10. Le critère d'un moteur

Un moteur n'est pas validé parce qu'il porte un nom — BOS, FVG, Order Block, CVD, macro.
Il doit démontrer un apport **incrémental** :

```
EV(M_base + M_j) − EV(M_base)   suffisamment positif devant δ_MEU
```

Sinon il est `DESCRIPTIVE_ONLY`, ou supprimé.
