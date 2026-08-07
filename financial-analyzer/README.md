# financial-analyzer

Système de décision financière sur XAU/USD — spécification et outils de validation.

Le projet est actuellement en **phase de réduction d'espace**, pas de construction de signal.
Avant de chercher un avantage, il détermine où un avantage peut encore exister après coûts,
latence et rareté des occurrences.

## Contenu

| Dossier | Rôle |
| --- | --- |
| `docs/` | spécification, journal de décisions (`DECISIONS.md`), registre des questions (`QUESTIONS.md`) |
| `feasibility/` | **code exécutable** : les deux phases 0 et leur intersection |
| `tests/` | 331 tests, un par garde-fou |
| `calendar-sources/` | dossier de preuve : sources normatives du calendrier |
| `connector-capability/` | fiches Q57/Q58 : ce que les horloges et le connecteur permettent d'affirmer |

## Exécuter

```bash
cd financial-analyzer
python3 -m pytest tests/ -q          # 331 tests
python3 -m feasibility.report        # carte de faisabilité (données synthétiques)
python3 -m feasibility.passive_demo  # campagne passive Q51-A de bout en bout
```

Dépendances : `numpy`, `pytest`.

## Le moteur de calendrier

`feasibility/calendar.py` est un **moteur temporel**, pas une liste d'horaires. Il répond, pour
tout intervalle sans cotation, à *ce qui était censé s'y passer* — et justifie sa réponse par une
version, une source et un statut de vérification.

Principe fondateur : **l'absence de ticks est une observation ; la fermeture est une information
externe versionnée.** Le moteur ne déduit jamais l'une de l'autre, et ne s'auto-modifie jamais à
partir des données observées.

Un calendrier par source et par marché d'exécution. Une lacune est segmentée exactement, puis
classée par l'intégralité de son contenu — jamais par ses extrémités.

`feasibility/calendar_sources.py` complète le moteur par sa **chaîne de preuve** : le calendrier
ne contient jamais une règle nue mais une affirmation documentée, et le compilateur refuse de
produire un calendrier lorsqu'une assertion critique n'a pas de preuve, qu'un conflit normatif
reste ouvert, ou qu'un fuseau ou une date d'effet est ambigu.

```
source → instantané → assertion → revue → manifest → compilation → calendrier → rapport
```

## La journalisation de latence

`feasibility/latency_journal.py` mesure **exactement ce qui est observable** et déclare ce qui
ne l'est pas. Un accusé de réception local ne sépare pas file locale, réseau, traitement courtier
et rappel : l'intervalle porte donc son statut d'agrégat et la liste des composantes qu'il ne
distingue pas — contrainte de type, pas commentaire.

La borne inférieure observable ignore l'inconnu, ce qui la rend asymétrique :

```
borne déjà trop lente     → exclusion concluante, sans campagne d'exécution
borne assez rapide        → seulement « non exclu à la couche messagerie »
```

## Le contrat d'observabilité

`feasibility/observability.py` répond à une question antérieure à toute mesure : **que peut-on
revendiquer ?** Q57 qualifie les horloges, Q58 la sémantique du connecteur, et leur croisement
produit la seule décomposition que Q19 est autorisé à utiliser.

Le point structurant est que **la borne se calcule entre des frontières, jamais en additionnant
des intervalles.** Deux intervalles nommés peuvent se recouvrir — l'aller-retour d'émission
contient déjà le traitement courtier — et les sommer produit une « borne inférieure » supérieure
à la durée réellement vécue :

```
14 ms d'aller-retour + 9 ms de traitement courtier situé dedans = 23 ms
                                        sur un chemin de 20 ms
```

`LatencyPath` décrit le chemin par ses frontières : deux segments consécutifs en partagent une,
donc ne se recouvrent jamais. Le double comptage devient impossible par construction plutôt
qu'interdit par convention.

Deux vues coexistent sans se confondre : le **chemin critique** — durée vécue, utilisée par le
verdict — et l'**attribution** par composante, avec ses trous, utilisée pour le diagnostic.

Les fiches de `connector-capability/` sont livrées **vides**, tout déclaré inconnu. C'est
volontaire, et un test le vérifie : une fiche déclarant tout inconnu produit des bornes
honnêtes, là où une supposition produirait des verdicts faux.

## La campagne passive — ce qui démarre maintenant

`feasibility/passive_recorder.py` fournit les cinq points à brancher dans la boucle réelle :

```
on_quote_received → on_event_eligible → on_evaluation_start
                  → on_evaluation_end → on_decision_ready
```

**Aucun ordre, aucun risque financier, aucun moteur prédictif.** La campagne mesure ce qui
sépare l'arrivée d'une cotation de la décision — et déclare vide tout le reste.

Elle produit une seule grandeur décisionnelle, `L^LB_p95 | rafale, cellule`. Ce n'est pas un
nombre mais une **surface de latence**, à intersecter avec la surface de coûts de Q40 :

```
CostSurface  ∩  PassiveLatencySurface   →  où il vaut encore la peine de chercher
```

Trois refus structurels valent d'être connus avant de brancher :

- une évaluation qui ne conclut jamais est comptée comme **abandonnée**, jamais complétée —
  la laisser en attente la sortirait du dénominateur, et la latence moyenne s'améliorerait à
  mesure que le système échoue ;
- la politique d'arrêt est **préenregistrée** : le module refuse une politique déclarée après
  la première observation, parce qu'une politique écrite après le résultat est le résultat
  reformulé ;
- une grappe est attribuée à **chaque** observation, y compris hors rafale — deux cotations
  calmes séparées de 50 ms ne sont pas indépendantes non plus.

C'est le premier moment du projet où laisser tourner le système une journée produit plus de
valeur que lui ajouter mille lignes de code.

## Ce que produit `feasibility`

```
D_feasible = D_cost  ∩  D_latency  ∩  D_frequency
```

Trois calculs indépendants de tout motif, de toute étiquette et de tout modèle prédictif — ce qui
leur permet de **conclure négativement avant qu'un seul signal ne soit défini**.

- **coût** — `κ(h) = C_total / σ(h)`, nombre d'unités d'amplitude à capturer pour seulement
  couvrir les frais, avec intervalle par rééchantillonnage par blocs ;
- **latence** — part du mouvement déjà survenue au moment où l'on pourrait agir, donc borne
  supérieure de ce que *n'importe quel* signal pourrait capturer ;
- **fréquence** — planchers économique et statistique, dont le maximum s'impose.

`ELIGIBLE_FOR_PREDICTIVE_TESTING` ne signifie **jamais** rentable : seulement qu'aucun des trois
arguments d'exclusion ne s'applique.

## Principes appliqués dans le code

Le paquet applique les décisions du journal plutôt que de les rappeler :

- aucun seuil par défaut — bande d'avantages plausibles, planchers de fréquence et quantiles sont
  **exigés en entrée**, pour ne pas pouvoir être choisis après lecture des résultats ;
- les deux méthodes de coût ne peuvent pas être mélangées : la combinaison invalide lève une
  erreur avant tout calcul ;
- coût et amplitude sont rééchantillonnés sur les **mêmes blocs** — ils partagent la séance ;
- l'exclusion s'appuie sur la borne de confiance défavorable, jamais sur l'estimation ponctuelle ;
- une dimension indéterminée n'accorde jamais l'éligibilité : l'ignorance ne vaut pas permission.

## Limites

Le générateur de `feasibility/synthetic.py` sert aux tests et à la démonstration. **Aucun chiffre
qu'il produit ne décrit un marché réel** : une exécution sur ces données renseigne sur le
générateur, pas sur l'or.

Sélection adverse et impact ne sont pas estimables sans campagne d'exécution réelle ; les
fonctions existent et retournent `nan` en son absence.

## Statut

Code de recherche, exécuté hors ligne sur données historiques. Il ne préjuge pas de la pile
technique du système de production, question restée ouverte (`QUESTIONS.md`, Q1).
