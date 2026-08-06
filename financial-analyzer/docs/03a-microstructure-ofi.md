# 03a — Moteur de microstructure : déséquilibre de flux d'ordres

> Statut : **figé** (étape 3.1 de la spécification).
> Premier agent spécialisé (étage 4 du pipeline). Consomme l'étage 3, produit un `AgentOutput`.

## 1. Ce que mesure réellement le déséquilibre de flux

L'intuition « acheteurs contre vendeurs » est correcte mais insuffisante, et l'étape 3.1 le dit
justement : il ne faut pas regarder que les ordres affichés.

La formulation retenue mesure, à chaque modification du carnet, **la variation nette de la file
d'attente aux meilleures limites** — ce qui unifie naturellement les trois mécanismes qui la
font bouger :

| Événement | Effet sur la file | Contribution |
| --- | --- | --- |
| Ordre **ajouté** à l'achat | allonge la file acheteuse | positif |
| Ordre **retiré** à l'achat | raccourcit la file acheteuse | négatif |
| **Exécution** contre la file acheteuse | consomme la file acheteuse | négatif |
| Symétriquement à la vente | | signes inversés |

Le point important : **un retrait d'ordre acheteur et une vente agressive ont le même effet
sur le carnet**, et la mesure les traite comme tels. Un déséquilibre construit uniquement sur
les transactions ignore la moitié de ce qui déplace le prix — souvent la moitié la plus
rapide, car annuler est instantané là où exécuter coûte le spread.

Un déplacement de la meilleure limite est traité comme une remise à zéro de file, et non comme
une variation de taille : c'est ce qui distingue une file qui se vide d'un niveau qui disparaît.

## 2. L'OFI brut n'est pas comparable dans le temps

Un même déséquilibre ne produit pas le même déplacement de prix selon l'épaisseur du carnet.
En carnet mince, un flux modeste déplace violemment ; en carnet épais, le même flux est absorbé.

**Règle** : l'OFI est toujours rapporté à la profondeur qui prévalait — la grandeur exploitable
est un déséquilibre *par unité de profondeur*, jamais un déséquilibre absolu. Un seuil posé sur
l'OFI brut mesure en réalité l'heure de la journée.

S'y ajoutent les conditionnements déjà posés : tranche de session, régime de volatilité, phase
de rollover (ADR-007, ADR-013). Un OFI « fort » en creux asiatique et un OFI « fort » au
recouvrement Londres–New York ne sont pas la même observation.

## 3. Le piège central : contemporain n'est pas prédictif

C'est le point qui décide de l'utilité réelle de ce moteur.

La relation entre déséquilibre de flux et variation de prix **sur la même fenêtre** est forte
et robuste. C'est un résultat solide, et c'est précisément ce qui rend le piège si efficace :
une régression bien construite affiche un pouvoir explicatif impressionnant, et il est
naturel de conclure qu'on tient un signal.

Or ce pouvoir explicatif est en grande partie **une identité comptable, pas une prédiction** :
les ordres qui ont consommé la file *sont* le mécanisme par lequel le prix a bougé. Mesurer les
deux sur la même fenêtre revient à observer une cause et son effet immédiat, puis à les
présenter comme une anticipation.

La capacité **prédictive** — déséquilibre mesuré sur `[t−Δ, t]`, rendement mesuré sur
`[t, t+h]` — est d'un ordre de grandeur inférieure, et **décroît en quelques secondes**.

**Règles imposées à tout signal de ce moteur :**

1. la fenêtre de mesure et la fenêtre de rendement sont **strictement disjointes** ;
2. entre les deux s'intercale un **décalage égal à la latence réelle de bout en bout** —
   réception, décodage, calcul, envoi d'ordre, accusé de réception ;
3. tout résultat obtenu sans ce décalage est déclaré non exploitable, quelle qu'en soit la
   qualité statistique.

Sans le point 2, on « prédit » un mouvement déjà survenu au moment où l'on aurait pu agir.

## 4. Demi-vie contre latence : ce moteur sert-il à entrer ?

Question à trancher par la mesure, pas par principe.

Le protocole est simple : mesurer la **demi-vie** du pouvoir prédictif du signal, puis la
comparer à la latence de bout en bout du système réel — celle qui inclut le trajet jusqu'au
broker et l'accusé de réception, pas celle du calcul.

| Résultat | Rôle du moteur |
| --- | --- |
| Demi-vie ≫ latence | déclencheur d'entrée légitime |
| Demi-vie ≈ latence | **calage d'exécution** dans une fenêtre déjà décidée, et veto |
| Demi-vie ≪ latence | veto et contexte uniquement ; aucun déclenchement |

Un élément du contexte pousse fortement vers les deux dernières lignes, et il vaut mieux
l'énoncer maintenant : **la microstructure observée est celle du listé, alors que l'exécution
se fait sur le spot** (Q11). Le signal doit donc traverser la base avant d'être exploitable, ce
qui ajoute latence *et* bruit. Un carnet de broker spot, quand il existe, est par ailleurs
nettement moins fiable (Q6).

Ce n'est pas une raison d'écarter le moteur : **veto et calage d'exécution ont une valeur
économique réelle** — éviter une entrée au mauvais moment et améliorer le prix d'exécution
agissent directement sur l'espérance nette de frais, qui est le critère du système. Mais le
rôle doit être établi par la mesure avant tout usage, et non supposé.

## 5. Absorption : pourquoi l'OFI seul se lit parfois à l'envers

C'est la nuance la plus rentable de cette étape, et l'étape 3.1 la désigne dans sa dernière
puce — « la capacité du prix à progresser après les achats ou ventes ».

Croiser le déséquilibre et le déplacement de prix effectif donne quatre régimes, et **deux
d'entre eux inversent la lecture naïve** :

| Déséquilibre | Le prix progresse | Le prix ne progresse pas |
| --- | --- | --- |
| **Fortement acheteur** | continuation — la demande consomme l'offre disponible | **absorption** : un vendeur passif encaisse tout le flux acheteur sans céder de terrain. Signal *défavorable* aux acheteurs |
| **Faible** | **fragilité** : le prix se déplace sans flux, carnet mince, mouvement peu fiable | équilibre, aucune information |

Lire un OFI fortement acheteur comme haussier alors que le prix ne progresse pas, c'est acheter
exactement face à celui qui absorbe — souvent le participant le mieux informé de la fenêtre.

**Règle** : le déséquilibre n'est **jamais** publié seul. Il est systématiquement apparié à la
progression de prix réalisée sur la même fenêtre, et c'est le **couple** qui constitue la
feature. Un moteur qui sort un OFI nu produit un signal ambigu dont le signe peut être faux.

## 6. Vitesse de consommation et résilience

Les deux dernières puces de l'étape 3.1 se formalisent ainsi :

- **vitesse de consommation** — rythme auquel la meilleure limite est absorbée, comparé au
  rythme auquel elle se reconstitue. Ce qui casse un niveau n'est pas la consommation seule,
  c'est la consommation *plus rapide que le réapprovisionnement* ;
- **impact réalisé** — déplacement du prix médian par unité de volume agressif, normalisé par
  la profondeur ;
- **résilience** — part du déplacement effacée dans les instants qui suivent. Un retour rapide
  et complet signifie que la liquidité s'est reconstituée et que rien n'a été réévalué ; une
  persistance signifie une réévaluation réelle.

C'est le triplet impact / résilience / vitesse de reconstitution qui distingue un mouvement
porteur d'information d'une simple secousse de liquidité — distinction que ni le volume ni
l'OFI ne peuvent produire séparément.

## 7. Ce qui contamine la mesure

Quatre sources de contamination, toutes déjà identifiées en amont ou à traiter ici.

**7.1 — Liquidité implicite.** Une partie de la profondeur affichée provient d'ordres de spread
calendaire recombinés (`02b-futures-comex.md` §4.3). Un OFI calculé dessus mesure une activité
qui n'a jamais eu lieu sur cette échéance. **L'OFI de référence est calculé sur la liquidité
réelle seule** ; la variante incluant l'implicite est conservée séparément, l'écart entre les
deux étant lui-même informatif.

**7.2 — Ordres éphémères.** Des ordres ajoutés puis retirés en quelques millisecondes gonflent
les compteurs sans représenter d'intention exécutable. Deux réponses complémentaires :
pondérer les ordres par leur **durée de vie**, et suivre le **ratio ajouts/annulations** comme
feature distincte — il décrit le type de participants actifs, pas la direction.

Le système ne cherche pas à qualifier l'intention derrière ces ordres. Il se protège d'un
signal trompeur, ce qui est une posture défensive et suffit à l'objectif.

**7.3 — Côté agresseur inféré.** Lorsque la source fournit le côté agresseur, il est utilisé
tel quel. Lorsqu'il doit être déduit, la valeur est marquée `DÉRIVÉ` (ADR-024) et l'erreur
d'inférence est propagée comme incertitude. Une déduction silencieuse est interdite.

**7.4 — Intégrité du carnet.** Un carnet reconstruit avec un trou de séquence produit un OFI
parfaitement calculé sur une fiction. Ce moteur exige un statut d'intégrité sain
(`02b-futures-comex.md` §4, ADR-024) et se déclare indisponible sinon.

## 8. Échantillonnage en temps-événement

Calculer ces grandeurs sur des intervalles d'horloge fixes mélange des périodes denses et des
périodes creuses : une seconde de recouvrement Londres–New York et une seconde de creux
asiatique ne contiennent pas le même nombre d'événements, et leurs distributions n'ont rien de
commun.

**Règle** : les features de microstructure sont échantillonnées en **temps-événement** — par
nombre d'événements, de transactions ou de volume écoulé — et non en temps d'horloge. Les
distributions deviennent nettement plus stables, ce qui est une condition pratique pour que les
seuils conditionnels de l'ADR-007 soient estimables.

Les grandeurs restent horodatées en temps d'horloge pour l'audit et la rejouabilité : c'est le
pas d'échantillonnage qui change, pas la datation.

## 9. Profondeur multi-niveaux

Le déséquilibre limité à la meilleure limite ignore ce qui se prépare derrière. L'étendre aux
niveaux suivants améliore le pouvoir explicatif, mais les niveaux profonds sont plus bruités et
plus exposés aux ordres éphémères.

**Règle** : les déséquilibres par niveau sont conservés **séparés**, jamais pré-additionnés en
un agrégat unique. La combinaison est apprise à la fusion (étage 7), où elle peut être
pondérée par régime — un carnet profond n'a pas la même signification en séance calme et en
séance de publication.

## 10. Contrat de sortie

```
AgentOutput (microstructure) {
  as_of, horizon_déclaré
  déséquilibre_normalisé[]        par niveau, rapporté à la profondeur
  progression_prix_appariée       indissociable du déséquilibre (§5)
  régime_lu                       CONTINUATION | ABSORPTION | FRAGILITÉ | ÉQUILIBRE
  impact_réalisé, résilience, vitesse_consommation, vitesse_reconstitution
  ratio_ajouts_annulations, durée_de_vie_médiane_des_ordres
  part_implicite                  écart entre carnet réel et carnet incluant l'implicite
  confiance
  abstention                      + motif
  preuves[]                       références aux événements ayant produit la lecture
  statuts_entrées[]               propagés selon ADR-025
  rôle_autorisé                   DÉCLENCHEUR | CALAGE | VETO   ← issu de la mesure §4
}
```

Le champ `rôle_autorisé` n'est pas décoratif : il est renseigné par la mesure de demi-vie et
**limite mécaniquement** l'usage que l'étage 9 peut faire de cette sortie.

## 11. Dépendances et indisponibilité

Déclaration au sens de l'ADR-026 :

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Carnet du contrat principal | intégrité OK, provenance OBSERVÉ ou RECONSTRUIT validé | **indisponible** |
| Flux de transactions avec côté agresseur | fraîcheur FRAIS | **indisponible** |
| Marquage de liquidité implicite | présent | dégradé, incertitude majorée |
| Profondeur au-delà du premier niveau | présent | dégradé, §9 restreint au premier niveau |
| Contrat principal identifié | ADR-010 | **indisponible** |
| Phase de rollover | ADR-013 | dégradé, incertitude majorée pendant la migration |

Conformément à l'ADR-026, une indisponibilité est transmise à l'étage 7 comme **ignorance**, et
élargit l'incertitude — elle n'est jamais un silence neutre.

## 12. À mesurer avant tout usage

Aucun de ces éléments n'est supposé connu :

- demi-vie du pouvoir prédictif, par tranche de session et par régime de volatilité ;
- latence de bout en bout réelle du système, mesurée jusqu'à l'accusé de réception du broker ;
- gain apporté par les niveaux profonds, une fois le premier niveau connu ;
- fréquence et signature statistique des quatre régimes du §5, et pouvoir prédictif de chacun ;
- transmission effective du signal listé vers le spot, à travers la base ;
- distributions conditionnelles servant à normaliser, et stabilité de ces distributions dans le
  temps.

Tant que le premier point n'est pas mesuré, `rôle_autorisé` reste à `VETO`. C'est le réglage le
plus prudent, cohérent avec I4 : le moteur commence par sa capacité à empêcher, et ne gagne le
droit de déclencher que sur preuve.

## 13. Questions ouvertes

- **Q19** — la latence de bout en bout est-elle mesurable dès maintenant sur l'infrastructure
  cible ? C'est le paramètre qui détermine à lui seul le rôle de ce moteur, et il ne dépend pas
  de la qualité du modèle.
- **Q20** — le carnet spot des brokers retenus est-il exploitable, ou la microstructure
  repose-t-elle intégralement sur le listé ? Dans le second cas, toute lecture doit franchir la
  base (Q11) et ce coût doit apparaître dans l'espérance nette.
- **Q21** — quelle profondeur d'historique de carnet est conservée ? Sans historique
  événementiel, ni la demi-vie ni les distributions conditionnelles ne sont estimables, et le
  moteur reste bloqué en mode veto par construction.
