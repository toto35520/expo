# 03d — Moteur d'épuisement

> Statut : **figé** (étape 3.4 de la spécification).
> Quatrième vue de microstructure (étage 4). À lire après `03a` à `03c`.

## 1. Absorption et épuisement produisent la même image

La distinction de l'étape 3.4 est exacte :

> absorption = quelqu'un bloque le mouvement · épuisement = les attaquants perdent leur force

Mais elle porte sur une **cause**, et la cause n'est pas observable. Ce que le système voit dans
les deux cas est identique : **du volume agressif et une absence de progression du prix.**

Un détecteur construit sur cette image seule ne distingue rien. Il produit une étiquette
choisie par l'analyste, pas par la donnée — et les deux motifs ont des suites différentes, donc
l'erreur d'étiquetage se paie directement.

## 2. Le discriminant est dynamique, pas statique

La séparation n'existe pas dans l'instantané. Elle existe dans les **dérivées** :

| | Agressivité au fil du temps | Réapprovisionnement du côté passif |
| --- | --- | --- |
| **Absorption** | soutenue, voire croissante | **fort et régulier** — la file est nourrie |
| **Épuisement** | **décroissante** — les attaques s'espacent et rapetissent | quelconque, souvent faible |

Autrement dit : dans l'absorption, le côté passif est **fort** ; dans l'épuisement, le côté
agressif est **faible**. Ce n'est pas la même chose, et cela se mesure — non par l'intensité,
mais par la **pente**.

Ta troisième puce — « diminution de l'agressivité » — n'est donc pas un symptôme parmi cinq.
**C'est le critère définitionnel.** Les autres puces sont partagées avec l'absorption et ne
séparent rien.

Grandeurs mesurées, toutes normalisées (ADR-028, ADR-033) et en temps-événement (ADR-032) :
débit de volume agressif, taille moyenne des empreintes agressives, fréquence des agressions,
rapport agressif/passif — et pour le côté passif, délai et volume de reconstitution après
chaque exécution.

## 3. Tes cinq symptômes décrivent deux motifs

En les relisant :

| Symptôme | Appartient à |
| --- | --- |
| volume très important | commun à l'absorption — ne sépare rien |
| faible progression du prix | commun à l'absorption — ne sépare rien |
| **diminution de l'agressivité** | **épuisement progressif** — le critère |
| incapacité à franchir la liquidité | absorption vue de l'autre côté |
| **accélération suivie d'un rejet** | **motif différent** (§6) |

La dernière ligne n'est pas un épuisement progressif. Une accélération violente suivie d'un
rejet n'est pas « les attaquants qui s'essoufflent » : c'est une poussée qui échoue d'un coup.
Mécanisme différent, signature différente, horizon différent.

**Les fusionner dans un détecteur unique garantit un taux de base illisible** — deux populations
mélangées, dont les issues se compensent. Le système les traite comme **deux motifs distincts**.

## 4. L'épuisement n'a de sens qu'ancré sur une impulsion

Un motif défini par une **diminution** pose un problème que l'absorption ne posait pas :
l'agressivité diminue en permanence. Après chaque poussée, à chaque pause, dans chaque creux de
liquidité. La fréquence inconditionnelle de « l'agressivité baisse » est énorme, et un détecteur
non ancré se déclenche en continu sans rien signaler.

**Conditions d'ancrage obligatoires :**

1. une **impulsion directionnelle préalable** d'amplitude et de durée qualifiées — l'épuisement
   est l'essoufflement de quelque chose, il faut donc que ce quelque chose ait existé ;
2. un **contexte de niveau** : extension, zone antérieure, extrême de séance. Un essoufflement
   au milieu de nulle part n'est pas exploitable ;
3. une **fenêtre bornée** rattachée à l'impulsion, pas une observation flottante.

Sans ces trois conditions, le motif décrit simplement « le marché s'est calmé ».

## 5. Le piège de calendrier

L'agressivité décroît systématiquement aux transitions de séance : clôture de Londres, fin de
séance new-yorkaise, approche de la coupure quotidienne, creux asiatique, période précédant un
fixing. Un détecteur naïf y verra de l'épuisement **tous les jours, aux mêmes heures**.

C'est le même défaut que celui traité par `ABSENT_PAR_CONCEPTION` (ADR-024) : une baisse
attendue n'est pas un signal. La décroissance d'agressivité est donc évaluée **relativement à la
décroissance normale de cette tranche de session** (ADR-007, ADR-021), jamais en absolu.

Sans cette correction, le moteur produit un signal quotidien parfaitement régulier — et
parfaitement vide.

## 6. Climax : un motif distinct

L'accélération suivie d'un rejet mérite son propre détecteur, avec sa propre signature :

- **hausse brutale de la vitesse** de déplacement du prix ;
- **effondrement de la profondeur** — le carnet se vide devant le prix ;
- **élargissement du spread** pendant la poussée ;
- **retour rapide** d'une part importante du mouvement ;
- très souvent, déclenchement **juste au-delà d'un niveau visible**.

Ce dernier trait est important : ce type de poussée coïncide fréquemment avec la prise de
liquidité accumulée derrière un niveau évident. Le mouvement est réel, mais il consomme des
ordres déclenchés mécaniquement plutôt qu'une conviction — d'où l'échec immédiat une fois cette
réserve épuisée.

Le climax est donc **ancré sur un niveau**, comme l'absorption l'est (ADR-040), et produit lui
aussi une invalidation exploitable : si le prix se maintient au-delà de l'extrême du rejet,
l'hypothèse est morte.

## 7. La correction la plus rentable : épuisement n'est pas retournement

C'est l'erreur la plus coûteuse de cette famille, et elle est presque universelle.

Que les attaquants perdent leur force signifie que **le mouvement s'arrête**. Cela ne signifie
pas qu'il s'inverse. La suite la plus fréquente d'un épuisement n'est pas un retournement :
c'est une **consolidation**, éventuellement suivie d'une reprise dans le même sens plus tard.

Traduction dans le moteur de scénarios (étage 6) :

| Effet de l'épuisement | Ampleur |
| --- | --- |
| Probabilité de **continuation immédiate** | **fortement réduite** |
| Probabilité de **consolidation** | fortement augmentée — c'est l'issue modale |
| Probabilité de **retournement** | **marginalement** augmentée |

**Règle** : l'épuisement **tue une hypothèse, il n'en crée pas.** Il retire de la masse de
probabilité à la continuation ; il ne fabrique pas un signal inverse.

Prendre une position à contre-sens sur un signal d'épuisement, c'est parier sur l'issue la
moins probable des trois — avec, en prime, un stop nécessairement large puisque le mouvement
initial vient de démontrer sa puissance.

## 8. Usage principal : veto sur entrée tardive

Il découle du §7. La valeur la plus solide de ce moteur est de **empêcher de rejoindre un
mouvement qui se termine**.

C'est une fonction d'abstention, parfaitement alignée sur I4 et sur le rôle par défaut de la
famille microstructure (ADR-030). Elle a une valeur économique directe : les entrées tardives
sur mouvement épuisé sont typiquement celles dont l'espérance nette de frais est la plus
négative, parce qu'elles combinent mauvais prix d'entrée et stop éloigné.

Ce moteur commence donc, comme les précédents, avec `rôle_autorisé = VETO`.

## 9. Quatrième vue de la même source

Comme l'absorption, l'épuisement est calculé sur **le même flux d'ordres** que les étapes 3.1 et
3.2. La famille microstructure compte désormais quatre vues, et le recouvrement doit être
déclaré (ADR-035).

Le test d'admission est donc plus exigeant à chaque nouvelle vue : non pas « ce moteur
prédit-il quelque chose ? », mais **« prédit-il quelque chose de plus, une fois connus les trois
autres ? »**. À la quatrième vue d'une même source, l'apport marginal attendu est faible, et
l'hypothèse par défaut doit être qu'il est nul jusqu'à preuve du contraire.

Il reste une raison solide de le construire malgré cela : l'épuisement et l'absorption ont des
**suites différentes** alors qu'ils partagent la même image. Séparer correctement les deux
améliore le taux de base des deux — ce qui est un gain de calibration, même sans signal
supplémentaire.

## 10. Contrat de sortie

```
ExhaustionEvent {
  as_of, échelle_d_analyse
  type                         ÉPUISEMENT_PROGRESSIF | CLIMAX
  côté_épuisé                  ACHETEUR | VENDEUR

  ancrage {                    obligatoire (§4)
    impulsion { début, amplitude, durée, mesurées }
    contexte_niveau
  }

  pente_agressivité            décroissance mesurée, normalisée
  pente_attendue_session       référence de la tranche horaire (§5)
  écart_à_la_normale           la seule grandeur exploitable
  réapprovisionnement_passif   sert à séparer d'avec l'absorption (§2)

  # climax uniquement
  pic_vitesse, effondrement_profondeur, élargissement_spread, part_retracée

  effet_sur_scénarios {        §7 — jamais un signal directionnel
    continuation   -- 
    consolidation  ++
    retournement   +
  }
  invalidation { niveau, condition }
  état                         EN_ATTENTE | CONFIRMÉ | INFIRMÉ | EXPIRÉ

  score_détection
  proba_suivi                  ou null, avec échelle nommée (ADR-037)
  taux_de_base                 par régime, échecs inclus (ADR-038)
  recouvrements_déclarés[]     famille microstructure, quatre vues
  confiance, abstention + motif
  statuts_entrées[]
  rôle_autorisé                VETO par défaut
}
```

Le champ `effet_sur_scénarios` n'est pas une commodité de présentation : c'est la traduction
structurelle du §7. Ce moteur n'a **aucun champ de direction proposée**, et cette absence est
délibérée.

## 11. Dépendances et indisponibilité

| Entrée | Statut minimal | Si non satisfait |
| --- | --- | --- |
| Flux de transactions avec côté agresseur | FRAIS, intégrité OK | **indisponible** |
| Carnet — profondeur et reconstitution | intégrité OK | **indisponible** pour séparer d'avec l'absorption ; épuisement dégradé en « stagnation, cause indéterminée » |
| Tranche de session et calendrier | ADR-021 | **indisponible** — sans référence de saisonnalité, le motif est ininterprétable (§5) |
| Impulsion préalable qualifiable | présente | **indisponible** — pas d'ancrage, pas de motif (§4) |
| Base spot/listé si le niveau est traduit | FRAIS | **indisponible** pour usage spot |

La deuxième ligne mérite attention : privé du carnet, le moteur ne peut plus distinguer
épuisement et absorption. Il doit alors le **dire** — « stagnation de cause indéterminée » — au
lieu de trancher arbitrairement. C'est une application directe de l'ADR-039.

## 12. À mesurer avant tout usage

- fréquence inconditionnelle du motif **avant ancrage**, pour mesurer combien l'ancrage filtre ;
- distribution des issues à trois classes — continuation, consolidation, retournement — pour
  vérifier ou infirmer le §7. C'est la mesure la plus importante de cette étape ;
- pouvoir de séparation effectif entre épuisement et absorption : sur les cas où les deux
  détecteurs pourraient se déclencher, la pente d'agressivité et la reconstitution passive
  suffisent-elles à trancher, et le résultat prédit-il des suites différentes ?
- apport marginal conditionnel aux trois autres vues (§9) ;
- pour le climax : proportion des cas survenant juste au-delà d'un niveau visible, et écart
  d'issue entre ceux-là et les autres ;
- valeur du veto seul : combien d'entrées à espérance négative sont évitées, et à quel coût en
  entrées valables manquées. C'est le seul chiffre qui justifie ce moteur si le reste échoue.

## 13. Questions ouvertes

- **Q26** — l'épuisement doit-il pouvoir déclencher la **sortie** d'une position existante, et
  pas seulement bloquer une entrée ? C'est un usage bien plus défendable qu'une entrée à
  contre-sens, mais il relève de l'étage 11 et doit être tranché là, pas ici.
- **Q27** — l'ancrage sur impulsion suppose une définition d'impulsion. Elle sera partagée avec
  d'autres moteurs et doit donc être définie **une seule fois**, versionnée, plutôt que
  redéfinie localement par chaque détecteur — sans quoi deux moteurs parleront de la même chose
  sans se comprendre.
