# 03c — Moteur d'absorption

> Statut : **figé** (étape 3.3 de la spécification).
> Troisième vue de microstructure (étage 4). À lire après `03a` et `03b`.

## 1. Le « 82 % » : trois grandeurs différentes sous un seul nom

Le format de sortie de l'étape 3.3 affiche `Confiance : 82 %`. Ce champ peut recouvrir trois
questions sans rapport entre elles :

| Question | Nature |
| --- | --- |
| **Le motif est-il réellement présent ?** | probabilité de **détection** |
| **Le prix va-t-il monter à l'horizon h ?** | probabilité **prédictive** |
| Le motif est-il « net » selon un barème interne ? | **score**, pas une probabilité |

Les confondre est le défaut le plus courant de ce type d'outil, et il est ici particulièrement
coûteux : une absorption peut être **certainement présente** (détection quasi sûre) et
**n'annoncer presque rien** (probabilité prédictive à peine au-dessus de la pièce lancée). Un
champ unique à 82 % laisse croire le contraire.

**Règle** : ces trois grandeurs sont des champs distincts, et la sortie ne les fusionne jamais.

## 2. Un pourcentage doit être calibré, sinon ce n'est pas un pourcentage

Le système a pour objectif des probabilités calibrées. Afficher « 82 % » à partir d'un barème
de points reviendrait à produire un nombre d'apparence probabiliste sans contenu fréquentiel —
c'est-à-dire exactement ce que l'ADR-002 interdit au modèle de langage, et l'ADR-025 à la
couche de données.

**Règle, applicable à tout le système** : une grandeur n'est exprimée en pourcentage que si
elle a été **confrontée à la fréquence réalisée**. « 82 % » signifie : *parmi les cas
historiques où ce moteur a annoncé 82 %, environ 82 % se sont effectivement produits.* Tant que
cette vérification n'existe pas, la sortie porte un **score sur une échelle nommée**
explicitement non probabiliste.

Ce n'est pas une restriction cosmétique : un pourcentage non calibré se propage jusqu'à la
fusion, qui le combine comme s'il était une probabilité, et corrompt la calibration de
l'ensemble. Un seul champ mal typé suffit.

## 3. L'exemple contient son propre résultat

La séquence décrite à l'étape 3.3 se termine par « une reprise de structure apparaît ensuite ».
Cette dernière clause est **l'issue**, pas un élément de détection.

Si elle entre dans la définition du motif, celui-ci n'est détecté que lorsqu'il a fonctionné.
Le taux de réussite mesuré vaut alors 100 % par construction, et la mesure n'a plus aucun sens.

**Règle** : le motif est émis **avant** de connaître son issue, sur les seuls éléments
disponibles à l'instant de la détection — flux agressif, absence de progression, comportement
du carnet. L'issue est étiquetée plus tard et **rattachée** à l'émission.

Corollaire indispensable : **les absorptions qui échouent doivent être détectées et comptées.**
Une absorption submergée — le prix traverse la zone — est le même motif jusqu'à son issue, et
c'est le cas majoritaire en marché directionnel. Sans ces échecs dans la base, aucun taux de
base n'existe, et donc aucune probabilité calibrée n'est possible.

Le champ `Validation structurelle : en attente` de ton format est le bon réflexe. Il est ici
généralisé : **tout motif naît dans l'état « en attente »**, et son issue est un événement
ultérieur, daté, qui alimente l'étage 12.

## 4. Le côté passif n'a peut-être aucune opinion

C'est la limite intrinsèque du moteur, et elle doit être inscrite dans sa sortie plutôt que
découverte à l'usage.

Un participant qui absorbe des ventes agressives sans céder de terrain peut être :

| Qui absorbe | Ce qui suit |
| --- | --- |
| Un acheteur **informé**, patient, qui construit une position | soutien durable, l'hypothèse tient |
| Un **teneur de marché** qui encaisse du flux et va se déboucler | le soutien disparaît, et le prix part souvent **contre** l'interprétation naïve |
| Un **algorithme d'exécution** suivant un calendrier | soutien parfaitement régulier, puis **disparition instantanée** à la fin du programme |

Le troisième cas explique le scénario frustrant où une absorption tient impeccablement pendant
quarante-six secondes, puis s'évapore : le programme d'exécution était terminé. L'absorbeur
n'avait aucune vue sur le prix ; il avait un volume à exécuter.

**Signatures à extraire pour tenter de séparer ces cas** — sans garantie, et à valider par la
mesure :

- **régularité** : un algorithme réapprovisionne à intervalles et tailles réguliers ; un acteur
  informé est irrégulier ;
- **signature d'ordre iceberg** : réapparition répétée d'une même taille affichée au même prix
  après chaque exécution ;
- **réaction à l'intensification** : l'absorbeur tient-il quand la pression augmente, ou
  se contente-t-il d'un débit constant ?
- **contexte horaire** : les programmes d'exécution se concentrent autour des repères de
  séance et des fixings (`02c` §2.3).

Tant que ces signatures ne sont pas validées, la sortie doit déclarer explicitement que la
nature de l'absorbeur est **indéterminée** — c'est une information honnête, pas une lacune.

## 5. Absorption n'est pas épuisement par absence

Un prix qui cesse de baisser **sans volume agressif** n'est pas une absorption : c'est
l'absence de vendeurs. Le mécanisme est différent, la suite aussi.

L'absorption exige la conjonction : **volume agressif élevé** *et* **absence de progression**.
La normalisation du volume (§6) est donc ce qui sépare les deux cas — sans elle, le moteur
confond « quelqu'un encaisse tout » et « il ne se passe rien ».

## 6. Normaliser le volume et la durée

Deux champs du format proposé sont qualitatifs ou ambigus :

**`Volume absorbé : élevé`** — élevé par rapport à quoi ? La grandeur exploitable est le volume
agressif absorbé **rapporté à la profondeur disponible et au volume attendu** pour cette
tranche de session (ADR-028, ADR-033). « Élevé » cache la normalisation au lieu de la porter.

**`Durée : 46 secondes`** — quarante-six secondes en creux asiatique et quarante-six secondes à
l'ouverture de New York ne décrivent pas le même phénomène. La durée est donc doublement
exprimée : en temps d'horloge pour l'audit, et **en temps-événement** pour l'analyse
(ADR-032).

## 7. La zone

Le format retient une **zone** plutôt qu'un point : c'est le bon choix, l'absorption a une
épaisseur. Trois précisions :

- **définition** : la zone est délimitée par la répartition du volume réellement absorbé, et
  non par les extrêmes de l'épisode. Un extrême touché une fois n'est pas une zone d'absorption ;
- **référentiel** : la zone est établie sur la série brute d'un contrat unique (ADR-011). Si
  elle est utilisée sur le spot alors qu'elle a été détectée sur le listé, elle doit être
  **traduite par la base courante** (`02b` §1) — un niveau listé n'est pas un niveau spot ;
- **péremption** : une zone d'absorption se dégrade avec le temps et avec le nombre de fois où
  elle a été retestée. La sortie porte une **fraîcheur** et un **compteur de retests**, et une
  zone périmée disparaît au lieu de rester indéfiniment sur la carte.

## 8. Le produit principal de ce moteur est une invalidation

L'apport le plus solide de l'absorption n'est pas la direction — c'est le **niveau**.

Si l'absorbeur est submergé et que le prix traverse la zone, l'hypothèse est morte. Ce n'est
pas une opinion : c'est un fait observable et daté. Cela fournit à l'étage 9 une **invalidation
structurelle**, donc un emplacement de protection fondé sur le comportement réel du marché
plutôt que sur un pourcentage arbitraire.

**Ordre de priorité retenu : l'absorption produit d'abord une invalidation, ensuite seulement
un élément directionnel.** L'invalidation est robuste et exploitable même si le pouvoir
prédictif directionnel se révèle faible — ce qui est l'hypothèse prudente tant que la mesure
n'a pas tranché.

## 9. Le point inconfortable : ce n'est pas un troisième témoin

L'absorption n'est pas une source d'information supplémentaire. C'est **le même flux d'ordres**
que les étapes 3.1 et 3.2, lu sous un troisième angle — et plus précisément, c'est le quadrant
« absorption » de `03a` §5 et de `03b` §4 rendu explicite.

Le recouvrement est donc **quasi total**, et il doit être déclaré comme tel (ADR-035).

Conséquence à assumer clairement : **le système ne dispose pas de trois moteurs de
microstructure indépendants. Il dispose d'une source d'information avec trois vues.** Trois
vues concordantes n'apportent pas trois confirmations ; elles décrivent le même fait. Une
fusion qui l'ignore produira une confiance très supérieure à ce que les données justifient,
sur la famille de signaux la plus bruitée du système.

Ce n'est pas une raison de supprimer un moteur : chaque vue extrait des grandeurs différentes
et exploitables — l'une le carnet, l'autre les transactions, la troisième la géométrie locale.
Mais elles entrent dans la fusion comme **une famille**, avec un poids de famille, pas comme
trois voix.

## 10. Contrat de sortie

Version corrigée du format de l'étape 3.3 :

```
AbsorptionEvent {
  as_of, échelle_d_analyse
  côté                          ACHETEUSE | VENDEUSE
  zone { bas, haut }            pondérée par le volume absorbé (§7)
  référentiel                   contrat et série d'origine ; base appliquée si traduit
  volume_absorbé_normalisé      rapporté à la profondeur et au volume attendu
  progression_prix              nulle ou négligeable, mesurée (§5)
  durée_horloge, durée_événement
  nature_absorbeur              INDÉTERMINÉE | RÉGULIÈRE_ALGORITHMIQUE | IRRÉGULIÈRE
  signature_iceberg             présente | absente | indéterminée

  score_détection               probabilité que le motif soit réellement présent
  proba_suivi                   probabilité calibrée d'aboutissement, ou null
  échelle_si_non_calibré        nom de l'échelle utilisée si proba_suivi est null (§2)
  taux_de_base                  fréquence historique de réussite de ce motif, par régime

  invalidation { niveau, condition }        ← produit principal (§8)
  état                          EN_ATTENTE | ABOUTIE | SUBMERGÉE | EXPIRÉE
  fraîcheur, compteur_retests

  recouvrements_déclarés[]      famille microstructure (§9)
  confiance, abstention + motif
  statuts_entrées[]
  rôle_autorisé                 VETO par défaut (ADR-030)
}
```

Différences avec le format d'origine, et leurs motifs :

| Champ d'origine | Devient | Motif |
| --- | --- | --- |
| `Confiance : 82 %` | `score_détection` + `proba_suivi` + `taux_de_base` | trois questions distinctes (§1, §2) |
| `Volume absorbé : élevé` | valeur normalisée | « élevé » cache la référence (§6) |
| `Durée : 46 secondes` | durée horloge **et** événement | 46 s ne veut pas dire la même chose selon l'heure (§6) |
| `Validation structurelle : en attente` | `état` à quatre valeurs | il faut aussi pouvoir enregistrer l'échec (§3) |
| — | `invalidation` | produit principal du moteur (§8) |
| — | `nature_absorbeur` | l'absorbeur peut n'avoir aucune vue (§4) |

## 11. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Flux de transactions avec côté agresseur | FRAIS, intégrité OK | **indisponible** |
| Carnet, liquidité réelle marquée | intégrité OK | dégradé — la nature de l'absorbeur devient indéterminable |
| Profondeur pour la normalisation | présente | dégradé |
| Contrat principal et phase de rollover | ADR-010, ADR-013 | dégradé pendant la migration |
| Base spot/listé, si la zone est traduite | FRAIS | **indisponible** pour usage spot |

## 12. À mesurer avant tout usage

- **taux de base** : parmi les absorptions détectées, quelle fraction aboutit, par régime et par
  tranche de session — avec les échecs inclus (§3) ;
- **calibration** : la probabilité annoncée correspond-elle à la fréquence réalisée ? Sans cette
  mesure, aucun pourcentage n'est publié (§2) ;
- pouvoir prédictif résiduel **une fois connus** les signaux de 3.1 et 3.2 — c'est la seule
  mesure qui dit si ce moteur apporte quelque chose, ou s'il reformule (§9) ;
- valeur de l'invalidation seule : un stop placé sur la zone fait-il mieux qu'un stop de
  volatilité équivalente ? C'est le test qui décide si l'apport principal du moteur est réel ;
- séparation effective entre absorption informée et absorption mécanique — et, si elle n'est
  pas atteignable, écart de résultat entre les deux populations mélangées.

## 13. Questions ouvertes

- **Q24** — la profondeur d'historique événementiel permet-elle de constituer un taux de base
  par régime ? Un motif rare mesuré sur peu de cas donne un taux de base dont l'intervalle de
  confiance est plus large que l'effet recherché — auquel cas le moteur reste en veto, sans
  probabilité publiée.
- **Q25** — les zones d'absorption doivent-elles être conservées entre séances, ou expirer à la
  clôture ? La réponse dépend de l'horizon visé, toujours non tranché depuis Q3.
