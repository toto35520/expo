# 03e — Détection d'ordres à quantité cachée

> Statut : **figé** (étape 3.5 de la spécification).
> Cinquième vue de microstructure (étage 4). À lire après `03a` à `03d`.

## 1. Question préalable : inférence ou observation ?

L'étape 3.5 pose le problème comme une **inférence** — « iceberg probable », « confiance
73 % ». C'est la bonne posture *si* le flux ne dit rien. Or cela dépend entièrement de la
classe de données consommée, et la réponse change complètement la nature du moteur.

| Classe de données | Ce que le système voit | Nature de la sortie |
| --- | --- | --- |
| Carnet **agrégé** par niveau | uniquement des tailles qui se reconstituent | **inférence**, probabiliste |
| Carnet **par ordre**, identité préservée à la recharge | l'ordre est identifiable d'une recharge à l'autre | **observation**, quasi déterministe |
| Carnet **par ordre**, nouvelle identité à chaque recharge | signature forte mais indirecte | inférence, mais bien mieux armée |

**Conséquence directe : si le flux permet de suivre l'identité de l'ordre à travers ses
recharges, le champ « confiance » n'a plus lieu d'être** — on ne publie pas 73 % pour un fait
qu'on observe. Publier une probabilité sur quelque chose de directement lisible est une perte
d'information déguisée en prudence.

**Cette vérification est le premier travail de l'étape 3.5**, avant toute écriture de détecteur.
Elle se fait dans la documentation du protocole du marché considéré — jamais de mémoire, comme
posé en `02b` §11. Les sémantiques varient : comportement de la priorité de file après recharge,
conservation ou non de l'identifiant, présence d'indicateurs dédiés.

Le détecteur est donc écrit en deux couches : un **noyau d'observation** utilisé quand la donnée
le permet, et une **couche d'inférence** utilisée sinon. Les deux ne produisent pas le même
type de sortie et ne doivent pas être confondus dans la fusion.

## 2. Si c'est une inférence : la signature est causale, pas statistique

Tes quatre critères décrivent bien le phénomène, mais ils sont **descriptifs**. Ils peuvent
être produits par plusieurs mécanismes différents. Le critère qui sépare réellement est
**causal** :

> **Un ordre à quantité cachée se recharge parce qu'il a été exécuté — jamais pour une autre
> raison.**

C'est une signature testable, et elle discrimine bien :

| Mécanisme observé | Recharge déclenchée par | Comportement distinctif |
| --- | --- | --- |
| **Quantité cachée** | l'exécution, immédiatement | ne bouge pas, ne s'annule pas spontanément |
| Plusieurs participants dans la file | rien — c'est de l'empilement | tailles hétérogènes, délais irréguliers |
| Réapprovisionnement manuel | décision humaine | délai long et variable |
| Algorithme de cotation | son propre horloge, le prix | **annule et se déplace**, y compris sans exécution |

Le dernier cas est le plus utile à écarter : un algorithme de cotation se recharge *aussi*, mais
il annule et se repositionne de sa propre initiative. Une quantité cachée, elle, ne se manifeste
**que** lorsqu'on la frappe.

Grandeurs à extraire : délai entre exécution et recharge, régularité de la taille rechargée,
absence d'annulation spontanée, nombre de cycles exécution-recharge, part du volume total du
niveau attribuable à ce cycle.

## 3. Le problème de la vérité terrain

Point décisif, et il conditionne le format de sortie.

Sans donnée qui révèle l'ordre, **on ne peut jamais vérifier qu'un iceberg était réellement
présent**. Il n'existe pas d'étiquette. Or calibrer une probabilité exige de confronter la
prédiction à la réalité (ADR-037). Une « confiance 73 % » sur la présence d'un iceberg est donc
**structurellement incalibrable** : rien ne permettra jamais de vérifier que 73 % des cas
annoncés à 73 % en contenaient un.

Ce n'est pas un défaut de méthode, c'est une impossibilité.

**Règle générale — applicable bien au-delà de cette étape :**

> Le système ne publie pas de probabilité sur un **état latent invérifiable**. Il publie une
> probabilité sur une **conséquence observable**.

Traduction concrète ici : au lieu de

```
Iceberg acheteur probable — Confiance : 73 %
```

le moteur produit

```
Motif de recharge répétée détecté — score de motif : <échelle nommée>
Probabilité que le niveau tienne à l'horizon h : <calibrée sur les cas historiques>
```

La seconde ligne est vérifiable, donc calibrable, donc utilisable par la fusion. La première ne
l'est pas — elle est conservée comme description, sans pourcentage.

Et si la vérification du §1 montre que le flux révèle l'ordre, la question disparaît : on
observe, on ne parie pas.

## 4. « Contrats exécutés estimés » : séparer le mesurable de l'invention

Ce champ recouvre deux grandeurs de statuts radicalement différents :

| Grandeur | Statut |
| --- | --- |
| Volume **déjà exécuté** à ce niveau depuis la détection | **observé, exact** — à publier |
| Taille **totale** de l'ordre caché | invérifiable |
| Quantité **restant** à exécuter | invérifiable, et la plus tentante |

La troisième est le nombre le plus dangereux du moteur : c'est celle qu'on voudrait connaître —
elle dirait quand le niveau va céder — et c'est précisément celle qu'aucune donnée ne fournit.
La produire reviendrait à fabriquer un chiffre, ce que l'ADR-025 interdit à la couche de données
au même titre que l'ADR-002 l'interdit au modèle de langage.

**Règle** : le champ publié est le **volume exécuté observé**, cumulé depuis la détection.
Aucune extrapolation sur le résiduel caché. Si un jour cette extrapolation est tentée, elle
constitue un modèle à part entière, avec sa propre calibration et sa propre incertitude — pas
un champ d'affichage.

## 5. Le signal le plus utile n'est pas la présence, c'est la disparition

Tant que la quantité cachée absorbe, le niveau tient et il ne se passe rien d'exploitable : la
situation est stable et déjà décrite par le moteur d'absorption.

L'événement qui change tout est **l'arrêt des recharges**. Le niveau devient alors non protégé,
et il cède fréquemment dans les instants qui suivent — ce qui en fait à la fois un signal
directionnel et une invalidation nette.

**Le moteur est donc d'abord un suiveur d'état, pas un classificateur d'instant :**

```
PRÉSUMÉ_ACTIF  →  RECHARGES_ESPACÉES  →  ÉPUISÉ  →  NIVEAU_CÉDÉ
                                       ↘  RETIRÉ_SANS_EXÉCUTION  (annulation, autre mécanisme)
```

La transition `ÉPUISÉ` est l'observable de valeur, et elle est **vérifiable après coup** — donc
calibrable, contrairement à la présence. La branche `RETIRÉ_SANS_EXÉCUTION` est importante : une
disparition sans exécution suggère que ce n'était pas une quantité cachée, et alimente la
correction du détecteur.

Cela rejoint exactement la logique de l'ADR-040 : le produit principal est un niveau et sa
condition d'invalidation, pas une direction.

## 6. Un avantage relatif : l'exécution coûte cher à simuler

Les motifs fondés sur le carnet affiché sont exposés aux ordres trompeurs — poser et retirer ne
coûte presque rien (`03a` §7.2). Ce moteur repose sur une base différente : **il ne se déclenche
que sur des exécutions réelles**, et une exécution engage effectivement du capital.

C'est le motif le plus difficile à simuler de toute la famille microstructure, et cela justifie
de lui accorder un poids relatif plus élevé qu'aux signaux purement déclaratifs du carnet —
sous réserve, comme toujours, que la mesure le confirme.

## 7. Seuil de preuve

« Plusieurs fois » (première puce de l'étape 3.5) doit devenir un nombre, et ce nombre ne se
choisit pas à l'intuition. Il se déduit du **modèle nul** (ADR-034) :

> à quelle fréquence un niveau voit-il N cycles exécution-recharge de taille comparable **par
> simple hasard**, compte tenu de son activité normale ?

Le seuil retenu est celui qui place le taux de fausse détection au niveau visé, et il dépend de
la liquidité du niveau, de la tranche de session et du régime. Un seuil unique appliqué partout
serait trop laxiste en séance dense et trop strict en séance creuse.

## 8. Contrat de sortie

Version corrigée du format de l'étape 3.5 :

```
HiddenLiquidityEvent {
  as_of
  mode_de_détection          OBSERVÉ | INFÉRÉ          ← §1, détermine tout le reste
  côté                       ACHETEUR | VENDEUR
  niveau                     aligné sur le pas de cotation ; hors grille ⇒ défaut
  référentiel                contrat et série d'origine ; base appliquée si traduit sur le spot

  cycles_observés            nombre de séquences exécution-recharge
  délai_médian_recharge      signature causale (§2)
  régularité_taille
  annulations_spontanées     doivent être nulles ou quasi nulles
  volume_exécuté_observé     cumulé depuis la détection — mesuré, exact (§4)
  # aucun champ de quantité cachée résiduelle : invérifiable par construction

  score_motif                échelle nommée, non probabiliste si mode = INFÉRÉ (§3)
  proba_niveau_tient         calibrée sur conséquence observable, par horizon (§3)
  seuil_de_preuve            issu du modèle nul applicable au niveau (§7)

  état                       PRÉSUMÉ_ACTIF | RECHARGES_ESPACÉES | ÉPUISÉ
                             | NIVEAU_CÉDÉ | RETIRÉ_SANS_EXÉCUTION
  invalidation { niveau, condition }
  recouvrements_déclarés[]   famille microstructure, cinquième vue
  confiance, abstention + motif
  statuts_entrées[]
  rôle_autorisé              VETO par défaut (ADR-030)
}
```

Différences avec le format d'origine :

| Champ d'origine | Devient | Motif |
| --- | --- | --- |
| `Iceberg acheteur probable` | `mode_de_détection` + `côté` | observation et inférence ne se confondent pas (§1) |
| `Confiance : 73 %` | `score_motif` **ou** rien, + `proba_niveau_tient` | la présence est invérifiable, donc incalibrable (§3) |
| `Contrats exécutés estimés` | `volume_exécuté_observé` | le résiduel caché ne s'estime pas (§4) |
| `Comportement après détection` | `état` à cinq valeurs | la transition est l'événement utile (§5) |

## 9. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Carnet par ordre, identité et action de mise à jour | intégrité OK | bascule en mode `INFÉRÉ`, jamais indisponible |
| Carnet agrégé au minimum | intégrité OK | **indisponible** |
| Flux de transactions horodaté finement | FRAIS, résolution native (ADR-020) | **indisponible** — la signature causale repose sur le délai exécution→recharge |
| Marquage de liquidité implicite | présent | dégradé : une recharge implicite n'est pas une quantité cachée (`02b` §4.3) |
| Base spot/listé si le niveau est traduit | FRAIS | **indisponible** pour usage spot |

La quatrième ligne est un piège concret : la recombinaison d'ordres de spread calendaire peut
faire réapparaître de la profondeur à un niveau sans qu'aucun ordre caché n'existe. Sans le
marquage, le détecteur confondra les deux.

## 10. À vérifier et à mesurer

**À vérifier en premier, avant d'écrire du code** — cela détermine l'architecture du moteur :

- le protocole du marché considéré expose-t-il un indicateur de quantité cachée ?
- l'identifiant d'ordre est-il conservé à travers les recharges ?
- comment la priorité de file évolue-t-elle après une recharge ?

**À mesurer ensuite :**

- fréquence du motif sous modèle nul, par niveau de liquidité et par tranche de session (§7) ;
- taux de base de `NIVEAU_CÉDÉ` après `ÉPUISÉ`, et délai typique entre les deux — c'est
  l'observable exploitable (§5) ;
- proportion de `RETIRÉ_SANS_EXÉCUTION`, qui mesure directement le taux de fausse détection du
  mode inféré ;
- apport marginal conditionnel aux quatre autres vues (ADR-035) ;
- si le mode observé est disponible : **taux d'erreur du mode inféré confronté à la vérité**.
  C'est la seule occasion, dans toute la famille microstructure, de disposer d'une vérité
  terrain — elle doit être exploitée pour étalonner les autres détecteurs par analogie.

Ce dernier point mérite d'être souligné : si la donnée par ordre est accessible ne serait-ce que
sur une période limitée, elle permet de **mesurer combien l'inférence se trompe**. C'est une
information rare et précieuse dans ce domaine, où presque rien n'est vérifiable.

## 11. Questions ouvertes

- **Q28** — la donnée par ordre est-elle accessible, même sur un historique limité ou en
  différé ? La réponse change la nature du moteur (§1) et ouvre la seule fenêtre de vérité
  terrain de toute la famille (§10).
- **Q29** — ce moteur a-t-il un sens sur le spot ? Les carnets de brokers spot n'exposent
  généralement rien de tel. Si la réponse est non, il est explicitement déclaré **listé
  uniquement**, et ses niveaux ne franchissent la base que comme information de contexte.
