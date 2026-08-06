# 04b — Ruptures de structure : BOS, CHOCH, MSS

> Statut : **figé** (étape 4.2 de la spécification).
> Repose entièrement sur `04a-swings.md`. Ne rien lire ici sans avoir lu la définition de pivot.

## 1. Ce ne sont pas trois détecteurs, c'est une machine à états

BOS et CHOCH ne se distinguent pas par leur géométrie — les deux sont un franchissement de
pivot. Ils se distinguent par **leur rapport à l'état structurel en cours** :

- franchissement **dans le sens** de l'état courant → continuation ;
- franchissement **contre** l'état courant → première rupture opposée.

C'est donc une seule mécanique, avec un état. Le formuler ainsi supprime la dernière part de
jugement : il n'y a plus à décider si « c'est un BOS ou un CHOCH », la réponse découle de l'état
précédent.

```
                 rupture haussière
   BAISSIÈRE ────────────────────────►  TRANSITION_HAUSSIÈRE
       ▲                                       │        │
       │  rupture baissière                    │        │ rupture haussière
       │  (confirmation)                       │        │ suivante
       └───────────────────────────────────────┘        ▼
                    rupture baissière             HAUSSIÈRE
                    (retour, échec du CHOCH)
```

Ta phrase — « le CHOCH ne signifie pas automatiquement un retournement » — devient **mécanique**
plutôt que prudentielle : une rupture opposée fait entrer dans un état de **transition**, jamais
directement dans l'état inverse. Le basculement n'est acquis qu'après une seconde rupture dans
le nouveau sens. Un CHOCH suivi d'une rupture dans l'ancien sens est un **échec de CHOCH**, et
cet échec est enregistré comme tel — c'est une information, pas un non-événement.

Nomenclature retenue :

| Terme | Définition dans la machine |
| --- | --- |
| **BOS** | franchissement dans le sens de l'état courant |
| **CHOCH** | franchissement contre l'état courant, depuis un état établi |
| **Basculement** | seconde rupture confirmant la transition |
| **Échec de CHOCH** | retour dans l'ancien sens depuis l'état de transition |
| **MSS** | qualification continue d'un CHOCH ou d'un basculement (§5) |

## 2. Le niveau de décomposition remplace l'unité de temps

Ta sortie s'exprime en unités de temps — H1, M15, M5, M1. Or l'étape 4.1 a délibérément
supprimé la dépendance aux bougies : une unité de temps est une convention d'agrégation
(ADR-022), et deux conventions donnent deux structures différentes sur les mêmes prix.

Exprimer la structure en unités de temps **réintroduirait la dépendance qu'on vient
d'éliminer**.

**Règle** : la structure est calculée **par niveau de décomposition θ** (ADR-055). Les
étiquettes temporelles restent disponibles comme **correspondance d'affichage** — utile pour la
lecture humaine — mais ne sont jamais la base du calcul.

```
Niveau θ₃ (large)   : haussière
Niveau θ₂ (moyen)   : correction baissière
Niveau θ₁ (fin)     : transition haussière
Niveau θ₀ (le plus fin) : indéterminé — rapport signal/bruit insuffisant
```

La correspondance vers H1/M15/M5/M1 est une table de présentation, versionnée, et rien d'autre.

## 3. BOS : supprimer la dépendance à la clôture

Tes cinq critères contiennent deux formulations du même besoin :

> « clôture au-delà du niveau » · « absence de simple mèche isolée »

Les deux disent : **la pénétration doit durer**. Mais « clôture » exige une bougie, donc une
convention d'agrégation — le problème qu'on vient d'écarter.

Formulation sans bougie, avec deux paramètres seulement :

| Paramètre | Rôle |
| --- | --- |
| **δ — profondeur** | de combien le prix doit dépasser le pivot, en unités de volatilité |
| **τ — persistance** | combien de temps, ou d'événements, il doit s'y maintenir |

Une mèche isolée échoue sur τ ; un effleurement échoue sur δ. Les deux critères d'origine sont
couverts, sans référence à une bougie, et avec deux paramètres explicitement calibrables plutôt
qu'une convention implicite.

**Sur la confirmation par volume ou vitesse** : elle est conservée, mais comme **attribut de
qualité** et non comme condition d'existence — même raisonnement qu'en `04a` §6. Une rupture
avec faible volume reste une rupture ; elle est simplement moins bien corroborée. En faire une
condition rendrait la détection dépendante de la disponibilité du volume, donc non reproductible
entre le listé et le spot.

## 4. Non-repeinture : la propriété à garantir explicitement

Les indicateurs de structure ont une réputation méritée de **repeindre** — d'afficher
aujourd'hui une histoire différente de celle qu'ils affichaient hier.

Avec la construction retenue, ce n'est pas le cas, et il vaut la peine de dire pourquoi : à θ
fixé, la suite des pivots confirmés est déterministe et croissante — un pivot confirmé ne
disparaît jamais. La suite des états structurels qui en découle est donc, elle aussi,
définitive.

**Ce qui peut changer, ce n'est pas le passé, c'est la valeur de θ.** Deux θ donnent deux
histoires, toutes deux valides à leur échelle. C'est pourquoi θ est versionné (ADR-056) et
publié avec chaque état.

**Test d'acceptation** : rejouer l'historique de façon incrémentale, en ne fournissant au moteur
que les données disponibles à chaque instant, doit produire **exactement** la même suite d'états
que le calcul en une passe sur l'historique complet. Toute divergence est une fuite temporelle.

## 5. MSS : une conjonction de cinq critères est un piège

Tes cinq conditions — prise de liquidité, déplacement, rupture, déséquilibre, maintien —
décrivent bien le phénomène. Les exiger **toutes**, sous forme binaire, pose trois problèmes qui
se renforcent :

1. **cinq seuils** à régler, donc un espace de recherche large et le problème de multiplicité de
   l'ADR-034 à son maximum ;
2. **rareté** : une conjonction de cinq conditions se produit peu, donc l'historique fournit peu
   de cas, donc l'intervalle de confiance du taux de base dépasse l'effet cherché — c'est
   exactement Q24 ;
3. **dérive de calibration** : face à un détecteur qui ne se déclenche presque jamais, la
   tentation est d'assouplir les seuils jusqu'à obtenir « assez » de signaux. On ajuste alors
   les paramètres à une **fréquence désirée**, pas aux données.

**Décision : le MSS n'est pas un détecteur binaire, c'est une qualification continue d'un
CHOCH.**

Chacun des cinq éléments devient un **attribut mesuré en continu**, attaché à toute rupture :

| Attribut | Mesure | Source |
| --- | --- | --- |
| Prise de liquidité préalable | cascade au-delà d'un niveau, ampleur et concentration | ADR-052 — recouvrement déclaré |
| Déplacement | amplitude de la jambe rapportée à la volatilité | `04a` |
| Rupture | profondeur δ et persistance τ effectives (§3) | ce moteur |
| Déséquilibre | mesure d'inefficience laissée par le mouvement | étape 4.3 |
| Maintien après rupture | comportement du prix après coup (§6) | événement différé |

Le « MSS » devient le **haut d'un continuum**, découpé par quantile plutôt que par cinq seuils
indépendants. Trois bénéfices : le taux de base est estimable sur toute l'échelle et non sur
quelques spécimens parfaits ; les attributs manquants dégradent le score au lieu d'annuler la
détection ; et l'on peut mesurer **lequel des cinq attributs porte réellement l'information** —
question qu'une conjonction binaire rend impossible à poser.

## 6. « Maintien du prix après rupture » est une issue, pas une entrée

Cinquième critère de ton MSS, et c'est le même défaut qu'à l'étape 3.3 : le maintien se constate
**après**. L'inclure dans la détection ne laisse détecter que les MSS qui ont fonctionné, et le
taux de réussite vaut 100 % par construction (ADR-038).

Deux produits distincts, tous deux légitimes, à ne pas confondre :

| Produit | Émission | Force | Coût |
| --- | --- | --- | --- |
| **Rupture immédiate** | à l'instant où δ et τ sont satisfaits | plus faible | aucun retard |
| **Rupture retenue** | après une fenêtre de maintien déclarée | plus forte | retard de la fenêtre |

Ce n'est pas un choix à trancher a priori : ce sont deux signaux différents, avec des taux de
base différents, à mesurer tous les deux. L'étage 9 choisira selon ce que le retard coûte en
prix d'entrée — arbitrage qui se calcule, il ne se devine pas.

## 7. Le désaccord entre échelles est l'état normal

Ta sortie illustre un cas où les quatre échelles disent des choses différentes. C'est **la
situation habituelle**, pas une anomalie : la concordance de toutes les échelles est rare, et
c'est précisément ce qui la rend informative.

Deux conséquences.

**Ce ne sont pas quatre témoins indépendants.** Les échelles sont emboîtées par construction
(ADR-055) : une rupture au niveau large implique des ruptures aux niveaux fins. « Quatre
échelles concordent » n'est donc **pas** quatre confirmations — c'est souvent une seule
information vue quatre fois. Recouvrement à déclarer au sens de l'ADR-035, exactement comme pour
la famille microstructure.

**La grandeur exploitable n'est pas l'état, c'est la relation entre états.** Sont donc publiés :
degré d'alignement entre niveaux, niveau le plus fin en état de transition, et **niveau dont
l'état est le plus proche de basculer** — cette dernière étant la plus utile pour anticiper.

## 8. Le bruit : une mesure, pas une étiquette particulière

`Structure M1 : bruit élevé` n'est pas de même nature que les trois autres lignes : ce n'est pas
une direction, c'est un constat sur la qualité du signal à cette échelle. L'intuition est juste,
la forme doit être systématisée.

**Chaque niveau publie une mesure de rapport signal/bruit** — par exemple la part du déplacement
net rapportée au chemin total parcouru, ou la fréquence de ruptures immédiatement invalidées.
En dessous d'un seuil calibré, le niveau retourne `INDÉTERMINÉ` **au lieu d'une direction**.

Ainsi le bruit n'est pas un cas particulier réservé à l'échelle la plus fine : c'est une
propriété mesurée à tous les niveaux, qui peut frapper n'importe lequel d'entre eux — notamment
lors des transitions de volatilité.

## 9. Le test qui décide de la valeur de tout ce moteur

Question à poser tôt, car la réponse peut invalider l'étape entière.

Une rupture de structure est, par construction, **corrélée à la tendance** : un franchissement de
sommet dans une tendance haussière survient parce que le prix monte. Le risque est donc réel que
« le BOS annonce la continuation » ne soit qu'une reformulation compliquée de « les tendances se
poursuivent ».

**Test exigé** : le BOS apporte-t-il quelque chose **conditionnellement à une mesure de tendance
simple** ? Concrètement, comparer le pouvoir prédictif du BOS à celui d'un indicateur de tendance
élémentaire calculé sur la même fenêtre, puis mesurer l'apport **incrémental** du premier une
fois le second connu.

- apport incrémental net → la structure porte une information propre, et son poids se calibre ;
- apport nul → le moteur est un habillage du momentum, et il doit être traité comme tel dans la
  fusion : une seule source, pas deux.

Le second cas n'est pas un échec du projet. C'est exactement le type de découverte que
l'architecture est faite pour produire — et la découvrir maintenant coûte infiniment moins cher
que de la découvrir en production.

## 10. Contrat de sortie

```
StructureState(par niveau θ) {
  niveau_θ, valeur_θ, correspondance_affichage      (§2)
  état            HAUSSIÈRE | BAISSIÈRE | TRANSITION_HAUSSIÈRE
                  | TRANSITION_BAISSIÈRE | INDÉTERMINÉ
  depuis_quand    instant_confirmation de l'état courant
  signal_sur_bruit, sous_seuil_de_bruit             (§8)

  dernière_rupture {
    type            BOS | CHOCH | BASCULEMENT | ÉCHEC_DE_CHOCH
    pivot_franchi   référence au SwingPoint, avec sa propre latence de confirmation
    δ_effectif, τ_effectif
    instant_franchissement, instant_confirmation    (ADR-053)
    produit         IMMÉDIAT | RETENU                (§6)

    attributs_mss {                                  (§5) — continus, jamais binaires
      prise_de_liquidité, déplacement, profondeur_rupture,
      déséquilibre, maintien
    }
    score_mss       position dans le continuum, par quantile
    corroboration { volume, vitesse }                attributs, pas conditions (§3)
  }

  état_maintien   EN_ATTENTE | MAINTENU | INVALIDÉ | EXPIRÉ
  invalidation { niveau, condition }
  recouvrements_déclarés[]   échelles emboîtées + momentum (§7, §9)
  version_définition, statuts_entrées[]
}

StructureAlignment {
  alignement_entre_niveaux
  niveau_le_plus_fin_en_transition
  niveau_le_plus_proche_du_basculement                (§7)
}
```

## 11. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Pivots **confirmés** du niveau considéré | ADR-053 | **indisponible** — un pivot provisoire ne peut pas être franchi (ADR-054) |
| Série brute d'un contrat unique | intégrité OK, sans trou | **indisponible** |
| Estimateur de volatilité pour δ | FRAIS | dégradé — δ en prix absolu, non comparable entre régimes |
| Volume, vitesse | présents | dégradé — corroboration absente, détection inchangée |
| Détecteur de cascade (ADR-052) | disponible | dégradé — attribut de prise de liquidité manquant, score MSS partiel |
| Déséquilibres (étape 4.3) | disponibles | dégradé — score MSS partiel |

## 12. À mesurer avant tout usage

- **le test du §9 en premier** : apport incrémental du BOS au-delà d'une mesure de tendance
  simple. Il conditionne le poids de tout le moteur ;
- taux de base par état de départ : après un CHOCH, quelle proportion aboutit à un basculement,
  et quelle proportion est un échec ? C'est ce qui donne son contenu à ta phrase « ne signifie
  pas automatiquement un retournement » ;
- comparaison rupture immédiate / rupture retenue : écart de taux de base contre coût du retard
  en prix d'entrée (§6) ;
- quel attribut du score MSS porte l'information — mesuré individuellement, pas seulement en
  bloc (§5) ;
- fréquence réelle de l'alignement complet entre niveaux, et sa valeur prédictive comparée au
  désaccord (§7) ;
- sensibilité de tous les résultats ci-dessus à θ, δ et τ, sur grille (ADR-034, ADR-056).
