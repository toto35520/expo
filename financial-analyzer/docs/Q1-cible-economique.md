# Q1 — Cible économique du système

> Statut : **structure figée, valeurs à déclarer.** Q1 était jusqu'ici « emplacement du
> code et pile technique ». Elle est devenue le préalable au premier verdict normatif :
> sans elle, Q64 ne serait qu'une série de nombres commodes.

---

## 1. La règle centrale

L'objectif primaire du système **n'est pas** :

```
le taux de réussite  ·  le nombre de trades  ·  le profit brut
```

Il est :

> **maximiser la valeur nette ajustée du risque**, sous contraintes de qualité par trade,
> avec `NO TRADE` comme décision de première classe.

`NO TRADE` n'est pas l'absence de décision. C'est une décision qui gagne quand elle est
juste, et le système doit pouvoir la produire massivement sans que cela compte comme un
échec.

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

**`δ_MEU` n'est pas l'espérance du système.** C'est son plancher. La relation économique
utilise l'espérance nette attendue lorsqu'elle est estimée, et retombe sur le plancher
faute de mieux — jamais l'inverse.

### `f_stat_min` — une condition, pas un objectif

Le nombre minimal d'occurrences permettant de **valider** quoi que ce soit. Elle ne dit
rien de ce qu'il faut gagner. La confondre avec un objectif de trading pousserait le
système à produire des signaux pour satisfaire une exigence statistique — exactement
l'inversion que ce document existe pour empêcher.

### `f_econ_min` — dérivée, jamais fixée

```
J_implied(f) = f × EV_net/occurrence × P(fill) − coûts_fixes
```

La fréquence économique se lit dans cette relation. La fixer indépendamment reviendrait à
déclarer trois fois la même chose et à ne plus savoir laquelle mord.

Le plancher effectif reste `max(f_econ_min, f_stat_min)` — **le plus contraignant des
deux, jamais leur confusion**.

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

> Une fois Q1 figée, la première campagne normative aura un critère de réussite qui ne
> pourra plus être choisi après avoir vu les résultats.
