# 03b — Delta et delta cumulé

> Statut : **figé** (étape 3.2 de la spécification).
> Second agent de microstructure (étage 4). À lire après `03a-microstructure-ofi.md`.

## 1. Ce que mesure réellement le delta

Toute transaction a un acheteur **et** un vendeur. Le delta ne mesure donc pas un excédent
d'achat — cela n'existe pas. Il mesure **qui a traversé le spread**, c'est-à-dire qui était
pressé.

**Le delta mesure l'impatience, pas l'accumulation.**

Cette reformulation n'est pas cosmétique, elle change les conclusions. Un acheteur important
qui travaille patiemment à l'achat limite produit un delta **négatif** pendant qu'il accumule :
ce sont les vendeurs impatients qui viennent le servir. Lire ce delta négatif comme une
pression vendeuse revient à conclure l'inverse de ce qui se passe.

C'est exactement le mécanisme d'absorption identifié en `03a` §5, vu depuis les transactions
plutôt que depuis le carnet. Ta quatrième ligne — prix baissant avec delta cumulé montant —
décrit précisément ce cas, et c'est la plus informative des quatre.

## 2. Le delta cumulé n'a pas de niveau

Une somme cumulée dépend entièrement du point où l'on a commencé à sommer. « Le delta cumulé
est à +12 000 » ne signifie rien tant que l'origine n'est pas précisée : le même marché, sommé
depuis une autre date, affichera une autre valeur sans qu'aucun fait n'ait changé.

Conséquences fermes :

- **aucune règle ne peut porter sur le niveau absolu** du delta cumulé ;
- deux courbes ancrées différemment ne sont **jamais** comparées ;
- l'ancre est un **paramètre déclaré et versionné**, au même titre que la frontière de journée
  (ADR-022) — dont elle hérite d'ailleurs les ambiguïtés lorsque l'ancre est « le début de la
  journée ».

Seules sont exploitables : la **variation** du delta cumulé sur une fenêtre explicite, et sa
**forme relative au prix** sur cette même fenêtre.

## 3. Normalisation

Un delta de +1 000 dans une séance à 10 000 lots et le même +1 000 dans une séance à 500 000
lots ne décrivent pas le même état. Le delta est donc rapporté au volume écoulé, puis
conditionné par tranche de session et régime de volatilité — même traitement que le
déséquilibre de carnet (ADR-028).

Deux précisions qui prolongent `03a` :

- **la distribution des tailles est conservée**, pas seulement la somme. Une agression de 500
  lots et 500 agressions d'un lot produisent le même delta et ne portent pas la même
  information ; un delta restreint aux grandes empreintes est suivi séparément ;
- l'échantillonnage reste en **temps-événement** (ADR-032).

## 4. Les quatre quadrants, relus

La grille de l'étape 3.2 est juste. Elle gagne à être formulée en termes de patience plutôt
que de pression, ce qui rend les deux cas non triviaux évidents plutôt que contre-intuitifs :

| Prix | Delta cumulé | Lecture | Qui est patient |
| --- | --- | --- | --- |
| Monte | Monte | continuation : les impatients achètent et le prix cède | personne en particulier |
| Monte | Baisse | **divergence** : le prix monte alors que les impatients vendent — un acheteur patient absorbe | l'acheteur |
| Baisse | Baisse | continuation vendeuse | personne en particulier |
| Baisse | Monte | **absorption** : les impatients achètent et le prix baisse quand même | le vendeur |

Règle générale qui s'en dégage : **quand prix et delta divergent, le côté patient est celui qui
va dans le sens du prix.** Et le côté patient est généralement le mieux informé — c'est celui
qui n'a pas besoin de se précipiter.

Cette lecture reste une **hypothèse à valider par la mesure**, pas un acquis (§5).

## 5. Deux marches aléatoires divergent en permanence

C'est l'objection statistique décisive, et elle doit être traitée avant toute exploitation.

Le delta cumulé est une somme cumulée de valeurs signées bruitées : c'est structurellement une
marche aléatoire. Le prix en est une autre. **Deux marches aléatoires produisent des
divergences visuelles en permanence, sans qu'aucune information n'y soit contenue.** Un œil
humain, ou une règle de détection, en trouvera autant qu'on voudra.

Une divergence n'est donc informative que si sa fréquence et son pouvoir prédictif **dépassent
ce que produit le hasard**.

**Exigence imposée à toute règle de divergence — sans exception :**

1. construire un **modèle nul** — série de delta rééchantillonnée par blocs, ou signes permutés,
   en préservant la structure de volume et de volatilité ;
2. recompter les divergences détectées et leurs rendements consécutifs sous ce modèle nul ;
3. n'accepter la règle que si l'écart au nul est net et **stable dans le temps** ;
4. conserver ce test comme référence : il est rejoué à chaque recalibration (étage 12).

Une divergence qui ne bat pas son modèle nul n'est pas un signal faible — c'est du bruit
nommé.

## 6. Sensibilité à la définition de l'oscillation

« Le prix monte, le delta cumulé baisse » suppose un découpage en mouvements. Or la détection
de divergence est **extrêmement sensible** à ce découpage : changer la définition d'une
oscillation change l'ensemble des divergences trouvées.

**Test de robustesse obligatoire** : la règle est évaluée sur une **grille de paramètres**, et
non à un réglage unique.

- un effet réel se **dégrade progressivement** quand on s'écarte du réglage optimal ;
- un artefact **apparaît à un seul réglage** et disparaît autour.

Un signal qui n'existe qu'à un jeu de paramètres précis est un surajustement, quelle que soit
sa significativité apparente.

## 7. Budget de recherche

Quatre quadrants, plusieurs fenêtres, plusieurs ancres, plusieurs seuils, plusieurs définitions
d'oscillation : la combinatoire dépasse vite le millier de tests implicites. À ce volume, des
résultats « significatifs » apparaissent mécaniquement.

Règles retenues :

- la **grille de recherche est déclarée à l'avance** et enregistrée ;
- le nombre de configurations testées est **compté**, et la significativité corrigée en
  conséquence ;
- une **fraction de l'historique est mise de côté** et n'est pas consultée pendant la recherche.
  Elle ne sert qu'une fois, à la validation finale ;
- toute exploration supplémentaire après avoir vu ces données est enregistrée comme telle et
  dégrade la confiance accordée au résultat.

Cette discipline vaut pour tous les moteurs. Elle est posée ici parce que la divergence est le
premier motif du système où la tentation d'explorer librement devient forte.

## 8. Le delta cumulé dépend du fournisseur

Une même agression consommant plusieurs ordres passifs peut être diffusée comme **une**
transaction ou comme **plusieurs**, selon la convention d'agrégation de la source. Le delta
change en conséquence, ainsi que la distribution des tailles — donc la lecture des grandes
empreintes.

Deux fournisseurs peuvent ainsi produire deux courbes de delta cumulé différentes pour le même
marché et la même journée.

**Règle** : la convention d'agrégation des transactions est un **paramètre déclaré et
versionné** de la série, comme la frontière de journée (ADR-022). Deux séries de conventions
différentes ne sont ni comparées ni fusionnées.

S'y ajoute la contrainte déjà posée : lorsque le côté agresseur doit être déduit plutôt que
fourni, la valeur est marquée `DÉRIVÉ` et son incertitude propagée (ADR-024, ADR-025). Un delta
cumulé calculé sur un côté agresseur inféré — cas probable sur le spot — est une grandeur
sensiblement plus bruitée que le même calcul sur le listé.

## 9. Ancrer sur un événement plutôt que cumuler indéfiniment

L'usage le plus défendable de cette famille n'est pas la courbe cumulée globale, mais la mesure
**locale et bornée** :

> quel volume agressif a été absorbé pendant que le prix testait ce niveau sans le franchir ?

Cette formulation a trois avantages décisifs :

- elle est **ancrée sur un événement identifiable** — le test d'un niveau — donc reproductible ;
- elle est **bornée dans le temps**, ce qui la soustrait à la dérive de la somme cumulée ;
- elle produit directement un élément exploitable à l'étage 9 : un niveau ayant absorbé un
  volume agressif important sans céder définit une **invalidation structurelle**, donc un
  emplacement de protection fondé sur autre chose qu'un pourcentage arbitraire.

C'est la forme prioritaire retenue. La courbe cumulée globale reste produite, mais comme
contexte.

## 10. Le vrai danger pour un système multi-moteurs

Ce moteur et celui de l'étape 3.1 **ne sont pas indépendants**. Le delta est la composante
« transactions » du déséquilibre de flux, lequel agrège transactions, ajouts et retraits. Ils
partagent une partie de leur information par construction, pas par accident.

Si la fusion probabiliste les traite comme deux témoignages distincts, elle compte **deux fois
la même observation** — et produit une confiance artificiellement élevée. C'est le mode d'échec
classique des architectures multi-moteurs : « cinq moteurs sont d'accord » signifie parfois
« un signal a été compté cinq fois ». Le résultat n'est pas seulement une erreur de niveau : il
détruit la calibration, qui est l'objectif central du système.

**Règle générale, applicable à tous les agents** : chaque agent **déclare ses recouvrements
structurels** — les entrées et les mécanismes qu'il partage avec d'autres. La fusion (étage 7)
doit traiter les agents structurellement liés comme une source unique à décomposer, jamais
comme des preuves indépendantes. La corrélation empirique mesurée sur l'historique **complète**
cette déclaration mais ne la remplace pas : elle est instable et s'effondre précisément dans
les régimes extrêmes, là où l'indépendance supposée coûte le plus cher.

## 11. Contrat de sortie

```
AgentOutput (delta) {
  as_of, horizon_déclaré
  ancre                      origine explicite du cumul (§2)
  delta_normalisé            rapporté au volume, conditionné à la session
  delta_grandes_empreintes   suivi séparé
  distribution_tailles
  quadrant                   CONTINUATION_H | DIVERGENCE_H | CONTINUATION_B | ABSORPTION
  absorption_au_niveau[]     { niveau, volume agressif absorbé, durée, franchi ou non }
  écart_au_modèle_nul        obligatoire pour toute divergence signalée (§5)
  robustesse_grille          comportement du signal sur la grille de paramètres (§6)
  convention_agrégation      §8
  côté_agresseur             FOURNI | DÉRIVÉ
  recouvrements_déclarés[]   § 10 — agents partageant tout ou partie de l'information
  confiance, abstention + motif
  statuts_entrées[]
  rôle_autorisé              CONDITIONNEMENT par défaut (§12)
}
```

## 12. Statut de la divergence dans la chaîne

L'étape 3.2 pose que la divergence ne déclenche jamais un trade. Traduction structurelle :

| Autorisé | Interdit |
| --- | --- |
| modifier la probabilité d'un scénario existant | créer un scénario |
| renforcer ou affaiblir une conviction déjà formée | fournir une direction à lui seul |
| fournir une invalidation structurelle via l'absorption locale (§9) | fixer une entrée |
| déclencher une abstention | lever une abstention |

Même famille que l'ADR-017 : ce moteur conditionne et peut bloquer, il n'origine pas.

## 13. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Flux de transactions avec côté agresseur fourni | fraîcheur FRAIS, intégrité OK | dégradé si déduit, **indisponible** si absent |
| Convention d'agrégation connue | déclarée | **indisponible** — la série n'est pas interprétable |
| Volume de référence pour la normalisation | FRAIS | dégradé |
| Ancre valide | définie | **indisponible** |
| Contrat principal et phase de rollover | ADR-010, ADR-013 | dégradé pendant la migration |

## 14. À mesurer avant tout usage

- fréquence des quatre quadrants **sous modèle nul** et écart du réel au nul ;
- pouvoir prédictif de chaque quadrant, avec le décalage de latence imposé par l'ADR-029 ;
- stabilité de ces résultats par régime, par tranche de session et dans le temps ;
- corrélation effective entre ce moteur et celui de l'étape 3.1, en régime calme **et** en
  régime de stress ;
- écart entre delta calculé sur le listé et delta reconstruit sur le spot, si cette
  reconstruction est envisagée ;
- valeur prédictive de l'absorption locale (§9) comparée à celle de la divergence globale — la
  première est l'usage prioritaire, encore faut-il vérifier qu'elle le mérite.

## 15. Questions ouvertes

- **Q22** — la convention d'agrégation des transactions des sources retenues est-elle
  documentée ? Sans elle, le delta cumulé n'est pas interprétable, et l'information est rarement
  fournie spontanément.
- **Q23** — quelle fraction de l'historique est réservée à la validation finale, et qui garantit
  qu'elle n'est pas consultée avant ? La règle du §7 n'a de valeur que si elle est appliquée
  matériellement, pas seulement décidée.
