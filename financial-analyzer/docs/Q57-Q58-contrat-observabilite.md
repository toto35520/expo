# Q57 — Q58 · Contrat d'observabilité de la latence

> Statut : **moteur figé et implémenté**, contenu à produire sur l'infrastructure réelle.
> Code : `feasibility/observability.py`, 48 tests dédiés. Fiches : `connector-capability/`.
>
> Q57 et Q58 se traitent ensemble parce qu'elles déterminent une seule et même frontière :
> celle entre **mesuré**, **agrégé** et **impossible à identifier**. Tant qu'elles ne sont
> pas résolues, le journal peut collecter, mais aucune décomposition fine n'entre dans Q19.

---

## Objet

Le résultat n'est pas une estimation de performance. C'est un **contrat de mesure** :

```
OBSERVED · AGGREGATE_ONLY · LOWER_BOUND · NOT_IDENTIFIABLE
```

attribué à chaque composante du chemin :

```
marché → fournisseur → hôte → évaluation → décision
       → connecteur → courtier → ordre actif → exécution
```

**Aucune métrique de Q19 ne peut être plus précise que ce contrat.**

---

# Partie A — Q57 : qualification de l'horloge

## 1. Quatre grandeurs distinctes

`résolution`, `exactitude`, `précision`, `stabilité` ne sont pas la même chose. Une horloge
affichant des nanosecondes ne fournit pas une précision nanoseconde. Le rapport ne publie
jamais `123,456789 ms` lorsque l'incertitude réelle est de ±5 ms — `can_publish()` refuse.

## 2. Résolution effective, pas résolution annoncée

`GranularityTest` mesure sur une série d'appels le plus petit écart **non nul réellement
observé**, l'écart médian, le p99 et le taux d'horodatages dupliqués — pour la murale et
pour la monotone. Si la granularité représente une part importante de la latence mesurée,
la mesure est limitée par l'horloge, pas par l'infrastructure.

## 3. Monotonie et discontinuité

Tout recul de la monotone invalide la session. Tout recul de la murale pendant que la
monotone avance est une discontinuité **quelle que soit son amplitude** : un seuil de
magnitude laisserait passer les petites corrections de synchronisation, précisément les
plus fréquentes. Le signe est un cas absolu ; la magnitude n'est un critère que pour les
corrections positives, selon une politique versionnée.

## 4. Quatre statuts

| Statut | Autorise | Interdit |
| --- | --- | --- |
| `CLOCK_QUALIFIED` | durées locales monotones, comparaison inter-systèmes dans l'incertitude déclarée | — |
| `CLOCK_QUALIFIED_LOCAL_ONLY` | durées locales monotones | décomposition entre horodatage fournisseur/courtier et hôte |
| `CLOCK_DEGRADED` | mesures accompagnées d'une incertitude importante | toute précision revendiquée |
| `CLOCK_UNQUALIFIED` | éventuellement l'ordre des événements locaux | toute durée |

## 5. Résolution inter-systèmes

Une durée entre deux horloges porte au minimum `u_AB ≥ u_A + u_B`. Le rapport publie
l'intervalle mesuré, l'incertitude et leur **rapport** :

```
R_u ≤ 0,10   HIGH_CONFIDENCE
0,10 – 0,25  USABLE
0,25 – 0,50  DEGRADED
> 0,50       NOT_RESOLVABLE
```

Les seuils sont versionnés ; ils ne modifient pas la mesure brute. Une incertitude de 1 ms
est excellente sur 100 ms et inutilisable sur 2 ms — c'est un rapport, jamais un absolu.

## 6. Veille, reprise, virtualisation

Après une reprise, `CLOCK_REQUALIFICATION_REQUIRED` jusqu'à nouvelle vérification. Aucune
hypothèse ne considère qu'un portable ou une VM reste temporellement stable après veille.
`BARE_METAL / VM / CONTAINER / UNKNOWN` est documenté, mais **la qualification reste
empirique** : le type d'hébergement ne la détermine pas.

## 7. Critère de passage (§38)

Q57 est résolue lorsque cinq conditions sont remplies — implémentées par `q57_resolved()` :

1. l'horloge monotone est qualifiée ;
2. sa résolution effective est mesurée ;
3. le couple murale/monotone est **instrumenté** (nombre minimal de lectures appariées) ;
4. la méthode de synchronisation est connue ;
5. l'incertitude inter-systèmes est **soit estimée, soit explicitement déclarée inconnue**.

> Une synchronisation médiocre n'empêche pas de résoudre Q57. Elle réduit seulement le
> domaine mesurable.

Le point 5 porte tout le poids. Le champ
`intersystem_uncertainty_declared_unknown` existe pour séparer deux situations que rien ne
distinguerait autrement : **ne pas avoir mesuré**, et **avoir cherché puis constaté qu'on
ne peut pas mesurer**. La première laisse Q57 ouverte, la seconde la résout.

---

# Partie B — Q58 : sémantique du connecteur courtier

## 8. Le nom d'un rappel n'a aucune valeur probatoire

`on_order_accepted()` ne démontre pas qu'un ordre est actif sur le marché. La sémantique
doit être **prouvée** — documentation, schéma d'API, confirmation du support, test
contrôlé, capture réseau, code source. `EventSemantics` refuse de se construire si un
événement est déclaré observable sans `evidence_id`, ou porte un horodatage sans domaine
d'horloge.

`OBSERVATIONAL_INFERENCE` ne suffit **jamais** seule : observer qu'un accusé arrive vite
n'établit pas ce qu'il signifie.

## 9. Qualifier le retour d'émission

Cinq significations possibles : mise en file locale, écriture socket, réception serveur,
validation serveur, création d'ordre. Si seule la première est démontrée, le journal ne
doit **jamais** utiliser cet horodatage comme accusé courtier.

## 10. Qualifier l'accusé

Reçu ? validé ? créé ? actif ? simple réponse RPC ? Et surtout : un accusé peut-il précéder
l'activation, ou être suivi d'un rejet tardif ? Si oui, `BROKER_ACK ≠ ORDER_ACTIVE`
**structurellement** — `ack_implies_active` ne devient vrai que si l'activation est
elle-même observable.

## 11. Un délai dépassé n'est pas un rejet

`LOCAL_VALIDATION_REJECT`, `BROKER_REJECT`, `MARKET_REJECT` produisent `REJECTED`.
`TIMEOUT_UNKNOWN_STATE` produit `UNKNOWN_PENDING_RECONCILIATION`. Le résoudre en rejet
autoriserait l'émission d'un second ordre alors que le premier existe peut-être déjà :
**une position double au lieu d'une**. D'où l'exigence d'une réconciliation, obligatoire
pour traiter délai dépassé, reconnexion, accusé perdu, rappel perdu et panne.

## 12. Requête et événement ne se confondent pas

`RPC_RESPONSE`, `BROKER_EVENT`, `MARKET_EVENT`, `LOCAL_EVENT`. Un retour d'appel distant et
un événement courtier portent deux informations différentes ; ils ne partagent pas un type
pour la seule raison qu'ils arrivent presque simultanément.

## 13. Ordres d'événements

Le connecteur déclare les séquences **réellement garanties**. Le journal n'impose que
celles-là : une API peut délivrer `PARTIAL_FILL` avant `ACK`, ou un rappel avant le retour
de l'appel qui l'a déclenché.

## 14. Versionnement

Toute modification du connecteur crée une nouvelle qualification. Une mise à jour de SDK
peut changer rappels, tamponnage, ordre des événements, horodatages et reprises :
`invalidated_by()` déclare les conclusions précédentes non valables.

## 15. Critère de passage (§39)

Q58 est résolue lorsque chaque événement **utilisé dans Q19** porte sémantique, preuve,
domaine d'horloge, garantie d'ordre déclarée et statut d'identifiabilité —
`q58_resolved()`.

> Les événements non identifiables sont acceptables. L'ambiguïté non documentée ne l'est
> pas.

## 16. Ce qui se qualifie sans risque financier

Lecture de la documentation et du code du connecteur, observation des rappels de connexion,
instrumentation, chronologie d'une session **sans trading**. Cela résout déjà une partie de
Q58. Les tests contrôlés — soumission, accusé, annulation, rejet volontaire, reconnexion —
attendent Q42, et leur objectif n'est pas la vitesse : c'est de comprendre ce que chaque
événement signifie.

---

# Partie C — La borne, par frontières

## 17. Le défaut corrigé

Q51 construisait sa borne en **additionnant des `LatencyInterval`**. Or deux intervalles
nommés peuvent parfaitement se recouvrir : `submit→ACK` contient déjà le traitement
courtier, les trajets réseau et la file locale. Les sommer double-compte.

Le symptôme est net et vérifiable : un aller-retour de 14 ms plus un traitement courtier de
9 ms situé **à l'intérieur** donne 23 ms sur un chemin dont la durée réellement vécue est
de 20 ms. Une « borne inférieure » supérieure au vécu n'en est plus une.

## 18. Des frontières, pas des durées

```python
@dataclass(frozen=True)
class LatencyBoundary:
    name: str
    timestamp_ns: int | None
    clock_domain: ClockDomain
    quality: BoundaryQuality
```

`LatencyPath` décrit le chemin par ses **frontières**. Deux segments consécutifs partagent
une frontière : ils sont disjoints par construction, et le double comptage devient
structurellement impossible plutôt qu'interdit par convention.

Trois conséquences directes :

- une frontière absente n'est **jamais interpolée** — les deux segments qu'elle borde
  deviennent `NOT_IDENTIFIABLE` et sortent de la borne, qui reste inférieure ;
- un segment traversant deux domaines d'horloge reste `NOT_RESOLVABLE_INTERSYSTEM` tant que
  Q57 n'a pas qualifié la comparaison, **même si les deux valeurs numériques existent** ;
- un segment plus court que son incertitude n'est pas une mesure.

Symétriquement, côté journal, `LatencyObservation` **refuse de se construire** si deux de
ses intervalles recouvrent le même mécanisme. Le recouvrement est détecté par les
composantes déclarées, donc transitivement : `outbound_leg` et `submit_to_ack_latency` ne
portent pas le même nom mais comptent tous deux la file locale et le réseau aller.

## 19. Deux vues qui ne se confondent pas

| Vue | Contenu | Usage |
| --- | --- | --- |
| **chemin critique** | `quote received → decision → ACK` | durée réellement vécue — **le gate l'utilise en priorité** |
| **attribution** | évaluation, calcul, `submit→ACK`… avec ses trous | diagnostic d'optimisation |

Le chemin critique englobe les trous non mesurés entre composantes ; il est donc toujours
supérieur ou égal à la somme d'attribution, et reste malgré tout une borne **inférieure**
de la latence totale — rien de ce qui précède la première frontière ni ne suit la dernière
n'y entre.

Une couverture faible signale un manque de prise pour l'optimisation, pas un défaut de
fondement : la durée vécue, elle, est mesurée.

## 20. Les qualités ne se mélangent pas

`EXACT_LOCAL`, `QUALIFIED_INTERSYSTEM`, `AGGREGATE`, `LOWER_BOUND`, `DEGRADED_CLOCK`,
`UNKNOWN`. Un p95 confondant durées exactes et durées à horloge dégradée décrit la
répartition des qualités de mesure autant que la latence elle-même.

---

# Partie D — La matrice

## 21. Croisement pessimiste

`build_matrix()` ne déclare une composante observable que si **les deux** — horloge et
connecteur — la rendent observable. Sur une infrastructure courante :

| Composante | Statut | Pourquoi |
| --- | --- | --- |
| attente de cadence, calcul, décision | `OBSERVED` | horloge monotone locale |
| `provider → réception locale` | `AGGREGATE_ONLY` | appariement, agrégation, distribution, transport, tamponnage — **jamais « latence réseau »** |
| `submit → ACK` | `AGGREGATE_ONLY` | file locale, réseau aller, traitement courtier, réseau retour, rappel |
| réseau aller, traitement courtier, réseau retour | `NOT_IDENTIFIABLE` | aucun horodatage courtier |
| `ACK → actif` | `NOT_IDENTIFIABLE` | l'accusé ne démontre pas l'activation |
| `actif → exécution` | `NOT_IDENTIFIABLE` | avant Q42 |
| **chemin critique** | `LOWER_BOUND` | des segments manquent |

Un agrégat **contribue sa durée entière** au total : ce qui rend le chemin une borne
inférieure, ce sont les segments manquants, pas les segments non décomposables.

Sans accusé prouvé, `submit → ACK` n'est pas « agrégé » : il est **absent**. Un connecteur
dont l'accusé n'est pas démontré ne fournit pas une mesure grossière, il ne fournit rien —
et le système ne mesure alors que lui-même (`LOCAL_ONLY`).

## 22. Verdict global

| Verdict | Signification |
| --- | --- |
| `FULLY_QUALIFIED` | rare — chemin critique et principales frontières inter-systèmes observables |
| `SUFFICIENT_FOR_LOWER_BOUND` | composantes locales et agrégats suffisants à une borne fiable |
| `LOCAL_ONLY` | seule la partie interne du système est qualifiée |
| `INSUFFICIENT_FOR_Q19` | ni horloges ni sémantiques ne permettent une borne exploitable |

`enforce_contract()` refuse ensuite toute attribution plus fine : nommer
`broker_processing` sur une infrastructure sans horodatage courtier produirait un chiffre
crédible et faux.

---

## Travail immédiat

**Q57.** Instrumenter dès maintenant, sur l'hôte qui exécutera **réellement** l'analyseur :
horloge murale, monotone, dérive, discontinuités, état de synchronisation, résolution
effective. Fiche : `connector-capability/host-clock-capability.json`.

**Q58.** La fiche `connector-capability/broker-connector-capability.json` est livrée
**vide**, tout déclaré inconnu, et le rester est un résultat valide :

```json
{ "submit_return_semantics": "UNKNOWN",
  "ack_semantics": "UNKNOWN",
  "order_active_observable": false,
  "broker_receive_timestamp_available": false }
```

> C'est meilleur qu'une fausse précision.

Un test vérifie que la fiche livrée ne revendique rien et produit bien la matrice la plus
pessimiste. `load_capability()` lit toute valeur absente comme inconnue — jamais comme
favorable — et refuse une sémantique non reconnue plutôt que de l'ignorer.

---

## Conclusion

Le projet franchit une frontière : **ce qui existe dans le système** et **ce que le système
est capable d'observer** ne sont pas la même chose. Q57/Q58 établissent cette frontière une
fois pour toutes.

Q19 peut désormais produire son premier verdict réel sans inventer aucune partie de la
latence :

```
mesuré + agrégé + borne certaine + inconnu explicitement
```

C'est suffisant pour éliminer rigoureusement des horizons trop courts, même si le courtier
reste une boîte noire.

**Prochain embranchement.** Il est simple, et il dépend d'un chiffre qui n'existe pas encore :

- si la borne Q19 élimine déjà les horizons microstructurels → inutile de financer Q42 ;
- si elle ne les élimine pas → Q42 devient la prochaine dépense rationnelle.
