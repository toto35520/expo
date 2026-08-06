# 04d — Inversion de déséquilibre (IFVG)

> Statut : **figé** (étape 4.4).
> Objet **dérivé** de `04c-fair-value-gap.md`. Ne rien lire ici sans avoir lu 04c.

## 0. Note de lecture

La spécification détaillée de cette étape intègre les deux corrections apportées à l'étape 4.3 —
statut en axes indépendants (ADR-073) et séparation marché de détection / marché d'exécution avec
traduction par la base (ADR-074). Elles sont ici généralisées et enrichies, notamment par le
traitement de l'**incertitude de traduction**, qui est un ajout réel.

---

# Partie A — Spécification normative

## 1. Définition et séquence

Un `IFVG` n'est pas un FVG dont on change le sens. C'est un **objet dérivé**, créé lorsqu'un FVG
subit un franchissement **accepté** dans le sens contraire à son rôle initial.

```
FVG source → franchissement de la borne critique → évaluation de l'acceptation
→ création éventuelle d'un rôle inversé → retour éventuel → réaction ou échec
```

Un simple contact, un remplissage complet ou une mèche au-delà **ne suffisent jamais**.

## 2. Relation source / dérivé

Chaque IFVG référence `source_fvg_id`. Les deux objets restent séparés : le FVG source conserve
bornes, sens, horodatages, historiques de remplissage et de mitigation, et sa validité dans son
rôle initial. L'IFVG ajoute rôle inversé, événement de franchissement, mesure d'acceptation,
horodatage de disponibilité propre, historiques de retests et de réactions, et sa propre
validité. **La création d'un IFVG ne supprime jamais le FVG source.**

## 3. Directions

`s_IFVG = −s_source`, avec `+1` haussier et `−1` baissier.

| Source | Franchissement accepté | Rôle inversé | Approche du retest |
| --- | --- | --- | --- |
| FVG haussier (support supposé) | vers le bas, sous `L` | IFVG **baissier** — résistance | depuis le dessous |
| FVG baissier (résistance supposée) | vers le haut, au-dessus de `U` | IFVG **haussier** — support | depuis le dessus |

## 4. Géométrie canonique

`Z_IFVG = [L, U]` — **identique à la source**. Le moteur ne déplace jamais rétroactivement les
bornes pour épouser la réaction observée.

Trois familles de bornes, séparées : `canonical_*` (immuables), `observed_reaction_*`
(descriptives), `execution_*` (dérivées de la base, §12).

`CE = (L+U)/2`, inchangé par l'inversion. Sa valeur comme support ou résistance est **testée, pas
postulée**.

## 5. Borne critique et franchissement

`B_exit = L` si `s_source = +1`, `U` si `s_source = −1`.

Profondeur signée : `D_t = max(0, −s_source·(P_t − B_exit))` — positive sous `L` pour une source
haussière, au-dessus de `U` pour une source baissière.

Profondeur normalisée : `D_t^σ = D_t / σ_breach`, où `σ_breach` est **estimée et figée au début
du franchissement**.

Le franchissement brut produit un `FVG_BREACH_EVENT`, **jamais un IFVG confirmé**.

## 6. Base de prix et volatilités

`breach_price_basis` obligatoire : `TRADE` sur le listé, `MEDIAN_COMPOSITE` sur le spot.
`analytical_breach` et `executable_breach` conservés séparément.

Trois volatilités **non interchangeables** : `sigma_at_fvg_creation`, `sigma_at_breach_start`,
`sigma_at_retest`. Chacune figée à son événement. Utiliser la volatilité de création plusieurs
heures plus tard fausserait toutes les mesures.

## 7. Candidat immédiat et inversion acceptée

Deux objets **temporellement distincts** :

| Objet | Disponibilité | Fiabilité |
| --- | --- | --- |
| `IFVG_CANDIDATE` | dès la profondeur minimale versionnée | faible — signale seulement que le rôle initial est peut-être en train d'échouer |
| `IFVG_ACCEPTED` | après la fenêtre d'acceptation | plus forte, plus tardive |

Publiés obligatoirement : `acceptance_confirmation_latency` et
`price_displacement_during_confirmation`. **Le système ne doit jamais laisser croire que
l'inversion confirmée était connue au premier tick de franchissement.**

## 8. Mesure continue de l'acceptation

Pas de conjonction arbitraire. Un vecteur de preuves est conservé :

| Grandeur | Définition |
| --- | --- |
| `A_D` | `max D_t / σ_breach` — profondeur |
| `A_T` | fraction de la fenêtre passée au-delà de `B_exit` — occupation temporelle |
| `A_V` | volume exécuté au-delà / volume total de la fenêtre |
| `A_M` | distance moyenne au-delà, normalisée |
| `failed_reclaim_count` | tentatives de réintégration échouées |
| `breach_velocity` | vitesse de franchissement |
| `order_flow_imbalance_beyond_boundary` | déséquilibre de flux au-delà |

Une fonction **versionnée** `I_A = f_acceptation(X_A) ∈ [0,1]` transforme ce vecteur en intensité.
La valeur continue est toujours conservée ; le découpage en quatre classes est une commodité
d'interface, aux seuils versionnés, qui ne la remplace jamais. Création d'un IFVG confirmé si
`I_A ≥ θ_A`.

## 9. Fenêtre d'acceptation

Exprimée sur plusieurs dimensions : `elapsed_seconds`, `market_event_count`, `traded_volume`,
`realized_volatility_time`. Publiés : début, fin, durée, événements, volume.

Cinq minutes pendant une publication majeure et cinq minutes en creux asiatique ne sont pas
comparables.

## 10. Disponibilité

`t_accepted = max(t_candidate, t_window_end, t_data_availability)`. Aucun backtest n'utilise
l'état `ACCEPTED` avant cet instant.

**Un remplissage complet n'est pas une inversion** : si le prix traverse, dépasse légèrement,
revient immédiatement et réintègre durablement, alors `source_fvg.fill_state = COMPLETE` et
`ifvg.formation_state = REJECTED_BREACH`. Inversement, un franchissement peu profond mais
durablement occupé avec activité réelle **peut** être accepté.

## 11. Quatre axes d'état indépendants

```
formation   NONE | BREACH_CANDIDATE | ACCEPTANCE_PENDING | ACCEPTED
            | REJECTED_BREACH | DATA_INVALID
retest      NOT_ELIGIBLE | NOT_RETESTED | RETEST_IN_PROGRESS
            | FIRST_RETEST_COMPLETED | MULTIPLE_RETESTS
reaction    NOT_EVALUATED | REACTION_PENDING | REACTION_CONFIRMED
            | REACTION_FAILED | CENSORED
validity    ACTIVE | SUSPENDED | INVALIDATED | EXPIRED
```

État exprimable et significatif : `formation = ACCEPTED`, `retest = FIRST_RETEST_COMPLETED`,
`reaction = REACTION_FAILED`, `validity = ACTIVE` — le rôle était correctement formé, le premier
retest n'a pas réagi, la zone reste utilisable pour un autre horizon.

**Éligibilité au retest** : un retest ne commence qu'après `t_accepted`. Tout retour antérieur
appartient encore à la phase de franchissement — règle qui empêche de détecter un IFVG et son
retest dans la même oscillation. Le prix doit en outre s'être éloigné de `D_reset ≥ k_reset·σ`
avant de revenir du côté attendu.

## 12. Marchés, base et incertitude

`detection_market` et `execution_market` obligatoires. Traduction :
`b(t) = P_execution(t) − P_detection(t)`, `L_e(t) = L_d + b(t)`, `U_e(t) = U_d + b(t)`.

Conservés : base à la création de la source, au franchissement, à l'acceptation, au retest. **La
base n'est jamais supposée constante.**

Incertitude `u_b(t)`, et rapport `B_U = u_b / (U_e − L_e)`. Au-delà d'un seuil versionné :
`validity_state = SUSPENDED`, `execution_eligibility = FALSE`. Une petite zone dont l'incertitude
de traduction vaut 80 % de la largeur n'est pas exploitable.

Fraîcheur : `basis_timestamp`, `basis_age_ms`, `basis_data_quality`, `basis_regime`. Base périmée
⇒ `execution_zone_status = UNAVAILABLE` : la zone analytique reste visible, aucune entrée n'est
proposée.

## 13. Retest, réaction, censure

**Contacts** : `analytical_retest_timestamp` et `executable_retest_timestamp` séparés. Base
exécutable `ASK` pour un IFVG haussier recherché à l'achat, `BID` pour un baissier recherché à la
vente, conforme au broker réel.

**Prix de référence** : `canonical_retest_entry_price` (premier prix exécutable entrant dans la
zone après éligibilité) et `actual_fill_price` restent séparés. Une borne théorique non
exécutable n'est jamais utilisée comme prix d'entrée.

**Profondeur** : `R = clip((U − P_min)/(U − L), 0, 1)` pour un IFVG haussier,
symétrique pour un baissier. La profondeur optimale est **apprise**, sans présumer que 50 % vaut
mieux que 25 % ou 75 %.

**Réaction** : `MFE = max[s(P_t − P_e)]`, `MAE = max[−s(P_t − P_e)]` sur l'horizon `H_R`,
normalisées par `σ_retest`. Confirmation par triple barrière — favorable, défavorable,
temporelle — aux valeurs versionnées.

**Censure** : perte de données, fermeture anticipée, rollover, erreur de cotation, intervention
manuelle, déconnexion, modification de l'instrument. `reaction_state = CENSORED`. **Les
observations censurées ne sont pas assimilées à des pertes.**

## 14. Validité, invalidation, expiration

**Invalidation canonique** : le rôle inversé n'est pas invalidé à la première pénétration. Il
faut une **acceptation au-delà de la borne opposée**, évaluée avec la même logique que le
franchissement initial — profondeur, durée, volume, occupation, flux, réintégrations.

**Invalidation structurelle ≠ échec de trade.** Un trade peut perdre alors que la zone reste
active ; une zone peut être invalidée sans qu'aucun trade ait été pris.

**Expiration** : dépend de l'horizon, donc **non fixable tant que Q36 n'est pas résolue**. Le
moteur conserve `age_seconds`, `age_events`, `age_volume`, `sessions_crossed`,
`macro_events_crossed`, `regime_changes_crossed`, `retests_since_acceptance`, et **publie l'âge
sans déclarer arbitrairement la zone expirée**.

## 15. Épisodes de rôle

Une zone peut changer plusieurs fois de rôle. Le moteur ne modifie pas le sens d'un objet
existant : il crée des **épisodes successifs** (`zone_id`, `role_episode_id`,
`role_episode_index`, `role_direction`), chacun avec sa création, son acceptation, ses retests,
ses réactions, son invalidation et sa disponibilité.

Conservés : `role_flip_count`, `total_crossing_count`, `accepted_crossing_count`,
`failed_crossing_count`. Le nombre de changements de rôle est un **attribut prédictif**, pas une
règle d'exclusion.

## 16. Familles causales

Le franchissement produisant l'IFVG peut aussi produire BOS, CHOCH, MSS, déplacement et prise de
liquidité. Regroupement obligatoire dans `ROLE_REVERSAL_CLUSTER`, avec les identifiants associés.
**Non comptés comme preuves indépendantes** (ADR-035).

Relation avec BPR : un chevauchement peut former un `BPR_CANDIDATE`, troisième objet. Aucune zone
source n'est fusionnée ni supprimée.

## 17. Trois hypothèses, trois modèles

| Hypothèse | Question | Modèle |
| --- | --- | --- |
| **Attraction** | après inversion acceptée, le prix revient-il depuis le nouveau côté ? | `IFVG_RETEST_MODEL` |
| **Réaction** | après retest exécutable, repart-il avec une espérance positive ? | `IFVG_REACTION_MODEL` |
| **Invalidation** | la borne opposée fournit-elle une meilleure invalidation qu'un stop comparable ? | `IFVG_INVALIDATION_MODEL` |

Un score unique ne doit jamais masquer leurs différences. L'hypothèse d'invalidation se compare à
un stop de volatilité, un stop sur pivot, un stop aléatoire apparié en distance et un stop
minimisant la perte extrême conditionnelle.

## 18. Contrôles et apport incrémental

Contrôles : support cassé devenu résistance, résistance cassée devenue support, zones aléatoires
de même largeur, anciens FVG entièrement remplis sans acceptation, zones de faible volume, milieu
de déplacement, anciens pivots cassés. Appariés sur largeur, âge, volatilité, profondeur de
cassure, momentum, régime, session, distance du prix, structure.

> **Question centrale** : le fait que la zone provienne initialement d'un FVG ajoute-t-il une
> information **au-delà du phénomène générique de changement de rôle** ?

Modèle de référence connaissant déjà cassure, acceptation, momentum, volatilité, structure,
liquidité et session. Si l'ajout de l'origine FVG n'améliore pas la performance hors échantillon,
l'IFVG n'est pas une source autonome — il peut rester une représentation géométrique utile.

## 19. Fuite temporelle et non-repeinture

Interdites au moment du signal : profondeur future du retest, réaction future, maintien futur,
nombre futur de retests, résultat du trade, acceptation calculée après sa disponibilité,
volatilité calculée avec des données ultérieures.

Chaque propriété porte `event_timestamp` et `availability_timestamp` ; le moteur de features ne
charge une propriété que si `availability_timestamp ≤ decision_timestamp`.

Immuables après acceptation : identifiants, direction, bornes canoniques, horodatages, version du
modèle d'acceptation. Les évolutions sont enregistrées comme **événements** (`RETEST_STARTED`,
`REACTION_CONFIRMED`, `ROLE_INVALIDATED`, …). Une correction de données crée une version, ne
modifie jamais silencieusement l'historique.

## 20. Tests d'acceptation

Déterminisme · batch contre streaming · pas d'inversion sur simple remplissage · disponibilité
respectée · retest jamais compté avant acceptation · symétrie stricte · aucune zone listée
utilisée en spot sans traduction · suspension au-delà du seuil d'incertitude de base ·
représentabilité de l'état combiné (remplissage complet + IFVG accepté + réaction échouée +
validité active) · épisodes successifs sans modification des précédents · deux horodatages de
retest possibles · révision de données sans modification silencieuse.

---

# Partie B — Corrections et compléments

## C1 — « L'acceptation » est déjà définie trois fois dans le système

Trois moteurs mesurent aujourd'hui la même notion sous trois noms :

| Moteur | Nom local | Référence |
| --- | --- | --- |
| Ruptures de structure | « maintien après rupture », rupture *retenue* | ADR-059, `04b` §6 |
| Balayages | `PRIX_ACCEPTÉ` / `PRIX_REJETÉ` | `03f` §8 |
| Inversion | `acceptance_intensity`, `I_A` | ce document §8 |

Et le §14 en demande implicitement une quatrième, puisque l'invalidation canonique doit être
évaluée « avec une logique analogue au franchissement initial ».

**C'est exactement la situation de Q27 avant l'étape 4.1** : une notion partagée, redéfinie
localement par chaque moteur, garantissant que deux moteurs se contrediront sur le même
événement.

**Décision** : `PriceAcceptance` devient un **primitif unique et versionné**, prenant en entrée
une frontière, une direction, une fenêtre et une volatilité de référence, et produisant le vecteur
`X_A` et l'intensité `I_A`. Les quatre usages en sont des appels paramétrés, jamais des
réimplémentations. Même traitement que la définition d'impulsion (ADR-056).

Bénéfice secondaire : une seule fonction à calibrer et à valider au lieu de quatre, et un seul
jeu de paramètres à faire varier dans les tests de sensibilité.

## C2 — Le seuil d'acceptation est une poignée de sélection, pas un réglage

Point statistique le plus important de cette étape.

Un IFVG n'existe que si le franchissement est **accepté**. La population d'IFVG est donc
**sélectionnée sur la continuation du mouvement**. Élever `θ_A` ne rend pas le détecteur « plus
strict » : cela **change la population étudiée** — les moves retenus sont plus forts, donc les
taux de retest, de réaction et d'invalidation changent tous ensemble.

Conséquence : publier « probabilité de retest : 72 % » à une valeur de `θ_A` n'a pas de sens
isolément, et permet de choisir `θ_A` pour obtenir le chiffre voulu.

**Règle** : toutes les probabilités des trois hypothèses sont publiées **en fonction de `θ_A`**,
sur toute la plage utile, et non à un point. Un effet réel se déforme régulièrement le long de
cette courbe ; un artefact apparaît à une valeur.

C'est le même principe que la robustesse sur grille (ADR-034), appliqué à un paramètre qui a la
particularité de définir l'échantillon lui-même.

## C3 — Le nombre de changements de rôle est contaminé par l'exposition

Le §15 fait de `role_flip_count` un attribut prédictif — c'est justifié, mais la variable est
biaisée telle quelle.

Une zone qui a changé cinq fois de rôle est une zone **près de laquelle le prix est resté**. Elle
est donc sélectionnée sur l'attraction : un compteur élevé prédit trivialement d'autres retours,
sans que la zone ait la moindre propriété particulière.

**Correction** : le dénominateur doit être l'**exposition** — temps passé à portée de la zone,
volume écoulé à portée, ou nombre d'occasions de franchissement — et non l'âge calendaire. La
variable exploitable est un **taux de retournement par unité d'exposition**, pas un compte brut.

## C4 — La censure doit entrer dans l'estimation, pas seulement dans l'étiquetage

Le §13 définit correctement `CENSORED` et interdit de l'assimiler à une perte. Il manque la suite :
**écarter les observations censurées biaise également**, dans l'autre sens, car la censure n'est
pas indépendante de l'issue — un rollover ou une fermeture interrompt préférentiellement les
réactions lentes.

**Décision** : les probabilités de retest et de réaction sont estimées par une méthode qui traite
explicitement la censure et les **risques concurrents**. Les trois issues de la triple barrière
— objectif atteint, invalidation atteinte, barrière temporelle — plus l'invalidation structurelle
sont des risques concurrents : la grandeur correcte est une **incidence cumulée**, pas une
proportion binomiale. Sans cela, les probabilités ne s'additionnent pas correctement et la
calibration est fausse par construction.

Une conséquence pratique : `probability_of_retest` doit s'accompagner de son **horizon** et de la
fraction censurée à cet horizon.

## C5 — La zone d'exécution est une vue, pas un champ

Le schéma stocke `execution_lower_bound` et `execution_upper_bound` comme scalaires. Or la base
évolue : ces bornes sont des **fonctions du temps**.

**Décision** : les bornes canoniques sont l'unique vérité stockée (conforme au §4 et à
l'ADR-080) ; les bornes d'exécution sont **recalculées à chaque évaluation** et ne sont jamais
persistées comme vérité. Ce qui figure au schéma n'est qu'un **instantané horodaté**, marqué comme
tel, avec la base et son incertitude au même instant.

Sans cette distinction, une zone d'exécution périmée sera utilisée comme si elle était courante —
exactement le mode d'échec que la fraîcheur de base du §12 cherche à empêcher.

## C6 — La suspension pour incertitude de base et les positions ouvertes

Le §12 suspend l'éligibilité à l'exécution quand `B_U` dépasse son seuil. Le cas non traité est
celui d'une **position déjà ouverte** sur cette zone lorsque la suspension se déclenche.

C'est la même question que Q18 en mode dégradé, et la réponse doit être cohérente : ne pas
augmenter, ne pas élargir les protections, et traiter la dégradation elle-même comme motif de
réduction. **Une exposition dont la zone de référence n'est plus traduisible n'est plus
mesurable.**

## C7 — Propagation d'une invalidation de source

Le §19 traite la révision de données pour l'IFVG lui-même. Il ne dit pas ce qui arrive quand le
**FVG source** passe en `DONNÉES_INVALIDES`.

**Décision** : l'invalidation d'une source se propage à tous les épisodes dérivés, qui passent en
`DATA_INVALID` avec référence à l'événement de révision d'origine. Un objet dérivé ne survit pas
à l'invalidation de ce dont il dérive.

## C8 — Dépendance de validation : l'IFVG hérite du verdict du FVG

Le point le plus important pour la conduite du projet.

L'ADR-071 pose une question encore sans réponse : **une zone qualifiée de FVG apporte-t-elle une
information au-delà d'une zone de contrôle appariée ?** L'ADR-056 en pose une analogue pour les
pivots eux-mêmes.

Si la réponse est négative, l'IFVG est un objet dérivé d'une population sans propriété
particulière — et son propre test (§18) risque de produire un résultat positif fortuit, puisqu'il
compare une population sélectionnée sur l'acceptation à des contrôles qui ne le sont pas
exactement de la même façon.

**Ordre de validation imposé :**

```
1. les niveaux de pivot réagissent-ils ?              (04a §10)
2. le FVG apporte-t-il quelque chose ?                 (ADR-071)
3. seulement alors — l'IFVG apporte-t-il quelque chose ? (§18)
```

Un résultat positif à l'étape 3 alors que l'étape 2 est négative doit être traité comme
**suspect**, non comme une découverte.

Cela n'empêche pas d'**écrire** le moteur maintenant — la spécification est utile et le code se
réutilise. Cela interdit de lui **accorder un poids** avant que sa fondation ait passé son propre
test.

## C9 — Note d'ampleur

Le moteur d'inversion compte quarante-six sections, quatre axes d'état, trois modèles, deux
marchés et une fonction d'acceptation versionnée — pour un objet **dérivé** d'un autre moteur
lui-même non encore validé.

Ce n'est pas une critique de la spécification, qui est correcte. C'est une observation de
séquencement : le coût de construction croît plus vite que le nombre de sources d'information
réellement distinctes, lequel n'a pas augmenté depuis l'étape 4.1. À budget de développement
fini, il vaut la peine de comparer explicitement le coût de ce moteur à celui des trois questions
bloquantes du registre (Q1, Q19, Q36), dont la résolution conditionne la valeur de **tout** ce
qui a été spécifié jusqu'ici.

## C10 — Corrections mineures

- **§4.4.13 (source)** : la formule de `t_accepted` est amputée de son signe d'égalité.
  Rétablie ici au §10.
- **§4.4.28 (source)** : idem pour la définition de la base `b_{d→e}(t)`. Rétablie au §12.
- **Formules vérifiées** : la profondeur signée du §5 donne bien un résultat positif du bon côté
  pour les deux sens ; les profondeurs de retest du §13 mesurent bien depuis la borne d'approche.
  Aucune correction nécessaire.
- **`I_A` déterministe ou calibré** : la recommandation de Q37 est adoptée — vecteur brut
  obligatoire, score déterministe reproductible, probabilité calibrée facultative. Le score
  déterministe garantit le test de double implémentation ; la probabilité calibrée, quand elle
  existe, est la seule autorisée à être exprimée en pourcentage (ADR-037).
