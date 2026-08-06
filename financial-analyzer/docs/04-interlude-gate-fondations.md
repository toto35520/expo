# Interlude 4 — Gate de validation des fondations structurelles

> Statut : **figé**. Document de conduite, pas de spécification de moteur.
> Gèle l'étape 4.5 et définit les conditions de reprise.

---

# Partie A — Protocole normatif

## 1. Décision de conduite

La spécification des objets structurels est **gelée** après `04a` (pivots), `04b` (ruptures),
`04c` (déséquilibre) et `04d` (inversion). L'étape 4.5 — blocs d'ordres — n'est pas engagée.

Motif : l'augmentation de la complexité descriptive n'est pas accompagnée d'une augmentation
équivalente des sources d'information indépendantes. Les objets définis dérivent d'une même
famille causale — chemin de prix → pivot → rupture → déplacement → déséquilibre → inversion.

L'architecture détaillée reste utile pour la reproductibilité. **Aucun poids prédictif** ne peut
être accordé à ces objets avant validation incrémentale.

## 2. Réponse à Q39 — priorité d'investissement

```
1. Q1     pile technique
2. Q19    latence de bout en bout
3. Q36    horizons opérationnels et politique d'invalidation
4. primitifs communs
5. validation séquentielle des fondations
6. seulement ensuite, poursuite de l'ontologie
```

Q36 bloque directement : fenêtres d'acceptation, barrières temporelles, expiration, distances
d'invalidation, définitions de retest, étiquettes d'apprentissage, valeur économique nette d'un
signal. Q1 et Q19 doivent être résolues **avant** de figer les protocoles expérimentaux.

## 3. Interface du primitif `PriceAcceptance`

Décision déjà prise (ADR-085) ; voici son interface arrêtée.

| Entrées | Sorties brutes | Sorties dérivées |
| --- | --- | --- |
| `boundary`, `crossing_direction` | `maximum_depth`, `normalized_depth` | `acceptance_intensity ∈ [0,1]` |
| `observation_start`, `observation_window` | `time_occupancy`, `event_occupancy`, `volume_occupancy` | `availability_timestamp` |
| `reference_volatility`, `price_basis` | `mean_distance_beyond`, `crossing_velocity` | `primitive_version` |
| `market`, `data_quality` | `order_flow_imbalance`, `failed_reclaim_count`, `reclaim_strength` | |

Usages : maintien après rupture · prix accepté après balayage · formation d'un IFVG ·
invalidation d'un rôle inversé · futurs moteurs de changement de rôle.
**Aucun moteur local ne redéfinit l'acceptation.**

## 4. Le seuil d'acceptation sélectionne la population

Quand `θ_A` augmente : moins d'événements, profondeur et persistance moyennes plus élevées,
disparition des cas faibles, population de plus en plus **sélectionnée sur la continuation
préalable**.

Les résultats sont donc publiés comme **fonctions** de `θ_A` — retest, réaction, invalidation,
espérance nette — jamais comme une probabilité unique à un seuil choisi après observation.

**Protocole de balayage** : grille enregistrée avant le test. Pour chaque valeur sont publiés
nombre d'événements, exposition totale, incidences, espérance nette, intervalle de confiance,
stabilité entre périodes et entre régimes.

Un effet crédible présente une évolution régulière, une cohérence entre échantillons, une
stabilité hors échantillon et une logique économique interprétable. **Un pic isolé à une valeur
précise est présumé artefact.**

## 5. Exposition des changements de rôle

Le compteur brut de retournements n'est pas utilisable seul : une zone ancienne ou fréquemment
visitée a mécaniquement plus d'occasions de changer de rôle.

Exposition mesurée en temps (`E_t`), en volume (`E_v`) et en occasions de franchissement. Les
variables exploitables sont les **taux** `N_flips/E_t`, `N_flips/E_v` et
`N_flips/N_opportunités`. Le compteur brut reste descriptif, sans poids autonome.

## 6. Risques concurrents et censure

Événements concurrents : objectif atteint, stop atteint, invalidation structurelle, expiration
temporelle. Censure : interruption de données, discontinuité de marché, rollover inexploitable,
terminaison manuelle non liée au marché.

Estimation par **incidences cumulées**, fonctions de risque par cause, traitement explicite de la
censure, et analyse de sensibilité lorsque la censure peut être informative.

Une observation censurée n'est ni une perte, ni un succès, ni simplement supprimée.

Publiés pour un horizon `H` : `CIF_target(H)`, `CIF_stop(H)`, `CIF_invalidation(H)`, `P(T>H)`.
Une proportion brute `TP / total` est insuffisante dès lors que les autres issues empêchent
d'observer le TP.

## 7. Bornes d'exécution dynamiques

Seules vérités persistées : bornes canoniques et marché de détection. La zone d'exécution est une
**fonction du temps**. Le stockage ne contient que des **instantanés horodatés** portant base,
incertitude, âge de la base et version de traduction. La vue est recalculée avant chaque
évaluation ou ordre ; une vue ancienne n'est jamais utilisée implicitement comme vue courante.

## 8. Dégradation de la base avec position ouverte

| Situation | Conduite |
| --- | --- |
| Sans position | entrées interdites, ordres conditionnels suspendus ou annulés, renforts interdits, signal marqué non exécutable |
| **Avec position** | protections déjà placées **maintenues** · risque évalué sur le marché réel d'exécution · renforts interdits · aucun déplacement de stop dépendant de la zone traduite · dégradation signalée · politique de Q18 appliquée |

Le système **ne clôture pas automatiquement** une position au seul motif que la traduction
intermarchés est devenue incertaine. **La perte de qualité analytique et l'invalidation
économique du trade sont deux événements différents.**

## 9. Propagation de validité

Chaque objet dérivé référence ses dépendances. Lorsqu'une source devient `DATA_INVALID`,
`SUPERSEDED` ou frappée d'une discontinuité d'instrument, les objets dérivés ne sont pas
supprimés : ils reçoivent `dependency_state = INVALID_SOURCE` et `validity_state = SUSPENDED`.

Le moteur détermine ensuite si l'objet reste géométriquement reproductible, peut être reconstruit
sur données corrigées, doit être remplacé par une nouvelle version, ou définitivement invalidé.

**Asymétrie essentielle** : une invalidation **de données** se propage nécessairement ; une
invalidation **prédictive** du rôle d'origine ne se propage pas — elle peut être précisément la
condition de naissance de l'objet dérivé.

## 10. Les gates

### G4.1 — Résolution des dépendances

`Q1`, `Q19`, `Q36` résolues, fournissant : cible économique exacte, marché de décision, marché
d'exécution, horizons supportés, définition des événements de résultat, coûts et contraintes.
Sans cela, aucune notion de performance n'est figeable.

### G4.2 — Implémentation minimale

Composants communs seulement : `EventTime`, `DataAvailability`, `PricePath`,
`VolatilityReference`, `SwingHierarchy`, `PriceAcceptance`, `BasisTranslation`,
`CompetingRiskOutcome`, `MatchedControlSampler`.

Interfaces avancées, scores narratifs et modèles complexes reportés. **Le but n'est pas encore de
produire un signal ; le but est de rendre les hypothèses falsifiables.**

### G4.3 — Test des pivots

`H₀` : à saillance, distance, volatilité, session et exposition comparables, un pivot confirmé ne
provoque pas davantage de réaction qu'un niveau de contrôle.

Population : uniquement les pivots **disponibles à leur confirmation**, jamais à leur horodatage
d'origine. Contrôles appariés sur distance, saillance, amplitude préalable, volatilité,
ancienneté, session, expositions.

Mesures : incidences de premier contact, de réaction, de franchissement ; MFE ; MAE ; espérance
nette ; qualité de l'invalidation.

Passage si l'apport hors échantillon est statistiquement distinguable, économiquement utile après
coûts, stable sur plusieurs périodes, non concentré sur un seul régime.

**En cas d'échec** : poids prédictif des pivots, du BOS et du CHOCH ramenés à zéro. Les tests
aval peuvent se poursuivre, marqués `FOUNDATION_FAILED` et `EXPLORATORY_ONLY`, avec exigence de
réplication renforcée.

### G4.4 — Test incrémental du déséquilibre

`H₀` : une fois connus déplacement, momentum, volatilité, session, régime, volume, structure
disponible et largeur de zone, la qualification de déséquilibre n'ajoute rien.

Modèle de référence sans le label ; modèle augmenté avec `is_fvg`, largeur, position, état de
remplissage, intensité de vide d'exécution. Apport mesuré en log-loss, score de Brier,
calibration, espérance nette, perte maximale, stabilité hors échantillon. **Une amélioration en
échantillon ne suffit pas.**

En cas d'échec : le déséquilibre reste une représentation géométrique — présentation d'une zone,
normalisation d'une entrée, contexte de déplacement, étude d'un vide d'exécution, structuration
d'une invalidation — mais **jamais une confirmation indépendante**.

### G4.5 — Test incrémental de l'inversion

`H₀` : une zone issue d'un déséquilibre ayant subi un changement de rôle accepté ne fait pas mieux
qu'une zone ordinaire ayant subi le même changement.

Contrôles : supports cassés devenus résistances, résistances devenues supports, zones aléatoires à
acceptation comparable, niveaux de faible volume franchis puis retestés, pivots franchis à même
intensité. Appariés sur intensité d'acceptation, profondeur, durée, volatilité, momentum, largeur,
ancienneté, session, exposition, distance au prix, structure.

Résultats **obligatoirement séparés** : attraction, réaction, invalidation, valeur économique. Un
résultat nul sur la réaction n'annule pas une éventuelle valeur pour l'invalidation.

## 11. Hiérarchie des conclusions

| Cas | Lecture |
| --- | --- |
| **A** — pivots +, déséquilibre +, inversion + | chaîne structurelle recevable, sous réserve de calibration |
| **B** — pivots +, déséquilibre nul | la structure sert, le label n'ajoute rien |
| **C** — déséquilibre + malgré pivots − | possible mais suspect ; réplication et contrôle renforcé du momentum |
| **D** — déséquilibre +, inversion nulle | l'inversion ne vaut pas mieux qu'un changement de rôle générique |
| **E** — tout nul | moteurs conservés comme outils descriptifs, `production_weight = 0`, `execution_authority = NONE` |

## 12. Règle de budget et condition de reprise

Aucune nouvelle famille structurelle ne dépasse le coût de validation de la précédente sans
preuve d'apport. Avant 4.5, estimer coûts de spécification, de données, d'implémentation, de
validation, de maintenance, risque de double comptage et gain informationnel attendu — puis
comparer le rapport gain/coût à celui de Q1, Q19, Q36, du moteur macro, du moteur de coûts et de
la qualité des données.

Reprise de 4.5 possible si : les gates pivots et déséquilibre ont produit un résultat solide
(condition scientifique) ; **ou** le moteur est développé comme composant descriptif réutilisable
avec `production_weight = 0`, `research_status = UNVALIDATED` et budget plafonné (condition
d'ingénierie) ; **ou** une exigence produit extérieure impose l'affichage, sans prétention d'alpha
validé (condition stratégique).

---

# Partie B — Trois garde-fous sans lesquels le verdict peut être faux

Le protocole ci-dessus décide de l'avenir de quatre moteurs. Il doit donc lui-même être fiable —
et trois éléments manquants peuvent le faire échouer silencieusement.

## C1 — Sans analyse de puissance, un verdict nul est ininterprétable

C'est la lacune la plus grave, et elle frappe précisément le résultat le plus lourd de
conséquences.

Un test dont la puissance est insuffisante rend « aucun effet » **quelle que soit la réalité**. Le
verdict `FOUNDATION_FAILED` — qui met à zéro le poids de trois moteurs — pourrait donc être
prononcé sur un échantillon simplement trop petit. Absence de preuve et preuve d'absence ne se
distinguent pas sans cette analyse.

Il existe ici une ancre rare et précieuse : **la plus petite taille d'effet économiquement utile
est calculable**. C'est celle qui compense tout juste les coûts — spread, commissions, glissement,
et le cas échéant la base. Elle ne dépend d'aucune croyance sur le marché.

**Règle, préalable à chaque gate :**

1. déclarer la taille d'effet minimale utile, dérivée des coûts (donc dépendante de Q36) ;
2. calculer la puissance disponible pour cette taille d'effet, avec l'échantillon réel, en
   tenant compte de l'autocorrélation et du regroupement par événement — les observations d'une
   même séance ne sont pas indépendantes, et l'ignorer surestime largement la puissance ;
3. si la puissance est insuffisante, **le déclarer avant de lancer le test** et corriger le
   verdict possible : le gate rend alors `INDÉTERMINÉ`, jamais `ÉCHEC`.

**Corollaire** : conclure « n'apporte rien » exige un **test d'équivalence** — montrer que l'effet
est inférieur à la plus petite taille utile — et non l'échec d'un test de significativité. Le
Cas E du §11 n'est fondé que sous cette condition ; sans elle, il est infondé.

## C2 — Le protocole doit être étalonné sur un signal nul avant d'être utilisé

Le composant qui décide de tout n'est pas un moteur : c'est `MatchedControlSampler`. Un
appariement défaillant produit des différences là où il n'y en a pas, ou en masque. Aucun des
trois gates n'a de valeur si cet instrument est faux — et rien dans le protocole ne le vérifie.

**Règle : contrôle négatif obligatoire avant tout test réel.**

Faire tourner la chaîne complète — échantillonnage, appariement, estimation par risques
concurrents, mesure d'apport incrémental — sur une **étiquette dont on sait qu'elle ne porte
aucune information** : pivots réattribués au hasard parmi des instants comparables, ou labels
permutés en préservant la structure temporelle.

- la chaîne rend un résultat nul → l'instrument est étalonné, les gates peuvent commencer ;
- la chaîne trouve un effet → **le protocole est cassé**, et tout résultat positif ultérieur est
  sans valeur. La cause est à corriger avant toute autre chose.

C'est la version « expérimentation » de la règle posée en `02e` §11 : une porte qu'on n'a jamais
vue s'ouvrir est une hypothèse. Ici, un instrument qu'on n'a jamais vu rendre un zéro correct
n'est pas un instrument.

## C3 — L'échantillon réservé se consomme, et trois gates séquentiels le brûlent

L'ADR-034 réserve une fraction d'historique pour la validation finale. Le protocole enchaîne trois
gates. Si chacun consulte cette réserve, il n'en reste rien au troisième — et le résultat le plus
structurant, celui de la chaîne complète, sera prononcé sur des données déjà vues.

**Politique retenue :**

| Étape | Données utilisées |
| --- | --- |
| Contrôle négatif (C2) | jeu d'exploration uniquement |
| G4.3, G4.4, G4.5 — conduite des tests | jeu d'exploration uniquement |
| Analyse de puissance (C1) | jeu d'exploration, ou données synthétiques |
| **Verdict final** | jeu réservé, **ouvert une seule fois**, sur la chaîne entière |

Toute consultation du jeu réservé est enregistrée avec sa date et son motif. Une seconde ouverture
n'est pas interdite mais **dégrade explicitement la confiance** du résultat, et cette dégradation
est publiée avec le verdict.

## C4 — Deux précisions sur le protocole

**Le balayage de `θ_A` est une courbe, pas dix-sept tests.** Tester chaque point séparément
recrée le problème de multiplicité que le balayage cherche à éviter. La grandeur jugée est la
**forme de la courbe** — régularité, monotonie, cohérence entre échantillons — évaluée comme un
objet unique. Un point isolé n'a pas de statut propre.

**Le Cas C n'est pas nécessairement incohérent.** Le déséquilibre, tel que défini en `04c`, ne
dépend pas des pivots : il se détecte sur une séquence de bougies ou sur un profil de densité.
Un résultat « déséquilibre positif, pivots négatifs » signifierait donc que **les événements de
déplacement portent une information que les niveaux ne portent pas** — conclusion plausible,
intéressante, et qui orienterait le système vers une pondération des événements plutôt que des
niveaux. Elle reste soumise à réplication renforcée, mais mérite d'être lue comme une découverte
possible plutôt que comme une anomalie.

## C5 — La famille microstructure attend le même traitement, et son gate coûte moins cher

Le gel porte sur la famille structure. La famille microstructure — six moteurs, `03a` à `03f` —
présente exactement le même déséquilibre : une source d'information, six vues, aucune validée.

Son test fondateur n'est cependant pas de même nature, et c'est une bonne nouvelle. Il ne
nécessite **ni étiquettes, ni contrôles appariés, ni modèle** : il suffit de comparer la
**demi-vie mesurée du signal** à la **latence de bout en bout mesurée** (ADR-030).

| | Gate structure | Gate microstructure |
| --- | --- | --- |
| Dépend de | Q36 (horizons), Q1 | **Q19 seule** |
| Nécessite | contrôles appariés, risques concurrents, modèles | deux mesures |
| Verdict | poids d'une famille de moteurs | rôle autorisé de la famille : déclencheur, calage ou veto |

Ce gate est donc nettement moins coûteux et peut être conduit **en parallèle** de la résolution de
Q36. Cela renforce l'ordre de priorité du §2 : Q19 n'est pas seulement la deuxième question, c'est
celle dont la résolution débloque immédiatement un verdict complet sur six moteurs.

## C6 — Le critère d'investissement gagne à être reformulé

La règle du §12 compare « gain informationnel espéré » et « coût total de cycle de vie ». Le
numérateur pose une difficulté : **c'est précisément ce que le test doit découvrir.** Estimé avant
le test, il n'est qu'une croyance — et une croyance optimiste justifie toujours de continuer.

Formulation plus robuste : comparer le **coût du test** au **coût de se tromper sans le faire**.

Un test peu coûteux capable de ramener à zéro le poids d'une famille entière a une valeur très
élevée, même si le gain attendu est inconnu — c'est justement l'inconnu qui a de la valeur.
Ce critère place mécaniquement Q1, Q19 et Q36 en tête : ils sont peu coûteux, et chacun débloque
ou invalide un large périmètre de travail déjà spécifié.

---

## Conclusion de conduite

> La prochaine étape n'est pas de définir davantage de vocabulaire. Elle est de transformer les
> hypothèses fondatrices en protocoles exécutables.

Une architecture supérieure n'est pas celle qui reconnaît le plus de motifs. C'est celle qui sait
démontrer lesquels apportent une information nouvelle, attribuer un poids nul aux autres, et
arrêter leur développement quand leur coût dépasse leur valeur.

**Ajout** : elle doit aussi savoir distinguer « ceci n'apporte rien » de « je n'ai pas les moyens
de le savoir ». C'est l'objet de C1, et c'est la différence entre un système qui élimine des
idées et un système qui les élimine au hasard.
