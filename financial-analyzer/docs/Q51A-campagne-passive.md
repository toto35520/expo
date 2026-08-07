# Q51-A / Q57 — Campagne passive de qualification réelle

> Statut : **collecteur implémenté et exécutable**, collecte à démarrer.
> Code : `feasibility/passive_campaign.py`, `feasibility/passive_recorder.py`,
> 73 tests dédiés. Démonstration : `python3 -m feasibility.passive_demo`.
>
> Première collecte réelle et **irréversible** du projet. Aucun ordre n'est émis.

---

## Objet

Répondre à une question qui ne dépend d'aucun signal, d'aucun modèle et d'aucun courtier :

> Même en ignorant toute la partie courtier encore inconnue, notre système est-il déjà
> trop lent pour certains horizons ?

La grandeur décisionnelle est

```
L^LB_p95 | rafale, cellule
```

où la cellule combine source, session, état de rafale, cadence d'évaluation, hôte et
version logicielle. **Ce n'est pas un nombre : c'est une surface de latence**, exactement
comme Q40 produit une surface de coûts.

---

## 1. Ce que la campagne mesure, et ce qu'elle laisse vide

| Mesuré | Explicitement absent |
| --- | --- |
| provider → réception locale *(si Q57 qualifie)* | émission → accusé |
| attente d'éligibilité, attente d'évaluation | traitement courtier, réseau |
| temps de calcul, temps de décision | ordre actif, file courtier |
| charge hôte, retard de boucle, profondeur de file | exécution, glissement |
| densité de ticks, rafale, spread, connexion, horloges | sélection adverse |

Le rapport quotidien **nomme la colonne de droite** à chaque édition. Un rapport qui la
tairait se lirait comme une latence complète.

## 2. Le chemin passif

```
B0 provider_event   ──┐ NOT_RESOLVABLE_INTERSYSTEM tant que Q57 ne qualifie pas
B1 local_receive    ──┤
B2 event_eligible     │  mesurables localement,
B3 evaluation_start   │  quelle que soit la qualité
B4 evaluation_end     │  de la synchronisation
B5 decision_ready   ──┘
```

La borne locale est **`B5 − B1`** : une différence de frontières, jamais une somme
d'intervalles (ADR-168, ADR-171). Le module vérifie l'identité entre cette différence et la
somme des quatre composantes — si elles divergeaient, ce serait le signe d'un recouvrement.

Une frontière absente n'est jamais remplacée par la précédente. Sans ce refus, la borne
retomberait silencieusement sur `B4 − B1` : une valeur plausible, qui mesure un chemin plus
court sans le dire.

## 3. Pourquoi le conditionnement n'est pas optionnel

Les signaux microstructurels apparaissent quand les ticks accélèrent, quand le carnet
change vite, quand la file reçoit davantage et quand la boucle d'événements est la plus
sollicitée. Donc

```
P(L | rafale) ≠ P(L)     et      Q₀.₉₅(L | rafale) > Q₀.₉₅(L)
```

Le p95 global ne peut jamais remplacer le p95 conditionnel pour Q19. Un test le vérifie
directement : sur un échantillon mixte, le p95 de la cellule rafale dépasse le p95 groupé,
qui dépasse lui-même celui de la cellule normale.

L'intensité reste **continue** dans chaque observation — cadence, vélocité, centile de
spread, centile de rafale. Les catégories `NORMAL / ELEVATED / BURST_P95 / BURST_P99` ne
servent qu'à présenter les résultats, jamais à les produire.

## 4. Les grappes — la correction la plus lourde de conséquence

Cent ticks d'une même rafale ne sont pas cent observations indépendantes. Le spécification
le dit pour les rafales ; le module l'applique **aussi au régime calme**.

> Deux cotations calmes séparées de 50 ms ne sont pas indépendantes non plus.

Ne regrouper que les rafales laisserait le régime normal se compter observation par
observation et gonflerait la précision apparente exactement là où le rapport est le plus lu.
`ClusterAssigner` attribue donc une grappe à **chaque** observation : identifiant de rafale
pendant les rafales, bloc temporel pendant le reste.

Une rafale ne se termine qu'après un retour sous le seuil **maintenu** pendant une période
de reset — sinon une oscillation autour du seuil fabriquerait des grappes artificielles.

Les intervalles de confiance rééchantillonnent les **grappes**, jamais les observations.

## 5. Trois piles, une seule décisionnelle

`PIPELINE_MINIMAL`, `PIPELINE_TARGET`, `PIPELINE_STRESS`. Exécuter tous les moteurs futurs
pour mesurer une latence maximale fictive produirait un chiffre défavorable qui ne décrit
aucune architecture réelle. Le verdict **refuse** un échantillon `STRESS` : il retourne
`PASSIVE_MEASUREMENT_INVALID`, pas un chiffre pessimiste (ADR-174).

## 6. La politique d'arrêt est préenregistrée, et le module le vérifie

> Une politique écrite après avoir vu le résultat n'est pas une politique : c'est le
> résultat lui-même, reformulé.

`StoppingPolicy` porte son auteur, son empreinte et sa date de déclaration.
`assess_stopping()` retourne `POLICY_INVALID` si la déclaration est postérieure à la
première observation, ou si la campagne ne tourne pas sur la qualification d'horloge que la
politique supposait.

Elle ne regarde **jamais** la valeur mesurée — seulement couverture, grappes, largeur
d'intervalle et qualité d'horloge (ADR-176).

### Le piège résiduel

Arrêter dès que l'intervalle devient étroit reste une règle d'arrêt dépendante des données :
les échantillons homogènes produisent des intervalles étroits plus souvent, donc l'intervalle
final **sous-estime** l'incertitude réelle. Le module ne l'interdit pas — il le **signale** :
`confidence_interval_is_optimistic` est vrai lorsque seule la largeur a déclenché l'arrêt.

## 7. Stabilité séquentielle

Après chaque journée, le p95 cumulé et son intervalle sont recalculés. Le tracé sert à voir
**si** l'estimation se stabilise ; il ne sert pas à choisir le moment d'arrêt, qui appartient
à la politique.

Aucun seuil arbitraire n'est fixé aujourd'hui — ni « dix jours », ni « cinq cents rafales ».
La suffisance dépendra de la variance mesurée, de la stabilité des quantiles, du nombre de
grappes et de la largeur des intervalles (ADR-175).

## 8. L'ancrage de la capturabilité — correction apportée au protocole

La phase 0 de Q19 mesure quelle fraction du mouvement est déjà consommée à `t₀ + L`. Le
choix de `t₀` change le sens du résultat, et le §21 ne le fixait pas.

Avec `t₀ = réception locale`, le mouvement survenu **avant** la réception est invisible :
il n'entre pas dans l'échantillon de déplacement, donc il n'est jamais compté comme perdu.
La fraction capturable en ressort **surestimée**.

```
ancrage LOCAL_RECEIVE      → borne SUPÉRIEURE de la capturabilité
ancrage QUALIFIED_MARKET   → estimation, seulement si Q57 qualifie B0 → B1
```

La conséquence suit l'asymétrie habituelle du projet : **une exclusion reste concluante**
— on n'exclut pas moins en surestimant — mais une non-exclusion obtenue sous ancrage local
est plus faible encore que d'ordinaire. `CapturabilityInput` porte son ancrage et le
signale.

## 9. Verdicts et embranchement

| Verdict | Signification |
| --- | --- |
| `PASSIVE_LATENCY_EXCLUDED` | la borne inférieure exclut déjà, courtier supposé instantané, aucune file, exécution immédiate — **négatif fort** |
| `PASSIVE_LATENCY_NOT_EXCLUDED` | compatible ; ne démontre rien sur messagerie, ordre actif, fill, glissement |
| `PASSIVE_LATENCY_INDETERMINATE` | données insuffisantes ou instables |
| `PASSIVE_MEASUREMENT_INVALID` | instrument, pile STRESS ou horloge défaillants — aucun verdict |

L'exclusion s'appuie sur la borne de confiance **basse** : si même l'estimation la plus
favorable de la borne inférieure dépasse l'admissible, la conclusion tient.

```
coût exclu                            → Q42 non prioritaire (le coût a déjà tranché)
coût non exclu + latence exclue       → Q42 non prioritaire (l'inconnu ne peut qu'aggraver)
coût non exclu + latence non exclue   → Q42 rationnelle
```

## 10. Le budget de latence

```
B_L(c, h) = L_max_admissible(c, h) − L^LB_passive(c)
```

C'est ce que Q42 devra faire tenir dans le segment encore inconnu. Une valeur négative
signifie que l'horizon est exclu sans avoir rien mesuré du courtier.

**`L_max_admissible` est déclarée, jamais déduite.** Elle dépend de `edge(L, h, c)`, qui
exige un signal : elle ne peut donc pas être calculée aujourd'hui. La fixer après lecture
de la borne mesurée reviendrait à choisir la conclusion — le même défaut qu'une bande
d'avantages déclarée après avoir vu la courbe. `AdmissibleLatency` exige source et date, et
refuse une valeur supérieure à son propre horizon.

---

# Le collecteur

## 11. Les cinq points à brancher

```python
eid = recorder.on_quote_received(market, provider_event_ns=None)
recorder.on_event_eligible(eid)
recorder.on_evaluation_start(eid)
recorder.on_evaluation_end(eid)
observation = recorder.on_decision_ready(eid, host_load)
```

Les horloges sont injectables : la boucle réelle passe `time.monotonic_ns` et
`time.time_ns`. Toute durée est mesurée sur la monotone ; la murale sert au rattachement et
à l'audit.

## 12. Ce que le collecteur refuse de produire

- une observation dont une frontière manque — comptée `NO_DECISION`, jamais complétée ;
- une observation dont les frontières sont désordonnées — comptée `OUT_OF_ORDER` ;
- une évaluation restée en attente au-delà d'un délai — `abandon_stale()` la compte comme
  abandonnée. **La laisser en attente la ferait sortir du dénominateur, et la latence
  moyenne s'améliorerait à mesure que le système échoue** ;
- une croissance mémoire non bornée — la saturation abandonne la plus ancienne et
  l'enregistre.

## 13. Deux règles d'horloge, une seule absolue

Le **signe** de `ΔW` s'applique sans seuil (ADR-162) : une murale qui recule pendant que la
monotone avance est une discontinuité quelle que soit son amplitude.

Mais ce contrôle ne voit que ce qui se passe **entre deux échantillons**. Un recul d'une
nanoseconde survenu au milieu d'un intervalle de 9 ms se solde par un `ΔW` positif et reste
invisible — il est d'ailleurs indiscernable d'une dérive ordinaire. C'est l'écart
`D = ΔW − ΔM` qui le révèle, et lui seul relève d'un seuil, versionné, puisqu'une correction
en douceur produit légitimement un `D` non nul.

## 14. Persistance et effet observateur

Journal **append-only**, vidé sur disque tous les `flush_every` événements avec `fsync` —
pas seulement à l'arrêt. Ce qui n'est pas vidé au moment d'un incident est perdu, d'où un
tampon volontairement petit. Une seconde exécution **ajoute**, elle ne réécrit jamais.

La sérialisation reste hors du chemin critique : seule la mise en file y entre. Le surcoût
résiduel est **mesuré** et publié.

Un coût mesuré à zéro est signalé plutôt que célébré : une horloge monotone réelle ne peut
pas ne pas avancer entre l'entrée et la sortie d'un appel. Zéro révèle une horloge injectée
ou une résolution insuffisante — pas une instrumentation gratuite.

---

## Ce qui démarre maintenant

Brancher les cinq points sur la boucle réelle et laisser tourner. Aucun ordre, aucun risque
financier, aucun moteur prédictif nécessaire.

C'est le premier moment du projet où **laisser tourner le système une journée produit plus
de valeur que lui ajouter mille lignes de code** — et la seule donnée du registre, avec
Q57, qui ne se reconstruit pas après coup.

L'intersection

```
CostSurface  ∩  PassiveLatencySurface
```

dira pour la première fois où il vaut encore la peine de chercher un signal. Et seulement
dans les cellules survivantes, Q42 devient une dépense rationnelle.
