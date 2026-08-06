# 04c — Déséquilibres de prix (Fair Value Gap)

> Statut : **figé** (étape 4.3 de la spécification).
> Repose sur `04a-swings.md` (décomposition) et `04b-bos-choch-mss.md` (état structurel).

## 1. Ce que le motif capture réellement

La définition en trois bougies est un **indicateur indirect**. Le phénomène sous-jacent est
autre :

> le prix a traversé une région si vite qu'il ne s'y est presque pas négocié.

C'est une propriété du **chemin de prix et de l'activité**, pas des bougies. La règle
« plus haut de la bougie 1 < plus bas de la bougie 3 » l'approche, mais mal :

- elle dépend de la convention d'agrégation (ADR-022) — deux fournisseurs, deux découpages,
  deux ensembles de déséquilibres sur les mêmes prix ;
- elle est **binaire** : un chevauchement d'un seul pas de cotation annule le motif, alors que la
  région est tout aussi peu négociée ;
- elle ne dit rien de l'intensité : deux gaps de même taille peuvent recouvrir des activités
  très différentes.

## 2. Définition retenue : la densité de négociation

Sur la jambe d'impulsion — définie comme une jambe de la décomposition θ (ADR-056) — le moteur
construit un **profil d'activité par niveau de prix** : temps passé, volume échangé, nombre de
transactions.

> Un déséquilibre est une **zone contiguë de densité anormalement basse** dans ce profil,
> rapportée à la densité de ses voisines immédiates et à la normale conditionnelle de la
> tranche de session (ADR-007).

Avantages, tous décisifs :

| Propriété | Conséquence |
| --- | --- |
| Indépendante des bougies | immunisée contre l'ADR-022 |
| **Continue** | l'intensité du déséquilibre est une grandeur, pas un booléen |
| Généralise le cas limite | un léger chevauchement ne fait plus disparaître le motif |
| Mesure directement le mécanisme | plus besoin de supposer que trois bougies en sont un bon proxy |

**Contrainte de données à assumer** : cette définition exige le volume ou l'activité par niveau
de prix, donc le **listé**. Sur le spot, seule la définition en trois bougies reste calculable.
Les deux ne sont pas équivalentes et ne doivent pas porter le même nom : la sortie déclare sa
`méthode`, et une zone détectée par repli sur bougies porte une incertitude supérieure.

La définition en trois bougies est donc conservée comme **méthode de repli et de comparaison**,
exactement comme la méthode « N bougies » l'est pour les pivots (ADR-054).

## 3. Le plus grand déséquilibre de l'or n'en est pas un

Point à traiter avant tout le reste, car un détecteur naïf classera ces cas **en tête** de son
palmarès de qualité — ils sont les plus grands.

| Écart de prix | Nature réelle |
| --- | --- |
| Ouverture du dimanche | **fermeture de marché** — personne n'a pu négocier |
| Reprise après la coupure quotidienne | fermeture de marché |
| Franchissement de frontière de roll | **artefact de raccord** (ADR-011) |
| Écart sur série ajustée | artefact de transformation (ADR-012) |
| Jour férié d'une place, l'autre restant ouverte | absence par conception (ADR-024) |

Aucun de ces écarts n'est un déséquilibre. Un déséquilibre suppose que le marché **pouvait**
négocier et ne l'a pas fait. Quand le marché est fermé, l'absence de négociation n'est pas une
inefficience : c'est une absence.

**Règles :**

1. tout écart chevauchant une période de fermeture, de coupure ou de férié est exclu — décision
   prise à partir du calendrier (ADR-021), pas d'un seuil ;
2. aucune zone ne franchit une frontière de roll ; les zones vivent sur la **série brute d'un
   contrat unique** (ADR-011) ;
3. aucune zone n'est jamais calculée sur une série ajustée.

Ceci ferme la boucle ouverte à l'étape 2.2 : les « faux FVG » n'y sont plus corrigés après coup,
ils sont rendus impossibles par la définition.

## 4. Le statut est un automate ; la pénétration est continue

Tes quatre statuts — neuf, touché, mitigé, invalidé — forment un automate, comme les pivots
(ADR-054) et la structure (ADR-057). Une précision est nécessaire : **la grandeur physique est la
profondeur de pénétration**, continue ; les statuts en sont des découpages déclarés.

```
profondeur_max_atteinte ∈ [0, 1]   ← la mesure
NEUF (0) → TOUCHÉ (>0) → MITIGÉ (≥ seuil déclaré) → COMBLÉ (1) → INVALIDÉ
```

`INVALIDÉ` demande sa propre définition, absente de ta liste : une zone est invalidée lorsque le
prix l'a entièrement traversée **et poursuivi au-delà** — la région a alors été négociée dans les
deux sens et ne représente plus aucun déséquilibre.

Sont conservés : la profondeur maximale atteinte, la profondeur de **chaque** visite, le nombre
de visites, et la réaction observée à chacune. Le nombre de remplissages de ta liste devient
ainsi une série d'événements datés plutôt qu'un compteur.

## 5. Les 50 % sont une convention, pas un mécanisme

L'encroachment à mi-zone est un repère largement utilisé. Aucun mécanisme de marché ne le
justifie *a priori* : c'est le milieu géométrique d'une zone définie par une convention
d'agrégation.

Ce n'est pas une raison de l'écarter — c'est une raison de le **tester**, et c'est facile :

> mesurer la **distribution empirique des profondeurs de pénétration au moment où le prix
> repart**.

- concentration nette autour de la moitié → le repère a un contenu, il est retenu et son seuil
  est calibré sur la mesure plutôt que fixé à 50 % ;
- distribution plate → le niveau est décoratif, et le seuil `MITIGÉ` doit être choisi sur un
  autre critère, ou abandonné.

Le moteur publie donc la profondeur continue, et le seuil de mitigation est un **paramètre
calibré**, non une constante. Il se peut qu'il tombe près de la moitié ; il se peut que non. La
mesure tranchera.

## 6. Le test décisif : autre chose que « les impulsions retracent » ?

Comme pour le BOS en `04b` §9, ce moteur porte un risque de circularité, et il est sévère.

Une zone de déséquilibre est **créée par un mouvement rapide**. Or les mouvements rapides
retracent partiellement, en moyenne, quel que soit ce qu'ils ont laissé derrière eux. Constater
que « 80 % des déséquilibres sont comblés » peut donc être parfaitement vrai et totalement
dépourvu d'information.

**Le bon test compare à des régions témoins**, tirées dans les mêmes conditions : même distance
au prix, même volatilité, même position dans la jambe d'impulsion, mais **sans** déséquilibre
mesuré.

- le prix revient-il plus souvent, ou plus vite, dans les zones de déséquilibre que dans les
  témoins ?
- **réagit-il différemment en y arrivant** ? C'est la question qui compte : le retour est
  probablement banal, la réaction ne l'est peut-être pas.

Si les deux réponses sont négatives, le déséquilibre est une reformulation du retracement, et
il entre dans la fusion comme **une seule source avec l'impulsion**, pas comme une seconde.

## 7. La densité tue la confluence

Problème pratique sous-estimé, et il compromet un attribut entier de ta liste.

Les zones de déséquilibre sont **nombreuses**. Sans règle d'expiration ni plafond, la carte s'en
couvre — et à partir d'une certaine densité, **tout prix se trouve « en confluence » avec
quelque chose**. L'attribut de confluence ne mesure alors plus une coïncidence remarquable, mais
la densité du détecteur lui-même.

Deux mécanismes obligatoires :

1. **expiration** — une zone disparaît après une durée, une distance parcourue en unités de
   volatilité, ou un nombre de visites. Le critère d'expiration est calibré, pas choisi ;
2. **plafond de densité** — le nombre de zones actives par niveau de décomposition est **borné**.
   Seules les meilleures selon le score de qualité sont conservées.

Sans le second, la confluence n'est pas mesurable : elle est garantie par construction. Et une
confluence garantie n'est pas une confirmation, c'est un miroir.

## 8. Le score de qualité

Construit comme celui du MSS (ADR-059) : **attributs continus, découpage par quantile**, jamais
une somme pondérée aux poids inventés.

Attributs retenus, tous normalisés et conditionnés à la session :

| Attribut | Mesure |
| --- | --- |
| Intensité du déséquilibre | creux de densité rapporté aux voisins (§2) |
| Taille | rapportée à la volatilité, avec la réserve d'ATR de `04a` §7 |
| Vigueur du déplacement | volume et vitesse de la jambe créatrice |
| Contexte horaire | tranche de session de création |
| Régime de marché | à la création |
| Confluence structurelle | position relative aux pivots et à l'état structurel — **sous réserve du §7** |
| Fraîcheur | âge, en volatilité parcourue plutôt qu'en temps |

Et il est soumis à la même exigence que le score de qualité des données (ADR-027) : **s'il ne
prédit pas un comportement différencié, il est retiré.** Un score qui ne sépare rien donne un
faux sentiment de hiérarchie.

## 9. Combien de sources indépendantes reste-t-il, réellement ?

Il faut le dire à ce stade plutôt que devant la fusion.

Le déséquilibre est créé par une jambe d'impulsion. La rupture de structure (`04b`) se produit
sur cette même jambe. La jambe elle-même est un objet de la décomposition (`04a`). Et
l'accélération qui l'a produite est déjà décrite par les moteurs de l'étape 3.

**Un même événement de marché est donc décrit par : une jambe, un pivot, une rupture, un
déséquilibre, un balayage, un déséquilibre de flux, un delta et éventuellement une absorption.**
Huit sorties. Une cause.

Le décompte honnête, à ce stade du projet :

| Familles | Sorties | Sources d'information réellement distinctes |
| --- | --- | --- |
| Microstructure (3.1 – 3.6) | 6 | **une** — le flux d'ordres |
| Structure (4.1 – 4.3) | 3+ | **une** — la géométrie du chemin de prix |
| Physique et macro (2.3) | plusieurs | une, et à basse fréquence |

Ce n'est pas un défaut de conception : chaque vue extrait des grandeurs différentes et utiles.
Mais cela impose deux choses, sans lesquelles le système produira une confiance très supérieure à
ce que les données autorisent :

- la fusion pondère par **famille**, pas par sortie (ADR-035) ;
- **tout nouveau moteur doit démontrer un apport incrémental conditionnel** aux moteurs déjà
  présents, et non un pouvoir prédictif absolu.

Corollaire à garder en tête pour les étapes suivantes : l'ajout d'un dixième moteur sur la même
source améliorera probablement le backtest et dégradera la calibration. C'est la trajectoire
classique de ce type de projet, et l'ADR-035 existe pour l'empêcher.

## 10. Contrat de sortie

```
ImbalanceZone {
  méthode              DENSITÉ | TROIS_BOUGIES_REPLI        (§2)
  niveau_θ, correspondance_affichage
  sens                 HAUSSIER | BAISSIER
  bornes { bas, haut }
  intensité            creux de densité mesuré ; null si méthode = repli

  instant_création, instant_confirmation                    (ADR-053)
  référentiel          contrat, série brute, convention d'agrégation
  exclusions_vérifiées fermeture, coupure, férié, frontière de roll  (§3)

  profondeur_max_atteinte      ∈ [0,1] — la mesure (§4)
  visites[]            { instant, profondeur, réaction observée }
  statut               NEUF | TOUCHÉ | MITIGÉ | COMBLÉ | INVALIDÉ
  seuil_mitigation     paramètre calibré, non constant (§5)

  âge_en_volatilité, expiration_prévue                      (§7)
  rang_de_densité      position dans le plafond du niveau (§7)

  attributs_qualité[], score_qualité                        (§8)
  recouvrements_déclarés[]   jambe d'impulsion, rupture, pivot (§9)
  statuts_entrées[]
}
```

## 11. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Profil d'activité par niveau de prix | FRAIS, intégrité OK | bascule en méthode de repli, incertitude majorée |
| Série brute d'un contrat unique, sans trou | intégrité OK | **indisponible** |
| Calendrier de marché | ADR-021 | **indisponible** — sans lui, les fermetures sont prises pour des déséquilibres (§3) |
| Phase de rollover | ADR-013 | **indisponible** pendant la migration |
| Décomposition θ et jambes d'impulsion | `04a` | **indisponible** |
| Estimateur de volatilité | FRAIS | dégradé — tailles non normalisées |

La troisième ligne est stricte à dessein : sans calendrier, ce moteur produit ses signaux les
plus spectaculaires et les plus faux.

## 12. À mesurer avant tout usage

- **le test des témoins du §6 en premier** — il décide si ce moteur est une source ou un
  habillage du retracement ;
- distribution empirique des profondeurs de rebond, pour valider ou invalider le repère à
  mi-zone (§5) ;
- écart entre méthode par densité et méthode de repli, sur les périodes où les deux sont
  calculables — c'est aussi la mesure de ce que le spot perd faute de volume ;
- nombre de zones actives par niveau, avant et après plafonnement, et effet du plafond sur la
  valeur prédictive de la confluence (§7) ;
- pouvoir de séparation du score de qualité (§8), sous peine de retrait ;
- part des zones exclues par les règles du §3 — si elle est élevée, cela confirme l'ampleur du
  piège évité.
