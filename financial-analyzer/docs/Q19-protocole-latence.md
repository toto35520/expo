# Q19 — Protocole opérationnel de mesure de latence et gate microstructure

> Statut : **exécutable**. Ce document n'est pas une spécification de moteur : c'est un protocole
> de mesure destiné à être conduit avant toute autre implémentation.
> Rend le verdict du gate fondateur de la famille microstructure (`03a` à `03f`).

## 1. Ce que Q19 demande réellement

La question n'est pas « quelle est la latence du code ». C'est :

> **Combien de temps s'écoule entre le moment où l'information existe sur le marché et le moment
> où une position est effectivement engagée à un prix connu — et que reste-t-il du signal à cet
> instant ?**

Deux conséquences immédiates.

**On ne peut pas répondre entièrement sans envoyer d'ordres.** La chaîne contient la file du
broker et l'exécution ; aucune mesure de temps de calcul ne les approche. Toute estimation
purement logicielle est un plancher, pas une réponse.

**La réponse n'est pas un nombre mais une distribution conditionnelle.** La latence se dégrade
précisément dans les états où les signaux de microstructure se déclenchent — rafales
d'événements, publications, ouvertures. Une latence médiane mesurée en séance calme est sans
rapport avec la latence subie au moment utile.

## 2. Décomposition complète

La décomposition proposée à l'addendum est reprise, **augmentée de deux termes manquants qui
peuvent dominer tous les autres** :

| Segment | Mesurable passivement | Commentaire |
| --- | --- | --- |
| **`L_dissémination`** — événement au moteur d'appariement → publication sur le flux | oui, indirectement | **terme manquant n°1.** Sur un flux agrégé, consolidé ou différé, il peut valoir plusieurs secondes et écraser tout le reste |
| `L_transport` — publication → réception locale | oui | dépend de l'hébergement |
| `L_normalisation` — décodage, arbitrage de lignes, contrôle qualité | oui | |
| `L_feature` — calcul des features | oui | |
| `L_modèle` — évaluation | oui | |
| **`L_cadence`** — attente du prochain cycle d'évaluation | oui | **terme manquant n°2.** Un système évaluant toutes les 100 ms ajoute en moyenne 50 ms et au pire 100 ms, systématiquement oubliés |
| `L_décision` → `L_ordre` — construction et émission | oui | |
| `L_broker` + `L_file` — traitement et mise en file | **non** | exige des ordres réels |
| `L_exécution` — appariement effectif et confirmation | **non** | exige des ordres réels |

`L_dissémination` se mesure par l'écart entre l'horodatage du moteur d'appariement et l'instant de
réception locale, avec la discipline d'horloge de l'ADR-008 : on ne soustrait pas deux horloges
sans avoir estimé leur décalage, et l'estimation elle-même est une mesure à part.

## 3. Phase 0 — le test décisif, sans modèle ni étiquette

**À exécuter en premier. Coût : quelques heures de calcul. Peut clore la question.**

L'idée : borner par le haut ce que **n'importe quel** signal pourrait capturer, sans connaître ce
signal.

### 3.1 Principe

Pour la classe d'événements que vise la famille microstructure — déplacements rapides —, on
mesure quelle part du mouvement total est **déjà survenue** au moment où l'on aurait pu agir.

```
t₀   première trace observable de l'événement dans les données brutes
t₀+L instant d'exécution possible, L tiré de la distribution de latence
```

Le mouvement résiduel `P(t₀+L+h) − P(t₀+L)` est une **borne supérieure** de ce que tout signal
détectant cet événement peut réaliser. On ne peut pas capturer ce qui a déjà eu lieu.

### 3.2 Ce que cela exige

Rien d'autre que des données de prix horodatées et une estimation de `L`. **Aucune définition de
signal, aucune étiquette, aucun modèle, aucun appariement.** C'est le seul test du protocole qui
échappe aux réserves de l'addendum sur les signaux grossiers.

### 3.3 Procédure

1. définir la classe d'événements par le prix seul — par exemple le centile supérieur des
   déplacements absolus sur une fenêtre courte, sans référence au carnet ;
2. pour chaque événement, reconstruire le chemin de prix depuis `t₀` ;
3. calculer la part du déplacement total réalisée avant `t₀+L`, **en intégrant sur la
   distribution de latence mesurée en phase 1 et 2**, pas à une valeur unique ;
4. calculer le déplacement résiduel net des coûts complets `C_total` ;
5. répéter par tranche de session et par régime de volatilité.

### 3.4 Lecture

| Résultat | Conclusion |
| --- | --- |
| Résiduel net **négatif** sur toute la plage de latence plausible | **conclusif** : aucun signal de cette famille n'est exploitable pour déclencher une entrée sur cette infrastructure. Verdict `LATENCY_NON_VIABLE` sans autre test |
| Résiduel net positif | non conclusif — la borne est atteignable, reste à savoir si un signal l'atteint. Poursuivre |
| Résiduel positif dans certains régimes seulement | `LATENCY_REGIME_DEPENDENT` — la suite du protocole est restreinte à ces régimes |

C'est l'unique test capable de rendre un verdict **négatif conclusif** avant toute construction de
signal. Il est aussi le moins coûteux du projet.

## 4. Phase 1 — mesure passive des segments observables

Instrumenter la chaîne de bout en bout côté système, sans envoyer d'ordre.

À enregistrer pour chaque événement traité : les quatre horloges de `02b` §3, l'instant de fin de
calcul des features, l'instant de décision, l'instant d'émission simulée, et le **compteur de
cycle** permettant de reconstituer `L_cadence`.

**Règles de mesure**, reprises des invariants existants :

- durées sur **horloge monotone locale** (ADR-020), jamais par soustraction d'horloges murales ;
- résolution native conservée, aucune troncature ;
- chaque échantillon de latence porte l'**état de marché concomitant** : débit d'événements
  instantané, régime de volatilité, tranche de session, fenêtre de publication, phase de rollover.

Ce dernier point n'est pas décoratif — il conditionne toute la phase 4.

## 5. Phase 2 — mesure de la boucle d'ordre, en conditions réelles

### 5.1 Le compte de démonstration n'est pas un substitut valide

Il faut le dire nettement : les environnements de démonstration acheminent souvent les ordres par
une infrastructure distincte, exécutent au prix affiché sans file d'attente réelle, ne produisent
ni rejet, ni recotation, ni exécution partielle, et n'exposent à aucune sélection adverse. Une
latence mesurée en démonstration **ne mesure pas la latence de production** et peut en différer
d'un ordre de grandeur.

Mesurer sur l'infrastructure réelle est le seul moyen honnête. Le coût en est modeste si l'on
procède en deux temps.

### 5.2 Deux niveaux de mesure, du moins coûteux au plus coûteux

**Niveau A — aller-retour sans exécution.** Ordres à cours limité placés **loin du marché**, donc
sans aucune chance d'exécution, puis annulés immédiatement. On mesure sur horloge locale :
émission → accusé de réception, puis annulation → confirmation.

Cela couvre `L_ordre + L_broker + L_file` sur l'infrastructure de production, pour un coût
essentiellement nul.

> **Précaution** : respecter les limites de débit et les conditions du courtier concernant le
> rapport ordres/annulations. Ce test se conduit à cadence modérée, et il vaut mieux l'annoncer
> au courtier que de le découvrir par une restriction de compte.

**Niveau B — exécution réelle à taille minimale.** Un nombre restreint d'ordres au marché, à la
plus petite taille négociable, pour mesurer `L_exécution`, le glissement effectif et le taux de
rejet ou de recotation.

C'est le seul segment qui coûte réellement de l'argent, et il est irremplaçable : le glissement
est un terme de `C_total`, donc une entrée directe de `δ_MEU`.

### 5.3 Combien d'échantillons

La grandeur d'intérêt est un centile élevé d'une distribution à queue épaisse. Une moyenne se
stabilise vite ; un centile à 95 % ou 99 % demande nettement plus, et surtout **des échantillons
dans chaque état de marché** — un millier d'aller-retours en séance calme n'apprend rien sur la
latence en rafale.

Le dimensionnement se fait sur l'intervalle de confiance visé pour le centile retenu, calculé
avant de commencer, et par bucket d'état de marché. Un bucket sous-échantillonné est déclaré tel
plutôt que moyenné avec les autres.

## 6. La latence se mesure là où le signal se déclenche

C'est la correction la plus importante de ce protocole.

Les signaux de microstructure se déclenchent lors de rafales d'événements. Or c'est exactement
alors que la file de décodage s'allonge, que le courtier est le plus sollicité et que les
recotations apparaissent. **La distribution marginale de la latence sous-estime donc
systématiquement la latence effectivement subie au moment utile.**

**Règle** : la grandeur qui entre dans le gate n'est pas `L_p95` sur l'ensemble des échantillons,
mais `L_p95 | rafale` — le centile calculé sur les échantillons dont l'état de marché concomitant
correspond à celui où le signal se déclencherait.

Le rapport de mesure publie la latence par bucket, et l'écart entre marginal et conditionnel est
lui-même un résultat : s'il est important, il indique une infrastructure qui se dégrade
précisément quand elle est sollicitée — information exploitable indépendamment du gate.

## 7. Remplacer la demi-vie par la fenêtre d'horizon rentable

### 7.1 Pourquoi la demi-vie ne suffit pas

`R(L) = 2^{−L/T½}` suppose une décroissance exponentielle depuis un maximum situé à l'instant du
signal. Deux hypothèses fragiles :

- la décroissance n'est pas nécessairement exponentielle ;
- **le maximum n'est pas nécessairement à l'origine.** Pour beaucoup de signaux, l'avantage
  *croît* d'abord — le mouvement doit se développer — avant de décroître. La formule donnerait
  alors `R(L) > 1`, ce qui la rend inapplicable.

### 7.2 Grandeur retenue

Pour un signal donné, une latence `L` et une durée de détention `h` :

```
edge(L, h) = E[ rendement net | signal à t, entrée à t+L, sortie à t+L+h ] − C_total
```

Le résultat publié est la **fenêtre d'horizon rentable** :

```
W = { h : edge(L, h) > 0 }
```

Trois formes possibles, toutes informatives :

| Forme de `W` | Lecture |
| --- | --- |
| vide | le signal n'est pas exploitable à cette latence |
| `[h_min, h_max]` avec `h_min > 0` | il faut **attendre** après l'entrée : le mouvement se développe. Information opérationnelle directe |
| `[0, h_max]` | exploitable immédiatement, décroissance classique |

### 7.3 Intégration sur la latence

`L` n'est pas déterministe. L'avantage réalisé est donc l'espérance sur la distribution de
latence conditionnelle mesurée en §6 :

```
edge_réalisé(h) = E_L[ edge(L, h) ]
```

Évaluer à `L_p50` surestime ; évaluer à `L_p99` sous-estime. **L'intégration sur la distribution
est la seule mesure correcte**, et elle change le résultat dès que la queue est épaisse — ce qui
est le cas ici.

### 7.4 Le coût de latence est asymétrique selon le type d'ordre

À ne pas confondre dans la mesure :

- **ordre au marché** : la latence se paie en **glissement**, terme certain qui entre dans
  `C_total` ;
- **ordre à cours limité** : la latence se paie en **non-exécution**, donc en occasion manquée.
  C'est une **observation censurée** au sens de l'addendum §5, et non une perte.

Les deux régimes doivent être mesurés séparément et rapportés séparément. Un signal peut être non
viable au marché et viable à cours limité, ou l'inverse.

## 8. Verdict du gate

Rendu selon la grille de l'addendum, avec les conditions d'application propres à ce gate :

| Verdict | Condition |
| --- | --- |
| `LATENCY_NON_VIABLE` | phase 0 conclusive, **ou** test d'équivalence montrant `edge_réalisé` sous `δ_MEU` sur un signal dont la qualité n'est pas en cause |
| `LATENCY_VIABLE` | `edge_réalisé` dépasse `δ_MEU` **et** la fréquence dépasse `f_min` |
| `LATENCY_REGIME_DEPENDENT` | viable sur des régimes préspécifiés uniquement |
| `LATENCY_INDETERMINATE` | résultat négatif obtenu sur signal grossier hors phase 0, ou latence trop incertaine, ou puissance insuffisante |
| `PROTOCOL_INVALID` | mesure de latence non conditionnelle, horloges non disciplinées, ou mesure conduite en démonstration |

**Asymétrie rappelée** : un résultat positif sur signal grossier est conclusif — un raffinement ne
peut qu'améliorer. Un résultat négatif sur signal grossier ne l'est pas, **sauf** s'il vient de la
phase 0, qui ne dépend d'aucune définition de signal.

## 9. Ce que chaque verdict autorise

| Verdict | Conséquence sur `03a`–`03f` |
| --- | --- |
| `LATENCY_VIABLE` | `rôle_autorisé` peut passer de `VETO` à `CALAGE` ou `DÉCLENCHEUR` selon la fenêtre `W` (ADR-030) |
| `LATENCY_REGIME_DEPENDENT` | rôle élargi **uniquement** dans les régimes identifiés, veto ailleurs |
| `LATENCY_NON_VIABLE` | `production_weight = 0` pour le déclenchement. Les moteurs **restent utiles** : veto, calage d'exécution, contexte, explication, analyse a posteriori. La spécification n'est pas supprimée |
| `LATENCY_INDETERMINATE` | `rôle_autorisé = VETO` maintenu, `research_status = UNRESOLVED` |

Dans tous les cas, la réponse à un verdict négatif n'est pas nécessairement l'abandon. Elle peut
être : rapprocher le calcul du marché, réduire la cadence d'évaluation, changer d'hébergement,
viser un horizon plus lent, agréger le signal, ou le reclasser en variable de contexte. **Ces
options se comparent par leur coût, une fois la latence connue** — ce qui est précisément l'objet
de ce protocole.

## 10. Instrumentation requise

```
LatencySample {
  sample_id, phase                    0 | 1 | 2A | 2B
  segment                             dissémination | transport | normalisation | feature
                                      | modèle | cadence | ordre | broker | file | exécution
  t_début, t_fin                      horloge monotone locale (ADR-020)
  durée_ns
  état_marché {                       conditionnement obligatoire (§6)
    débit_événements, régime_volatilité, tranche_session,
    fenêtre_publication, phase_rollover, qualité_données
  }
  type_ordre                          n/a | limite_lointaine | marché_taille_min
  résultat_ordre                      accusé | annulé | exécuté | rejeté | recoté | non_exécuté
  glissement                          phase 2B uniquement
  version_infrastructure, version_horloge, décalage_horloge_estimé
}
```

Deux exigences : les échantillons sont conservés bruts et non agrégés — un centile ne se
recalcule pas depuis une moyenne — et chaque campagne porte une version d'infrastructure, toute
modification d'hébergement ou de courtier invalidant les mesures antérieures.

## 11. Séquencement et coût

| Phase | Prérequis | Coût | Peut conclure ? |
| --- | --- | --- | --- |
| **0** — borne supérieure sur données de prix | historique de ticks | calcul seul | **oui, négativement** |
| **1** — segments passifs | flux en direct, instrumentation | développement | non |
| **2A** — aller-retour sans exécution | compte réel, accord de débit | quasi nul | non |
| **2B** — exécution à taille minimale | compte réel financé | quelques dizaines d'euros de frais et de glissement | non |
| **3** — fenêtre rentable | phases 0 à 2 + signaux grossiers | calcul | oui, positivement |

**La phase 0 se fait immédiatement et sans dépendance.** Les phases 2A et 2B ne dépendent que
d'un compte réel, pas de Q1 ni de Q36 — elles peuvent donc être conduites **en parallèle** de la
résolution des autres questions bloquantes. Seule la phase 3 requiert `δ_MEU`, donc Q36.

## 12. Ce que ce protocole ne résout pas

- il mesure la latence de l'infrastructure **actuelle** ; un changement d'hébergement ou de
  courtier impose une nouvelle campagne ;
- il ne dit rien de la qualité des signaux, seulement de leur exploitabilité temporelle ;
- la phase 2B mesure le glissement à taille minimale ; le glissement à taille réelle est
  supérieur et devra être réestimé lorsque le dimensionnement sera défini (étage 8) ;
- il suppose connu `C_total`, donc `δ_MEU`, donc Q36 — sauf pour la phase 0, qui peut être
  conduite avec une plage de coûts plutôt qu'une valeur.

## 13. Décisions à prendre pour lancer le protocole

1. accepter le principe d'une campagne de mesure **sur compte réel** (phases 2A et 2B) et son
   budget ;
2. fixer la cadence d'évaluation cible du système, qui détermine `L_cadence` ;
3. fixer les buckets d'état de marché servant au conditionnement de §6 ;
4. fixer le centile de latence retenu pour le gate — `p95` par défaut ;
5. accepter que la phase 0 puisse, seule, clore la question par la négative.
