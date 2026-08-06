# 04a — Moteur de structure : détection des points pivots

> Statut : **figé** (étape 4.1 de la spécification).
> Fondation de l'étage 4 côté structure. **Toutes les définitions ultérieures — blocs d'ordres,
> déséquilibres, ruptures de structure — reposent sur celle-ci.**

## 1. Ce qu'exige réellement « une définition mathématique »

L'exigence de l'étape 4 est juste et rarement tenue. Elle se décompose en trois propriétés
vérifiables :

1. **déterminisme** — mêmes entrées, mêmes paramètres, même résultat, à l'octet près ;
2. **absence de jugement** — aucun seuil choisi « parce que ça marche mieux visuellement » ;
   tout seuil est soit dérivé d'une distribution mesurée, soit déclaré comme paramètre à
   calibrer ;
3. **reproductibilité indépendante** — deux implémentations écrites séparément à partir de la
   spécification doivent produire **exactement le même ensemble de pivots** sur les mêmes
   données.

Le troisième point est le seul test réellement contraignant, et il est retenu comme **critère
d'acceptation** de ce moteur. Une définition qui ne le passe pas n'est pas mathématique : elle
est simplement écrite en langage technique.

## 2. Un pivot n'existe qu'après coup

C'est le problème central de toute analyse structurelle, et il est invisible sur un graphique.

Une définition « N bougies à gauche, N bougies à droite » signifie qu'un sommet **n'est
identifiable que N bougies après sa formation**. Le graphique, lui, affiche le pivot à sa date
de formation — comme s'il avait été connu à ce moment. Il ne l'était pas.

Toute analyse construite sur cette illusion produit des résultats de backtest excellents et
inatteignables.

**Règle** : chaque pivot porte **deux horodatages**.

| Champ | Signification |
| --- | --- |
| `instant_formation` | l'extrême de prix lui-même |
| `instant_confirmation` | le moment où la définition est satisfaite, donc où le système peut le connaître |

**L'instant de disponibilité au sens de I1 est `instant_confirmation`**, jamais
`instant_formation` — application directe de l'ADR-008. Le feature store ne sert un pivot
qu'à partir de sa confirmation.

Conséquence structurante à assumer : **plus un pivot est significatif, plus il est confirmé
tard.** Un pivot majeur peut n'être identifiable que très longtemps après son extrême. Le
compromis latence / fiabilité n'est pas un défaut d'implémentation, il est inscrit dans la
définition même. Il doit donc être mesuré et publié, pas contourné.

## 3. Les bougies ne sont pas une base solide

Une détection fondée sur des bougies hérite de tous les problèmes de l'ADR-022 : la frontière
de journée et le pas d'agrégation sont des conventions, différentes d'un fournisseur à l'autre,
et décalées d'une heure deux fois par an. **Deux conventions produisent deux ensembles de
pivots différents sur les mêmes prix.**

S'y ajoute une fragilité propre : « N bougies à droite » mesure un nombre de bougies, donc une
durée qui dépend du pas choisi — pas une propriété du marché.

## 4. Méthode retenue : décomposition par changement de direction

Plutôt que de compter des bougies, on définit les pivots **sur le chemin de prix lui-même** :

> Un extrême est confirmé lorsque le prix s'en est écarté de plus d'un seuil θ dans le sens
> opposé. Tant que ce retournement de θ n'a pas eu lieu, l'extrême reste **provisoire** et peut
> s'étendre.

Cette formulation a quatre avantages décisifs :

- **indépendante des bougies** — donc immunisée contre l'ADR-022 ;
- **un seul paramètre interprétable**, θ, exprimable en unités de volatilité plutôt qu'en prix
  absolu ;
- **l'instant de confirmation est explicite** — c'est celui où le seuil est franchi, ce qui rend
  le §2 mécanique plutôt que déclaratif ;
- **naturellement multi-échelle** : plusieurs θ appliqués au même chemin produisent plusieurs
  niveaux de structure emboîtés (§5).

Elle impose en contrepartie un état intermédiaire explicite :

```
PROVISOIRE  →  CONFIRMÉ
```

Un extrême provisoire **ne peut jamais être utilisé comme s'il était confirmé** — c'est la
version « structure » de l'interdiction d'imputer (ADR-025). Le champ provisoire existe pour
l'affichage et la surveillance, pas pour la décision.

La méthode « N bougies » reste implémentée en parallèle, uniquement comme **point de
comparaison** : elle permet de mesurer combien les deux approches divergent, et de vérifier
que les conclusions ne dépendent pas de ce choix.

## 5. La hiérarchie vient de l'emboîtement, pas de seuils

Tes cinq classes — micro, interne, intermédiaire, externe, structurel majeur — décrivent une
**hiérarchie**. Or une classification par seuils indépendants ne produit pas une hiérarchie
cohérente : rien n'empêche un pivot d'être classé « intermédiaire » tout en n'étant contenu
dans aucune structure supérieure, ni deux critères de se contredire (forte amplitude, faible
durée).

**Décision : la classe est définie par la position dans l'emboîtement, pas par des seuils.**

En appliquant plusieurs seuils croissants θ₁ < θ₂ < θ₃ … au même chemin de prix, on obtient
une décomposition emboîtée par construction : tout pivot d'un niveau supérieur est aussi un
pivot de tous les niveaux inférieurs, et l'inverse est faux. La cohérence est structurelle, pas
vérifiée après coup.

| Classe | Définition retenue |
| --- | --- |
| Micro | pivot du niveau le plus fin uniquement |
| Interne | pivot contenu à l'intérieur d'une jambe de niveau supérieur |
| Intermédiaire | pivot survivant à un seuil moyen |
| Externe | pivot délimitant une jambe de niveau supérieur |
| Structurel majeur | pivot survivant au seuil le plus large |

À cela s'ajoute une **significativité continue** — amplitude normalisée, durée, volume,
contexte — qui n'est **pas** la classe mais une mesure indépendante. Un pivot peut être de
classe modeste et de significativité élevée ; les confondre appauvrit l'information.

Le nombre de niveaux et les valeurs de θ sont des paramètres versionnés, calibrés sur la
distribution observée, jamais choisis pour l'esthétique du graphique.

## 6. Ce que deviennent tes six critères

| Critère d'origine | Devient |
| --- | --- |
| Nombre de bougies à gauche et à droite | remplacé par θ ; conservé comme méthode de comparaison (§4) |
| Amplitude minimale | c'est θ lui-même, exprimé en volatilité |
| Distance en ATR | normalisation de θ — avec la réserve du §7 |
| Volume | **attribut de significativité**, pas critère de détection ; disponible sur le listé uniquement |
| Durée | attribut de significativité |
| Importance temporelle | **annotation de contexte** (§8), jamais un critère |

Le déplacement de volume, durée et importance temporelle depuis « critères de détection » vers
« attributs » est délibéré : un pivot est un fait géométrique du chemin de prix. Ce qui
l'entoure le qualifie, mais ne décide pas de son existence. Mélanger les deux rend la
définition non reproductible — un pivot « détecté sauf si le volume est faible » dépend de la
disponibilité du volume, donc de la source de données.

## 7. Le piège de l'ATR aux transitions de régime

Normaliser en ATR est correct sur le principe et biaisé au pire moment.

L'ATR est une moyenne rétrospective : lors d'une expansion de volatilité, il **n'a pas encore
rattrapé** le nouveau régime. Les mouvements paraissent donc anormalement grands en unités
d'ATR juste après une accélération, et anormalement petits juste après un calme prolongé — soit
exactement les moments où la structure est la plus disputée.

Correctifs retenus :

- normaliser aussi par la **volatilité réalisée sur la durée propre du mouvement**, et non
  seulement par une moyenne à fenêtre fixe ;
- calculer l'ATR sur la **série ajustée en différence** (ADR-011), la seule qui préserve les
  écarts en dollars ;
- traiter la période de rattrapage comme un **état déclaré** — une transition de volatilité
  connue majore l'incertitude sur les classes attribuées pendant cette fenêtre ;
- évaluer la sensibilité des résultats à la fenêtre d'ATR sur une grille (ADR-034).

## 8. Importance temporelle : une annotation

Un pivot coïncidant avec un extrême de séance, un extrême hebdomadaire, un fixing ou une
fenêtre de publication n'est pas « plus pivot ». Il est **contextualisé**.

Ces attributs sont attachés au pivot, alimentent la significativité et la fusion, mais
n'entrent jamais dans la détection. Sans cette séparation, un pivot changerait de nature selon
la disponibilité du calendrier — ce qui casserait le déterminisme du §1.

## 9. Le paramètre le plus porteur de tout l'étage

Tout ce qui suit — blocs d'ordres, déséquilibres de prix, ruptures de structure, changements de
caractère — se définit **par référence aux pivots**. Une modification de θ ne change pas un
détail : elle redessine l'ensemble de la structure aval.

Trois conséquences :

- la définition de pivot est **unique et versionnée** pour tout le système. Aucun moteur ne
  redéfinit localement ce qu'est un swing ;
- elle **résout Q27** : la notion d'impulsion partagée entre moteurs est une jambe de la
  décomposition, à un niveau déclaré ;
- la **sensibilité de chaque conclusion aval à θ est mesurée et publiée**. Un résultat qui
  n'existe qu'à une valeur de θ est un artefact (ADR-034), pas une découverte.

## 10. Les niveaux de pivot existent-ils vraiment ?

Question qui doit être posée avant de construire quoi que ce soit dessus, et qui l'est rarement.

**Test** : le prix réagit-il aux niveaux de pivot détectés **plus qu'à des niveaux de contrôle**
tirés au hasard avec une saillance comparable, dans les mêmes conditions de session et de
volatilité ?

- si oui, l'ampleur de l'écart donne le poids légitime de toute la famille structure ;
- si non, les briques ultérieures héritent d'une fondation vide, et il vaut mieux le savoir
  avant d'écrire cinq moteurs par-dessus.

C'est l'application de l'ADR-034 à la structure. Ce test est un **prérequis de l'étape 4**, pas
une validation finale.

## 11. Contrat de sortie

```
SwingPoint {
  instant_formation, instant_confirmation      ← disponibilité = confirmation (§2)
  latence_de_confirmation                       mesurée, publiée
  type                    SOMMET | CREUX
  prix
  état                    PROVISOIRE | CONFIRMÉ | INVALIDÉ

  niveau_de_décomposition                       indice de θ (§5)
  classe                  MICRO | INTERNE | INTERMÉDIAIRE | EXTERNE | MAJEUR
  parent                  pivot du niveau supérieur qui le contient (emboîtement)

  significativité {                             indépendante de la classe (§5)
    amplitude_normalisée, volatilité_de_la_jambe, durée, volume_si_disponible
  }
  contexte[]              extrême de séance, extrême hebdomadaire, fixing,
                          fenêtre de publication — annotations (§8)

  référentiel             contrat, série (brute — ADR-011), convention d'agrégation
  θ_utilisé, version_définition
  statuts_entrées[]
}
```

Deux champs méritent attention : `latence_de_confirmation`, qui rend visible le coût du §2 et
permet à l'étage 9 de savoir si un pivot est arrivé trop tard pour être exploitable ; et
`parent`, qui matérialise l'emboîtement et rend la hiérarchie vérifiable plutôt que déclarée.

## 12. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Série de prix brute d'un contrat unique | intégrité OK, sans trou | **indisponible** — l'imputation est interdite (ADR-025) |
| Convention d'agrégation et frontière de journée déclarées | ADR-022, ADR-036 | **indisponible** |
| Estimateur de volatilité pour normaliser θ | FRAIS | dégradé — θ en prix absolu, classes non comparables |
| Volume | présent | dégradé — significativité incomplète, détection inchangée |
| Calendrier | ADR-021 | dégradé — annotations de contexte absentes |
| Base spot/listé si les pivots sont transposés | FRAIS | **indisponible** pour usage spot |

La quatrième ligne illustre la valeur de la séparation du §6 : sans volume, la détection reste
identique et seule la significativité est incomplète. Si le volume avait été un critère de
détection, l'absence de volume aurait changé l'ensemble des pivots.

## 13. À mesurer avant tout usage

- **le test du §10 en premier** — il conditionne tout l'étage ;
- distribution de la latence de confirmation par niveau de décomposition : combien de pivots
  majeurs arrivent trop tard pour être exploitables ?
- divergence entre la méthode par seuil et la méthode par bougies, et impact de cette
  divergence sur les conclusions aval (§4) ;
- sensibilité de chaque brique ultérieure à θ (§9) ;
- fréquence des extrêmes provisoires qui s'étendent avant confirmation — c'est la mesure du
  risque de conclure trop tôt ;
- biais de classification pendant les transitions de volatilité (§7).
