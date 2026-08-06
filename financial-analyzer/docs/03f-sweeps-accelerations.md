# 03f — Balayages et accélérations

> Statut : **figé** (étape 3.6 de la spécification).
> Sixième vue de microstructure (étage 4). À lire après `03a` à `03e`.

## 1. Trois événements de marché, et un défaut de données

Les quatre cas à distinguer selon l'étape 3.6 ne sont pas de même nature. Trois décrivent un
comportement du marché ; le quatrième décrit une **panne du socle**.

| Cas | Nature | Traité par |
| --- | --- | --- |
| Déplacement institutionnel | événement de marché | ce moteur |
| Trou de liquidité | événement de marché | ce moteur |
| Impulsion de nouvelle | événement de marché | ce moteur, avec le calendrier et l'inter-marchés |
| **Pic dû au spread** | **défaut de données** | **le contrôle qualité, en amont** |

Un pic de prix médian causé par l'élargissement asymétrique du spread, ou par un fournisseur
qui déraille, n'est pas un mouvement : c'est une cotation invalide. Il relève des mécanismes
déjà posés — divergence idiosyncratique (ADR-009), rang quantile de spread (ADR-007), quorum
(ADR-006).

**En faire une classe du classifieur serait une erreur d'architecture.** Le moteur apprendrait
à tolérer des données corrompues au lieu que le socle les rejette, et le défaut deviendrait
invisible : chaque pic de spread serait « expliqué » plutôt que signalé. La règle est
l'inverse : **si un tel pic atteint ce moteur, c'est le contrôle qualité qui a échoué**, et
l'incident doit être enregistré comme tel.

Il reste trois classes à discriminer, et elles ont des suites opposées — d'où l'importance de
bien les séparer.

## 2. Le discriminant principal : déplacement rapporté au volume

C'est ta cinquième puce — « déplacement avec ou sans volume » — et c'est le meilleur critère
disponible. Il s'agit de l'impact réalisé déjà défini en `03a` §6 : déplacement du prix par
unité de volume agressif, normalisé par la profondeur.

| Classe | Volume | Impact par unité de volume | Retour du prix |
| --- | --- | --- | --- |
| **Déplacement institutionnel** | élevé | ordinaire ou modéré | faible — le prix reste |
| **Trou de liquidité** | **faible** | **anormalement élevé** | fort et rapide |
| **Impulsion de nouvelle** | élevé | élevé | partiel |

Un trou de liquidité se reconnaît à ceci : **le prix a beaucoup bougé alors que peu de contrats
ont changé de mains**. Rien n'a été réévalué, il n'y avait simplement personne. Un déplacement
institutionnel, à l'inverse, coûte cher à produire — c'est ce coût qui en fait un signal.

## 3. Ce qu'il faut mesurer avant l'événement

Piège méthodologique majeur : **après un balayage, tous les carnets paraissent minces.** La
liquidité a été consommée. Mesurer la profondeur après coup ne distingue donc rien du tout.

Le discriminant est l'**état du carnet immédiatement avant** le premier événement de la
séquence : profondeur cumulée, nombre de niveaux garnis, taille moyenne par niveau, comparés à
leur normale conditionnelle (ADR-007).

- carnet **normalement garni** puis consommé → quelqu'un a payé pour traverser ;
- carnet **déjà vide** avant le déclenchement → trou de liquidité, le prix a glissé faute
  d'opposition.

**Exigence d'implémentation** : l'état du carnet est capturé en continu de façon à pouvoir être
consulté *tel qu'il était* juste avant tout événement détecté — ce qui est une application
directe de la bitemporalité (ADR-004, ADR-008), et un coût de stockage à budgéter.

## 4. L'impulsion de nouvelle : la simultanéité inter-marchés

Deux sous-cas, de difficulté très inégale.

**Publication programmée** — l'instant est connu à l'avance (`02d` §8). Ce n'est pas une
inférence mais une **lecture d'état** : le moteur consulte le calendrier et sait qu'il est dans
une fenêtre de publication. Aucune classification statistique n'est nécessaire, et prétendre le
contraire serait ajouter du bruit à une information certaine.

**Nouvelle non programmée** — déclaration, incident géopolitique, rumeur. Là, l'instant n'est
pas connu. Le meilleur discriminant disponible est la **simultanéité inter-marchés** :

> une information réelle sur l'or reprice **aussi** le dollar, les taux réels et l'argent.
> Un trou de liquidité sur l'or ne bouge que l'or.

C'est un critère puissant, et c'est aussi le plus difficile à falsifier : provoquer un mouvement
simultané et cohérent sur plusieurs marchés corrélés n'est pas à la portée d'un accident de
carnet.

**Lacune à signaler franchement** : les étapes 2.1 à 2.4 ne prévoient **aucune donnée
inter-marchés**. Le socle actuel ne contient que l'or — spot, listé, physique. En l'état, ce
discriminant n'est pas calculable, et le moteur ne pourra pas séparer proprement l'impulsion de
nouvelle du trou de liquidité.

Deux options, à trancher : ajouter au socle un flux minimal de marchés corrélés, ou accepter que
cette classe reste confondue et le déclarer explicitement dans la sortie. La seconde option est
acceptable, la confusion silencieuse ne l'est pas.

## 5. Décrire la cascade, pas l'intention

Ta dernière puce mentionne une « possible chasse de stops ». Le phénomène observable est réel et
bien documenté :

- des ordres de protection s'accumulent juste au-delà des niveaux visibles ;
- lorsque le prix les atteint, ils se déclenchent **mécaniquement** ;
- ces déclenchements sont des ordres agressifs, qui consomment la liquidité et poussent le prix
  plus loin, déclenchant les suivants ;
- une fois la réserve épuisée, la pression disparaît d'un coup et le prix revient souvent.

Ce qui n'est **pas** observable, c'est qu'un acteur ait délibérément provoqué la séquence. Cette
intention est un état latent invérifiable, et l'ADR-046 s'applique : le système ne publie pas de
probabilité sur ce type d'état.

**Le motif est donc nommé par ce qu'on voit** — cascade de liquidation au-delà d'un niveau —
et non par un mobile supposé. La sortie décrit : niveau franchi, concentration de l'agression
juste au-delà, brièveté de la poussée, part retracée.

Ce motif recouvre largement le climax de l'ADR-044 : c'en est le mécanisme le plus fréquent. Les
deux détecteurs doivent être réconciliés plutôt que juxtaposés — un même événement ne doit pas
être compté deux fois par la fusion (ADR-035).

## 6. Définir un balayage sans seuil absolu

« Consommation rapide de plusieurs niveaux » exige trois paramètres, dont aucun ne peut être
fixé en absolu :

| Paramètre | Référence |
| --- | --- |
| Combien de niveaux | rapporté à la profondeur habituelle du moment |
| En combien de temps | en **temps-événement** (ADR-032), et relativement au rythme normal de la tranche de session |
| Par quoi | idéalement un ordre unique — donc **observable** si la donnée par ordre existe (ADR-045), inféré sinon |

La troisième ligne mérite attention : un balayage par un ordre unique et un balayage par
cinquante ordres simultanés de participants différents n'ont pas la même signification. Le
premier est une décision ; le second est une panique ou une réaction en chaîne. Si la donnée
par ordre est disponible, cette distinction est **observée** et non supposée.

Le seuil de déclenchement se calibre sur le modèle nul (ADR-034) : à quelle fréquence N niveaux
sont-ils consommés en un tel intervalle **par le fonctionnement ordinaire** du marché à cette
heure ?

## 7. La classe ne peut être confirmée qu'après coup

Comme pour tous les motifs (ADR-038), la classification définitive dépend de la suite : le prix
reste-t-il, revient-il ? Le moteur émet donc à l'instant `t` une **distribution sur les
classes**, jamais une étiquette unique, et la classe réalisée est étiquetée plus tard.

C'est important pour la calibration : les trois classes ont des suites opposées, donc une
étiquette prématurée serait à la fois affirmative et fausse dans une part significative des cas.

## 8. Le vrai produit : le nouveau prix est-il accepté ?

Le balayage lui-même est rarement exploitable — il est trop rapide, et la latence l'a déjà
rendu inaccessible (ADR-029). Ce qui est exploitable, c'est **ce qui se passe juste après** :

> la liquidité se reconstitue-t-elle **au nouveau niveau**, ou le prix revient-il chercher
> l'ancien ?

- reconstitution au nouveau niveau → le marché a **accepté** le nouveau prix, le déplacement
  est une réévaluation ;
- non-reconstitution et retour → le déplacement était **mécanique**, il se referme.

C'est la mesure de résilience de `03a` §6, appliquée à un événement identifiable et daté. Elle
est plus lente que le balayage — donc atteignable malgré la latence — et elle porte l'essentiel
de l'information.

Elle fournit aussi l'invalidation, conformément à la logique désormais commune à toute la
famille (ADR-040, ADR-048) : si le prix repasse durablement de l'autre côté de l'extrême du
balayage, l'hypothèse de réévaluation est morte.

## 9. Contrat de sortie

```
SweepEvent {
  as_of, échelle
  direction
  niveaux_consommés, étendue_prix
  durée_horloge, durée_événement
  origine                    ORDRE_UNIQUE | MULTIPLE | INDÉTERMINÉE   (§6)

  # état AVANT l'événement — le discriminant (§3)
  profondeur_avant, niveaux_garnis_avant, écart_à_la_normale_avant

  volume_agressif, impact_par_unité_de_volume        (§2)
  contexte_calendrier        HORS_FENÊTRE | FENÊTRE_PUBLICATION | POST_PUBLICATION
  simultanéité_intermarchés  valeur, ou INDISPONIBLE si le socle ne la fournit pas (§4)
  franchissement_de_niveau   niveau visible franchi, concentration au-delà (§5)

  distribution_classes {     jamais une étiquette unique (§7)
    institutionnel, trou_de_liquidité, impulsion_nouvelle, indéterminé
  }
  état                       EN_ATTENTE | PRIX_ACCEPTÉ | PRIX_REJETÉ | EXPIRÉ
  reconstitution_au_nouveau_niveau, part_retracée      (§8)
  invalidation { niveau, condition }

  recouvrements_déclarés[]   famille microstructure ; **recouvrement fort avec le climax**
  score_motif, proba_prix_accepté       (calibrée si mesurée, sinon échelle nommée)
  confiance, abstention + motif
  statuts_entrées[]
  rôle_autorisé              VETO par défaut
}
```

Il n'y a **pas** de classe « pic de spread » dans `distribution_classes` : ce cas ne doit jamais
parvenir jusqu'ici (§1).

## 10. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Carnet, avec historique court permettant l'état *avant* | intégrité OK | **indisponible** — sans référence antérieure, aucune classe n'est séparable (§3) |
| Transactions avec côté agresseur et horodatage natif | FRAIS | **indisponible** |
| Calendrier macro | ADR-021 | dégradé — l'impulsion programmée redevient une inférence |
| Séries inter-marchés | FRAIS | dégradé, `simultanéité_intermarchés = INDISPONIBLE` (§4) |
| Verdict qualité sain sur le spread | portes dures franchies | **indisponible** — un pic de spread doit être rejeté en amont (§1) |
| Marquage de liquidité implicite | présent | dégradé — la profondeur avant l'événement est surestimée |

## 11. À mesurer avant tout usage

- séparabilité effective des trois classes à partir des grandeurs du §2 et du §3, mesurée sur
  des cas étiquetés a posteriori ;
- fréquence du motif sous modèle nul, par tranche de session (§6) ;
- taux de base de `PRIX_ACCEPTÉ` par classe — c'est la mesure qui donne sa valeur au moteur ;
- gain apporté par la simultanéité inter-marchés, **s'il est possible de l'obtenir**, comparé au
  coût d'ajouter ces flux au socle (§4) ;
- recouvrement effectif avec le détecteur de climax : proportion d'événements détectés par les
  deux, et écart d'issue entre eux ;
- écart d'issue entre balayages d'origine unique et balayages d'origine multiple, lorsque la
  donnée par ordre le permet (§6).
