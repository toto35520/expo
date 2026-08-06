# Q53 — Sources normatives et chaîne de preuve du calendrier

> Statut : **figé et implémenté**. Code : `feasibility/calendar_sources.py`, 35 tests dédiés.
> Dossier de preuve : `calendar-sources/`.
>
> Q52 garantit que le moteur applique correctement une règle temporelle.
> **Q53 garantit que la règle mérite d'être appliquée.**

---

# Partie A — Protocole normatif

## 1. Principe

Le calendrier ne contient jamais une règle nue — « XAU/USD ferme chaque jour à 22 h ». Il
contient une **affirmation documentée** : le symbole XAUUSD du compte RAW sur ce serveur est
annoncé indisponible entre X et Y, selon la spécification récupérée le Z, applicable à partir
de W.

**La règle et sa preuve sont inséparables.** Une règle sans réponse vérifiable à *qui l'affirme,
quand, pour quelle période, avec quel statut et quel document* n'est pas normative.

Chaîne complète, vérifiable de bout en bout :

```
source → instantané → assertion → revue → manifest → compilation → calendrier → rapport
```

## 2. Assertion atomique

L'unité est la `CalendarAssertion`. Une page indiquant plusieurs horaires produit **plusieurs**
assertions — c'est ce qui permet d'en superseder une sans toucher aux autres.

Types : séance régulière, pause quotidienne, jour férié, fermeture anticipée, ouverture
retardée, maintenance, jour de portage multiplié, heure de rollover, fuseau serveur, diffusion
indisponible, interruption exceptionnelle.

## 3. Hiérarchie des sources — par domaine, jamais globale

| Domaine | Source normative | Secondaire |
| --- | --- | --- |
| **Marché listé** | place : calendrier officiel, avis de marché, spécification de contrat | courtier, plateforme, agrégateur |
| **Symbole OTC chez un courtier** | spécification effective du symbole sur le compte réel | documentation générale du courtier |
| **Flux de données** | documentation du fournisseur, contrat, statut de service | — |
| **Observation** | jamais normative | proposition uniquement |

Une source secondaire ne remplace pas la place lorsqu'elle décrit les horaires de la place.
L'observation ne devient **jamais** automatiquement normative.

## 4. Portée

Chaque assertion déclare courtier, serveur, type de compte, symbole, marché, source de données,
juridiction. **Les champs non applicables sont explicitement nuls** — l'absence déclarée se
distingue de l'oubli.

Usages interdits : calendrier de la place pour déclarer le symbole du courtier fermé, horaires
généraux du courtier pour tous ses serveurs, calendrier spot pour le contrat à terme,
**compte de démonstration pour décrire un compte réel**.

## 5. Conflits

Deux sources qui se contredisent produisent un `CalendarSourceConflict` explicite. **Aucune
résolution silencieuse.**

Priorité : portée spécifique au symbole et au compte, puis au marché, puis générale, puis
communication officielle plus récente, puis secondaire, puis observation. **La spécificité peut
primer sur l'autorité générale.**

La récence n'est **qu'un attribut** : une page récente peut décrire une autre période, un autre
produit ou un autre serveur.

## 6. Acquisition et preuve

Chaque acquisition crée un `SourceSnapshot` immuable : origine, date, contenu ou représentation
conservable, empreinte, type, langue, marché, méthode, statut. Quand le contenu ne peut être
conservé intégralement — empreinte, métadonnées, extrait utilisé, capture structurée, date,
provenance suffisent.

Pour chaque assertion : instantané, localisation dans la source, extrait minimal, méthode
d'interprétation, auteur de la validation.

## 7. Extraction et revue

Une extraction automatique naît `PARSED_UNREVIEWED`. États : `PARSED_UNREVIEWED`,
`REVIEW_REQUIRED`, `APPROVED`, `REJECTED`, `SUPERSEDED`. La validation vérifie fuseau, date
d'effet, jours concernés, symbole, compte, exceptions, ambiguïtés linguistiques.

## 8. Fuseaux et dates d'effet

Une source affichant « GMT+2 » : décalage fixe, ou heure locale saisonnière ? L'assertion
conserve l'expression source, le fuseau IANA normalisé et la méthode de normalisation. Si le
document n'est pas clair, `timezone_interpretation = AMBIGUOUS` et l'assertion **ne peut pas
être approuvée**.

Date d'effet : `EXPLICIT_IN_SOURCE`, `INFERRED_FROM_PUBLICATION_DATE`,
`INFERRED_FROM_OBSERVATION`, `UNKNOWN`. Une règle à date inconnue n'est pas appliquée
rétroactivement.

## 9. Fraîcheur et changements

`FRESH`, `REVIEW_DUE`, `STALE`, `UNKNOWN_FRESHNESS`. Une assertion périmée n'est pas
nécessairement fausse — mais elle ne peut pas soutenir silencieusement un verdict définitif.

Changements : `NO_CHANGE`, `PRESENTATION_ONLY_CHANGE`, `SEMANTIC_CHANGE`, `SOURCE_REMOVED`,
`SOURCE_UNAVAILABLE`. **Une refonte de mise en page ne crée pas une règle différente.**

## 10. Manifest, compilation, impact

Chaque version publiée possède un manifest immuable : assertions, sources, conflits non résolus,
éléments provisoires, empreinte, approbateur. Deux constructions indépendantes du même manifest
doivent produire la même empreinte ; **un manifest dépendant d'informations non conservées est
invalide**.

Compilation en quatre étapes — charger, vérifier les conflits, appliquer priorités et
exceptions, émettre les segments — avec trois échecs bloquants (§ Partie B).

Une correction identifie les rapports affectés : `NO_MATERIAL_IMPACT`, `RECOMPUTE_RECOMMENDED`,
`RECOMPUTE_REQUIRED`, `VERDICT_INVALIDATED`. **Les anciens rapports ne sont jamais réécrits.**

## 11. Observation comme contrôle

Les données de Q50 comparent le calendrier à la réalité : ouverture retardée, arrêt anticipé du
flux, activité inattendue, silence inattendu. Ces divergences alimentent
`CalendarObservationMismatch` et, au-delà d'un seuil préenregistré, une proposition de révision.
**La publication reste soumise à validation explicite** — sinon une panne répétée serait
progressivement reclassée en fermeture normale.

## 12. Règles critiques et mode provisoire

Critiques parce qu'elles modifient fortement la censure ou les coûts : fermeture quotidienne,
jour férié, maintenance, portage multiplié, heure de rollover, fuseau serveur. Elles exigent
source normative, preuve conservée, validation humaine, date de prochaine revue.

Sans source normative : `PROVISIONAL`. Le calendrier fonctionne, le rapport l'affiche, et les
intervalles concernés **ne produisent aucun verdict final irréversible**.

---

# Partie B — Implémentation

## Les trois échecs bloquants

Ils ne sont pas des garde-fous défensifs : chacun correspond à un cas où `calendar.py`
appliquerait **parfaitement un horaire faux**.

**1 — Assertion critique sans preuve.** Source absente du jeu d'instantanés, source non
normative, ou assertion non revue. Trois tests vérifient les trois refus séparément. Une
assertion *non* critique tolère une source secondaire, mais le calendrier devient provisoire.

**2 — Conflit normatif ouvert.** Deux sources normatives de **même spécificité** qui se
contredisent bloquent la compilation. Si les spécificités diffèrent, le conflit est enregistré
et informatif : la fiche de symbole du compte l'emporte sur la page générique du courtier.

**3 — Fuseau ou période d'effet ambigu.** `AMBIGUOUS` sur le fuseau, `UNKNOWN` sur la date
d'effet, ou période d'effet incohérente. Le premier cas est le plus insidieux : « GMT+2 »
interprété comme décalage fixe décale toutes les sessions d'une heure la moitié de l'année,
sans qu'aucun test temporel ne le signale.

## Ce que l'implémentation a précisé

**La spécificité de portée est comptée, pas jugée.** Un champ nul est un joker — la règle ne se
prononce pas sur cette dimension ; un champ renseigné doit correspondre exactement. La
spécificité est le nombre de dimensions contraintes, et l'arbitrage
`spécificité → autorité → récence` en découle mécaniquement. Un test vérifie explicitement
qu'une assertion **ancienne et spécifique** l'emporte sur une **récente et générale**.

**Le changement de présentation se distingue par l'empreinte sémantique.** Chaque assertion
porte une empreinte calculée sur son **contenu** — portée, type, fuseau, horaires, jours, période
d'effet — à l'exclusion des métadonnées de présentation. Comparer les seules empreintes de
contenu de la source créerait une règle nouvelle à chaque refonte de page.

**Le manifest est reproductible parce qu'il hache le contenu.** L'empreinte porte sur les
empreintes sémantiques des assertions et les empreintes de contenu des sources, triées, plus la
version du compilateur — pas sur les identifiants seuls. Deux compilations produisent le même
`calendar_id`.

**L'impact historique est mesuré par échantillonnage d'états, pas par comparaison de règles.**
Deux jeux de règles différents peuvent produire le même comportement sur les intervalles
publiés. La comparaison porte donc sur `state_at` aux instants effectivement couverts par les
rapports.

**Le statut du contenu pilote le mode provisoire du moteur.** `CONFLICTING` > `PROVISIONAL` >
`STALE` > `VERIFIED`, et tout ce qui n'est pas `VERIFIED` met `calendar.provisional = True` —
donc `UNKNOWN_GAP` sur toutes les lacunes et aucun verdict définitif. Le lien entre Q53 et Q52
est ainsi mécanique plutôt que déclaratif.

## Dossier de preuve

`calendar-sources/` est en place avec son arborescence, son gabarit de métadonnées et l'ordre
de collecte recommandé. Il est **vide de contenu réel** : c'est précisément ce que Q53 rend
possible de collecter sans risque de confusion entre officiel et inféré.

## Ce que ce module ne fait pas

- il n'acquiert rien : la collecte est manuelle ou déléguée à un collecteur externe ;
- il ne juge pas la véracité d'une source, seulement son **autorité déclarée dans son domaine**
  et la conservation de sa preuve ;
- il ne publie jamais de nouvelle version normative automatiquement — un job de rafraîchissement
  ne peut créer qu'une demande de revue.

---

## Questions ouvertes précisées

**Q54 — seuil de temps inconnu.** Q53 permet désormais de distinguer deux causes :
`UNKNOWN_CALENDAR_RULE` (aucune règle applicable) et `UNKNOWN_SOURCE_AUTHORITY` (règle
existante mais non normative). Le seuil devra être défini **par cellule** : une minute inconnue
au milieu d'une entrée est plus grave qu'une heure inconnue pendant une période non analysée.

**À ne pas fixer avant d'avoir vu la géométrie réelle des inconnues sur le premier export Q50.**
Un seuil global posé à l'avance produirait une règle inadaptée.

**Q55 — horloge des labels.** Quatre valeurs à déclarer par famille : `WALL_CLOCK`,
`MARKET_TIME_DETECTION`, `MARKET_TIME_EXECUTION`, `JOINT_MARKET_TIME`. Q53 garantit que les
calendriers nécessaires seront identifiables et sourcés.

**Q56 — gouvernance.** Rôles à définir : collecteur, réviseur, approbateur, auteur d'override,
auditeur. Une même personne peut les cumuler dans la première version, **mais cette
concentration doit être affichée** — le moteur enregistre l'approbateur, il ne peut pas vérifier
son indépendance.
