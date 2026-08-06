# 02b — Futures COMEX sur l'or

> Statut : **figé** (étape 2.2 de la spécification).
> Prolonge `02-socle-donnees.md`. Couvre les mêmes étages 1 et 2 du pipeline, pour la
> composante listée du socle.

## 1. Pourquoi les futures, alors que l'instrument tradé est le spot

Ce n'est pas « une source de prix de plus ». Les futures COMEX apportent quatre choses que le
spot OTC ne peut pas fournir :

1. **la découverte de prix** — le spot OTC suit largement le listé, pas l'inverse ;
2. **des données de flux réelles** — volume échangé, agresseur, carnet, transactions
   horodatées par un moteur d'appariement unique, là où le spot n'offre que des cotations
   indicatives de brokers ;
3. **un ancrage indépendant du panel de brokers** (§7 de `02-socle-donnees.md`) : si tous les
   fournisseurs spot dérivent de concert, seule une référence extérieure le révèle ;
4. **une distribution implicite de marché**, via les options (§10) — la seule probabilité
   *cotée* accessible au système.

**Conséquence immédiate et facile à manquer : un niveau observé sur GC n'est pas un niveau sur
le spot.** Les deux diffèrent de la base, qui bouge avec les taux et le coût de portage. Toute
structure détectée sur le listé (support, résistance, zone d'imbalance) doit être **traduite
par la base courante** avant d'être utilisée sur XAU/USD, ou écartée. Reporter tel quel un
niveau GC sur un graphe spot est une erreur silencieuse qui se paie en stops mal placés.

## 2. Univers d'instruments

| Instrument | Taille | Rôle dans le système |
| --- | --- | --- |
| **GC** | 100 onces troy | découverte de prix, microstructure, flux — la référence |
| **MGC** | 10 onces troy | granularité d'exécution ; **jamais** source de signal de prix |
| Échéance principale | — | définie par la liquidité, pas par le calendrier (§2.1) |
| Échéance suivante | — | surveillée en permanence pour le rollover (§6) |
| Options sur futures | — | surface de volatilité, asymétrie, distribution implicite (§10) |

MGC est un marché dérivé de GC, plus mince : l'utiliser comme source de signal revient à
observer le reflet plutôt que l'objet. En revanche, **une divergence GC/MGC anormale est en
elle-même un indicateur de stress de liquidité**, au même titre que la dispersion
inter-fournisseurs du spot.

### 2.1 Ce qu'est réellement le « contrat principal »

Sur l'or COMEX, la liquidité se concentre historiquement sur un sous-ensemble d'échéances
(les mois pairs — février, avril, juin, août, octobre, décembre), tandis que d'autres
échéances sont listées mais peu traitées. **L'échéance la plus proche n'est donc pas
nécessairement l'échéance active.**

Définir le contrat principal par la proximité d'expiration conduit périodiquement à suivre un
mois sériel quasi désert : carnet vide, spread large, faux signaux de microstructure garantis.

**Règle retenue** : le contrat principal est celui qui porte la liquidité, déterminé par
volume et open interest observés, jamais par la distance à l'échéance. Le rang de liquidité
est recalculé quotidiennement et **stocké avec sa date d'effet**, de sorte qu'un rejeu sache
quel contrat était le principal à l'instant considéré.

## 3. L'événement canonique

Le schéma de l'étape 2.2 est repris, avec une correction importante : **il n'existe pas un
horodatage d'échange, mais plusieurs**, produits à des étages différents de la chaîne. Les
confondre rend la mesure de latence fausse et le classement des événements approximatif.

```
MarketEvent {
  # temps — quatre horloges distinctes, jamais fusionnées
  transact_time          horodatage du moteur d'appariement (référence d'ordonnancement)
  sending_time           horodatage d'émission du paquet par la plateforme de diffusion
  receive_time           horodatage local de réception   ← disponibilité au sens de I1
  processed_time         horodatage local de fin de décodage

  # identité et ordre
  sequence_number        séquence du canal de diffusion
  channel_id, feed_line  ligne A ou B (§4.1)
  instrument, contract_month
  security_id

  # contenu
  event_type             cotation | transaction | statut | instantané | fin de lot
  bid_price, bid_quantity, ask_price, ask_quantity, price_level
  trade_price, trade_quantity
  aggressor_side
  order_id, order_priority     si Market by Order
  update_action                nouveau | modification | suppression
  is_implied                   liquidité implicite plutôt que réelle (§4.3)

  # provenance
  book_state_hash        empreinte du carnet après application
  decoder_version
}
```

Conformément à l'ADR-008, **`receive_time` reste l'instant de disponibilité** au sens
bitemporel. `transact_time` sert à l'ordonnancement interne et à la mesure de latence, pas à
décider qu'une information était connue.

`processed_time` n'est pas cosmétique : entre réception et fin de décodage il peut s'écouler
un délai variable sous charge, et c'est ce délai — pas la latence réseau — qui détermine à
quel moment le système peut réellement agir.

## 4. Intégrité du carnet

Un carnet reconstruit à partir d'un flux incrémental est **faux en silence** dès qu'un message
manque. Aucune valeur aberrante n'apparaît : le carnet est simplement décalé, et tous les
agents de microstructure en aval travaillent sur une fiction.

### 4.1 Continuité de séquence

Les flux événementiels de ce type sont diffusés en lignes redondantes. Le décodeur doit
arbitrer entre lignes par numéro de séquence, détecter les trous, et déclencher une reprise
(canal de rejeu ou instantané) plutôt que continuer.

**Un trou de séquence non résolu invalide le carnet.** L'instrument passe en `BLIND` et
alimente `blocking_reasons` du verdict qualité, exactement comme un flux spot périmé.

### 4.2 Contrôles de cohérence permanents

- **carnet croisé** (meilleur achat ≥ meilleure vente) : impossible hors état transitoire →
  invalidation immédiate ;
- **réconciliation instantané / incrémental** : le carnet reconstruit est comparé
  périodiquement aux instantanés diffusés ; un écart est une invalidation, pas un
  avertissement ;
- **profondeur non monotone**, quantités négatives, niveaux dupliqués : mêmes conséquences ;
- **cohérence Market by Order / Market by Price** lorsque les deux sont consommés : la somme
  des ordres par niveau doit reproduire le niveau agrégé.

### 4.3 Liquidité implicite — le piège du carnet

Les marchés de spreads calendaires génèrent de la liquidité **implicite** dans les carnets
outright : une partie de la profondeur affichée ne correspond à aucun ordre réel posé sur
cette échéance, mais à la combinaison d'un ordre de spread et d'un ordre sur une autre
échéance.

Mesurer la profondeur sans distinguer réel et implicite surestime la liquidité disponible,
et fabrique des signaux de déséquilibre de carnet qui n'existent pas. D'où le champ
`is_implied`, obligatoire : **tout agent de microstructure doit pouvoir choisir de travailler
sur la liquidité réelle seule.**

## 5. Volume et open interest : une asymétrie de disponibilité

| Grandeur | Fréquence | Disponibilité réelle |
| --- | --- | --- |
| Volume | temps réel, message par message | immédiate |
| Open interest | **une fois par jour** | préliminaire le matin suivant, définitif ensuite |

L'open interest n'est **pas** une série temps réel. Le traiter comme telle est une violation
directe de I1 : on utiliserait à l'instant `t` un chiffre publié le lendemain. C'est une erreur
d'autant plus courante que la plupart des sources l'affichent sans mentionner sa date de
publication.

**Règle** : l'open interest entre dans le feature store avec une date de disponibilité égale à
sa publication, et deux versions distinctes (préliminaire, définitif) — le passage de l'une à
l'autre étant lui-même un événement daté. Toute règle de décision consommant l'OI doit rester
calculable avec l'OI **de la veille**, seul réellement disponible.

## 6. Le rollover est un processus, pas une date

Le volume et l'open interest ne migrent pas au même moment : **le volume bascule
généralement avant l'open interest**. Il existe donc une fenêtre de plusieurs séances où
l'échéance sortante conserve encore l'essentiel des positions ouvertes tandis que l'activité
est déjà passée sur la suivante.

Poser une date de roll unique écrase cette réalité et produit exactement les artefacts que
l'étape 2.2 cherche à éviter.

**État de rollover suivi en continu :**

```
RollState {
  contrat_sortant, contrat_entrant
  part_volume_entrant           en tendance sur plusieurs séances
  part_oi_entrant               avec sa date de disponibilité (§5)
  spread_calendaire             niveau, et sa propre liquidité
  phase                         STABLE | MIGRATION_VOLUME | MIGRATION_OI | TERMINÉ
  jours_avant_premier_avis
  jours_avant_dernier_jour
}
```

Deux règles opérationnelles :

- la **détection de bascule doit être calculable en temps réel**, donc pilotée par le volume,
  l'open interest ne servant que de confirmation différée — et non l'inverse ;
- on ne bascule **jamais** au moment où la liquidité de l'échéance sortante s'effondre ni
  après l'entrée dans la période de préavis de livraison : les dates de préavis et de dernier
  jour de cotation sont des données du calendrier, au même titre que les jours fériés
  (ADR-007).

Pendant la phase de migration, la qualité du signal de microstructure est intrinsèquement
dégradée sur les deux échéances. Cette phase doit **majorer l'incertitude en aval**, pas être
traitée comme une séance ordinaire.

## 7. Séries continues : il en faut trois, pas une

C'est le cœur du problème posé à l'étape 2.2. L'or cote structurellement en report : chaque
échéance plus lointaine vaut normalement plus cher que la précédente, pour des raisons de coût
de portage et de financement. Coller bout à bout les prix de deux échéances crée donc un saut
qui **n'a jamais été un mouvement de marché**.

Les trois traitements possibles ne sont pas interchangeables — chacun préserve une grandeur et
en détruit une autre :

| Série | Construction | Préserve | Détruit | Usage exclusif |
| --- | --- | --- | --- | --- |
| **Brute par contrat** | aucun raccord | les **niveaux réels** | la continuité | structures, supports/résistances, zones d'imbalance, prix ronds, exécution |
| **Ajustée en différence** | soustraction de l'écart de roll sur tout l'historique | les **écarts en dollars** | les niveaux (l'historique ancien devient fictif) | ATR, distances de stop en dollars, P&L |
| **Ajustée en ratio** | multiplication par un facteur | les **rendements en pourcentage** | les écarts absolus | volatilité, corrélations, modèles statistiques |

**Règle : le type de série est imposé par le calcul, jamais choisi par commodité.** Toute
fonction consommant une série de prix déclare celle dont elle a besoin ; fournir la mauvaise
est une erreur de type, pas une approximation.

Cela répond directement aux trois symptômes cités :

- **faux gaps** — ils naissent du raccord brut ; ils disparaissent si les niveaux sont lus sur
  la série brute par contrat ;
- **faux imbalances / FVG** — un saut de roll a exactement la signature d'une inefficience de
  prix sur trois bougies. **Toute détection de structure s'exécute sur la série brute d'un
  contrat unique**, et un niveau détecté sur l'échéance sortante ne migre vers l'entrante
  qu'après traduction par le spread calendaire — ou il est écarté ;
- **faux signaux de volatilité** — un écart de roll interprété comme un rendement gonfle la
  volatilité mesurée ; d'où la série en ratio, obligatoire pour toute estimation de vol.

## 8. Le piège majeur : une série ajustée est rétroactive

C'est le point le plus coûteux de cette étape, et il n'apparaît dans aucune des listes
précédentes.

**Une série ajustée change tout son passé à chaque roll.** L'historique ajusté tel qu'il existe
aujourd'hui n'est pas celui qu'un observateur aurait vu il y a six mois : chaque nouveau
raccord translate rétroactivement l'ensemble des données antérieures.

Conséquence : entraîner un modèle ou mesurer une calibration sur l'historique ajusté
d'aujourd'hui, c'est utiliser une information qui n'existait pas à l'époque. La fuite est
totale, silencieuse, et **elle améliore les résultats de backtest** — donc rien ne la signale.
C'est précisément le mode d'échec que l'invariant I1 et l'ADR-004 existent pour interdire, et
la version futures de cet invariant est plus insidieuse que la version données : ici, ce n'est
pas une donnée future qui fuit, c'est une *transformation* future.

**Règle** : les facteurs d'ajustement sont des données bitemporelles à part entière. Chacun est
stocké avec sa date d'effet, et le système sait reconstruire **la série telle qu'elle
apparaissait à l'instant `t`** — jamais telle qu'elle apparaît aujourd'hui. Tout backtest et
toute mesure de calibration consomment cette reconstruction datée.

## 9. Base et spread calendaire : un signal, pas une nuisance

L'écart entre échéances, et entre listé et spot, n'est pas un artefact à neutraliser. Il
porte de l'information : conditions de financement, coût de portage, tensions sur la
disponibilité physique du métal, stress de collatéral.

Sont donc conservés comme **features à part entière**, et non comme corrections :

- le spread calendaire entre échéance principale et suivante, avec sa propre liquidité ;
- la base entre le listé et le prix de référence spot construit en `02-socle-donnees.md` ;
- la déformation de ces écarts dans le temps.

Une base qui se disloque brutalement est un signal de stress de premier ordre — et l'un des
rares capteurs capables de distinguer un mouvement de prix ordinaire d'une tension de
financement.

## 10. Options sur futures : la seule probabilité cotée

Les options apportent quelque chose qu'aucun indicateur technique ne peut produire : une
**distribution de probabilité cotée par le marché**, extraite de la surface de volatilité.
C'est un intrant direct pour le moteur de scénarios (étage 6) et un point de comparaison pour
la fusion probabiliste (étage 7).

Extraits et conservés : structure par terme de la volatilité implicite, asymétrie (écart de
prix entre options de vente et d'achat équidistantes), convexité, volatilité implicite
comparée à la volatilité réalisée, échéances d'options et niveaux d'exercice concentrés.

**Restriction impérative.** La distribution extraite des options est *risque-neutre* : elle
incorpore une prime de risque et **n'est pas** une probabilité du monde réel. La transmettre
telle quelle en sortie du système reviendrait à publier comme calibrée une grandeur qui ne
l'est pas.

Elle est donc utilisée comme **a priori et comme référence de comparaison** dans la fusion
probabiliste — jamais comme probabilité finale. L'écart entre distribution implicite et
distribution estimée par le système est lui-même une information exploitable, et l'ajustement
de prime de risque qui relie les deux doit être estimé et versionné comme n'importe quel autre
paramètre (I7).

## 11. À vérifier avant implémentation — aucune spécification recopiée de mémoire

Les tailles de contrat données à l'étape 2.2 (100 et 10 onces troy) sont retenues. Toutes les
autres caractéristiques contractuelles doivent être lues dans la **spécification officielle en
vigueur** et versionnées avec leur date d'effet, jamais figées en dur d'après un souvenir :

- pas de cotation minimal et valeur du pas, pour GC comme pour MGC ;
- échéances listées et échéances réellement liquides ;
- règle exacte du premier jour de préavis et du dernier jour de cotation ;
- horaires de séance, coupure quotidienne, calendrier des jours fériés ;
- limites de variation et mécanismes de suspension.

Ces éléments changent, et une valeur périmée codée en dur produit des erreurs de calendrier de
roll — donc exactement les faux signaux que cette étape vise à éliminer.

## 12. Questions ouvertes

- **Q9** — mode d'accès aux données listées : temps réel événementiel avec carnet par ordre,
  carnet agrégé, ou données différées. Le choix conditionne la faisabilité de tous les agents
  de microstructure. C'est aussi une contrainte de coût et de licence, à trancher avant
  d'écrire le décodeur.
- **Q10** — profondeur d'historique disponible pour les futures et pour la surface d'options.
  L'estimation des distributions conditionnelles de l'ADR-007 et la calibration de l'étage 12
  en dépendent directement.
- **Q11** — l'exécution se fait-elle sur le spot OTC, sur le listé, ou les deux ? Si le signal
  vient du listé mais l'exécution du spot, la base devient un coût de décision à modéliser
  explicitement dans l'espérance mathématique nette, et non une approximation négligeable.
