# 02e — Contrôle qualité : statuts, score et admissibilité

> Statut : **figé** (étape 2.5 de la spécification).
> Formalise l'étage 2 du pipeline et le `DataQualityVerdict` esquissé en
> `02-socle-donnees.md` §8.

## 1. Ce qu'un score unique détruit

Un score de 0 à 100 est utile, mais il porte un défaut qu'il faut neutraliser avant de
l'adopter : **il agrège des défaillances qui ne sont pas substituables.**

Un score de 60 peut signifier « tout est légèrement dégradé » ou « un flux critique est mort,
le reste est parfait ». Ces deux états appellent des réponses opposées, et le score seul ne
permet pas de les distinguer.

Le problème s'aggrave dès qu'on lui associe un seuil : **un score agrégé autorise la
compensation**. Un spread excellent vient alors compenser un flux périmé, et le système finit
par décider sur des données mortes parce que la moyenne reste bonne. C'est une violation
directe de la monotonie des vetos (I5) et de l'abstention par défaut (I4).

**Décision : deux objets distincts, aux pouvoirs différents.**

| Objet | Nature | Pouvoir |
| --- | --- | --- |
| **Portes dures** | ensemble de conditions booléennes, non compensables | décident de l'**admissibilité** ; une seule qui tombe suffit à interdire |
| **Score de qualité** | continu, 0 à 100 | **ne peut que dégrader** : réduit conviction et taille, n'autorise jamais rien |

Le score n'ouvre aucune porte. Il ne fait que rendre plus prudent ce qui a déjà été autorisé
par ailleurs.

## 2. Le statut n'est pas une valeur unique, c'est un vecteur

La liste de l'étape 2.5 mélange des dimensions orthogonales. `UNLICENSED` n'est pas un état de
santé : une donnée peut être parfaitement valide **et** non redistribuable. En faire une valeur
exclusive de `VALID` rend cet état inexprimable. Même remarque pour `RECONSTRUCTED`, qui décrit
la *manière d'obtenir* la valeur et non sa qualité — un carnet reconstruit après reprise sur
instantané est reconstruit *et* valide.

Statut retenu, sur **quatre axes indépendants** :

```
DataStatus {
  fraîcheur    FRAIS | PÉRIMÉ | MANQUANT
  intégrité    OK | ABERRANT | CONFLICTUEL | CORROMPU
  provenance   OBSERVÉ | DÉRIVÉ | RECONSTRUIT | IMPUTÉ | ABSENT_PAR_CONCEPTION
  diffusion    PUBLIC | RESTREINT
}
```

Correspondance avec la liste d'origine :

| Étape 2.5 | Devient |
| --- | --- |
| `VALID` | fraîcheur FRAIS + intégrité OK |
| `STALE` | fraîcheur PÉRIMÉ |
| `MISSING` | fraîcheur MANQUANT |
| `OUTLIER` | intégrité ABERRANT — anormal **par rapport à son propre historique** |
| `CONFLICTING` | intégrité CONFLICTUEL — anormal **par rapport à ses pairs** (ADR-009) |
| `RECONSTRUCTED` | provenance RECONSTRUIT, **compatible avec un état sain** |
| `UNLICENSED` | diffusion RESTREINT, **compatible avec un état sain** (ADR-018) |

Deux valeurs ajoutées, `CORROMPU` et `ABSENT_PAR_CONCEPTION`, traitées ci-dessous.

**`CORROMPU`** couvre les cas où la donnée n'est pas seulement suspecte mais structurellement
invalide : trou de séquence non résolu, carnet croisé, échec de réconciliation avec un
instantané (`02b-futures-comex.md` §4). Ce n'est pas un aberrant à pondérer, c'est une donnée à
écarter.

## 3. L'absence par conception : la valeur qui manque à ta liste

Une donnée absente parce que **le marché est fermé** n'a rien à voir avec une donnée absente
parce que le flux est tombé. Jour férié britannique, coupure quotidienne du listé, week-end,
demi-séance : dans tous ces cas l'absence est l'état normal et attendu.

Sans cette distinction, chaque férié londonien dégrade le score et déclenche des alarmes — et
le système apprend à ignorer ses propres alertes, ce qui est pire que de ne pas en avoir. C'est
le même défaut que celui identifié en `02d-horloge-universelle.md` §5, ici sur l'axe qualité.

`ABSENT_PAR_CONCEPTION` est déterminé par le calendrier (ADR-021) et **n'entraîne aucune
pénalité de score**. Il rend en revanche indisponibles les consommateurs qui dépendent de cette
donnée (§5).

## 4. L'imputation est interdite sur le chemin de décision

`IMPUTÉ` désigne une valeur remplacée ou complétée par le système. Elle est autorisée pour
l'affichage, la surveillance et les graphiques.

**Elle est interdite pour toute valeur entrant dans une décision.**

Le motif est le même que celui de l'ADR-002, appliqué à l'autre extrémité de la chaîne : cet
ADR interdit au modèle de langage de produire des nombres qu'il n'a pas calculés ; il serait
incohérent d'autoriser la couche de données à produire des nombres qu'elle n'a pas observés.
**Un trou reste un trou**, et un trou sur une entrée critique conduit à l'abstention — pas à un
remplissage plausible.

Cette règle a un corollaire pratique : les séries à trous ne sont pas « réparées » avant
usage. Les consommateurs qui ne tolèrent pas les trous se déclarent indisponibles.

## 5. Le statut se propage et ne se lave pas par le calcul

Mode d'échec classique : une série périmée entre dans le calcul d'un indicateur, et
l'indicateur en ressort sans aucune marque. L'agrégation a **blanchi** une donnée morte.

**Règle de propagation** : toute valeur dérivée hérite du **pire statut de ses entrées**, sur
chaque axe indépendamment. Une moyenne calculée sur une entrée périmée est périmée. Une valeur
calculée à partir d'une source restreinte est restreinte (ADR-018). La provenance s'accumule
plutôt qu'elle ne se remplace.

Conséquence directe : le statut voyage avec la donnée jusqu'à l'enregistrement de décision, et
il est possible de répondre à la question « sur quelle qualité de données cette décision
a-t-elle été prise ? » sans reconstruire quoi que ce soit.

## 6. La criticité n'existe pas dans l'absolu

« Aucun signal si les données critiques sont insuffisantes » suppose de savoir ce qui est
critique — or cela dépend entièrement du consommateur. Le carnet d'ordres est vital pour un
agent de microstructure et sans objet pour un agent de régime macro. L'open interest est
critique pour la détection de rollover et inutile ailleurs.

**Règle** : chaque consommateur — agent, moteur, règle — déclare ses entrées requises et le
statut minimal qu'il accepte sur chacune. L'admissibilité est évaluée **par consommateur**, pas
globalement.

```
ConsumerRequirements {
  consumer_id
  entrées_requises[]   { feature, fraîcheur_min, intégrité_min, provenance_admise[] }
  entrées_optionnelles[]
  comportement_si_dégradé   INDISPONIBLE | DÉGRADÉ_AVEC_INCERTITUDE_MAJORÉE
}
```

Un socle partiellement dégradé ne tue donc pas le système entier : il rend indisponibles les
consommateurs qui en dépendent. C'est plus fin, mais cela ouvre un piège qu'il faut fermer
tout de suite.

## 7. Un agent absent n'est pas un agent neutre

Si un agent devient indisponible et disparaît simplement de la fusion, celle-ci ne voit plus
que les agents restants — et conclut avec la même assurance qu'auparavant. Or l'agent manquant
aurait peut-être contredit les autres.

**Une indisponibilité doit donc élargir l'incertitude, pas réduire le panel.** L'étage 7 reçoit
la liste des agents absents et leur poids habituel ; leur silence est traité comme de
l'ignorance, jamais comme un accord tacite.

Cette règle prolonge le quorum de l'ADR-006, du niveau des fournisseurs à celui des agents :
en dessous d'un panel minimal, la fusion n'est pas moins fiable — elle n'est pas légitime.

## 8. Forme du score

Le score reste utile pour hiérarchiser, surveiller et moduler la taille. Sa construction obéit
à trois contraintes :

1. **non compensatoire** — pénalités **multiplicatives**, jamais moyennées : un défaut ne peut
   pas être annulé par une excellence ailleurs ;
2. **monotone** — ajouter un défaut ne peut que baisser le score ;
3. **décomposable** — le score est toujours publié avec sa décomposition ; un score nu est
   inexploitable pour agir.

```
DataQualityScore {
  valeur                 0 à 100
  décomposition[]        { dimension, statut, pénalité appliquée, source }
  portes_dures[]         { nom, franchie, motif }   ← indépendant du score
  admissibilité_par_consommateur[]
  valide_jusqu_à         un verdict a une durée de vie
}
```

Les poids de pénalité ne sont **pas fixés ici**. Les inventer reviendrait à faire exactement ce
que l'ADR-002 interdit. Ils sont estimés à l'étage 12 (§9) et versionnés comme artefacts (I7).

## 9. Un score qui ne prédit rien doit être retiré

Un score de qualité est une hypothèse : *une qualité de données plus faible produit des
décisions moins bonnes*. Cette hypothèse est **testable**, et elle doit l'être.

L'étage 12 mesure la relation entre le score au moment de la décision et le résultat réalisé —
erreur de calibration, écart entre espérance annoncée et espérance réalisée. Trois issues :

- la relation existe → le score est utilisé pour moduler la taille, et ses poids sont calibrés
  sur cette relation plutôt que choisis à la main ;
- la relation est absente → le score est **décoratif** et doit être retiré du chemin de
  décision : le maintenir donnerait un faux sentiment de contrôle ;
- la relation est inverse sur une dimension → cette dimension est mal mesurée, et c'est le
  détecteur qu'il faut corriger.

Sans cette boucle, le score devient une cible à optimiser plutôt qu'une mesure — et il finit
par mesurer le réglage de ses propres seuils.

## 10. Trois comportements distincts en mode dégradé

« Aucun signal publié » ne couvre qu'un cas sur trois. Il faut les séparer explicitement, car
ils ne se déclenchent pas ensemble :

| Situation | Comportement |
| --- | --- |
| Nouvelle décision demandée, socle insuffisant | **abstention** : `NoTrade` avec motif, enregistré |
| Décision déjà calculée, socle devenu insuffisant avant publication | **non-publication**, la décision reste dans l'audit |
| **Position ouverte**, socle devenu insuffisant | **ne pas se taire** : gestion conservatrice |

Le troisième cas est le plus important et le plus facile à oublier. Un système qui devient muet
alors qu'il porte une exposition ne protège personne. En mode dégradé avec position ouverte :

- aucune augmentation de taille, aucun nouvel engagement ;
- les protections déjà en place restent actives et ne sont jamais élargies ;
- la dégradation elle-même est un motif de réduction ou de sortie, pas d'attente ;
- si le socle ne permet même plus d'évaluer la position, la sortie l'emporte sur le maintien —
  une exposition non mesurable n'est pas une exposition tenable.

## 11. Une porte non testée n'est pas une porte

Toutes les protections de cette étape partagent une propriété gênante : **elles ne se
déclenchent qu'en cas de panne**, donc jamais pendant le développement. Une porte qu'on n'a
jamais vue s'ouvrir est une hypothèse, pas un mécanisme.

L'injection de pannes fait donc partie de la livraison de l'étage 2, au même titre que le code :
coupure de flux, flux gelé qui continue de ticker, rejeu post-reconnexion, décalage d'horloge,
trou de séquence, carnet croisé, divergence d'un fournisseur, divergence de tout le panel,
férié inattendu, verdict qualité périmé.

Chaque porte doit avoir été **observée en train de bloquer** avant que le système ne traite un
euro.

## 12. Questions ouvertes

- **Q17** — le score de qualité doit-il être visible par l'opérateur en continu, ou seulement
  lors d'une dégradation ? Un indicateur affiché en permanence est ignoré au bout de quelques
  jours ; un indicateur qui n'apparaît qu'en cas d'anomalie est lu.
- **Q18** — quel comportement par défaut en mode dégradé avec position ouverte : réduction
  automatique, sortie automatique, ou alerte à l'opérateur ? La réponse dépend de Q4 (alerte ou
  exécution automatique) et doit être tranchée avant l'étage 8.
