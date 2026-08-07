# Journal des décisions d'architecture

Format : contexte → décision → conséquences. Une décision figée ne se contredit pas en
silence : elle se remplace par une nouvelle entrée qui la supersède explicitement.

---

## ADR-001 — Pipeline en 12 étages, organisé en DAG

**Statut** : figé (étape 1)

**Contexte.** Le système doit produire des décisions traçables et attribuables. Un
monolithe « données → verdict » rend impossible de localiser l'origine d'une erreur.

**Décision.** Le traitement est découpé en 12 étages aux contrats explicites, reliés en graphe
orienté avec quatre arêtes de rétroaction (veto qualité, kill-switch, recalibration, retrait
d'agent). Voir `01-architecture.md` §2 et §3.

**Conséquences.** Chaque étage est testable isolément. Une dégradation de performance est
imputable à un étage nommé. Le coût est une plus grande surface d'interfaces à maintenir :
il est accepté.

---

## ADR-002 — Frontière stricte entre IA générative et moteurs numériques

**Statut** : figé (étape 1)

**Contexte.** Un modèle de langage produit des nombres plausibles sans les calculer. Utilisé
comme source de prix, de probabilités ou de tailles de position, il détruit la calibration
tout en la rendant invisible.

**Décision.** Le LLM est cantonné à la compréhension de texte, l'explication, la comparaison
de scénarios et la détection de contradictions. Il n'a aucun droit d'écriture sur des
grandeurs numériques. La frontière est appliquée par validation de schéma (type de sortie
fermé) **et** par ancrage numérique (tout chiffre d'un texte généré doit exister dans
l'enregistrement de décision, sinon rejet).

**Conséquences.** Les explications sont vérifiables mécaniquement. Un chiffre non ancré est un
incident, pas une approximation. Les sorties textuelles deviennent régénérables sans risque de
dérive du contenu chiffré.

---

## ADR-003 — Abstention par défaut et monotonie des vetos

**Statut** : figé (étape 1)

**Contexte.** La capacité à ne rien faire est un objectif explicite. Un système qui doit
toujours conclure finit par produire des décisions à espérance négative.

**Décision.** La sortie par défaut du pipeline est `NoTrade`. Elle n'est levée que si toutes
les portes sont franchies (qualité, régime, EV nette après frais, risque). Les étages aval
peuvent uniquement réduire la conviction et la taille, jamais les augmenter.

**Conséquences.** Le taux d'abstention devient une métrique de santé à suivre, dans les deux
sens : trop bas, les portes ne filtrent rien ; trop haut, le système est inutile ou une porte
est mal réglée.

---

## ADR-004 — Feature store bitemporel

**Statut** : figé (étape 1)

**Contexte.** La promesse de probabilités calibrées est vide si les features utilisées à
l'instant `t` contiennent de l'information indisponible à `t`. C'est le mode d'échec le plus
courant et le plus silencieux de ce type de système : il ne se voit qu'en production.

**Décision.** Le store distingue la date d'application d'une valeur et sa date de
disponibilité. Toute lecture est datée `as_of(t)` et filtrée sur la disponibilité. Les
définitions de features sont versionnées ; une formule modifiée crée une nouvelle version, elle
ne réécrit jamais l'historique.

**Conséquences.** Backtest et temps réel partagent le même chemin de lecture — condition pour
que les métriques du premier prédisent quoi que ce soit du second. Coût en complexité de
stockage : accepté.

---

## ADR-005 — Emplacement du code et pile technique

**Statut** : **ouvert**

**Contexte.** Le dépôt hôte est le monorepo Expo (fork `toto35520/expo`), orienté
TypeScript / React Native. Les étages 5, 7 et 12 (régime, fusion, calibration) reposent sur de
l'outillage statistique dont l'écosystème naturel est Python.

**Options.** (a) service Python autonome + interface de consultation dans le monorepo ;
(b) tout en TypeScript ; (c) noyau numérique Python + agents et présentation en TypeScript.

**En attente** de la réponse à Q1. La documentation reste dans `financial-analyzer/docs/` et
sera déplacée avec le code si nécessaire — aucune décision d'implémentation n'est prise avant
ce choix.

**Devenu bloquant à l'étape 2** : les étages 1 et 2 sont désormais spécifiés assez finement
pour être implémentés. Ils ne le seront pas tant que cet ADR reste ouvert.

---

## ADR-006 — Quorum de 3 fournisseurs indépendants

**Statut** : figé (étape 2)

**Contexte.** Le XAU/USD spot est OTC : aucune tape consolidée, donc aucun prix vrai contre
lequel valider un flux. La validation ne peut être que croisée. Or une médiane sur deux
sources est une moyenne, et ne permet aucune détection d'aberration : si les deux divergent,
rien n'indique laquelle a tort.

**Décision.** Un prix de référence n'autorise une décision qu'avec **au moins 3 fournisseurs
sains et indépendants**. Deux flux revendus par le même agrégateur comptent pour un.
En dessous du quorum : mode dégradé, prix affiché mais décision interdite.

**Conséquences.** L'indépendance des sources devient une condition de validité du système, pas
un choix d'approvisionnement. Le nombre de fournisseurs sains est une métrique de santé
permanente, et le sous-quorum un motif de blocage explicite.

---

## ADR-007 — Aucun seuil absolu sur le spread ni sur la fraîcheur

**Statut** : figé (étape 2)

**Contexte.** Le spread normal du XAU/USD varie d'un ordre de grandeur entre le recouvrement
Londres–New York et le rollover quotidien. L'intervalle normal entre ticks varie tout autant
entre séance européenne et creux asiatique. Un seuil fixe est simultanément trop permissif aux
heures liquides et générateur de fausses alarmes le reste du temps.

**Décision.** Spread et fraîcheur sont évalués par **rang quantile dans une distribution
conditionnelle** à `(fournisseur, tranche de session, régime de volatilité)`, estimée sur
l'historique observé par le système. Le calendrier de marché (week-end, fériés, rollover,
fixings LBMA) est une dépendance de premier ordre.

**Conséquences.** Le contrôle qualité ne peut pas fonctionner correctement dès le premier jour :
il lui faut une période d'observation pour estimer ses distributions. Cette période doit être
traitée explicitement comme un état dégradé, pas comme un fonctionnement nominal.

---

## ADR-008 — L'instant de disponibilité est la réception, jamais l'horodatage fournisseur

**Statut** : figé (étape 2)

**Contexte.** Les horloges des fournisseurs dérivent et leurs conventions d'horodatage
diffèrent (émission, mise en file, appariement). Utiliser `t_provider` comme base temporelle
introduit un désordre chronologique invisible, et peut faire entrer dans le feature store une
donnée à un instant où le système ne la détenait pas encore — violation directe de I1.

**Décision.** `t_received` est la seule base temporelle de confiance et l'instant de
disponibilité au sens bitemporel. `t_provider` sert exclusivement à mesurer la latence et à
détecter la désynchronisation d'horloge, elle-même traitée comme une pathologie de flux.

**Conséquences.** Le système est délibérément « en retard » sur le marché d'une latence
mesurée plutôt que faussement synchrone. Les backtests héritent de cette latence, ce qui est
la seule façon d'obtenir des résultats transposables au temps réel.

---

## ADR-009 — Distinguer divergence idiosyncratique et divergence systémique

**Statut** : figé (étape 2)

**Contexte.** Un écart de prix entre fournisseurs a deux causes de nature opposée : un flux
défaillant, ou un marché réellement disloqué. Les confondre conduit soit à mettre en
quarantaine des flux sains pendant les épisodes de stress — précisément quand on a besoin
d'eux — soit à traiter une dislocation de marché comme un incident technique.

**Décision.** Un fournisseur qui s'écarte seul de la médiane robuste est mis en quarantaine
(problème de données). Une dispersion élevée **simultanée sur l'ensemble du panel** n'entraîne
aucune quarantaine : elle est transmise au détecteur de régime comme signal de stress, et
bloque la décision pour un motif distinct, tracé comme tel.

**Conséquences.** Les deux causes d'abstention restent séparables a posteriori dans l'audit,
ce qui permet de régler leurs seuils indépendamment.

---

## ADR-010 — Le contrat principal est défini par la liquidité, pas par l'échéance

**Statut** : figé (étape 2.2)

**Contexte.** Sur l'or COMEX, la liquidité se concentre sur un sous-ensemble d'échéances.
L'échéance listée la plus proche est régulièrement un mois sériel peu traité : carnet vide,
spread large, microstructure inexploitable.

**Décision.** Le contrat principal est déterminé par le volume et l'open interest observés,
jamais par la distance à l'expiration. Le rang de liquidité est recalculé quotidiennement et
stocké avec sa date d'effet, pour qu'un rejeu retrouve le contrat principal *de l'époque*.

**Conséquences.** La notion de « front month » devient une donnée calculée et versionnée du
système, pas une convention implicite. MGC est exclu des sources de signal de prix : c'est un
marché dérivé de GC, et l'observer revient à lire le reflet plutôt que l'objet — sa divergence
avec GC reste en revanche un indicateur de stress de liquidité.

---

## ADR-011 — Trois séries continues coexistantes, à usage typé

**Statut** : figé (étape 2.2)

**Contexte.** L'or cote structurellement en report : raccorder deux échéances crée un saut qui
n'a jamais eu lieu. Les trois traitements possibles préservent chacun une grandeur différente
et en détruisent une autre — aucun n'est universellement correct.

**Décision.** Le système maintient simultanément la série **brute par contrat** (niveaux
réels), la série **ajustée en différence** (écarts en dollars) et la série **ajustée en ratio**
(rendements). Chaque fonction consommant des prix déclare la série dont elle a besoin.
Fournir la mauvaise est une erreur de type. En particulier : toute détection de structure
(niveaux, zones d'imbalance, FVG) s'exécute sur la série brute d'un contrat unique, et un
niveau ne franchit une frontière de roll qu'après traduction par le spread calendaire.

**Conséquences.** Coût de stockage et de complexité triplé sur les séries de prix, accepté.
En échange, les trois symptômes visés — faux gaps, faux imbalances, fausse volatilité —
deviennent structurellement impossibles plutôt que corrigés au cas par cas.

---

## ADR-012 — Les facteurs d'ajustement de roll sont bitemporels

**Statut** : figé (étape 2.2)

**Contexte.** Une série ajustée réécrit tout son passé à chaque roll : l'historique ajusté tel
qu'il existe aujourd'hui n'est pas celui qu'un observateur voyait il y a six mois. Entraîner ou
calibrer dessus utilise une transformation qui n'existait pas encore. La fuite est invisible et
**améliore** les résultats de backtest, donc rien ne la signale.

**Décision.** Chaque facteur d'ajustement est stocké avec sa date d'effet. Le système sait
reconstruire la série telle qu'elle apparaissait à un instant donné, et tout backtest ou
mesure de calibration consomme cette reconstruction datée — jamais la série courante.

**Conséquences.** Extension de l'ADR-004 : ce n'est plus seulement la donnée qui est
bitemporelle, mais aussi la transformation qui lui est appliquée. Le rejeu d'une décision
ancienne exige de restaurer l'état des facteurs à cette date.

---

## ADR-013 — L'open interest est une donnée quotidienne différée

**Statut** : figé (étape 2.2)

**Contexte.** Le volume est temps réel, l'open interest est publié une fois par jour, en
préliminaire puis en définitif. La plupart des sources l'affichent sans sa date de
publication, ce qui invite à le traiter comme une série temps réel — et à consommer à
l'instant `t` un chiffre publié le lendemain.

**Décision.** L'open interest entre dans le feature store avec une date de disponibilité égale
à sa publication et en deux versions distinctes (préliminaire, définitif), le passage de
l'une à l'autre étant un événement daté. Toute règle de décision doit rester calculable avec
l'open interest de la veille. Corollaire : la détection de rollover est pilotée par le volume,
l'open interest ne servant que de confirmation différée.

**Conséquences.** Aucune règle du système ne peut dépendre d'un open interest intraday. Les
stratégies qui en auraient besoin sont écartées d'emblée plutôt que découvertes fausses en
production.

---

## ADR-014 — La distribution implicite des options est un a priori, jamais la probabilité finale

**Statut** : figé (étape 2.2)

**Contexte.** La surface d'options fournit la seule distribution de probabilité réellement
cotée par le marché. Elle est cependant *risque-neutre* : elle incorpore une prime de risque et
diffère systématiquement de la probabilité du monde réel.

**Décision.** La distribution implicite alimente le moteur de scénarios comme a priori et sert
de référence de comparaison à la fusion probabiliste. Elle n'est jamais publiée ni utilisée
comme probabilité calibrée. L'ajustement de prime de risque reliant les deux est un paramètre
estimé et versionné.

**Conséquences.** L'écart entre distribution implicite et distribution estimée par le système
devient lui-même une feature exploitable. Le système ne peut pas se contenter de relayer le
marché : il doit produire sa propre estimation et assumer l'écart.

---

## ADR-015 — Les séries basse fréquence sont indexées sur leur publication, et leurs révisions conservées

**Statut** : figé (étape 2.3)

**Contexte.** La couche physique et régionale mêle des séries dont la latence de publication va
de quelques minutes à plusieurs semaines, et qui sont fréquemment révisées. Le réflexe naturel
est de les prolonger sur la série intraday à partir de leur *période de référence*. Le backtest
consomme alors pendant des semaines un chiffre que personne ne connaissait, ses résultats
s'améliorent, et rien ne le signale.

**Décision.** Toute série basse fréquence est prolongée à partir de sa **date de publication**.
Les révisions sont conservées et non écrasées : la valeur connue à `t` est celle publiée à `t`,
même corrigée depuis. Toute feature dérivée hérite de la latence de sa source et la déclare.

**Conséquences.** Troisième extension de l'ADR-004 : après la donnée (ADR-004) et la
transformation (ADR-012), c'est la **connaissance qu'on en avait** qui devient datée. Rejouer
une décision passée impose de le faire avec les chiffres erronés de l'époque, ce qui est la
seule reconstitution honnête.

---

## ADR-016 — Un résidu de cohérence unique entre spot, Londres et listé

**Statut** : figé (étape 2.3)

**Contexte.** Suivre trois prix séparément ne dit pas lequel a tort. Soustraire deux prix bruts
mélange coût de portage, décalage temporel et bruit de cotation. Par ailleurs le spot OTC *est*
le marché londonien : ce ne sont pas deux marchés concurrents mais un référentiel et sa
cotation.

**Décision.** Le système maintient un résidu unique reliant le prix de référence spot au listé
traduit par la base, ancré aux fixings lorsqu'ils existent. L'écart entre listé et physique est
mesuré par l'instrument qui le cote — l'échange futures contre physique — et non par une
différence de prix brute. La sortie de plage du résidu suit la logique de l'ADR-009 : un
marché isolé qui s'écarte est un incident technique, les trois qui se disloquent ensemble sont
un état de marché.

**Conséquences.** Un seul capteur à calibrer au lieu de trois comparaisons ad hoc, et une
séparation nette entre « réparer une connexion » et « réduire l'exposition ».

---

## ADR-017 — La couche physique conditionne et bloque, elle ne déclenche jamais

**Statut** : figé (étape 2.3)

**Contexte.** Les données physiques et de benchmark ont une fréquence et une latence
incompatibles avec le déclenchement d'une entrée. Leur information est déjà incorporée au prix
au moment où elle devient disponible.

**Décision.** Ces données peuvent conditionner les scénarios, pondérer la fusion selon le
régime, durcir les contraintes de risque et ajouter un motif de blocage. Elles ne peuvent ni
produire un signal d'entrée, ni fixer un niveau, ni augmenter une taille, ni lever un blocage
existant. Le fixing LBMA est traité comme un état de session (`PRE_FIXING`, `EN_ENCHÈRE`,
`POST_FIXING`) alimentant les distributions conditionnelles de l'ADR-007, et non comme un
signal.

**Conséquences.** Application directe de la monotonie des vetos (I5) : une prime physique
favorable ne peut pas autoriser un trade que le reste du système refuse. L'effet de flux autour
des fixings est traité comme un effet de calendrier à modéliser, jamais comme un rendement
acquis.

---

## ADR-018 — Classe de redistribution transportée jusqu'à la frontière de sortie

**Statut** : figé (étape 2.3)

**Contexte.** Le benchmark londonien est sous licence. Or le système comporte une couche qui
produit du texte destiné à être lu. Rien n'empêche structurellement une valeur sous licence
d'être citée dans une explication publiée — fuite involontaire, mais fuite.

**Décision.** Chaque source porte une classe de redistribution, transportée avec la donnée
jusqu'à la sortie. La frontière de sortie filtre les valeurs non redistribuables : elles restent
utilisables en calcul et citables dans l'enregistrement de décision interne, mais ne peuvent
pas apparaître dans une sortie publiable. Ce filtre est appliqué au même point de la chaîne que
le contrôle d'ancrage numérique de l'ADR-002.

**Conséquences.** La frontière de sortie devient un point de contrôle unique portant deux
garanties : aucun chiffre inventé, aucun chiffre non redistribuable. Le coût est une contrainte
de provenance à propager sur toute la chaîne de features.

---

## ADR-019 — Observations en UTC, horaires en heure locale et fuseau

**Statut** : figé (étape 2.4)

**Contexte.** Les marchés et les publications sont définis en heure locale, avec des règles de
changement d'heure qui diffèrent entre juridictions. La conversion vers UTC n'est pas un
décalage constant mais une fonction discontinue du temps. L'Union européenne et les États-Unis
ne basculant pas aux mêmes dates, l'écart Londres ↔ New York diffère de l'usuel pendant environ
un mois par an — en pleine saison de publications macro.

**Décision.** Les observations (ticks, transactions, événements) sont stockées en UTC à
résolution native. Les **règles** — ouvertures, coupures, fixings, publications programmées —
sont stockées en heure locale avec leur identifiant de fuseau et converties à la lecture par
une base de fuseaux tenue à jour. Figer un horaire de marché en UTC est un défaut. Le fuseau de
l'opérateur est un fuseau de présentation : il n'entre dans aucun calcul, aucun seuil, aucune
agrégation.

**Conséquences.** Aucune conversion de fuseau écrite à la main dans le code. Le défaut visé ne
se manifestant que deux fois par an, il ne peut pas être détecté par les tests ordinaires : la
contrainte doit être structurelle.

---

## ADR-020 — Ordonnancement par séquence, durées sur horloge monotone

**Statut** : figé (étape 2.4)

**Contexte.** Deux événements peuvent porter le même horodatage. Par ailleurs l'horloge murale
peut reculer — correction de synchronisation, seconde intercalaire, lissage — ce qui produit
des durées négatives ou aberrantes.

**Décision.** L'ordre des événements est défini par `(horodatage, numéro de séquence, index
d'arrivée)`, jamais par l'horodatage seul. Toute mesure de durée, de latence ou de fraîcheur
s'appuie sur une horloge monotone locale ; l'horloge murale ne sert qu'à l'enregistrement.
Aucune troncature de résolution à l'ingestion.

**Conséquences.** La reconstruction du carnet devient déterministe, donc rejouable (I2). Un tri
instable sur des ticks produirait sinon un carnet différent à chaque exécution.

---

## ADR-021 — Calendriers et base de fuseaux : bitemporels et versionnés

**Statut** : figé (étape 2.4)

**Contexte.** Jours fériés, demi-séances et horaires sont annoncés à l'avance et parfois
modifiés. Les règles de changement d'heure sont modifiées par les États, parfois
rétroactivement, et la base de fuseaux est mise à jour plusieurs fois par an.

**Décision.** Le calendrier de marché, le calendrier macro et la version de la base de fuseaux
sont des artefacts versionnés, enregistrés dans chaque enregistrement de décision. Rejouer une
décision exige le calendrier et les règles de conversion **tels qu'ils étaient connus à
l'époque**. Les jours fériés sont suivis par marché — une place peut être fermée pendant qu'une
autre cote, produisant des séances partiellement ouvertes légitimes. Fermeture programmée et
interruption subie restent des états distincts.

**Conséquences.** Quatrième application du même principe : après la donnée (ADR-004), la
transformation (ADR-012) et la connaissance (ADR-015), c'est la **règle de conversion** qui
devient datée. Effet secondaire important : sans les fériés par marché, le contrôle qualité
signale un flux périmé à chaque jour férié britannique, et le système apprend à ignorer ses
propres alarmes.

---

## ADR-022 — La frontière de journée est un paramètre déclaré de toute agrégation

**Statut** : figé (étape 2.4)

**Contexte.** La séance du listé et la journée du spot OTC ne commencent pas au même moment, et
le rollover des brokers s'exprime dans un fuseau serveur qui suit un changement d'heure ne
correspondant ni à Londres ni à New York. Deux conventions produisent donc des bougies
journalières différentes — donc des plus hauts et plus bas différents — et un décalage d'une
heure redécoupe silencieusement les bougies deux fois par an.

**Décision.** La frontière de journée et de semaine est un paramètre déclaré et versionné de
toute agrégation. Deux séries agrégées selon des conventions différentes ne sont ni comparées
ni fusionnées. Tout niveau extrait d'une bougie transporte la convention dont il est issu.

**Conséquences.** Un plus-haut journalier cesse d'être traité comme un fait de marché : c'est
un fait relatif à une frontière de journée. Même famille de défaut que les faux niveaux de
rollover (ADR-011), et même remède — typer la série plutôt que corriger après coup.

---

## ADR-023 — Portes dures et score de qualité sont deux objets séparés

**Statut** : figé (étape 2.5)

**Contexte.** Un score agrégé de 0 à 100 confond des défaillances non substituables : 60 peut
signifier « tout légèrement dégradé » ou « un flux critique mort ». Pire, associé à un seuil, il
autorise la **compensation** — un spread excellent annule un flux périmé, et le système décide
sur des données mortes parce que la moyenne reste bonne. C'est une violation directe de I4 et I5.

**Décision.** Deux objets aux pouvoirs distincts. Les **portes dures** sont des conditions
booléennes non compensables qui décident seules de l'admissibilité : une seule qui tombe
interdit. Le **score** est continu et ne peut que dégrader — il réduit conviction et taille,
n'autorise jamais rien. Sa construction est multiplicative (non compensatoire), monotone, et
toujours publiée avec sa décomposition ; un score nu est inexploitable.

**Conséquences.** Le score devient un modulateur de prudence, jamais une autorisation. Aucun
réglage de seuil sur le score ne peut ouvrir une porte fermée.

---

## ADR-024 — Statut multi-axes, avec absence par conception

**Statut** : figé (étape 2.5)

**Contexte.** La liste de statuts de l'étape 2.5 mélange des dimensions orthogonales : une
donnée peut être valide **et** non redistribuable, ou reconstruite **et** saine. Les rendre
mutuellement exclusifs rend ces états inexprimables. Par ailleurs aucune valeur ne distingue
« absent parce que le marché est fermé » de « absent parce que le flux est tombé ».

**Décision.** Le statut porte quatre axes indépendants — fraîcheur, intégrité, provenance,
diffusion. `CORROMPU` est ajouté sur l'axe intégrité pour les invalidités structurelles (trou
de séquence, carnet croisé, échec de réconciliation), qui s'écartent au lieu de se pondérer.
`ABSENT_PAR_CONCEPTION` est ajouté sur l'axe provenance, déterminé par le calendrier
(ADR-021), et n'entraîne **aucune pénalité de score**.

**Conséquences.** Les fériés et coupures cessent de dégrader le score et de déclencher des
alarmes — sans quoi le système apprend à ignorer ses propres alertes. Restriction de diffusion
et reconstruction deviennent compatibles avec un état sain.

---

## ADR-025 — Interdiction d'imputer sur le chemin de décision, propagation au pire des entrées

**Statut** : figé (étape 2.5)

**Contexte.** Deux mécanismes fabriquent silencieusement de la donnée : le remplissage des
trous, et le blanchiment par agrégation — une série périmée entre dans un indicateur, qui en
ressort sans aucune marque.

**Décision.** L'imputation est autorisée pour l'affichage et la surveillance, **interdite pour
toute valeur entrant dans une décision** : un trou reste un trou et conduit à l'abstention.
Toute valeur dérivée hérite du **pire statut de ses entrées**, axe par axe ; la provenance
s'accumule au lieu de se remplacer.

**Conséquences.** Symétrie exacte avec l'ADR-002 : ce dernier interdit au modèle de langage de
produire des nombres qu'il n'a pas calculés, celui-ci interdit à la couche de données de
produire des nombres qu'elle n'a pas observés. Le statut voyage jusqu'à l'enregistrement de
décision, qui répond sans reconstruction à « sur quelle qualité de données ceci a-t-il été
décidé ? ».

---

## ADR-026 — Admissibilité par consommateur ; un agent absent élargit l'incertitude

**Statut** : figé (étape 2.5)

**Contexte.** La criticité d'une donnée n'existe pas dans l'absolu : le carnet est vital pour un
agent de microstructure et sans objet pour un agent macro. Mais une admissibilité fine ouvre un
piège — si un agent indisponible disparaît simplement de la fusion, celle-ci conclut avec la
même assurance qu'avant, alors que l'agent manquant aurait pu contredire les autres.

**Décision.** Chaque consommateur déclare ses entrées requises et le statut minimal qu'il
accepte ; l'admissibilité est évaluée par consommateur, pas globalement. En contrepartie, une
indisponibilité **élargit l'incertitude** en aval : l'étage 7 reçoit la liste des agents
absents et leur poids habituel, et traite leur silence comme de l'ignorance, jamais comme un
accord tacite. En dessous d'un panel minimal, la fusion n'est pas moins fiable — elle est
illégitime.

**Conséquences.** Extension du quorum de l'ADR-006 des fournisseurs vers les agents. Une
dégradation partielle du socle réduit le périmètre du système au lieu de l'arrêter, sans jamais
augmenter faussement sa confiance.

---

## ADR-027 — Le score de qualité doit démontrer son pouvoir prédictif

**Statut** : figé (étape 2.5)

**Contexte.** Un score de qualité encode une hypothèse testable : une qualité de données plus
faible produit des décisions moins bonnes. Non testée, cette hypothèse devient une cible
d'optimisation et le score finit par mesurer le réglage de ses propres seuils.

**Décision.** L'étage 12 mesure la relation entre score au moment de la décision et résultat
réalisé. Si la relation existe, les poids du score sont calibrés sur elle plutôt que choisis à
la main. Si elle est absente, le score est **retiré du chemin de décision** — le conserver
donnerait un faux sentiment de contrôle. Si elle s'inverse sur une dimension, c'est le
détecteur de cette dimension qui est corrigé.

**Conséquences.** Aucun poids de pénalité n'est fixé a priori dans la spécification. Le
contrôle qualité devient lui-même un objet mesuré, soumis aux mêmes exigences de preuve que
les agents.

---

## ADR-028 — Déséquilibre de flux normalisé par la profondeur, jamais brut

**Statut** : figé (étape 3.1)

**Contexte.** Un même déséquilibre déplace violemment un carnet mince et se fait absorber par un
carnet épais. L'amplitude brute de l'OFI suit donc principalement l'heure de la journée : un
seuil posé dessus mesure la session, pas la pression.

**Décision.** Le déséquilibre est toujours rapporté à la profondeur prévalente, et conditionné
par tranche de session, régime de volatilité et phase de rollover (ADR-007, ADR-013). Les
déséquilibres par niveau de carnet sont conservés séparés et jamais pré-additionnés : leur
combinaison est apprise à l'étage 7, où elle peut dépendre du régime.

**Conséquences.** Les seuils deviennent estimables et comparables dans le temps. Coût : la
mesure dépend de la qualité de la profondeur, donc du marquage de liquidité implicite.

---

## ADR-029 — Toute évaluation intègre un décalage égal à la latence réelle

**Statut** : figé (étape 3.1)

**Contexte.** La relation entre déséquilibre de flux et variation de prix **sur la même
fenêtre** est forte — mais c'est en grande partie une identité comptable : les ordres qui ont
consommé la file *sont* le mécanisme par lequel le prix a bougé. Une régression contemporaine
affiche donc un pouvoir explicatif impressionnant qui n'est pas une capacité de prédiction. La
capacité prédictive réelle est d'un ordre de grandeur inférieure et décroît en quelques
secondes.

**Décision.** Fenêtre de mesure et fenêtre de rendement strictement disjointes, séparées par un
décalage égal à la **latence de bout en bout réelle** — jusqu'à l'accusé de réception du
broker, pas jusqu'à la fin du calcul. Tout résultat obtenu sans ce décalage est déclaré non
exploitable, quelle que soit sa qualité statistique.

**Conséquences.** Beaucoup de résultats spectaculaires disparaissent, ce qui est l'effet
recherché. La latence de bout en bout devient un paramètre de premier ordre du système, à
mesurer avant tout travail de modélisation.

---

## ADR-030 — Le rôle du moteur de microstructure est fixé par sa demi-vie mesurée

**Statut** : figé (étape 3.1)

**Contexte.** Un signal dont la demi-vie est inférieure à la latence d'exécution est inutilisable
pour déclencher une entrée, même s'il est réel. Le contexte pousse vers ce cas : la
microstructure est observée sur le listé alors que l'exécution se fait sur le spot, donc le
signal doit traverser la base avant d'être exploitable.

**Décision.** Le champ `rôle_autorisé` de la sortie de l'agent — `DÉCLENCHEUR`, `CALAGE` ou
`VETO` — est renseigné par la mesure de demi-vie confrontée à la latence réelle, et limite
mécaniquement l'usage que l'étage 9 peut en faire. **Valeur par défaut : `VETO`**, tant que la
mesure n'a pas été faite.

**Conséquences.** Application de I4 au niveau d'un agent : le moteur commence par sa capacité à
empêcher et ne gagne le droit de déclencher que sur preuve. Veto et calage d'exécution
conservent une valeur économique réelle, puisqu'ils agissent sur l'espérance nette de frais.

---

## ADR-031 — Le déséquilibre n'est jamais publié seul

**Statut** : figé (étape 3.1)

**Contexte.** Un déséquilibre fortement acheteur accompagné d'une absence de progression du prix
signifie qu'un vendeur passif absorbe tout le flux sans céder de terrain. Lire ce cas comme
haussier revient à acheter face à celui qui absorbe. Le signe du signal naïf est alors faux.

**Décision.** Le déséquilibre est systématiquement apparié à la progression de prix réalisée
sur la même fenêtre, et c'est le **couple** qui constitue la feature. Quatre régimes sont
qualifiés explicitement : continuation, absorption, fragilité, équilibre. Un moteur qui sortirait
un déséquilibre nu produirait un signal ambigu et parfois inversé. S'y ajoutent impact réalisé,
résilience et vitesse de reconstitution, seul triplet capable de distinguer une réévaluation
réelle d'une secousse de liquidité.

**Conséquences.** La sortie de l'agent est structurellement plus riche qu'un scalaire signé, ce
qui complique la fusion mais supprime une inversion de signe systématique dans les phases
d'absorption — c'est-à-dire aux points de retournement, là où l'erreur coûte le plus.

---

## ADR-032 — Échantillonnage en temps-événement

**Statut** : figé (étape 3.1)

**Contexte.** Une seconde de recouvrement Londres–New York et une seconde de creux asiatique ne
contiennent pas le même nombre d'événements. Échantillonner en temps d'horloge mélange donc des
populations sans rapport et rend les distributions instables.

**Décision.** Les features de microstructure sont échantillonnées en temps-événement — par
nombre d'événements, de transactions ou de volume écoulé. La datation en temps d'horloge est
conservée pour l'audit et la rejouabilité : c'est le pas d'échantillonnage qui change, pas
l'horodatage.

**Conséquences.** Les distributions conditionnelles de l'ADR-007 deviennent estimables sur ce
moteur. Coût : les fenêtres n'ont plus une durée constante, ce dont l'appariement avec les
rendements futurs doit tenir compte.

---

## ADR-033 — Le delta mesure l'impatience ; le delta cumulé est toujours ancré

**Statut** : figé (étape 3.2)

**Contexte.** Toute transaction a un acheteur et un vendeur : un excédent d'achat n'existe pas.
Le delta mesure qui a traversé le spread, donc qui était pressé. Un acheteur important
travaillant à l'achat limite produit un delta négatif pendant qu'il accumule. Par ailleurs une
somme cumulée dépend entièrement de son origine : « le delta cumulé est à +12 000 » ne signifie
rien sans elle.

**Décision.** Le delta est interprété comme une mesure d'impatience, jamais d'accumulation.
Aucune règle ne porte sur le niveau absolu du delta cumulé ; l'ancre est un paramètre déclaré et
versionné, et deux courbes ancrées différemment ne sont jamais comparées. Le delta est rapporté
au volume écoulé et conditionné à la session, et la distribution des tailles est conservée en
plus de la somme.

**Conséquences.** Les deux quadrants non triviaux — divergence et absorption — deviennent
lisibles par une règle simple : quand prix et delta divergent, le côté patient est celui qui va
dans le sens du prix. Cette lecture reste soumise à validation (ADR-034).

---

## ADR-034 — Toute divergence exige un modèle nul et une robustesse sur grille

**Statut** : figé (étape 3.2)

**Contexte.** Le delta cumulé est structurellement une marche aléatoire, le prix en est une
autre. Deux marches aléatoires produisent des divergences visuelles en permanence sans contenir
la moindre information. De plus, la détection de divergence dépend fortement du découpage en
oscillations : changer ce découpage change l'ensemble des divergences trouvées.

**Décision.** Aucune règle de divergence n'est exploitable sans (1) un modèle nul — série
rééchantillonnée par blocs ou signes permutés, préservant volume et volatilité — que le signal
réel doit battre nettement et de façon stable ; (2) une évaluation sur **grille de paramètres**,
un effet réel se dégradant progressivement là où un artefact n'existe qu'à un réglage. La grille
de recherche est déclarée à l'avance, le nombre de configurations testées est compté, et une
fraction de l'historique est matériellement réservée à la validation finale.

**Conséquences.** Discipline applicable à tous les moteurs, posée ici parce que la divergence est
le premier motif où la tentation d'explorer librement devient forte. Une divergence qui ne bat
pas son modèle nul n'est pas un signal faible : c'est du bruit nommé.

---

## ADR-035 — Les agents déclarent leurs recouvrements structurels

**Statut** : figé (étape 3.2)

**Contexte.** Le delta est la composante « transactions » du déséquilibre de flux, lequel agrège
transactions, ajouts et retraits. Ces deux moteurs partagent leur information par construction,
pas par accident. Une fusion qui les traite comme deux témoignages distincts compte deux fois la
même observation : « cinq moteurs sont d'accord » signifie alors « un signal a été compté cinq
fois ».

**Décision.** Chaque agent déclare ses recouvrements structurels — entrées et mécanismes
partagés avec d'autres agents. L'étage 7 traite les agents structurellement liés comme une
source unique à décomposer, jamais comme des preuves indépendantes. La corrélation empirique
mesurée sur l'historique complète cette déclaration mais ne la remplace pas : elle est instable
et s'effondre précisément dans les régimes extrêmes, là où l'indépendance supposée coûte le plus
cher.

**Conséquences.** C'est la contrainte centrale de l'architecture multi-moteurs. Sans elle, le
système produit une confiance artificiellement élevée et détruit la calibration — c'est-à-dire
son objectif principal. Tout nouvel agent devra déclarer ses recouvrements avant d'être admis
dans la fusion.

---

## ADR-036 — La convention d'agrégation des transactions est un paramètre déclaré

**Statut** : figé (étape 3.2)

**Contexte.** Une agression consommant plusieurs ordres passifs peut être diffusée comme une
transaction ou comme plusieurs selon la source. Le delta et la distribution des tailles changent
en conséquence : deux fournisseurs produisent deux courbes de delta cumulé différentes pour le
même marché et la même journée.

**Décision.** La convention d'agrégation est déclarée et versionnée avec la série. Deux séries de
conventions différentes ne sont ni comparées ni fusionnées. Lorsque le côté agresseur est déduit
plutôt que fourni, la valeur est marquée `DÉRIVÉ` et son incertitude propagée.

**Conséquences.** Même famille que l'ADR-022 sur la frontière de journée : une grandeur qui
paraît objective est en réalité relative à une convention, et la convention doit voyager avec la
donnée.

---

## ADR-037 — Pas de pourcentage sans calibration ; détection et prédiction séparées

**Statut** : figé (étape 3.3)

**Contexte.** Un champ unique nommé « confiance » recouvre trois questions sans rapport : le
motif est-il présent, le prix va-t-il suivre, et le motif est-il net selon un barème interne.
Une absorption peut être certainement présente et n'annoncer presque rien. Par ailleurs un
pourcentage issu d'un barème de points a l'apparence d'une probabilité sans en avoir le contenu
fréquentiel.

**Décision.** Probabilité de détection, probabilité prédictive et score interne sont des champs
distincts, jamais fusionnés. Une grandeur n'est exprimée en pourcentage que si elle a été
confrontée à la fréquence réalisée — sinon elle porte un score sur une échelle explicitement
nommée non probabiliste.

**Conséquences.** Troisième face du même principe, après l'ADR-002 (le modèle de langage
n'invente pas de nombres) et l'ADR-025 (la couche de données non plus) : **aucun étage ne
produit de nombre d'apparence probabiliste sans contenu fréquentiel**. Un seul champ mal typé
corromprait la calibration de toute la fusion.

---

## ADR-038 — Un motif est émis avant son issue, et ses échecs sont comptés

**Statut** : figé (étape 3.3)

**Contexte.** La description d'un motif inclut spontanément sa réussite — « puis une reprise de
structure apparaît ». Si cette clause entre dans la détection, le motif n'est détecté que
lorsqu'il a fonctionné, et son taux de réussite vaut 100 % par construction.

**Décision.** Le motif est émis à partir des seuls éléments disponibles à l'instant de la
détection, dans l'état `EN_ATTENTE`. Son issue est un événement ultérieur daté, rattaché à
l'émission, avec au moins trois issues possibles : aboutie, submergée, expirée. Les échecs sont
conservés et comptés.

**Conséquences.** C'est la condition d'existence d'un taux de base, donc de toute probabilité
calibrée. Règle générale applicable à tous les motifs du système, pas seulement à l'absorption.
En marché directionnel, les absorptions submergées sont majoritaires : les omettre inverserait
la statistique.

---

## ADR-039 — La nature de l'absorbeur est déclarée, y compris quand elle est indéterminée

**Statut** : figé (étape 3.3)

**Contexte.** Un participant qui absorbe sans céder de terrain peut être un acheteur informé, un
teneur de marché qui va se déboucler, ou un algorithme d'exécution suivant un calendrier. Dans
le dernier cas le soutien est parfaitement régulier puis disparaît instantanément à la fin du
programme : l'absorbeur n'avait aucune vue sur le prix, il avait un volume à exécuter.

**Décision.** La sortie porte un champ de nature d'absorbeur, alimenté par des signatures
mesurables — régularité des réapprovisionnements, signature d'ordre iceberg, réaction à
l'intensification de la pression, contexte horaire. Tant que ces signatures ne sont pas
validées, la valeur reste `INDÉTERMINÉE`, ce qui est une information honnête et non une lacune.

**Conséquences.** Le moteur cesse de supposer une intention directionnelle derrière un
comportement qui peut être purement mécanique. Impose de mesurer l'écart de résultat entre les
populations, y compris si elles restent inséparables.

---

## ADR-040 — L'absorption produit d'abord une invalidation, ensuite un signal

**Statut** : figé (étape 3.3)

**Contexte.** L'apport le plus solide de l'absorption n'est pas la direction mais le niveau : si
l'absorbeur est submergé et que le prix traverse la zone, l'hypothèse est morte — fait
observable et daté, non opinion.

**Décision.** Le produit principal du moteur est une invalidation structurelle exploitable à
l'étage 9, fournissant un emplacement de protection fondé sur le comportement réel du marché
plutôt que sur un pourcentage arbitraire. L'élément directionnel est secondaire. La zone est
délimitée par la répartition du volume absorbé et non par les extrêmes de l'épisode, établie sur
la série brute d'un contrat unique (ADR-011), traduite par la base si utilisée sur le spot, et
porte une fraîcheur et un compteur de retests.

**Conséquences.** Le moteur reste utile même si son pouvoir prédictif directionnel se révèle
faible — hypothèse prudente retenue par défaut. Le test décisif devient : un stop placé sur la
zone fait-il mieux qu'un stop de volatilité équivalente ?

---

## ADR-041 — Absorption et épuisement se séparent par les dérivées, pas par l'image

**Statut** : figé (étape 3.4)

**Contexte.** « Quelqu'un bloque » et « les attaquants s'essoufflent » sont deux causes
distinctes qui produisent exactement la même observation : volume agressif élevé et absence de
progression du prix. Un détecteur construit sur l'instantané produit une étiquette choisie par
l'analyste, pas par la donnée — et les deux motifs ont des suites différentes.

**Décision.** La séparation se fait sur les dérivées : dans l'absorption le côté passif est
**fort** (réapprovisionnement soutenu et régulier) ; dans l'épuisement le côté agressif est
**faible** (pente d'agressivité décroissante). La diminution de l'agressivité n'est pas un
symptôme parmi d'autres, c'est le critère définitionnel. Privé du carnet, le moteur déclare
« stagnation de cause indéterminée » au lieu de trancher arbitrairement.

**Conséquences.** Séparer correctement les deux motifs améliore le taux de base des **deux**,
donc la calibration, même sans apporter de signal supplémentaire. C'est la justification
principale de ce moteur.

---

## ADR-042 — L'épuisement n'existe qu'ancré sur une impulsion et relativement à sa saisonnalité

**Statut** : figé (étape 3.4)

**Contexte.** Un motif défini par une diminution se heurte à deux fréquences parasites.
D'abord, l'agressivité décroît en permanence : la fréquence inconditionnelle de « l'agressivité
baisse » est énorme. Ensuite, elle décroît **systématiquement** aux transitions de séance —
clôture de Londres, fin de séance new-yorkaise, approche de la coupure, creux asiatique — de
sorte qu'un détecteur naïf produit un signal quotidien parfaitement régulier et parfaitement
vide.

**Décision.** Trois conditions d'ancrage obligatoires : une impulsion directionnelle préalable
qualifiée, un contexte de niveau, une fenêtre bornée rattachée à l'impulsion. Et la
décroissance d'agressivité est évaluée **relativement à la décroissance normale de la tranche de
session** (ADR-007, ADR-021), jamais en absolu.

**Conséquences.** Même remède que `ABSENT_PAR_CONCEPTION` (ADR-024) : une baisse attendue n'est
pas un signal. La définition d'impulsion devient un objet partagé et versionné, à définir une
seule fois pour tous les moteurs qui l'utiliseront.

---

## ADR-043 — L'épuisement tue une hypothèse, il n'en crée pas

**Statut** : figé (étape 3.4)

**Contexte.** Que les attaquants perdent leur force signifie que le mouvement s'arrête, pas
qu'il s'inverse. L'issue modale d'un épuisement est une **consolidation**, éventuellement suivie
d'une reprise dans le même sens. Traiter l'épuisement comme un signal de retournement revient à
parier sur l'issue la moins probable des trois, avec un stop nécessairement large puisque le
mouvement initial vient de démontrer sa puissance.

**Décision.** L'épuisement retire de la masse de probabilité à la continuation immédiate, en
transfère l'essentiel vers la consolidation et marginalement vers le retournement. La sortie du
moteur ne comporte **aucun champ de direction proposée** — absence délibérée. Son usage
principal est le veto sur entrée tardive, fonction d'abstention alignée sur I4.

**Conséquences.** La valeur économique du moteur passe par les entrées évitées plutôt que par
les entrées produites. Les entrées tardives sur mouvement épuisé cumulant mauvais prix et stop
éloigné, c'est la population dont l'espérance nette est la plus négative.

---

## ADR-044 — Le climax est un motif distinct de l'épuisement progressif

**Statut** : figé (étape 3.4)

**Contexte.** « Accélération suivie d'un rejet » n'est pas un essoufflement graduel : c'est une
poussée qui échoue d'un coup. Signature, horizon et mécanisme diffèrent. Fusionner les deux dans
un détecteur unique mélange deux populations dont les issues se compensent et rend le taux de
base illisible.

**Décision.** Détecteur séparé, avec sa propre signature — pic de vitesse, effondrement de la
profondeur, élargissement du spread, retour rapide d'une part importante du mouvement,
déclenchement fréquent juste au-delà d'un niveau visible. Comme l'absorption, le climax est
ancré sur un niveau et produit une invalidation exploitable.

**Conséquences.** Le dernier trait est mesurable et devient un test : la proportion de climax
survenant juste au-delà d'un niveau visible, et l'écart d'issue entre ceux-là et les autres.

---

## ADR-045 — Déterminer si la quantité cachée est observable avant d'écrire un détecteur

**Statut** : figé (étape 3.5)

**Contexte.** Selon la classe de données, un ordre à quantité cachée relève de l'inférence ou de
l'observation directe. Avec un carnet par ordre conservant l'identité à travers les recharges,
le fait est lisible ; avec un carnet agrégé, il ne peut qu'être supposé. Publier une probabilité
sur un fait directement observable est une perte d'information déguisée en prudence.

**Décision.** La sémantique du protocole est vérifiée dans sa documentation officielle avant
toute écriture de code — indicateur dédié éventuel, conservation de l'identifiant à la recharge,
évolution de la priorité de file. Le moteur est écrit en deux couches, un noyau d'observation et
une couche d'inférence, dont les sorties portent un mode explicite et ne se confondent pas dans
la fusion. Le critère discriminant du mode inféré est **causal** : une quantité cachée se
recharge parce qu'elle a été exécutée, jamais de sa propre initiative — ce qui l'écarte d'un
algorithme de cotation, lequel annule et se repositionne spontanément.

**Conséquences.** Si le mode observé est disponible, le champ de confiance disparaît. Si les
deux modes coexistent, le mode observé fournit une **vérité terrain** permettant de mesurer le
taux d'erreur du mode inféré — la seule occasion de ce type dans toute la famille microstructure.

---

## ADR-046 — Pas de probabilité sur un état latent invérifiable

**Statut** : figé (étape 3.5)

**Contexte.** Sans donnée révélant l'ordre, il n'existe aucune étiquette permettant de vérifier
qu'un iceberg était présent. Une « confiance 73 % » sur cette présence est donc structurellement
incalibrable : rien ne permettra jamais de vérifier que 73 % des cas annoncés à 73 % en
contenaient un. Ce n'est pas un défaut de méthode mais une impossibilité.

**Décision.** Le système ne publie pas de probabilité sur un état latent invérifiable. Il publie
une probabilité sur une **conséquence observable** — ici, la probabilité que le niveau tienne à
un horizon donné, calibrable sur les cas historiques. La description du motif est conservée,
sans pourcentage, accompagnée d'un score sur une échelle nommée.

**Conséquences.** Règle générale dépassant cette étape, et complément direct de l'ADR-037 : ce
dernier interdit les pourcentages non calibrés, celui-ci interdit les pourcentages
**incalibrables par nature**. Réoriente les sorties du système vers les grandeurs vérifiables.

---

## ADR-047 — Aucune estimation de la quantité cachée résiduelle

**Statut** : figé (étape 3.5)

**Contexte.** Le champ « contrats exécutés estimés » recouvre trois grandeurs de statuts
opposés : le volume déjà exécuté au niveau (observé, exact), la taille totale de l'ordre
(invérifiable), et la quantité restante (invérifiable, et la plus tentante puisqu'elle dirait
quand le niveau va céder).

**Décision.** Seul le volume exécuté observé depuis la détection est publié. Aucune
extrapolation sur le résiduel caché. Si une telle extrapolation est un jour tentée, elle
constitue un modèle à part entière avec sa calibration et son incertitude propres — jamais un
champ d'affichage.

**Conséquences.** Application de l'ADR-025 au niveau d'un agent : la couche d'analyse ne fabrique
pas plus de nombres que la couche de données ou le modèle de langage.

---

## ADR-048 — L'événement exploitable est la cessation, pas la présence

**Statut** : figé (étape 3.5)

**Contexte.** Tant que la quantité cachée absorbe, le niveau tient et la situation est déjà
décrite par le moteur d'absorption. L'événement qui change la situation est l'arrêt des
recharges : le niveau devient non protégé et cède fréquemment dans les instants qui suivent.

**Décision.** Le moteur est un suiveur d'état plutôt qu'un classificateur d'instant :
`PRÉSUMÉ_ACTIF → RECHARGES_ESPACÉES → ÉPUISÉ → NIVEAU_CÉDÉ`, avec une branche
`RETIRÉ_SANS_EXÉCUTION` qui mesure directement le taux de fausse détection. La transition
`ÉPUISÉ` est vérifiable après coup, donc calibrable, contrairement à la présence.

**Conséquences.** Même logique que l'ADR-040 : le produit principal est un niveau et sa condition
d'invalidation. Avantage propre à ce moteur : il ne se déclenche que sur des exécutions réelles,
lesquelles engagent du capital — c'est le motif le plus difficile à simuler de la famille, ce
qui justifie un poids relatif plus élevé qu'aux signaux purement déclaratifs du carnet.

---

## ADR-049 — Un pic de spread est un défaut de données, jamais une classe de motif

**Statut** : figé (étape 3.6)

**Contexte.** Parmi les quatre cas à distinguer lors d'un balayage, trois décrivent un
comportement de marché et le quatrième — le pic dû au spread — décrit une panne du socle : une
cotation invalide, relevant de la divergence idiosyncratique (ADR-009), du rang quantile de
spread (ADR-007) et du quorum (ADR-006).

**Décision.** Le pic de spread ne figure pas parmi les classes du classifieur. S'il parvient
jusqu'à ce moteur, c'est le contrôle qualité qui a échoué, et l'incident est enregistré comme
tel.

**Conséquences.** Évite que le moteur apprenne à tolérer des données corrompues au lieu que le
socle les rejette. Sans cette séparation, chaque pic de spread serait « expliqué » plutôt que
signalé, et le défaut deviendrait invisible.

---

## ADR-050 — L'état du carnet avant l'événement est la seule référence discriminante

**Statut** : figé (étape 3.6)

**Contexte.** Après un balayage, tous les carnets paraissent minces : la liquidité a été
consommée. Mesurer la profondeur après coup ne sépare donc pas le trou de liquidité du
déplacement réel. Le discriminant est l'état du carnet **immédiatement avant** le premier
événement de la séquence — carnet normalement garni puis consommé contre carnet déjà vide.

**Décision.** L'état du carnet est capturé en continu de manière à être consultable *tel qu'il
était* juste avant tout événement détecté. Sans cette référence antérieure, le moteur se déclare
indisponible plutôt que de classer à l'aveugle.

**Conséquences.** Application directe de la bitemporalité (ADR-004, ADR-008) à la microstructure,
avec un coût de stockage à budgéter. Le discriminant principal reste l'impact par unité de
volume : un trou de liquidité déplace beaucoup le prix pour peu de contrats échangés, là où un
déplacement institutionnel coûte cher à produire — et c'est ce coût qui en fait un signal.

---

## ADR-051 — L'impulsion de nouvelle se qualifie par le calendrier puis par la simultanéité inter-marchés

**Statut** : figé (étape 3.6)

**Contexte.** Une publication programmée est une **lecture d'état**, pas une inférence : le
calendrier donne l'instant. Pour une nouvelle non programmée, le meilleur discriminant est la
simultanéité inter-marchés — une information réelle sur l'or reprice aussi le dollar, les taux
réels et l'argent, là où un trou de liquidité ne bouge que l'or. Or les étapes 2.1 à 2.4 ne
prévoient **aucune donnée inter-marchés**.

**Décision.** Le calendrier est consulté en premier et prime sur toute classification
statistique. Pour le cas non programmé, deux options à trancher : ajouter au socle un flux
minimal de marchés corrélés, ou accepter que la classe reste confondue **et le déclarer dans la
sortie** (`simultanéité_intermarchés = INDISPONIBLE`). La confusion silencieuse est exclue.

**Conséquences.** Première lacune identifiée dans le socle depuis l'étape 2 : le système ne
contient que de l'or. Question Q30 ouverte.

---

## ADR-052 — Nommer la cascade observable, pas l'intention supposée

**Statut** : figé (étape 3.6)

**Contexte.** Des ordres de protection s'accumulent au-delà des niveaux visibles ; atteints, ils
se déclenchent mécaniquement, consomment la liquidité, poussent le prix plus loin et déclenchent
les suivants ; la réserve épuisée, la pression disparaît d'un coup. Ce mécanisme est observable.
Qu'un acteur l'ait délibérément provoqué ne l'est pas.

**Décision.** Le motif est nommé par ce qui est observé — cascade de liquidation au-delà d'un
niveau — et non par un mobile supposé. La sortie décrit niveau franchi, concentration de
l'agression au-delà, brièveté de la poussée, part retracée. Aucune probabilité n'est publiée sur
l'intention (ADR-046).

**Conséquences.** Ce motif recouvre largement le climax (ADR-044), dont il est le mécanisme le
plus fréquent : les deux détecteurs sont réconciliés plutôt que juxtaposés, pour qu'un même
événement ne soit pas compté deux fois par la fusion (ADR-035).

---

## ADR-053 — Un pivot porte deux horodatages ; sa disponibilité est sa confirmation

**Statut** : figé (étape 4.1)

**Contexte.** Une définition « N bougies à droite » rend un sommet identifiable seulement N
bougies après sa formation. Le graphique l'affiche pourtant à sa date de formation, comme s'il
avait été connu à ce moment. Toute analyse construite sur cette illusion produit des résultats de
backtest excellents et inatteignables.

**Décision.** Chaque pivot porte `instant_formation` et `instant_confirmation`. L'instant de
disponibilité au sens de I1 est la **confirmation**, jamais la formation. La latence de
confirmation est mesurée et publiée dans la sortie, pour que l'étage 9 sache si un pivot est
arrivé trop tard pour être exploitable.

**Conséquences.** Le compromis latence / fiabilité devient explicite : plus un pivot est
significatif, plus il est confirmé tard. Ce n'est pas un défaut d'implémentation mais une
propriété de la définition, à mesurer plutôt qu'à contourner.

---

## ADR-054 — Les pivots sont définis sur le chemin de prix, pas sur les bougies

**Statut** : figé (étape 4.1)

**Contexte.** Une détection fondée sur des bougies hérite des conventions d'agrégation et de
frontière de journée (ADR-022) : deux conventions produisent deux ensembles de pivots différents
sur les mêmes prix, et un décalage d'une heure redécoupe tout deux fois par an. « N bougies à
droite » mesure par ailleurs une durée qui dépend du pas choisi, pas une propriété du marché.

**Décision.** Un extrême est confirmé lorsque le prix s'en écarte de plus d'un seuil θ dans le
sens opposé ; tant que ce retournement n'a pas eu lieu, l'extrême reste `PROVISOIRE` et peut
s'étendre. Un extrême provisoire ne peut jamais être utilisé comme s'il était confirmé — version
structurelle de l'interdiction d'imputer (ADR-025). La méthode par bougies reste implémentée
comme point de comparaison, pour mesurer la divergence entre approches.

**Conséquences.** θ est exprimable en unités de volatilité, l'instant de confirmation devient
mécanique, et la méthode est naturellement multi-échelle. Réserve à traiter : la normalisation
par ATR est biaisée aux transitions de régime, l'ATR n'ayant pas rattrapé le nouveau niveau
— d'où une normalisation complémentaire par la volatilité réalisée sur la durée propre du
mouvement.

---

## ADR-055 — La hiérarchie des pivots est relationnelle, pas un découpage par seuils

**Statut** : figé (étape 4.1)

**Contexte.** Cinq classes définies par seuils indépendants ne forment pas une hiérarchie
cohérente : rien n'empêche un pivot d'être classé « intermédiaire » sans être contenu dans une
structure supérieure, ni deux critères de se contredire — forte amplitude et faible durée.

**Décision.** Plusieurs seuils croissants appliqués au même chemin produisent une décomposition
**emboîtée par construction** : tout pivot d'un niveau supérieur est pivot de tous les niveaux
inférieurs. La classe découle de cette position, et chaque pivot porte son parent. À cela
s'ajoute une **significativité continue** — amplitude, durée, volume, contexte — qui n'est pas
la classe mais une mesure indépendante. Volume, durée et importance temporelle deviennent des
attributs, jamais des critères de détection.

**Conséquences.** La cohérence de la hiérarchie est structurelle et non vérifiée après coup. La
séparation détection / attributs préserve le déterminisme : sans volume, la détection reste
identique et seule la significativité est incomplète.

---

## ADR-056 — Définition de pivot unique, versionnée, et sensibilité mesurée en aval

**Statut** : figé (étape 4.1)

**Contexte.** Blocs d'ordres, déséquilibres de prix, ruptures de structure et changements de
caractère se définissent tous par référence aux pivots. Une modification de θ ne change pas un
détail : elle redessine toute la structure aval.

**Décision.** La définition de pivot est unique et versionnée pour l'ensemble du système ; aucun
moteur ne la redéfinit localement. La sensibilité de chaque conclusion aval à θ est mesurée et
publiée. Critère d'acceptation du moteur : **deux implémentations écrites séparément à partir de
la spécification doivent produire exactement le même ensemble de pivots** — seul test réellement
contraignant de l'exigence « définition mathématique ». Prérequis de l'étape 4 : vérifier que le
prix réagit aux niveaux de pivot plus qu'à des niveaux de contrôle de saillance comparable.

**Conséquences.** Résout Q27 : l'impulsion partagée entre moteurs est une jambe de la
décomposition à un niveau déclaré. Si le test de réaction échoue, toutes les briques ultérieures
héritent d'une fondation vide — mieux vaut le savoir avant d'écrire cinq moteurs par-dessus.

---

## ADR-057 — La structure de marché est une machine à états, pas trois détecteurs

**Statut** : figé (étape 4.2)

**Contexte.** BOS et CHOCH ont la même géométrie — un franchissement de pivot. Ils ne diffèrent
que par leur rapport à l'état structurel courant. Les traiter comme deux détecteurs distincts
laisse subsister une décision de jugement là où il n'y en a pas.

**Décision.** Un état structurel est maintenu par niveau de décomposition. Un franchissement
dans le sens de l'état est un BOS ; contre l'état, un CHOCH, qui fait entrer dans un état de
**transition** et jamais directement dans l'état inverse. Le basculement exige une seconde
rupture dans le nouveau sens ; un retour dans l'ancien sens est un **échec de CHOCH**,
enregistré comme information et non comme non-événement.

**Conséquences.** « Le CHOCH ne signifie pas automatiquement un retournement » devient mécanique
plutôt que prudentiel. Le taux de base des deux issues depuis l'état de transition devient
mesurable, ce qui donne un contenu chiffré à cette prudence.

---

## ADR-058 — Une rupture est une pénétration soutenue, définie sans référence à une clôture

**Statut** : figé (étape 4.2)

**Contexte.** « Clôture au-delà du niveau » et « absence de simple mèche isolée » expriment le
même besoin : la pénétration doit durer. Mais « clôture » suppose une bougie, donc une convention
d'agrégation (ADR-022) — la dépendance que l'ADR-054 vient d'éliminer.

**Décision.** Une rupture est définie par deux paramètres : une profondeur δ en unités de
volatilité et une persistance τ en temps-événement. Une mèche isolée échoue sur τ, un
effleurement sur δ. Volume et vitesse sont conservés comme **attributs de corroboration**, jamais
comme conditions d'existence — sans quoi la détection dépendrait de la disponibilité du volume et
différerait entre le listé et le spot.

**Conséquences.** Deux paramètres explicitement calibrables remplacent une convention implicite.
Propriété garantie : à θ fixé, la suite des états est déterministe et ne se repeint pas. Test
d'acceptation associé — un rejeu incrémental doit produire exactement la même suite d'états
qu'un calcul en une passe sur l'historique complet.

---

## ADR-059 — Le MSS est un score continu, pas une conjonction binaire

**Statut** : figé (étape 4.2)

**Contexte.** Exiger simultanément cinq conditions binaires cumule trois défauts : cinq seuils à
régler (multiplicité maximale, ADR-034), rareté de la conjonction donc intervalle de confiance du
taux de base plus large que l'effet cherché, et dérive de calibration — face à un détecteur qui
ne se déclenche presque jamais, on assouplit les seuils jusqu'à obtenir « assez » de signaux,
ajustant les paramètres à une fréquence désirée plutôt qu'aux données.

**Décision.** Les cinq éléments deviennent des attributs mesurés en continu et attachés à toute
rupture ; le MSS est le haut de ce continuum, découpé par quantile. Le critère « maintien après
rupture » étant une issue et non une entrée (ADR-038), deux produits distincts coexistent : la
rupture immédiate et la rupture retenue après fenêtre de maintien, avec des taux de base
différents à mesurer séparément.

**Conséquences.** Le taux de base devient estimable sur toute l'échelle plutôt que sur quelques
spécimens parfaits, les attributs manquants dégradent le score au lieu d'annuler la détection, et
il devient possible de mesurer **lequel des cinq attributs porte l'information** — question
qu'une conjonction binaire interdit de poser.

---

## ADR-060 — Les échelles sont emboîtées et publient leur rapport signal/bruit

**Statut** : figé (étape 4.2)

**Contexte.** La structure exprimée en unités de temps réintroduirait la dépendance aux
conventions d'agrégation que l'ADR-054 a supprimée. Par ailleurs les échelles sont emboîtées par
construction : une rupture au niveau large implique des ruptures aux niveaux fins, donc « quatre
échelles concordent » n'est pas quatre confirmations mais souvent une information vue quatre
fois. Enfin, « bruit élevé » n'est pas une direction : c'est un constat de qualité de signal.

**Décision.** La structure est calculée par niveau de décomposition θ, les étiquettes temporelles
n'étant qu'une correspondance d'affichage versionnée. Le recouvrement entre échelles est déclaré
(ADR-035). Chaque niveau publie une mesure de rapport signal/bruit et retourne `INDÉTERMINÉ` en
dessous d'un seuil calibré, au lieu d'une direction. Les grandeurs exploitables sont
l'alignement entre niveaux et le niveau le plus proche du basculement, pas les états pris
isolément.

**Conséquences.** Le bruit cesse d'être un cas particulier de l'échelle la plus fine : c'est une
propriété mesurée partout, qui frappe notamment lors des transitions de volatilité. Test associé,
posé tôt car il peut invalider l'étape : le BOS apporte-t-il quelque chose **conditionnellement à
une mesure de tendance simple**, ou n'est-il qu'un habillage du momentum ?

---

## ADR-061 — Le déséquilibre se mesure par la densité de négociation, pas par trois bougies

**Statut** : ⚠️ **remplacé par l'ADR-065** (spécification détaillée de l'étape 4.3)

> Cette décision faisait de la densité la définition principale et des trois bougies un repli.
> La spécification détaillée retient une position plus juste : **deux objets de première classe**
> coexistent, `ICT_FVG` et `EXECUTION_VOID`, dont le recouvrement est une grandeur mesurée. Le
> constat sur la dépendance aux bougies reste valable et est repris par l'ADR-066.

**Contexte.** La règle des trois bougies est un indicateur indirect du phénomène réel : une
région traversée si vite qu'elle n'a presque pas été négociée. Elle dépend de la convention
d'agrégation (ADR-022), elle est binaire — un chevauchement d'un pas de cotation annule le motif
alors que la région reste tout aussi peu négociée — et elle ne dit rien de l'intensité.

**Décision.** Un déséquilibre est une zone contiguë de densité anormalement basse dans le profil
d'activité par niveau de prix construit sur la jambe d'impulsion, rapportée à ses voisines et à
la normale conditionnelle de la session. La méthode en trois bougies est conservée comme repli et
comme comparaison ; la sortie déclare sa méthode, et une zone détectée par repli porte une
incertitude supérieure.

**Conséquences.** La définition devient continue et indépendante des bougies. Contrainte assumée :
elle exige l'activité par niveau de prix, donc le listé — sur le spot, seul le repli est
calculable, ce qui mesure aussi ce que le spot perd faute de volume.

---

## ADR-062 — Un écart dû à une fermeture ou à un raccord n'est pas un déséquilibre

**Statut** : figé (étape 4.3)

**Contexte.** Les plus grands écarts de prix de l'or sont l'ouverture du dimanche, la reprise
après coupure quotidienne et les frontières de roll. Un détecteur naïf les classe **en tête** de
son palmarès de qualité, puisqu'ils sont les plus grands. Or un déséquilibre suppose que le
marché **pouvait** négocier et ne l'a pas fait : quand le marché est fermé, l'absence de
négociation n'est pas une inefficience, c'est une absence.

**Décision.** Tout écart chevauchant une fermeture, une coupure ou un férié est exclu sur
décision du calendrier (ADR-021) et non d'un seuil. Aucune zone ne franchit une frontière de
roll ; les zones vivent sur la série brute d'un contrat unique (ADR-011) et ne sont jamais
calculées sur une série ajustée (ADR-012).

**Conséquences.** Ferme la boucle ouverte à l'étape 2.2 : les faux déséquilibres ne sont plus
corrigés après coup, ils sont rendus impossibles par la définition. Sans calendrier, ce moteur
produit ses signaux les plus spectaculaires et les plus faux — d'où son indisponibilité stricte
en l'absence de calendrier.

---

## ADR-063 — La pénétration est continue ; les statuts et le repère à mi-zone sont des hypothèses

**Statut** : ⚠️ **partiellement remplacé par l'ADR-068 et l'ADR-073**

> Le principe — pénétration continue, statuts déclarés, repère à mi-zone à tester — est conservé
> et précisé par la spécification détaillée. L'ADR-068 sépare remplissage, mitigation et
> invalidation ; l'ADR-073 corrige la mise en œuvre en statut multi-axes.

**Contexte.** Les statuts neuf / touché / mitigé / invalidé forment un automate, mais la grandeur
physique est la profondeur de pénétration, continue. Par ailleurs le repère à mi-zone n'est
justifié par aucun mécanisme : c'est le milieu géométrique d'une zone définie par une convention.

**Décision.** Le moteur publie la profondeur maximale atteinte et la profondeur de chaque visite ;
les statuts sont des découpages déclarés de cette mesure, et le seuil de mitigation est un
**paramètre calibré sur la distribution empirique des profondeurs de rebond**, non une constante
à 50 %. `INVALIDÉ` reçoit sa définition manquante : la zone a été entièrement traversée et le
prix a poursuivi au-delà.

**Conséquences.** Le repère à mi-zone devient testable plutôt que postulé. S'il ressort de la
mesure, il est retenu et calibré ; si la distribution est plate, il est décoratif et abandonné.

---

## ADR-064 — Plafond de densité des zones actives, faute de quoi la confluence est vide

**Statut** : figé (étape 4.3)

**Contexte.** Les zones de déséquilibre sont nombreuses. Sans expiration ni plafond, la carte s'en
couvre, et au-delà d'une certaine densité **tout prix se trouve en confluence avec quelque
chose**. L'attribut de confluence mesure alors la densité du détecteur, pas une coïncidence
remarquable.

**Décision.** Deux mécanismes obligatoires : une règle d'expiration calibrée — durée, distance
parcourue en volatilité, nombre de visites — et un **plafond du nombre de zones actives par
niveau de décomposition**, ne conservant que les meilleures selon le score de qualité. Le score
lui-même est construit par attributs continus et découpage en quantiles (ADR-059), et retiré s'il
ne sépare pas les comportements (ADR-027).

**Conséquences.** Une confluence garantie par construction n'est pas une confirmation, c'est un
miroir. Le plafond rend l'attribut mesurable. Constat général associé, à retenir pour la fusion :
huit sorties du système peuvent décrire un seul événement de marché ; le décompte honnête des
sources réellement distinctes est de l'ordre de deux ou trois, et tout nouveau moteur doit
démontrer un apport **incrémental conditionnel**, jamais un pouvoir prédictif absolu.

---

> **Note de numérotation.** La spécification détaillée de l'étape 4.3 proposait ses propres
> décisions numérotées 061 à 068, en collision avec les ADR-061 à 064 déjà figés sur le même
> sujet. Les numéros 065 à 072 leur sont attribués, dans l'ordre d'origine. Aucun numéro déjà
> publié n'est réutilisé — les décisions contredites sont marquées comme remplacées, jamais
> réécrites.
>
> | Numérotation d'origine | Numéro retenu |
> | --- | --- |
> | ADR-061 (ICT_FVG / EXECUTION_VOID) | **ADR-065** |
> | ADR-062 (convention d'agrégation versionnée) | **ADR-066** |
> | ADR-063 (disponibilité = clôture de la 3ᵉ bougie) | **ADR-067** |
> | ADR-064 (remplissage / mitigation / invalidation) | **ADR-068** |
> | ADR-065 (score appris et calibré) | **ADR-069** |
> | ADR-066 (famille causale déplacement + BOS + FVG) | **ADR-070** |
> | ADR-067 (témoins appariés et modèle de momentum) | **ADR-071** |
> | ADR-068 (contacts analytiques / exécutables) | **ADR-072** |

---

## ADR-065 — `ICT_FVG` et `EXECUTION_VOID` sont deux objets de première classe

**Statut** : figé (étape 4.3 détaillée) · remplace l'ADR-061

**Contexte.** Un déséquilibre graphique et un vide d'exécution ne mesurent pas la même chose. Le
premier dépend de la convention d'agrégation des bougies ; le second est fondé sur l'activité
réellement observée. Traiter l'un comme le repli de l'autre, comme le faisait l'ADR-061, empêche
de mesurer leur relation.

**Décision.** Les deux objets sont détectés, stockés et évalués séparément. Ils peuvent se
superposer mais ne sont jamais équivalents. Le recouvrement entre eux est une **grandeur
mesurée**, dont la valeur prédictive additionnelle est à établir. L'`EXECUTION_VOID` est retenu
sous forme d'**intensité continue** plutôt que de conjonction de trois seuils, pour les mêmes
raisons que l'ADR-059.

**Conséquences.** L'`EXECUTION_VOID` exige volume et activité par niveau de prix : il n'est
calculable que sur le listé. Sur le spot, le recouvrement vaut `INDISPONIBLE` et jamais `0` —
une absence de mesure n'est pas une absence de vide.

---

## ADR-066 — Un `ICT_FVG` est indissociable de sa convention d'agrégation versionnée

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Un même chemin de prix produit des motifs différents selon l'unité de temps,
l'heure d'ancrage, le fuseau, le fournisseur, la base de prix, les ticks manquants et la méthode
de construction des bougies. Enregistrer `timeframe = M5` ne permet ni de reproduire ni de
comparer.

**Décision.** Chaque objet porte un identifiant d'agrégation complet — type et taille de barre,
fuseau et décalage d'ancrage, base de prix, marché, fournisseur, version de schéma. **Deux
objets issus de conventions différentes sont deux objets différents**, même si leurs zones sont
proches, et ne sont ni fusionnés ni comparés.

**Conséquences.** Application directe des ADR-022 et ADR-036 à la structure. Rend exécutable le
test d'acceptation « le changement d'heure ne modifie pas silencieusement les conventions ».

---

## ADR-067 — La disponibilité est la clôture de la troisième bougie

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Un graphique affiche le motif dès la formation de la bougie centrale. Le moteur ne
peut le connaître qu'après la clôture de la troisième.

**Décision.** `availability_timestamp = close_time(C_{i+1})`. Avant cet instant l'objet est
`PROVISOIRE` et ne peut jamais servir à envoyer un ordre. `origin_timestamp` est fixé au **début
de la bougie centrale**, sans ambiguïté, sans quoi tous les âges se décalent d'une bougie.

**Conséquences.** Cas non couvert et tranché ici : l'`EXECUTION_VOID` n'a pas de troisième
bougie. Sa disponibilité est l'instant où la traversée est achevée **et** la fenêtre de mesure de
densité complète — strictement postérieure à la traversée, faute de quoi le vide serait détecté
pendant sa formation.

---

## ADR-068 — Remplissage, mitigation et invalidation sont trois notions distinctes

**Statut** : figé (étape 4.3 détaillée) · précise l'ADR-063

**Contexte.** Une zone peut être entièrement remplie sans que le scénario soit invalidé — le prix
traverse, prend la liquidité au-delà de la borne distale, réintègre, puis repart dans le sens
initial. Inversement une zone peut n'être pas remplie et avoir perdu toute pertinence.

**Décision.** Les trois notions sont mesurées séparément. La mitigation exige une **réaction
postérieure au contact**, définie mathématiquement, et n'est attribuée qu'après coup : au moment
du contact, le moteur ne connaît que `CANDIDATE`. Le prix de référence de la réaction est le
**prix exécutable au contact**, et la volatilité de normalisation est celle disponible **au
contact**, non à la création. La politique d'invalidation appartient à la stratégie.

**Conséquences.** Interdit l'usage rétroactif de la confirmation comme si elle était disponible
au premier contact (ADR-038).

---

## ADR-069 — Le score de qualité est appris à partir de probabilités mesurées

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Un barème additif aux poids choisis produit un nombre d'apparence rigoureuse sans
contenu fréquentiel.

**Décision.** Les variables brutes sont stockées d'abord ; un modèle calibré estime ensuite des
probabilités distinctes — premier contact, rejet après contact, remplissage complet, réaction au
CE, continuation — et des excursions attendues. Le score n'est qu'une **présentation synthétique
de ces probabilités**.

**Conséquences.** Application de l'ADR-037. Précision ajoutée : les excursions adverses et
favorables ont des distributions asymétriques à queue épaisse, dont la moyenne est un mauvais
résumé — publier des quantiles, pas seulement l'espérance.

---

## ADR-070 — Déplacement, rupture et déséquilibre forment une seule famille causale

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Ces trois objets peuvent provenir du même mouvement de prix. Les additionner comme
trois preuves séparées produit un double ou triple comptage.

**Décision.** Ils sont regroupés dans une famille causale unique,
`STRUCTURAL_DISPLACEMENT_CLUSTER`, transmise telle quelle à la fusion. Une séquence structurelle
fortement documentée n'est pas trois signaux statistiquement indépendants.

**Conséquences.** Instanciation concrète de l'ADR-035 côté structure, symétrique de la famille
microstructure. L'avertissement correspondant figure dans la sortie utilisateur.

---

## ADR-071 — Valeur établie contre témoins appariés et contre un modèle simple

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Une zone de déséquilibre est créée par un déplacement fort ; sa performance
apparente peut provenir entièrement du momentum, de la volatilité, du régime ou de la rupture
structurelle.

**Décision.** Deux tests obligatoires. Premièrement, comparaison à des zones témoins appariées
sur largeur, âge, session, volatilité, distance au prix, déplacement préalable et position dans
le range — ainsi qu'aux milieux d'impulsion, VWAP, retracements standards et zones de faible
volume. Deuxièmement, mesure de l'**apport incrémental** une fois connus momentum, volatilité,
régime et rupture. Réponse négative hors échantillon ⇒ aucun poids autonome dans l'analyseur.

**Conséquences.** Ces tests doivent être conduits **séparément pour chaque hypothèse** —
attraction, réaction, invalidation (ADR-074) : une réponse globale négative masquerait un usage
valable. Le budget de recherche de l'ADR-034 s'applique intégralement, la combinatoire de cette
étape dépassant le millier de tests implicites.

---

## ADR-072 — Contacts analytiques et contacts exécutables sont stockés séparément

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Un prix médian composite peut toucher une zone alors que le prix réellement
négociable ne la touche pas. Un élargissement brutal du spread peut créer un contact fictif.

**Décision.** `analytical_touch` et `executable_touch` sont conservés séparément. Une entrée
n'est validée que sur le prix exécutable — `ask` à l'achat, `bid` à la vente. Un contact causé
uniquement par une anomalie de spread porte `touch_quality = SPREAD_DISTORTED` et n'est pas
assimilé à une mitigation. La base de prix utilisée pour mesurer le remplissage est également
déclarée : un remplissage mesuré sur le médian et une entrée validée sur l'exécutable peuvent
différer d'un spread entier, ce qui suffit à franchir ou non le CE.

**Conséquences.** Relie le moteur de structure au socle de données : la qualité du spread
(ADR-007, ADR-009) conditionne l'interprétation des contacts.

---

## ADR-073 — Le statut d'une zone est un vecteur, pas un état unique

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** La spécification détaillée établit qu'une zone peut être entièrement remplie sans
être invalidée, et non remplie tout en ayant perdu sa pertinence. Or son énumération de statuts
place `FULLY_FILLED`, `INVALIDATED` et `MITIGATION_CANDIDATE` dans un champ unique, donc
mutuellement exclusifs — rendant ces deux situations inexprimables. Contradiction interne.

**Décision.** Quatre axes indépendants : confirmation (`PROVISOIRE | CONFIRMÉ`), remplissage
(`NEUF | TOUCHÉ | PARTIEL | CE_ATTEINT | COMPLET`), mitigation (`SANS_OBJET | CANDIDATE |
CONFIRMÉE | ÉCHOUÉE`), validité (`ACTIVE | INVALIDÉE | EXPIRÉE | DONNÉES_INVALIDES`).

**Conséquences.** Même correction que pour les statuts de données (ADR-024), et pour la même
raison : des dimensions orthogonales forcées dans une énumération unique rendent inexprimables
les états qui comptent le plus.

---

## ADR-074 — Détection et exécution sur des marchés différents exigent une traduction par la base

**Statut** : figé (étape 4.3 détaillée)

**Contexte.** Une zone détectée sur le listé et une zone utilisable sur le spot ne partagent pas
la même échelle de prix : elles diffèrent de la base, qui évolue avec les taux et le coût de
portage. Afficher une zone unique sous l'étiquette « GC / XAU/USD » masque un décalage
systématique, de l'ordre de grandeur de la largeur des petites zones.

**Décision.** Tout objet de structure porte son marché de détection et son marché d'exécution, la
base au moment de la création et au moment du contact, les bornes traduites avec leur
incertitude, et la fraîcheur de la base. Sans base fraîche, l'objet est indisponible pour l'usage
spot.

**Conséquences.** Généralise à tout l'étage 4 la mise en garde de `02b` §1. Ajoute une
troisième hypothèse à tester au §26 de la spécification — l'**hypothèse d'invalidation** : la
borne distale fournit-elle un meilleur emplacement de protection qu'un stop de volatilité
équivalente ? Elle peut être vraie même si attraction et réaction sont fausses, et agit sur
l'espérance nette par le dimensionnement plutôt que par la direction.

---

> **Note de numérotation (étape 4.4).** La spécification détaillée proposait des décisions
> numérotées 073 à 082, en collision avec les ADR-073 et ADR-074 figés à l'étape 4.3. Les numéros
> **075 à 084** leur sont attribués dans l'ordre d'origine. Deux d'entre elles convergent avec des
> décisions déjà prises — elles sont enregistrées comme extensions explicites plutôt que comme
> doublons.
>
> | Numérotation d'origine | Numéro retenu | Relation |
> | --- | --- | --- |
> | ADR-073 (objet dérivé distinct) | **ADR-075** | — |
> | ADR-074 (acceptation mesurable obligatoire) | **ADR-076** | — |
> | ADR-075 (candidat immédiat / accepté retardé) | **ADR-077** | — |
> | ADR-076 (quatre axes d'état) | **ADR-078** | généralise ADR-073 |
> | ADR-077 (marchés séparés, base, incertitude) | **ADR-079** | étend ADR-074 |
> | ADR-078 (bornes canoniques immuables) | **ADR-080** | — |
> | ADR-079 (épisodes de rôle versionnés) | **ADR-081** | — |
> | ADR-080 (trois hypothèses, trois modèles) | **ADR-082** | — |
> | ADR-081 (cluster causal de retournement) | **ADR-083** | — |
> | ADR-082 (prix, base et volatilité figés au retest) | **ADR-084** | — |

---

## ADR-075 — L'IFVG est un objet dérivé, la source n'est jamais modifiée

**Statut** : figé (étape 4.4)

**Contexte.** Inverser le sens d'un FVG existant détruirait son historique et rendrait
impossible l'étude du rôle initial comme du rôle inversé.

**Décision.** L'IFVG est un objet distinct référençant `source_fvg_id`. Le FVG source conserve
bornes, sens, horodatages et historiques ; l'IFVG possède ses propres disponibilité, retests,
réactions et validité. Sa création ne supprime jamais la source.

**Conséquences.** Les deux rôles restent mesurables séparément, condition pour répondre à la
question de recherche de l'étape.

---

## ADR-076 — Une acceptation mesurable est obligatoire ; un remplissage ne suffit pas

**Statut** : figé (étape 4.4)

**Contexte.** Un FVG peut être entièrement traversé puis immédiatement réintégré. Traiter ce cas
comme une inversion produirait un objet à chaque oscillation.

**Décision.** L'inversion exige une acceptation mesurée par un vecteur continu — profondeur,
occupation temporelle, volume au-delà, distance moyenne, réintégrations échouées, vitesse, flux —
agrégé par une fonction versionnée en une intensité `I_A ∈ [0,1]`. Le découpage en classes est une
commodité d'interface, jamais un substitut à la valeur continue. Un franchissement peu profond
mais durablement occupé peut être accepté ; un franchissement profond immédiatement réintégré ne
l'est pas.

**Conséquences.** Remplissage et inversion deviennent deux phénomènes distincts et mesurables
séparément.

---

## ADR-077 — Candidat immédiat et inversion acceptée sont publiés séparément

**Statut** : figé (étape 4.4)

**Contexte.** L'acceptation ne peut être évaluée qu'après une fenêtre. Publier un seul objet
laisserait croire que l'inversion confirmée était connue au premier tick de franchissement.

**Décision.** `IFVG_CANDIDATE` est disponible immédiatement avec une fiabilité faible ;
`IFVG_ACCEPTED` n'est disponible qu'après la fenêtre. Le coût de la confirmation est publié :
latence et déplacement du prix pendant la confirmation.

**Conséquences.** Même structure que la rupture immédiate contre la rupture retenue (ADR-059) :
deux produits distincts, deux taux de base, un arbitrage qui se calcule.

---

## ADR-078 — Formation, retest, réaction et validité sont quatre axes indépendants

**Statut** : figé (étape 4.4) · généralise l'ADR-073

**Contexte.** Un rôle inversé peut être correctement formé, retesté, ne pas avoir réagi, et rester
néanmoins valide pour un autre horizon. Un statut unique rend cet état inexprimable.

**Décision.** Quatre axes indépendants, avec `CENSORED` sur l'axe réaction et `SUSPENDED` sur
l'axe validité.

**Conséquences.** Confirme la correction apportée à l'étape 4.3 et l'étend à un objet dont le
cycle de vie est plus riche. L'éligibilité au retest ne commence qu'après l'acceptation, ce qui
empêche de détecter une inversion et son retest dans la même oscillation.

---

## ADR-079 — Traduction de base assortie d'une incertitude, avec suspension

**Statut** : figé (étape 4.4) · étend l'ADR-074

**Contexte.** L'ADR-074 imposait la traduction par la base entre marché de détection et marché
d'exécution. Il manquait le traitement de l'**incertitude** de cette traduction.

**Décision.** L'incertitude `u_b` est publiée, ainsi que son rapport à la largeur de la zone.
Au-delà d'un seuil versionné, la validité passe à `SUSPENDED` et l'éligibilité à l'exécution est
retirée : une zone dont l'incertitude de traduction vaut une fraction importante de la largeur
n'est pas exploitable. Une base périmée rend la zone d'exécution indisponible, la zone analytique
restant visible.

**Conséquences.** Les bornes d'exécution sont des **vues recalculées**, jamais une vérité
persistée (seules les bornes canoniques le sont). Cas complémentaire à trancher avec Q18 : une
suspension survenant alors qu'une position est ouverte suit la conduite du mode dégradé — ne pas
augmenter, ne pas élargir les protections, traiter la dégradation comme motif de réduction.

---

## ADR-080 — Les bornes canoniques sont immuables

**Statut** : figé (étape 4.4)

**Contexte.** Ajuster rétroactivement les bornes pour épouser la réaction observée fabriquerait
une performance apparente.

**Décision.** Les bornes canoniques ne changent jamais après confirmation. Les bornes de réaction
observée et les bornes d'exécution sont des propriétés dérivées, stockées séparément et marquées
comme telles.

**Conséquences.** Condition de la non-repeinture et du test batch contre streaming.

---

## ADR-081 — Chaque changement de rôle accepté crée un épisode versionné

**Statut** : figé (étape 4.4)

**Contexte.** Une zone peut changer plusieurs fois de rôle. Modifier le sens d'un objet existant
réécrirait l'historique à chaque oscillation.

**Décision.** Épisodes successifs identifiés et versionnés, chacun avec sa création, son
acceptation, ses retests, ses réactions et sa validité. Les compteurs de franchissements et de
retournements sont des attributs prédictifs, pas des règles d'exclusion.

**Conséquences.** Correction nécessaire relevée ici : un compteur de retournements brut est
**biaisé par l'exposition** — une zone ayant changé cinq fois de rôle est une zone près de
laquelle le prix est resté, donc sélectionnée sur l'attraction. Le dénominateur doit être
l'exposition (temps ou volume écoulé à portée, occasions de franchissement), et la variable
exploitable un taux par unité d'exposition.

---

## ADR-082 — Trois hypothèses, trois modèles, trois validations

**Statut** : figé (étape 4.4)

**Contexte.** Attraction, réaction et qualité de l'invalidation sont indépendantes. Une forte
probabilité de retest peut coexister avec une réaction non exploitable.

**Décision.** Trois modèles distincts et trois validations séparées, contre des contrôles
appariés. Un score unique ne masque jamais leurs différences. Une réponse négative sur la
direction ne doit pas masquer une utilité pour le placement du risque.

**Conséquences.** Confirme l'ajout de l'hypothèse d'invalidation (ADR-074) et l'installe comme
troisième pilier permanent de la famille structure. Deux exigences statistiques associées :
toutes les probabilités sont publiées **en fonction du seuil d'acceptation**, celui-ci définissant
l'échantillon et non un simple réglage ; et l'estimation traite explicitement la **censure et les
risques concurrents**, les issues de la triple barrière étant concurrentes — la grandeur correcte
est une incidence cumulée, pas une proportion binomiale.

---

## ADR-083 — Cluster causal de retournement

**Statut** : figé (étape 4.4)

**Contexte.** Le franchissement produisant l'inversion peut aussi produire un CHOCH, un MSS, un
déplacement et une prise de liquidité — un seul mouvement, cinq sorties.

**Décision.** Regroupement obligatoire dans `ROLE_REVERSAL_CLUSTER`, transmis tel quel à la
fusion, jamais compté comme plusieurs preuves indépendantes.

**Conséquences.** Deuxième instanciation de l'ADR-035 côté structure, après
`STRUCTURAL_DISPLACEMENT_CLUSTER` (ADR-070).

---

## ADR-084 — Prix, base de prix et volatilité sont figés à l'événement qui les utilise

**Statut** : figé (étape 4.4)

**Contexte.** Trois volatilités coexistent — création de la source, début du franchissement,
retest — et ne sont pas interchangeables. Utiliser la volatilité de création plusieurs heures plus
tard fausse toutes les mesures normalisées.

**Décision.** Chaque grandeur est estimée avec l'information disponible à son événement, puis
figée pour cet événement. Le prix de référence d'une réaction est le prix **exécutable** au
retest, jamais une borne théorique non négociable. Contacts analytiques et exécutables restent
séparés.

**Conséquences.** Rend exécutable le test d'absence de fuite temporelle : chaque propriété porte
son horodatage de disponibilité, et le moteur de features ne la charge que si celle-ci précède
l'instant de décision.

---

## ADR-085 — `PriceAcceptance` est un primitif unique et versionné

**Statut** : figé (étape 4.4) · décision ajoutée

**Contexte.** La notion d'« acceptation d'un prix » est aujourd'hui définie **quatre fois** dans le
système : maintien après rupture de structure (ADR-059), prix accepté après balayage (`03f` §8),
acceptation du franchissement d'inversion (ADR-076), et invalidation canonique du rôle inversé,
que la spécification décrit elle-même comme « une logique analogue au franchissement initial ».

C'est la situation exacte de Q27 avant l'étape 4.1 : une notion partagée redéfinie localement,
garantissant que deux moteurs se contrediront sur le même événement.

**Décision.** `PriceAcceptance` devient un primitif unique et versionné, prenant une frontière,
une direction, une fenêtre et une volatilité de référence, et produisant le vecteur de preuves et
l'intensité. Les quatre usages en sont des appels paramétrés, jamais des réimplémentations.

**Conséquences.** Une seule fonction à calibrer, valider et faire varier dans les tests de
sensibilité, au lieu de quatre. Même traitement que la définition d'impulsion (ADR-056).

---

## ADR-086 — L'ordre de validation suit l'ordre de dérivation

**Statut** : figé (étape 4.4) · décision ajoutée

**Contexte.** Trois tests fondateurs restent sans réponse : les niveaux de pivot provoquent-ils
une réaction (ADR-056) ; le déséquilibre apporte-t-il quelque chose au-delà d'un contrôle apparié
(ADR-071) ; l'inversion apporte-t-elle quelque chose au-delà d'un changement de rôle générique
(ADR-082). Chacun dépend du précédent.

**Décision.** Ordre imposé : pivots, puis déséquilibre, puis inversion. **Un résultat positif à un
niveau dont le niveau inférieur a échoué est traité comme suspect, non comme une découverte.**
Écrire les moteurs par avance reste légitime — la spécification est utile et le code se réutilise —
mais aucun poids ne leur est accordé avant que leur fondation ait passé son propre test.

**Conséquences.** Observation de séquencement associée : le coût de construction croît nettement
plus vite que le nombre de sources d'information réellement distinctes, lequel n'a pas augmenté
depuis l'étape 4.1. À budget fini, ce coût mérite d'être comparé à celui de la résolution des
questions bloquantes du registre, qui conditionnent la valeur de tout ce qui a été spécifié.

---

## ADR-087 — Gel de la spécification structurelle et validation séquentielle par gates

**Statut** : figé (interlude 4)

**Contexte.** Quatre moteurs structurels sont spécifiés — pivots, ruptures, déséquilibre,
inversion — sans qu'aucun n'ait été validé. Ils dérivent d'une même famille causale, de sorte que
la complexité descriptive croît nettement plus vite que le nombre de sources d'information
indépendantes. Engager l'étape 4.5 ajouterait un étage sur une fondation non testée.

**Décision.** La spécification structurelle est gelée après `04d`. Quatre gates sont définis :
résolution des dépendances (Q1, Q19, Q36), implémentation des primitifs communs seulement, puis
tests séquentiels des pivots, du déséquilibre et de l'inversion. Chaque gate a une hypothèse
nulle, une population, des contrôles appariés, des mesures et une condition de passage. L'échec
d'un gate ramène à zéro le poids prédictif de son étage, les étages dérivés restant explorables
sous marquage `FOUNDATION_FAILED` et `EXPLORATORY_ONLY`. La reprise de 4.5 exige une condition
scientifique, d'ingénierie plafonnée, ou stratégique explicite.

**Conséquences.** Répond à Q39. Le projet passe d'un mode d'accumulation à un mode d'élimination.
Les moteurs déjà spécifiés conservent leur valeur de reproductibilité mais aucun poids de
production tant que leur gate n'est pas franchi.

---

## ADR-088 — Propagation de validité : les données se propagent, la prédiction non

**Statut** : figé (interlude 4)

**Contexte.** Un objet dérivé référence une source. Deux invalidations très différentes peuvent
frapper cette source : une invalidation **de données** (donnée corrompue, révisée, discontinuité
d'instrument) et une invalidation **prédictive** du rôle d'origine.

**Décision.** Une invalidation de données se propage nécessairement : l'objet dérivé passe en
`dependency_state = INVALID_SOURCE` et `validity_state = SUSPENDED`, sans suppression, puis le
moteur détermine s'il est reproductible, reconstructible, à remplacer par une version, ou
définitivement invalide. Une invalidation prédictive **ne se propage pas** : elle peut être
précisément la condition de naissance de l'objet dérivé.

**Conséquences.** Un objet dérivé ne survit jamais à la corruption de ce dont il dérive, mais
survit à l'échec prédictif de son parent. Sans cette asymétrie, la création même d'une inversion
serait contradictoire.

---

## ADR-089 — Perte de qualité analytique et invalidation économique sont deux événements

**Statut** : figé (interlude 4)

**Contexte.** Lorsque l'incertitude de traduction intermarchés dépasse son seuil alors qu'une
position est ouverte, deux réactions opposées sont tentantes : ignorer la dégradation, ou clôturer
automatiquement.

**Décision.** Sans position : entrées interdites, ordres conditionnels suspendus ou annulés,
renforts interdits, signal marqué non exécutable. Avec position ouverte : les protections déjà
placées sont **maintenues**, le risque est évalué sur le marché réel d'exécution, les renforts sont
interdits, aucun déplacement de stop dépendant de la zone traduite n'est autorisé, la dégradation
est signalée, et la politique de Q18 s'applique. **Le système ne clôture pas automatiquement au
seul motif que la traduction est devenue incertaine.**

**Conséquences.** Cohérent avec le mode dégradé de `02e` §10 : ne pas augmenter, ne pas élargir
les protections, traiter la dégradation comme motif de réduction — mais sans confondre la perte
d'un outil d'analyse avec la mort d'une position.

---

## ADR-090 — Analyse de puissance et test d'équivalence obligatoires avant chaque gate

**Statut** : figé (interlude 4) · décision ajoutée

**Contexte.** Un test de puissance insuffisante rend « aucun effet » quelle que soit la réalité. Or
le verdict le plus lourd du protocole — `FOUNDATION_FAILED`, qui ramène à zéro le poids de trois
moteurs — pourrait être prononcé sur un échantillon simplement trop petit. Absence de preuve et
preuve d'absence sont indiscernables sans cette analyse.

**Décision.** Avant chaque gate : (1) déclarer la **taille d'effet minimale économiquement utile**,
dérivée des coûts réels — spread, commissions, glissement, base — donc dépendante de Q36 ; (2)
calculer la puissance disponible pour cette taille sur l'échantillon réel, en tenant compte de
l'autocorrélation et du regroupement par événement, faute de quoi la puissance est largement
surestimée ; (3) si la puissance est insuffisante, le déclarer **avant** le test, le verdict
possible devenant `INDÉTERMINÉ` et jamais `ÉCHEC`. Conclure « n'apporte rien » exige un **test
d'équivalence** montrant que l'effet est inférieur à la plus petite taille utile, non l'échec d'un
test de significativité.

**Conséquences.** Le Cas E de la hiérarchie des conclusions n'est fondé que sous cette condition.
La plus petite taille d'effet utile est une ancre rare : elle se calcule à partir des coûts et ne
dépend d'aucune croyance sur le marché.

---

## ADR-091 — Contrôle négatif du protocole avant tout test réel

**Statut** : figé (interlude 4) · décision ajoutée

**Contexte.** Le composant qui décide de tout n'est aucun moteur, mais l'échantillonneur de
contrôles appariés. Un appariement défaillant fabrique des différences inexistantes ou en masque.
Aucun gate n'a de valeur si cet instrument est faux, et rien dans le protocole ne le vérifie.

**Décision.** La chaîne complète — échantillonnage, appariement, estimation par risques
concurrents, mesure d'apport incrémental — est d'abord exécutée sur une **étiquette connue pour ne
porter aucune information** : pivots réattribués au hasard parmi des instants comparables, ou
labels permutés en préservant la structure temporelle. Résultat nul ⇒ instrument étalonné, les
gates peuvent commencer. Effet détecté ⇒ **le protocole est cassé**, tout résultat positif
ultérieur est sans valeur, et la cause est corrigée avant toute autre chose.

**Conséquences.** Version expérimentale de la règle de `02e` §11 : un instrument qu'on n'a jamais
vu rendre un zéro correct n'est pas un instrument.

---

## ADR-092 — Politique d'usage de l'échantillon réservé à travers les gates

**Statut** : figé (interlude 4) · décision ajoutée

**Contexte.** L'ADR-034 réserve une fraction d'historique pour la validation finale. Le protocole
enchaîne trois gates ; si chacun y puise, il n'en reste rien au troisième — et le résultat le plus
structurant serait prononcé sur des données déjà vues.

**Décision.** Contrôle négatif, conduite des trois gates et analyse de puissance se font sur le
**jeu d'exploration** uniquement. Le **jeu réservé est ouvert une seule fois**, pour le verdict
final sur la chaîne entière. Toute consultation est enregistrée avec sa date et son motif ; une
seconde ouverture n'est pas interdite mais **dégrade explicitement la confiance**, et cette
dégradation est publiée avec le verdict.

**Conséquences.** Deux précisions de méthode associées. Le balayage du seuil d'acceptation est
jugé comme **une courbe unique** — régularité, monotonie, cohérence — et non comme une série de
tests indépendants, sans quoi il recrée le problème de multiplicité qu'il cherche à éviter. Et un
résultat « déséquilibre positif, pivots négatifs » n'est pas incohérent : le déséquilibre ne
dépend pas des pivots, et ce cas signifierait que les **événements de déplacement** portent une
information que les **niveaux** ne portent pas — conclusion plausible qui réorienterait la
pondération du système.

---

## ADR-093 — Effet minimal économiquement utile et puissance démontrée avant chaque gate

**Statut** : figé (addendum interlude 4)

**Contexte.** Un résultat non significatif peut traduire un échantillon insuffisant, une variance
élevée, des observations dépendantes, une censure excessive, ou un effet réel inférieur à la
résolution expérimentale — pas une absence d'effet.

**Décision.** Chaque gate déclare `δ_MEU = C_total + M_sécurité`, exprimé dans l'unité économique
finale, et démontre une puissance suffisante pour cette taille d'effet. Le regroupement par
événement, séance, zone et événement macro est obligatoire ; la taille effective d'échantillon
remplace le nombre de lignes ; les méthodes supposant l'indépendance sont exclues. Un rapport de
puissance complet est publié avant le gate, et la puissance cible n'est jamais réduite après coup.

**Conséquences.** Une amélioration de log-loss sans conséquence économique mesurable ne valide
aucun moteur. Complément ajouté : `δ_MEU` s'accompagne d'un plancher de fréquence `f_min`, le
critère portant sur l'espérance nette **par unité de temps** et non par occurrence — un effet réel
survenant deux fois par an n'est ni exploitable ni validable. Ce plancher est calculable avant
tout test, à partir du seul historique d'occurrences.

---

## ADR-094 — L'inutilité se démontre par test d'équivalence

**Statut** : figé (addendum interlude 4)

**Contexte.** Échouer à rejeter une hypothèse nulle ne prouve pas qu'elle est vraie.

**Décision.** Conclure qu'un moteur n'apporte rien exige de démontrer que son effet est contenu
dans `[−δ_MEU, +δ_MEU]`, l'intervalle de confiance devant y être entièrement inclus. L'échec d'un
test de significativité ne suffit jamais.

**Conséquences.** Rend le verdict `FAIL_EQUIVALENT_TO_ZERO` opposable, et interdit de le confondre
avec un simple manque de preuve.

---

## ADR-095 — Six verdicts distincts, aux conséquences distinctes

**Statut** : figé (addendum interlude 4)

**Contexte.** Un protocole qui ne dispose que de « ça marche » et « ça ne marche pas » attribuera
l'un des deux même quand il ne sait pas.

**Décision.** `PASS_USEFUL_EFFECT`, `FAIL_EQUIVALENT_TO_ZERO`, `INDETERMINATE_UNDERPOWERED`,
`INDETERMINATE_WIDE_INTERVAL`, `PROTOCOL_INVALID`, `HOLDOUT_COMPROMISED`. `FOUNDATION_FAILED`
exige simultanément équivalence à zéro, contrôle négatif réussi, puissance vérifiée et intégrité
du jeu réservé.

**Conséquences.** Un `INDETERMINATE` met le poids de production à zéro **par prudence**, sans
constituer une preuve d'absence et sans justifier la suppression de la spécification. Poids nul et
moteur réfuté deviennent deux états différents.

---

## ADR-096 — Contrôle négatif temporellement et structurellement contraint

**Statut** : figé (addendum interlude 4) · précise l'ADR-091

**Contexte.** Une permutation totalement aléatoire détruirait l'autocorrélation, la saisonnalité,
les grappes de volatilité et l'exposition — rendant le contrôle trop facile à passer et sans
valeur diagnostique.

**Décision.** L'étiquette négative conserve tout ce que le protocole prétend contrôler et ne
détruit que l'information spécifique testée : permutation par blocs, réattribution de pivots entre
instants comparables, pseudo-zones de mêmes caractéristiques. Le pipeline complet est exécuté
jusqu'au verdict. Un effet détecté sur étiquette vide invalide le protocole et **suspend tous les
résultats positifs obtenus avec le même pipeline**.

**Conséquences.** Liste de causes à instruire en cas d'échec : fuite temporelle, appariement,
exposition, dépendances, sélection après observation, censure, réutilisation du jeu réservé,
coûts asymétriques, double comptage.

---

## ADR-097 — Audit de l'appariement : balance, support commun, sensibilité

**Statut** : figé (addendum interlude 4)

**Contexte.** L'échantillonneur de contrôles appariés décide de tous les résultats. Un appariement
défaillant fabrique ou masque des effets.

**Décision.** Balance mesurée sur toutes les variables d'appariement, seuils préenregistrés,
`MATCHING_INVALID` en cas d'échec. Le modèle de résultat ne sert jamais à corriger un appariement
défaillant. Positivité vérifiée : sans support commun, les événements sont exclus et la conclusion
précise sa population réelle. Analyse de sensibilité estimant la force qu'aurait dû avoir un
facteur non observé pour expliquer l'effet.

**Conséquences.** Un résultat fragile à un faible biais résiduel ne reçoit pas le poids d'un
résultat robuste.

---

## ADR-098 — Ouverture unique du jeu réservé et dette de holdout

**Statut** : figé (addendum interlude 4) · précise l'ADR-092

**Contexte.** Trois gates séquentiels consommeraient le jeu réservé avant le verdict final.

**Décision.** Le jeu réservé est ouvert **une seule fois**, pour la chaîne figée entière, après gel
des objets, population, horizons, coûts, métriques, contrôles, modèles, seuils, politique de
censure et versions logicielles. Événement d'audit obligatoire. Toute ouverture supplémentaire
crée une **dette de holdout** publiée, effaçable uniquement par un jeu temporel jamais observé, une
réplication sur une autre source, une période future, ou un marché comparable défini à l'avance.

**Conséquences.** Complément ajouté sur la **constitution** du jeu : un tirage aléatoire est
insuffisant, l'autocorrélation et le chevauchement de régimes faisant fuir l'information. Le jeu
réservé est une **période contiguë postérieure**, séparée par un intervalle tampon au moins égal à
la plus longue dépendance modélisée. La forme la plus solide reste une période **future non encore
survenue** au moment du gel, ce qui rend la fuite matériellement impossible.

---

## ADR-099 — La courbe de seuil est un objet fonctionnel unique

**Statut** : figé (addendum interlude 4)

**Contexte.** Analyser un balayage comme une collection de tests indépendants, puis retenir le
meilleur seuil, recrée exactement la multiplicité que le balayage cherchait à éviter.

**Décision.** Le résultat est une fonction, examinée sur sa forme, sa régularité, sa dérivée, sa
monotonie, sa stabilité entre périodes et régimes, avec **bandes de confiance simultanées** et
comptage des événements restants à chaque valeur. Un pic isolé absent des périodes voisines est
présumé artefact. Le seuil opérationnel est choisi après analyse, en optimisant un critère
préspécifié sous contraintes de puissance, d'effectif, de perte maximale, de stabilité et de
calibration.

**Conséquences.** Interdit de choisir le seuil pour maximiser un chiffre affiché.

---

## ADR-100 — Gate fondateur de la famille microstructure

**Statut** : figé (addendum interlude 4)

**Contexte.** Six moteurs partagent une source événementielle unique. Avant d'affiner leur
sémantique, il faut savoir si leur information survit à la latence réelle de l'architecture.

**Décision.** Le gate compare l'**effet résiduel après latence de bout en bout** au seuil
économiquement utile. Verdicts : `LATENCY_VIABLE`, `LATENCY_NON_VIABLE`, `LATENCY_INDETERMINATE`,
`LATENCY_REGIME_DEPENDENT`. Un verdict négatif ne supprime pas les moteurs : il peut conduire à
rapprocher le calcul du marché, réduire la latence, viser un horizon plus lent, agréger le signal,
ou le reclasser en variable de contexte.

**Conséquences.** Asymétrie imposée : un résultat **positif** obtenu sur un signal grossier est
conclusif — un raffinement ne peut qu'améliorer. Un résultat **négatif** sur signal grossier ne
l'est pas, un signal bruité ayant une décroissance apparente raccourcie ; il rend
`LATENCY_INDETERMINATE`, sauf s'il provient du pré-test de phase 0, qui ne dépend d'aucune
définition de signal.

---

## ADR-101 — La priorité d'un test se mesure au coût de se tromper sans lui

**Statut** : figé (addendum interlude 4)

**Contexte.** Un gain informationnel estimé avant le test n'est qu'une croyance, et une croyance
optimiste justifie toujours de continuer.

**Décision.** La priorité est déterminée par le rapport entre le coût de l'erreur évitable et le
coût du test. Le coût de se tromper inclut développement inutile, données, maintenance, faux
sentiment de diversification, double comptage, risque d'exécution, capital perdu et retard sur les
composants essentiels. Ordre retenu : Q19, Q36, Q1, contrôles négatifs, puissance, gates
structurels, nouvelles familles.

**Conséquences.** Un test peu coûteux capable de ramener une famille entière à zéro a une valeur
élevée **parce que** son résultat est inconnu.

---

## ADR-102 — La latence se mesure conditionnellement aux états où le signal se déclenche

**Statut** : figé (protocole Q19) · décision ajoutée

**Contexte.** Les signaux de microstructure se déclenchent lors de rafales d'événements — c'est
précisément alors que la file de décodage s'allonge, que le courtier est le plus sollicité et que
les recotations apparaissent. La distribution marginale de la latence sous-estime donc
systématiquement la latence subie au moment utile.

**Décision.** Chaque échantillon de latence porte son état de marché concomitant — débit
d'événements, régime de volatilité, tranche de session, fenêtre de publication, phase de rollover.
La grandeur entrant dans le gate est le centile **conditionnel à la rafale**, non le centile
marginal. Deux termes de latence habituellement omis sont mesurés explicitement : la
**dissémination** entre l'appariement et la publication du flux, qui peut dominer sur un flux
agrégé ou différé, et la **cadence d'évaluation**, qui ajoute systématiquement la moitié de sa
période en moyenne.

**Conséquences.** L'écart entre latence marginale et conditionnelle est un résultat en soi : élevé,
il révèle une infrastructure qui se dégrade quand elle est sollicitée.

---

## ADR-103 — La fenêtre d'horizon rentable remplace la demi-vie

**Statut** : figé (protocole Q19) · décision ajoutée

**Contexte.** Une décroissance exponentielle depuis un maximum situé à l'instant du signal est une
double hypothèse fragile. Pour beaucoup de signaux l'avantage **croît** d'abord, le mouvement
devant se développer, ce qui rend la formule de demi-vie inapplicable.

**Décision.** La grandeur publiée est l'ensemble des durées de détention pour lesquelles
l'avantage net dépasse les coûts. Trois formes informatives : vide (non exploitable), bornée avec
une borne inférieure strictement positive (il faut attendre après l'entrée), ou classique.
L'avantage est **intégré sur la distribution de latence** mesurée, non évalué à un point — évaluer
à la médiane surestime, au 99ᵉ centile sous-estime, et la queue est épaisse.

**Conséquences.** Le coût de la latence est asymétrique selon le type d'ordre : au marché il se
paie en glissement, terme certain de `C_total` ; à cours limité il se paie en non-exécution, qui
est une **observation censurée** et non une perte. Les deux régimes sont mesurés et rapportés
séparément.

---

## ADR-104 — La boucle d'ordre se mesure en production, jamais en démonstration

**Statut** : figé (protocole Q19) · décision ajoutée

**Contexte.** Les environnements de démonstration acheminent souvent les ordres par une
infrastructure distincte, exécutent au prix affiché sans file réelle, ne produisent ni rejet ni
recotation ni exécution partielle, et n'exposent à aucune sélection adverse. La latence qu'ils
mesurent peut différer de celle de production d'un ordre de grandeur.

**Décision.** Mesure en deux niveaux sur compte réel. **Niveau A** : ordres à cours limité placés
loin du marché puis annulés immédiatement, mesurant l'aller-retour émission → accusé et
annulation → confirmation sur l'infrastructure de production, à coût quasi nul — dans le respect
des limites de débit et des conditions du courtier. **Niveau B** : un nombre restreint d'ordres au
marché à taille minimale, seul moyen de mesurer l'exécution effective, le glissement et le taux de
rejet. Le dimensionnement vise un intervalle de confiance sur un centile élevé, **par bucket
d'état de marché** ; un bucket sous-échantillonné est déclaré tel plutôt que moyenné.

**Conséquences.** Une mesure conduite en démonstration rend `PROTOCOL_INVALID`. Toute modification
d'hébergement ou de courtier invalide les campagnes antérieures, d'où une version
d'infrastructure attachée à chaque échantillon.

---

## ADR-105 — Le coût est une surface, pas un scalaire ; `δ_MEU` en hérite

**Statut** : figé (protocole Q40)

**Contexte.** Le coût total dépend simultanément de l'horizon de détention, du type d'ordre, de la
tranche de session, de la taille et du régime de volatilité. Le terme de financement, seul terme
proportionnel à la durée, rend en particulier le coût dépendant de l'horizon.

**Décision.** Il n'existe pas un seuil `δ_MEU` mais une **surface**
`δ_MEU(h, type d'ordre, session, taille, régime)`. Un gate rend un verdict **par cellule**, ou
déclare explicitement la cellule sur laquelle il conclut. Le coût entrant dans le seuil est le
coût **conditionnel à l'état de marché où le signal se déclenche**, jamais le coût moyen — pendant
exact de la latence conditionnelle (ADR-102).

**Conséquences.** Un moteur peut légitimement être `PASS` en séance liquide et
`FAIL_EQUIVALENT_TO_ZERO` en creux asiatique ; ce n'est pas une contradiction. Éclaire pourquoi
Q36 bloque Q40 : fixer les horizons revient à choisir la tranche de surface sur laquelle le projet
se prononce, non à exprimer une préférence.

---

## ADR-106 — Pas de terme de latence séparé du glissement

**Statut** : figé (protocole Q40)

**Contexte.** La formule de coût de l'addendum additionne un terme de glissement et un terme de
latence. Or un glissement mesuré de bout en bout **contient déjà** l'effet de la latence : les
additionner compte deux fois la même chose, surestime le seuil et rejette donc des effets réels.

**Décision.** Deux formulations valides, jamais mélangées. **Mesurée** — le glissement observé en
phase 2B de Q19 remplace tout terme de latence. **Modélisée** — avant la campagne, une fonction
explicite de la latence, de la volatilité et du type d'ordre tient lieu de glissement, et son
incertitude entre dans `M_sécurité`. La formulation mesurée est préférée dès qu'elle existe.

**Conséquences.** `M_sécurité` est décomposée en trois composantes estimées séparément —
incertitude d'estimation, dégradation recherche/production, décroissance de l'avantage dans le
temps — la troisième étant la plus grande et la moins connue, ce qu'un chiffre unique masquerait.

---

## ADR-107 — L'horizon minimal viable se calcule avant tout signal

**Statut** : figé (protocole Q40)

**Contexte.** Les coûts de transaction sont approximativement fixes par aller-retour, tandis que la
volatilité croît approximativement en racine carrée du temps. Le rapport `κ(h) = C_total(h)/σ(h)`
— nombre d'écarts-types à capturer pour seulement couvrir ses frais — décroît donc en `1/√h`.

**Décision.** Le projet calcule `κ(h)` et en déduit `h_min`, l'horizon en dessous duquel aucun
avantage prédictif réaliste ne peut couvrir ses frais, **par tranche de session**. Ce calcul ne
requiert ni signal, ni étiquette, ni modèle, ni compte réel : seulement le spread effectif du
courtier, la commission et la volatilité réalisée multi-échelle. Il constitue le livrable minimal
du protocole Q40 et ne dépend d'aucune autre question ouverte.

**Conséquences.** Pendant exact de la phase 0 de Q19 : les deux calculs bornent le domaine du
possible avant qu'une ligne de moteur ne soit écrite — l'un par la latence, l'autre par les coûts,
et leurs conclusions se cumulent. Réserve explicite : `h_min` est une borne, non une garantie ;
un horizon supérieur est simplement **non exclu par les coûts**, et l'approximation en `√h` se
dégrade en présence de tendance, d'autocorrélation ou de sauts.

---

## ADR-108 — La sélection adverse est un coût mesuré, pas un poste de barème

**Statut** : figé (protocole Q40)

**Contexte.** Un ordre à cours limité n'est pas exécuté au hasard : il est exécuté
préférentiellement quand le marché vient vers vous, donc quand vous avez tort. Le rendement
conditionnel à l'exécution est systématiquement inférieur au rendement inconditionnel. Ce coût
n'apparaît sur aucun relevé de frais et ne se déduit d'aucun barème.

**Décision.** La sélection adverse est mesurée en comparant le résultat des ordres réellement
exécutés à celui qu'aurait produit une exécution garantie au même prix. Elle entre dans
`C_total` pour toute stratégie passive.

**Conséquences.** Un backtest supposant une exécution à cours limité systématique est optimiste,
et l'ampleur du biais est exactement ce terme. Renforce le traitement de la non-exécution en
observation censurée (ADR-103) plutôt qu'en absence neutre.

---

## ADR-109 — Le coût minimal utile est une surface déclarée par cellule

**Statut** : figé (Q40 phase 0) · confirme et précise l'ADR-105

**Décision.** `δ_MEU` est défini par horizon, type d'ordre, session, taille et régime. Aucun
verdict global ne peut masquer cette dépendance : chaque gate déclare la cellule ou le domaine
sur lequel il conclut.

**Conséquences.** Une même famille de moteurs peut être exclue sur une cellule et éligible sur une
autre. C'est un résultat, pas une incohérence.

---

## ADR-110 — Deux méthodes de coût, jamais mélangées

**Statut** : figé (Q40 phase 0)

**Décision.** Soit l'implementation shortfall observé, soit la décomposition modélisée. Une
estimation ne combine jamais les deux. L'interdiction est appliquée par le constructeur de
conventions : une combinaison invalide échoue avant tout calcul.

**Conséquences.** Le respect de la règle cesse de dépendre de la discipline de l'auteur.

---

## ADR-111 — L'implementation shortfall contient déjà latence et glissement

**Statut** : figé (Q40 phase 0) · confirme l'ADR-106

**Décision.** En méthode observée, ni spread, ni glissement, ni coût de latence ne sont ajoutés :
ils sont contenus dans l'écart entre le prix de remplissage et le prix de référence de décision.

**Conséquences.** Les additionner gonflerait le seuil et rejetterait des effets réels.

---

## ADR-112 — Conventions de prix, de spread et d'aller-retour déclarées et versionnées

**Statut** : figé (Q40 phase 0)

**Décision.** Toute expérience porte `reference_price_convention`, `cost_measurement_method`,
`round_trip_definition` et `spread_counting_convention`, avec une empreinte stable. Ne jamais
comparer une performance de mi-prix à mi-prix avec un coût déjà mesuré depuis le mi-prix, ni un
aller simple avec un coût aller-retour.

**Conséquences.** Deux résultats de conventions différentes deviennent identifiables comme
incomparables, au lieu de l'être silencieusement.

---

## ADR-113 — Le coût passif inclut exécution partielle, non-exécution et sélection adverse

**Statut** : figé (Q40 phase 0) · précise l'ADR-108

**Décision.** Un ordre à cours limité n'est jamais considéré comme gratuit au motif qu'il n'a pas
payé le spread de façon visible. Sont publiés : probabilité d'exécution, exécution partielle,
délai, dérive post-exécution, taux d'annulation avant exécution, incertitude de file. Un backtest
supposant une exécution intégrale au contact de la limite est invalide pour la mesure économique.

---

## ADR-114 — L'amplitude est mesurée empiriquement ; la racine du temps est un contrôle

**Statut** : figé (Q40 phase 0)

**Décision.** `σ(h)` est estimée par un estimateur robuste sur les déplacements observés. La loi
en `√h` sert à vérifier l'ordre de grandeur et à repérer les anomalies, jamais à imposer une
courbe.

**Conséquences.** Mesuré à l'exécution : sur des données comportant des sauts, le rapport
observé/attendu atteint **2,6**. Extrapoler l'amplitude longue depuis un horizon court par la
racine du temps l'aurait sous-estimée d'un facteur deux et demi.

---

## ADR-115 — La bande d'avantages plausibles est préenregistrée

**Statut** : figé (Q40 phase 0)

**Décision.** `[a_min, a_max]` est déclarée avant tout calcul de κ, avec sa source et sa date. Le
code exige les deux : une bande sans provenance est rejetée, faute de quoi rien ne distinguerait
une bande préenregistrée d'une bande choisie après lecture de la courbe.

---

## ADR-116 — L'exclusion par les coûts s'appuie sur la borne inférieure de κ

**Statut** : figé (Q40 phase 0)

**Décision.** `COST_NON_VIABLE` exige `LCB[κ] > a_max` ; `COST_HEADROOM` exige `UCB[κ] < a_min`.
L'incertitude joue donc contre la conclusion tranchée dans les deux sens. L'horizon minimal de
coût exige un franchissement **persistant** sur plusieurs horizons consécutifs.

**Conséquences.** Mesuré à l'exécution : sur le jeu de démonstration, la borne supérieure passe
sous `a_max` sur **deux** horizons consécutifs là où la règle en exige trois — le protocole
répond donc « aucun horizon minimal trouvé », là où une lecture ponctuelle aurait annoncé une
valeur. La règle de persistance a joué son rôle sur le premier jeu rencontré.

---

## ADR-117 — Fréquence économique et fréquence statistique sont deux conditions

**Statut** : figé (Q40 phase 0)

**Décision.** `f_min = max(f_min_econ, f_min_stat)`. La première conditionne l'utilité, la seconde
la validabilité. Une borne optimiste d'espérance suffit à conclure `FREQUENCY_NON_VIABLE` **avant
tout test prédictif** si même elle exige plus d'occurrences qu'il n'en survient.

---

## ADR-118 — L'autorité de déclenchement vit dans l'intersection des trois domaines

**Statut** : figé (Q40 phase 0)

**Décision.** `D_feasible = D_cost ∩ D_latency ∩ D_frequency`. Une exclusion l'emporte sur une
indétermination, laquelle l'emporte sur une non-exclusion : **l'ignorance ne vaut jamais
permission**. `ELIGIBLE_FOR_PREDICTIVE_TESTING` ne signifie pas rentable.

---

## ADR-119 — Les ordres lointains annulés mesurent la messagerie, pas l'exécution

**Statut** : figé (Q40 phase 0) · précise l'ADR-104

**Décision.** Ils mesurent émission, accusé, annulation, taux de rejet et stabilité de connexion
sur l'infrastructure de production. Ils **ne mesurent pas** la latence de remplissage, la
priorité de file, le glissement réel, l'impact, la recotation ni la sélection adverse. Ils sont
valides pour une partie du chemin de Q19, jamais comme substitut à une campagne d'exécution.

---

## ADR-120 — Jeu réservé du modèle de coûts : période contiguë postérieure

**Statut** : figé (Q40 phase 0) · confirme l'ADR-098

**Décision.** Contigu, postérieur, séparé par un tampon couvrant la dépendance maximale du
protocole — horizon maximal, durée de position, mémoire du modèle de coût, fenêtre de volatilité,
fenêtre de régime, chevauchement de labels. Aucune ligne du jeu réservé ne contribue au calibrage
de la courbe de coûts.

---

## ADR-121 — La densité de ticks conditionne la validité de l'amplitude

**Statut** : figé (Q40 phase 0) · décision issue de l'implémentation

**Contexte.** Première exécution du protocole : l'amplitude était **identique au chiffre près**
pour des horizons de 1 s, 10 s et 60 s, à la valeur `1,4826 × pas de cotation`. La médiane des
déplacements valait exactement un tick, parce que la série ne contenait qu'un tick toutes les
29 secondes. κ devenait plat aux horizons courts — ce qui se serait lu comme « les coûts ne
dominent pas davantage à 1 s qu'à 60 s », soit l'inverse du mécanisme que la phase 0 doit révéler.

**Décision.** Le nombre de ticks par horizon est publié avec chaque estimation d'amplitude, et
les horizons dont l'amplitude sature sur le pas de cotation sont écartés de l'interprétation :
ils mesurent la discrétisation, pas le marché.

**Conséquences.** S'applique aux données réelles : en creux de liquidité, un horizon de quelques
secondes peut être exactement dans ce régime, et le verdict de coût y serait un artefact.

---

## ADR-122 — Une latence dépassant l'horizon compte comme consommation totale

**Statut** : figé (Q40 phase 0) · décision issue de l'implémentation

**Contexte.** La première version du pré-test écartait les événements où l'instant d'exécution
possible tombait après la fin de la fenêtre d'évaluation. Ne restaient donc que les événements où
l'on avait eu le temps d'agir — un biais de sélection sur les cas favorables. Effet mesuré : à
l'horizon d'une seconde avec une latence p95 de deux secondes, l'échantillon se vidait et le
verdict passait de `NON_VIABLE` à `INDETERMINATE`, transformant un résultat conclusif en absence
de conclusion.

**Décision.** Ces cas comptent comme consommation totale et résiduel nul, jamais comme exclusion
de l'échantillon.

**Conséquences.** Après correction, la part consommée à l'horizon d'une seconde passe de 18 % à
71 % et le verdict redevient conclusif — *il n'y a littéralement plus rien à capturer au moment
où l'on peut enfin agir*.

---

## ADR-123 — Les calculs réels partent des cotations bid/ask, jamais des seules bougies

**Statut** : figé (adaptateur courtier)

**Contexte.** Les données OHLC ne permettent de connaître ni le spread au moment du
déclenchement, ni la densité réelle de cotations, ni les changements intrabar, ni les séquences
bid/ask, ni les rafales, ni les arrivées tardives.

**Décision.** L'entrée de tout calcul de phase 0 est une série de cotations bid/ask horodatées.
Les bougies sont des vues dérivées, produites ensuite et jamais en amont.

**Conséquences.** Une liste historique de spreads ne suffit pas : amplitude, densité, rafales et
coûts doivent être calculés sur la **même chronologie**, et un spread sans son instant n'est
rattachable à rien.

---

## ADR-124 — Les unités économiques sont portées par la valeur

**Statut** : figé (adaptateur courtier) · décision issue de l'implémentation

**Contexte.** Sur XAU/USD, confondre « par once » et « par lot » est un facteur cent. L'erreur
est silencieuse — les deux nombres restent plausibles — et traverse ensuite tout le calcul de
coût. Une convention documentée ne protège de rien.

**Décision.** Chaque grandeur porte son unité ; additionner une unité de cotation et une monnaie
de compte lève une erreur. La seule conversion autorisée passe par la spécification de contrat,
laquelle porte sa source et sa date de relevé et refuse tout calcul de portage tant que la
politique de portage multiplié n'a pas été vérifiée auprès du courtier.

**Conséquences.** Le mode d'échec le plus coûteux de la couche économique devient un état
inaccessible plutôt qu'une consigne.

---

## ADR-125 — Une lacune se classe par ce qui se passe pendant, pas à ses bornes

**Statut** : figé (adaptateur courtier) · décision issue de l'implémentation

**Contexte.** Défaut relevé par le rapport lui-même : sur vingt-cinq journées, **vingt-quatre
coupures nocturnes étaient classées comme interruptions de données** et 83 % de la période
déclarée censurée. La cause tient à la géométrie du problème — une coupure nocturne va de la
clôture de New York à l'ouverture de Londres, et **aucune de ses deux bornes n'est en session
fermée**. Tester les extrémités ne pouvait donc jamais reconnaître une nuit.

Second défaut, trouvé par un test : la cadence « après la lacune » était calculée sur la fenêtre
**précédant** chaque cotation, si bien que le premier tick suivant une lacune affichait une
cadence nulle — la lacune elle-même — et qu'une vraie coupure entre deux périodes actives était
classée inconnue au lieu d'interruption.

**Décision.** La classification échantillonne l'intérieur de la lacune et compare une cadence
rétrospective à une cadence **prospective** distincte.

**Conséquences.** Après correction, les vingt-quatre lacunes deviennent des fermetures de marché
et la part censurée tombe à zéro. Sans cette correction, tout export réel aurait été déclaré
inexploitable — la nuit représente la majorité du temps calendaire.

---

## ADR-126 — La résolution d'horodatage est mesurée et comparée à l'inter-arrivée en rafale

**Statut** : figé (adaptateur courtier) · décision issue de l'implémentation

**Contexte.** Une résolution à la milliseconde suffit à quinze cotations par seconde et perd
tout l'ordre interne d'une rafale à cinq cents. Or la rafale est précisément le régime qui
gouverne la latence conditionnelle (ADR-102).

**Décision.** La granularité effective est inférée du plus petit écart non nul réellement
observé, puis comparée à l'inter-arrivée en rafale. Insuffisante, elle produit une réserve
explicite : la mesure de coût reste possible, l'ordre interne des rafales ne l'est pas.
Symétriquement, sans synchronisation d'horloge fiable la latence **absolue** est déclarée
indisponible, l'ordre temporel local restant utilisable.

---

## ADR-127 — Les coûts non mesurés sont traités par scénarios, jamais fixés à zéro

**Statut** : figé (adaptateur courtier)

**Contexte.** Glissement agressif, impact et sélection adverse ne sont mesurables que par une
campagne d'exécution. Les omettre revient à les poser à zéro, ce qui produit une carte de
faisabilité optimiste présentée comme neutre.

**Décision.** Trois cartes sont produites : optimiste (coûts certains seuls), centrale, prudente
(bornes supérieures déclarées sur les termes non mesurés). Chaque borne porte sa justification ;
une borne sans justification est refusée.

**Conséquences.** L'écart entre carte optimiste et carte prudente **mesure directement ce que
l'absence de campagne d'exécution coûte en certitude** — c'est-à-dire ce que vaut Q42.

---

## ADR-128 — La carte de faisabilité n'est jamais publiée sans son rapport de qualité

**Statut** : figé (adaptateur courtier)

**Contexte.** Une carte affichée seule ne permet pas de savoir si elle est interprétable. Un
horizon dominé par la quantification produit des verdicts qui ne sont que des artefacts de
discrétisation.

**Décision.** Le rapport de qualité précède toujours la carte et porte son propre verdict, distinct
de tout verdict économique : `MEASURABLE`, `MEASURABLE_WITH_RESERVATIONS`, `NOT_MEASURABLE` par
horizon. La construction des entrées de calcul **échoue explicitement** si aucun horizon n'est
mesurable, si le contrat n'est pas versionné, si la bande d'avantages n'est pas préenregistrée,
ou si le marché d'exécution de la cellule ne correspond pas au contrat chargé.

**Conséquences.** Le jalon du projet cesse d'être « obtenir la courbe kappa » pour devenir
« prouver que l'export permet de la mesurer ». Les verdicts économiques ne deviennent
interprétables qu'après.

---

## ADR-129 — Un calendrier versionné par source et par marché d'exécution

**Statut** : figé et implémenté (Q52)

**Contexte.** Marché de détection et marché d'exécution ne partagent ni horaires, ni
maintenances, ni jours fériés, ni interruptions, ni fuseau serveur, ni demi-séances, ni
disponibilité de cotation. Un calendrier « XAU/USD » générique ne décrit ni l'un ni l'autre.

**Décision.** `Calendar(GC) ≠ Calendar(broker XAU/USD)`. Une lacune est évaluée contre le
calendrier de **la source qui aurait dû produire les données**. Trois niveaux coexistent :
calendrier de place, calendrier du fournisseur, calendrier du symbole sur le compte réel — ce
dernier faisant foi pour l'exécution.

**Conséquences.** L'état composite intermarchés devient explicite : un signal détecté sur un
marché ouvert n'a aucune autorité d'exécution si le marché d'exécution est fermé, et exécuter
pendant que le marché de détection est fermé est possible mais avec un **contexte dégradé
déclaré**.

---

## ADR-130 — Une lacune se classe par l'intégralité de son contenu

**Statut** : figé et implémenté (Q52) · généralise l'ADR-125

**Décision.** Le moteur calcule la durée occupée par chaque état sur l'intervalle et classe
d'après cette répartition. Ni l'état au début, ni l'état à la fin, ni le premier tick après la
coupure n'entrent dans la décision.

**Conséquences.** Correction apportée à l'implémentation : un seuil exprimé **en fraction** ne
suffit pas. Une panne d'une heure après réouverture pèse 5 % d'un intervalle de vingt-et-une
heures et serait avalée par une nuit. La **durée absolue** de la partie ouverte prime donc sur
sa fraction — c'est exactement le cas qu'une fermeture planifiée ne doit pas masquer.

---

## ADR-131 — Toute lacune traversant plusieurs états est segmentée avant classification

**Statut** : figé et implémenté (Q52)

**Décision.** Les instants de transition sont **énumérés exactement** — bornes de règles
récurrentes jour par jour dans leur fuseau, bornes d'exceptions, bornes d'overrides — et non
échantillonnés : un échantillonnage manquerait une maintenance de quelques minutes, qui est
précisément le cas qu'on cherche à voir. Les segments couvrent l'intervalle exactement, sans
trou ni recouvrement.

**Conséquences.** La censure ne porte que sur les segments où des cotations étaient attendues :
une fermeture planifiée ne retire rien de l'échantillon. Sur la démonstration, la part censurée
passe ainsi de 83 % à 0,02 %.

---

## ADR-132 — Calendrier normatif et disponibilité observée sont deux couches séparées

**Statut** : figé et implémenté (Q52)

**Décision.** Le calendrier dit ce qui devait arriver ; l'observation mesure ce qui s'est
produit. Une divergence produit un événement auditable — cotations reçues pendant une fermeture
attendue, silence pendant une période ouverte — sans jamais corriger le calendrier.

---

## ADR-133 — Les règles de calendrier sont bitemporelles

**Statut** : figé et implémenté (Q52)

**Décision.** Chaque règle porte un temps de **validité** (quel était l'état du marché) et un
temps de **connaissance** (ce que le système pouvait savoir). Une simulation décisionnelle ne
voit que ce qui était connu à l'instant simulé ; l'audit historique voit l'état réel.

**Conséquences.** Une fermeture annoncée en cours de séance n'apparaît pas dans un backtest
placé avant l'annonce, tout en restant visible pour le contrôle de qualité.

---

## ADR-134 — Fuseaux IANA obligatoires ; datetimes naïfs et décalages fixes interdits

**Statut** : figé et implémenté (Q52)

**Décision.** Chaque règle est définie dans son fuseau d'origine puis convertie. Un datetime
naïf est **refusé** aux frontières du moteur. Une heure locale supprimée par le passage à
l'heure d'été est refusée plutôt que déplacée — la déplacer produirait un horaire d'ouverture
que personne n'a jamais publié. Une heure répétée au retour à l'heure standard est levée par
`fold`, les deux occurrences correspondant à deux instants réellement distincts.

**Conséquences.** Les journées de 23 et 25 heures sont traitées correctement. Illustration
rencontrée à l'exécution : le Royaume-Uni étant resté à UTC+1 toute l'année en 1970, un décalage
codé en dur aurait décalé d'une heure toutes les sessions du jeu de démonstration sans qu'aucun
test ne le signale.

---

## ADR-135 — Les exceptions datées priment sur les règles récurrentes

**Statut** : figé et implémenté (Q52)

**Décision.** Deux couches : règles habituelles et exceptions datées. Une exception couvrant un
instant **remplace** localement les règles récurrentes ; les règles ne sont consultées que si
aucune exception ne s'applique. Une demi-séance est représentée comme ouverture réduite puis
clôture anticipée, jamais comme fermeture quotidienne — sinon sa densité, son spread et sa
volatilité seraient mélangés à ceux d'une séance normale dans les cellules de coûts.

**Conséquences.** La priorité entre états qui se chevauchent est explicite et **ne détruit pas
les états secondaires** : ils restent dans `contributing_states`, avec la règle de résolution
appliquée.

---

## ADR-136 — Le calendrier ne s'auto-modifie jamais à partir des observations

**Statut** : figé et implémenté (Q52)

**Décision.** L'absence de ticks est une observation ; la fermeture est une information externe
versionnée. Les observations ne peuvent produire que des **propositions de révision**, portant
un drapeau de validation explicite obligatoire.

**Conséquences.** Sans cette barrière, une panne répétée serait progressivement reclassée en
fermeture normale, et le calendrier finirait par décrire les défaillances du flux plutôt que le
marché.

---

## ADR-137 — Temps calendaire et temps de marché sont deux horloges distinctes

**Statut** : figé et implémenté (Q52)

**Décision.** Un horizon est déclaré en temps réel ou en temps de marché, jamais implicitement.
Le moteur publie durée calendaire, durée de cotations attendues et durée observée. Une fenêtre
traversant une fermeture ne se compare pas directement à une fenêtre entièrement ouverte.

**Conséquences.** S'applique aussi au tampon séparant exploration et jeu réservé : les
fermetures ne comptent pas comme information de marché active dans sa longueur effective.

---

## ADR-138 — Collecte autorisée sous calendrier provisoire, interprétation non

**Statut** : figé et implémenté (Q52)

**Décision.** Sans calendrier versionné, toutes les lacunes restent `UNKNOWN_GAP` — jamais une
fermeture supposée — le rapport publie le temps inconnu, conserve toutes les lacunes pour
reclassification, et interdit toute suppression définitive de données fondée sur le calendrier
provisoire.

**Conséquences.** Les trois chantiers avancent indépendamment : collecte de cotations (Q50),
journalisation d'exécution (Q51) et classification temporelle (Q52). Aucun n'attend les deux
autres. Q52 bloque l'interprétation finale, pas la collecte.

---

## ADR-139 — Une règle de calendrier est une assertion atomique liée à une preuve conservée

**Statut** : figé et implémenté (Q53)

**Contexte.** Une règle nue — « XAU/USD ferme à 22 h » — ne permet de répondre à aucune des
questions qui décident de sa validité : qui l'affirme, quand elle a été récupérée, à quelle
période elle s'applique, si elle est officielle ou inférée, quel document la prouve.

**Décision.** L'unité de contenu est l'assertion atomique, indissociable de son instantané de
source. Une page indiquant plusieurs horaires produit plusieurs assertions — ce qui permet d'en
superseder une sans toucher aux autres.

---

## ADR-140 — L'autorité d'une source dépend de la portée de l'assertion

**Statut** : figé et implémenté (Q53)

**Décision.** Il n'existe pas de hiérarchie globale. Place, fournisseur, courtier, compte et
symbole possèdent chacun leur source normative dans leur domaine. Une source secondaire ne
remplace pas la place lorsqu'elle décrit les horaires de la place, et l'observation ne devient
jamais normative automatiquement.

**Conséquences.** Chaque assertion déclare sa portée — courtier, serveur, type de compte,
symbole, marché, source de données, juridiction — avec les champs non applicables
**explicitement nuls**. Un champ nul est un joker ; un champ renseigné doit correspondre
exactement, ce qui empêche mécaniquement d'appliquer une règle de compte de démonstration à un
compte réel.

---

## ADR-141 — La spécification du symbole et du compte prime sur la documentation générale

**Statut** : figé et implémenté (Q53)

**Décision.** Pour le marché d'exécution, l'arbitrage suit `spécificité de portée → autorité de
source → récence`. La spécificité est comptée comme le nombre de dimensions contraintes, de
sorte qu'une fiche de symbole du compte l'emporte sur une page générique du courtier — même
plus récente.

**Conséquences.** Un test vérifie explicitement qu'une assertion ancienne et spécifique
l'emporte sur une assertion récente et générale.

---

## ADR-142 — Toute contradiction produit un conflit explicite

**Statut** : figé et implémenté (Q53)

**Décision.** Aucune résolution silencieuse par récence ou priorité implicite. Deux sources
normatives de **même spécificité** qui se contredisent **bloquent la compilation**. Des
spécificités différentes produisent un conflit enregistré mais informatif, tranché par la
règle de l'ADR-141.

**Conséquences.** La récence n'est qu'un attribut : une page récente peut décrire une autre
période, un autre produit ou un autre serveur.

---

## ADR-143 — Chaque récupération produit un instantané immuable et une empreinte

**Statut** : figé et implémenté (Q53)

**Décision.** La chaîne `source → assertion → manifest → calendrier → rapport` est vérifiable
par empreintes à chaque maillon. Quand le contenu ne peut être conservé intégralement,
l'empreinte, les métadonnées, l'extrait utilisé et la provenance suffisent — leur absence, elle,
invalide la preuve.

**Conséquences.** L'empreinte du manifest porte sur le **contenu** — empreintes sémantiques des
assertions et empreintes des sources, triées, plus la version du compilateur — et non sur les
identifiants seuls. Deux compilations du même manifest produisent le même identifiant de
calendrier.

---

## ADR-144 — Une extraction automatique reste non normative jusqu'à validation

**Statut** : figé et implémenté (Q53)

**Décision.** Une extraction naît `PARSED_UNREVIEWED`. Les règles **critiques** — fermeture
quotidienne, jour férié, maintenance, portage multiplié, heure de rollover, fuseau serveur —
exigent une source normative, une preuve conservée et une revue humaine. Sans l'une des trois,
la compilation échoue.

**Conséquences.** Ces règles sont critiques parce qu'elles modifient fortement la censure ou les
coûts : une erreur y déplace le verdict de faisabilité sans laisser de trace dans les données.

---

## ADR-145 — Dates de récupération, d'effet et de connaissance sont distinctes et obligatoires

**Statut** : figé et implémenté (Q53)

**Décision.** Chaque assertion porte sa date de récupération, sa période de validité avec la
base qui la fonde (`EXPLICIT_IN_SOURCE`, `INFERRED_FROM_PUBLICATION_DATE`,
`INFERRED_FROM_OBSERVATION`, `UNKNOWN`) et sa période de connaissance. Une date d'effet
`UNKNOWN` bloque la compilation : l'appliquer rétroactivement reviendrait à supposer que la
règle a toujours été vraie.

**Conséquences.** Même traitement pour le fuseau. « GMT+2 » interprété comme décalage fixe
alors qu'il s'agit d'une heure locale saisonnière décale toutes les sessions d'une heure la
moitié de l'année, sans qu'aucun test temporel ne le signale — d'où le blocage sur
`timezone_interpretation = AMBIGUOUS`.

---

## ADR-146 — Les observations produisent des divergences et des propositions, jamais des règles

**Statut** : figé et implémenté (Q53) · confirme l'ADR-136

**Décision.** Les données de collecte comparent le calendrier à la réalité et produisent des
divergences typées. Au-delà d'un seuil préenregistré, une proposition de révision est créée,
portant un drapeau de validation explicite obligatoire. La publication reste manuelle.

---

## ADR-147 — Chaque version est compilée depuis un manifest immuable

**Statut** : figé et implémenté (Q53)

**Décision.** Le manifest contient assertions, sources, conflits non résolus et éléments
provisoires. Deux constructions indépendantes du même manifest produisent la même empreinte ;
un manifest dépendant d'informations non conservées est invalide. Une correction crée une
nouvelle version et identifie les rapports affectés — `NO_MATERIAL_IMPACT`,
`RECOMPUTE_RECOMMENDED`, `RECOMPUTE_REQUIRED`, `VERDICT_INVALIDATED` — **sans jamais les
réécrire**.

**Conséquences.** L'impact est mesuré par échantillonnage d'états sur les intervalles
effectivement publiés, non par comparaison de règles : deux jeux de règles différents peuvent
produire le même comportement là où les rapports portaient.

---

## ADR-148 — Un calendrier non vérifié ne produit aucun verdict final

**Statut** : figé et implémenté (Q53)

**Décision.** Le statut du contenu — `CONFLICTING`, `PROVISIONAL`, `STALE`, `VERIFIED` — est
calculé à la compilation. Tout ce qui n'est pas `VERIFIED` place le moteur de Q52 en mode
provisoire : toutes les lacunes redeviennent inconnues et aucun verdict définitif n'est
prononçable sur les intervalles concernés.

**Conséquences.** Le lien entre chaîne de preuve et classification temporelle devient mécanique
plutôt que déclaratif. Une assertion périmée n'est pas nécessairement fausse, mais elle ne peut
plus soutenir silencieusement un verdict.

---

## ADR-149 — Toute durée locale est mesurée sur l'horloge monotone

**Statut** : figé et implémenté (Q51)

**Décision.** L'horloge murale peut sauter — synchronisation, correction système, changement
manuel, virtualisation, reprise après veille. Les durées locales se mesurent sur l'horloge
monotone ; la murale sert à l'alignement inter-systèmes et à l'audit. Une durée négative lève
une erreur explicite désignant la cause probable.

**Conséquences.** Point relevé à l'implémentation : **un recul de l'horloge murale pendant que
la monotone avance est une discontinuité quelle que soit son amplitude**. Un seuil de magnitude
seul laissait passer un recul d'une milliseconde — précisément le cas le plus fréquent. La
détection combine désormais signe et magnitude.

---

## ADR-150 — Aucune décomposition non observable n'est inventée

**Statut** : figé et implémenté (Q51)

**Contexte.** Un accusé de réception local ne permet pas de distinguer file locale, réseau
aller, traitement courtier, réseau retour et rappel local si le courtier ne fournit pas ses
propres horodatages.

**Décision.** Chaque intervalle déclare son statut — observé, agrégé seulement, non
identifiable — et un agrégat **doit** énumérer les composantes qu'il ne sépare pas. Un
intervalle non identifiable ne porte aucune durée. L'aller-retour d'émission se nomme
`submit_to_ack_latency` et le trajet du flux `provider_to_local_receive_latency` : jamais
« latence réseau » ni « latence courtier ».

**Conséquences.** La contrainte est portée par le type, pas par un commentaire : construire un
agrégat sans sa liste de composantes échoue. C'est ce qui empêche de le renommer d'après l'une
d'elles.

---

## ADR-151 — La latence de référence est conditionnelle à l'état au déclenchement

**Statut** : figé et implémenté (Q51) · confirme l'ADR-102

**Décision.** Le centile utile à Q19 est conditionnel aux rafales, non marginal. L'état de
rafale est enregistré **au déclenchement** et **à l'accusé**, séparément, avec les variables
continues d'intensité — ce qui permet de tracer la latence en fonction de la cadence plutôt que
de dépendre de seuils arbitraires.

---

## ADR-152 — Le retard de cadence est mesuré, pas approximé

**Statut** : figé et implémenté (Q51)

**Décision.** L'attente entre éligibilité et évaluation est mesurée événement par événement.
L'approximation `cadence / 2` reste un diagnostic théorique sous arrivée uniforme, jamais une
mesure : les cotations arrivent en rafale et s'alignent souvent sur des frontières de temps
rondes.

---

## ADR-153 — Identité logique et identité de tentative sont séparées

**Statut** : figé et implémenté (Q51)

**Décision.** Un retry conserve le même ordre logique et crée une nouvelle tentative. Sans cette
séparation, un délai d'attente suivi d'un accusé compterait comme deux ordres et l'idempotence
serait invérifiable.

---

## ADR-154 — Le journal d'ordres est append-only et chaîné

**Statut** : figé et implémenté (Q51)

**Décision.** Aucun événement n'est réécrit ; les états courants sont reconstruits depuis les
événements. Chaque entrée porte l'empreinte de la précédente, rendant toute modification
historique détectable. Le moteur n'impose que les relations garanties par la sémantique du
connecteur — un rappel d'accusé peut légitimement précéder le retour de l'appel d'émission.

---

## ADR-155 — Les événements créateurs d'ordre sont persistés avant l'action

**Statut** : figé et implémenté (Q51)

**Décision.** Intention d'ordre, début d'émission et demande d'annulation sont écrits de façon
durable avant ou au moment de l'action. Le journal refuse leur enregistrement non durable.

**Conséquences.** Sans cette règle, un incident peut laisser un ordre réel chez le courtier sans
aucune trace locale de son origine.

---

## ADR-156 — Une campagne conserve sa politique et sa probabilité d'échantillonnage

**Statut** : figé et implémenté (Q51)

**Décision.** Les probes couvrent sessions, quartiles de cadence, rafales et régimes de spread.
La probabilité de sélection est enregistrée par état, permettant de repondérer les distributions
lorsqu'une cellule a été volontairement suréchantillonnée.

**Conséquences.** Sans cette conservation, une campagne concentrée sur les périodes calmes ferait
sous-estimer à Q19 la latence conditionnelle — exactement l'inverse de ce qu'elle cherche.

---

## ADR-157 — Une bonne latence de messagerie ne démontre rien sur l'exécution

**Statut** : figé et implémenté (Q51)

**Décision.** Le verdict favorable de la phase de messagerie s'appelle
`LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER`, jamais « latence viable ». Les composantes non
mesurées — exécution, position en file, sélection adverse — peuvent encore exclure la cellule.

---

## ADR-158 — Une borne inférieure déjà trop lente suffit à conclure

**Statut** : figé et implémenté (Q51) · **mécanisme corrigé par l'ADR-168**

**Décision.** La borne inférieure observable somme uniquement les composantes réellement
mesurées : ce qui n'est pas observable n'est pas compté, donc la latence réelle ne peut
qu'être supérieure. Si cette borne dépasse déjà l'horizon, le verdict négatif est **concluant
sans campagne d'exécution**.

**Conséquences.** C'est ce qui permet de savoir si une campagne réelle plus coûteuse vaut la
peine d'être financée, avant de la lancer.

> **Correction.** L'asymétrie tient — c'est le mot « somme » qui était faux. Additionner des
> intervalles susceptibles de se recouvrir pouvait produire une borne **supérieure** à la durée
> réellement vécue. L'ADR-168 remplace l'addition par des frontières temporelles ; la conclusion
> de cette décision est inchangée, sa mise en œuvre ne l'est pas.

---

## ADR-159 — Une latence dépassant l'horizon compte comme consommation totale

**Statut** : figé et implémenté (Q51) · confirme l'ADR-122

**Décision.** L'observation n'est **jamais** supprimée de l'échantillon. Elle compte pour une
consommation entière de l'horizon.

**Conséquences.** Écarter ces cas ne conserverait que les événements où l'on avait eu le temps
d'agir — le biais de sélection déjà corrigé à la phase 0 de Q19.

---

## ADR-160 — La journalisation passive démarre sans condition

**Statut** : figé et implémenté (Q51)

**Décision.** Q51-A ne dépend ni de Q42, ni de Q52, ni d'un modèle. Tout probe capable de créer
un ordre réel reste bloqué tant que budget et coupe-circuit ne sont pas définis — le module
refuse l'autorisation.

**Conséquences.** Trois flux avancent en parallèle : Q50 mesure le marché, Q51 mesure la capacité
à agir dessus, Q52 classe le temps. Leur intersection est le premier domaine de recherche qui ne
repose plus sur des hypothèses synthétiques.

---

## ADR-161 — Résolution, exactitude, précision et stabilité sont quatre grandeurs distinctes

**Statut** : figé et implémenté (Q57)

**Décision.** La qualification d'une horloge distingue explicitement ces quatre grandeurs.
Aucune précision affichée ne peut excéder l'incertitude qualifiée : `can_publish()` refuse toute
publication plus fine que l'incertitude **mesurée**, et une horloge ne peut être qualifiée pour
l'inter-systèmes sur la seule foi d'une précision annoncée.

**Conséquences.** La résolution effective est mesurée sur une série d'appels — plus petit écart
non nul réellement observé — et non lue dans la documentation de l'API. Une horloge affichant des
nanosecondes peut n'avancer que par pas de 15 µs.

---

## ADR-162 — Un recul de l'horloge murale est une discontinuité quelle que soit son amplitude

**Statut** : figé et implémenté (Q57) · confirme l'ADR-149

**Décision.** Tout recul de la murale pendant une progression monotone constitue une
discontinuité, sans seuil. Pour les corrections positives, une variation excessive de
`ΔW − ΔM` produit également une discontinuité, selon une politique versionnée.

**Conséquences.** Un seuil de magnitude laisserait passer les petites corrections de
synchronisation — précisément les plus fréquentes. Le signe est un critère absolu ; la magnitude
n'en est un que dans le sens positif.

---

## ADR-163 — Un intervalle inter-systèmes n'est exploitable qu'une fois les domaines qualifiés

**Statut** : figé et implémenté (Q57)

**Décision.** Une durée entre deux horloges différentes reste `NOT_RESOLVABLE_INTERSYSTEM` tant
que Q57 n'a pas qualifié les domaines et leur incertitude de synchronisation — **même si les deux
valeurs numériques existent**. La classe de résolution est un **rapport** `u/L`, jamais un seuil
absolu.

**Conséquences.** Une incertitude de 1 ms est excellente sur 100 ms et inutilisable sur 2 ms.
Publier la seconde comme une mesure ferait passer un décalage de synchronisation pour une latence.

---

## ADR-164 — La sémantique des événements courtier est une capacité versionnée liée à une preuve

**Statut** : figé et implémenté (Q58)

**Décision.** Chaque événement porte sa sémantique, son domaine d'horloge, sa garantie d'ordre et
un `evidence_id`. Toute modification du connecteur crée une nouvelle qualification : les
conclusions précédentes ne sont pas supposées valables.

**Conséquences.** Une mise à jour de SDK peut changer rappels, tamponnage, ordre des événements,
horodatages et reprises. `invalidated_by()` rend la péremption explicite plutôt que tacite.

---

## ADR-165 — Le nom d'un rappel n'établit jamais l'état d'un ordre

**Statut** : figé et implémenté (Q58)

**Décision.** `on_order_accepted()` ne démontre pas qu'un ordre est reçu, accepté, actif, annulé
ou exécuté. Un événement déclaré observable sans preuve ne se construit pas.
`OBSERVATIONAL_INFERENCE` ne suffit jamais seule à qualifier un événement ambigu.

**Conséquences.** `BROKER_ACK ≠ ORDER_ACTIVE` structurellement tant que l'activation n'est pas
elle-même observable. Le retour d'émission n'est jamais utilisé comme accusé courtier lorsque
seule la mise en file locale est démontrée.

---

## ADR-166 — Un délai dépassé produit un état inconnu, jamais un rejet implicite

**Statut** : figé et implémenté (Q58)

**Décision.** `TIMEOUT_UNKNOWN_STATE` produit `UNKNOWN_PENDING_RECONCILIATION`. La réconciliation
est obligatoire pour traiter délai dépassé, reconnexion, accusé perdu, rappel perdu et panne.

**Conséquences.** Résoudre un délai dépassé en rejet autoriserait l'émission d'un second ordre
alors que le premier existe peut-être déjà chez le courtier : une position double au lieu d'une.

---

## ADR-167 — Q19 n'attribue jamais de composante plus fine que la matrice d'observabilité

**Statut** : figé et implémenté (Q57 + Q58)

**Décision.** Le croisement Q57 × Q58 produit la **seule** décomposition autorisée. Une composante
n'est déclarée observable que si les deux la rendent observable. `enforce_contract()` lève une
erreur sur toute attribution plus fine, et sur toute promotion d'un agrégat en observation.

**Conséquences.** Sans horodatage courtier, nommer `broker_processing` produirait un chiffre
crédible et faux. Sans accusé prouvé, l'aller-retour n'est pas « agrégé » : il est absent — un
connecteur non démontré ne fournit pas une mesure grossière, il ne fournit rien.

---

## ADR-168 — La borne de latence est construite à partir de frontières, jamais par addition

**Statut** : figé et implémenté (Q57 + Q58) · corrige l'ADR-158

**Décision.** `LatencyPath` décrit le chemin critique par ses **frontières temporelles**. Deux
segments consécutifs partagent une frontière : ils sont disjoints par construction. Côté journal,
`LatencyObservation` refuse de se construire si deux de ses intervalles recouvrent le même
mécanisme — recouvrement détecté transitivement par les composantes déclarées.

**Conséquences.** L'addition naïve produisait des bornes supérieures au vécu : 14 ms
d'aller-retour plus 9 ms de traitement courtier situé **à l'intérieur** donnent 23 ms sur un
chemin de 20 ms. Une borne inférieure supérieure au vécu n'en est pas une. Le double comptage
devient structurellement impossible plutôt qu'interdit par convention.

---

## ADR-169 — Le chemin critique sert au verdict, l'attribution au diagnostic

**Statut** : figé et implémenté (Q57 + Q58)

**Décision.** Deux vues sont publiées et ne se confondent pas. La vue chemin critique
— `quote received → decision → ACK` — est la durée réellement vécue et fonde le verdict de
faisabilité. La vue attribution sert au diagnostic d'optimisation.

**Conséquences.** Le chemin critique englobe les trous non mesurés entre composantes ; il est donc
toujours ≥ la somme d'attribution, tout en restant une borne **inférieure** de la latence totale.
Une couverture faible signale un manque de prise pour l'optimisation, pas un défaut de fondement.
Les qualités de mesure ne sont jamais confondues dans une même distribution.

---

## ADR-170 — Déclarer correctement NOT_IDENTIFIABLE est une résolution valide

**Statut** : figé et implémenté (Q57 + Q58)

**Décision.** Résoudre Q57/Q58 n'exige pas que toutes les composantes soient observables. Une
synchronisation médiocre réduit le domaine mesurable sans empêcher la résolution ; un événement
déclaré inobservable **est** qualifié. Ce qui bloque, c'est l'ambiguïté non documentée.

**Conséquences.** Le champ `intersystem_uncertainty_declared_unknown` sépare deux situations que
rien ne distinguerait autrement : ne pas avoir mesuré, et avoir cherché puis constaté qu'on ne
peut pas mesurer. La première laisse Q57 ouverte, la seconde la résout. La fiche connecteur livrée
vide est un résultat valide : une fiche déclarant tout inconnu produit des bornes honnêtes, là où
une supposition produirait des verdicts faux.

---

## ADR-171 — La première métrique réelle de Q19 est une borne construite par frontières

**Statut** : figé et implémenté (Q51-A) · applique l'ADR-168

**Décision.** `L^LB` se calcule comme `B5 − B1`, différence de frontières mesurées, jamais
comme somme d'intervalles. Une frontière absente n'est jamais remplacée par la précédente :
l'observation est refusée.

**Conséquences.** Sans ce refus, la borne retomberait silencieusement sur `B4 − B1` — une
valeur plausible qui mesure un chemin plus court sans le dire. Le module vérifie en outre
l'identité entre la différence de frontières et la somme des quatre composantes ; une
divergence signalerait un recouvrement.

---

## ADR-172 — La métrique décisionnelle est publiée par cellule et conditionnée à la rafale

**Statut** : figé et implémenté (Q51-A) · confirme l'ADR-102

**Décision.** Aucun p95 global ne peut représenter les conditions de déclenchement
microstructurelles. La publication minimale est p50, p75, p90, p95, p99 pour NORMAL,
ELEVATED, BURST_P95 et BURST_P99 séparément. L'intensité continue — cadence, vélocité,
centiles de spread et de rafale — reste conservée dans chaque observation.

**Conséquences.** Les signaux apparaissent là où la file se remplit et où la boucle
d'événements est la plus sollicitée : `P(L | rafale) ≠ P(L)`. Les catégories ne servent qu'à
présenter les résultats, jamais à les produire — `L_p95(λ)` reste traçable sans elles.

---

## ADR-173 — Q51-A fonctionne avec une capacité courtier entièrement non qualifiée

**Statut** : figé et implémenté (Q51-A)

**Décision.** La campagne passive ne suppose aucune latence courtier et démarre avec une
fiche Q58 vide. Émission, accusé, ordre actif, file courtier, exécution, glissement et
sélection adverse restent **explicitement absents** de chaque rapport.

**Conséquences.** Le rapport quotidien nomme cette liste à chaque édition. Un rapport qui la
tairait se lirait comme une latence complète.

---

## ADR-174 — Seule la pile TARGET alimente le verdict principal

**Statut** : figé et implémenté (Q51-A)

**Décision.** La collecte distingue `PIPELINE_MINIMAL`, `PIPELINE_TARGET` et
`PIPELINE_STRESS`. Le verdict refuse un échantillon STRESS et retourne
`PASSIVE_MEASUREMENT_INVALID`.

**Conséquences.** Exécuter tous les moteurs futurs pour mesurer une latence maximale fictive
produirait un chiffre défavorable ne décrivant aucune architecture envisagée. Le refuser
vaut mieux que le pondérer.

---

## ADR-175 — La suffisance dépend de la stabilité et des grappes, pas d'un nombre de ticks

**Statut** : figé et implémenté (Q51-A)

**Décision.** Aucun seuil arbitraire — ni « dix jours », ni « cinq cents rafales ». La
suffisance dépend de la variance mesurée, de la stabilité des quantiles, du nombre de
grappes indépendantes et de la largeur des intervalles.

**Conséquences.** Une grappe est attribuée à **chaque** observation, y compris hors rafale :
deux cotations calmes séparées de 50 ms ne sont pas indépendantes non plus. Ne regrouper que
les rafales gonflerait la précision apparente du régime normal. Une rafale ne se termine
qu'après un retour sous le seuil maintenu pendant une période de reset, sinon une oscillation
autour du seuil fabriquerait des grappes artificielles.

---

## ADR-176 — La politique d'arrêt est préenregistrée et ne peut dépendre du résultat

**Statut** : figé et implémenté (Q51-A) · **garde-fou corrigé par l'ADR-181**

**Décision.** `StoppingPolicy` porte auteur, empreinte et date de déclaration. Le module
refuse d'évaluer une campagne contre une politique postérieure à sa première observation, ou
supposant une autre qualification d'horloge que celle réellement obtenue. L'évaluation ne
regarde jamais la valeur mesurée.

**Conséquences.** Une politique écrite après avoir vu le résultat n'est pas une politique :
c'est le résultat reformulé. Le piège résiduel est signalé plutôt qu'interdit — arrêter dès
que l'intervalle devient étroit sélectionne les échantillons homogènes, donc l'intervalle
final sous-estime l'incertitude ; `confidence_interval_is_optimistic` le déclare.

> **Correction.** « Signaler plutôt qu'interdire » était insuffisant. Sous une règle d'arrêt
> qui lit l'intervalle, la couverture nominale n'est pas *optimiste* : elle **n'est plus
> garantie**. L'ADR-181 remplace l'avertissement par une contrainte de mode, et
> `confidence_interval_is_optimistic` n'est plus qu'un diagnostic historique. Le reste de
> cette décision — préenregistrement, auteur, empreinte, indépendance à la valeur mesurée —
> est inchangé.

---

## ADR-177 — Un horizon exclu par la borne passive n'exige aucune campagne Q42

**Statut** : figé et implémenté (Q51-A)

**Décision.** `PASSIVE_LATENCY_EXCLUDED` est un verdict négatif fort : il tient même en
supposant courtier instantané, aucune file et exécution immédiate. L'exclusion s'appuie sur
la borne de confiance basse.

**Conséquences.** La partie inconnue de la latence ne peut qu'aggraver le constat. Financer
une campagne réelle pour le confirmer achèterait une précision sur une conclusion déjà
acquise — et avec un risque financier.

---

## ADR-178 — Q42 devient prioritaire seulement si un horizon survit au coût et à la borne passive

**Statut** : figé et implémenté (Q51-A)

**Décision.** Trois cas : coût excluant → Q42 non prioritaire ; latence passive excluant →
Q42 non prioritaire ; les deux survivant → Q42 rationnelle, parce que les inconnues
courtier déterminent alors le verdict. Une borne indéterminée ne justifie pas non plus le
financement.

**Conséquences.** Q42 cesse d'être une campagne vague pour devenir une question précise :
*le segment encore inconnu tient-il dans le budget résiduel ?* Cela réduit considérablement
le coût expérimental.

---

## ADR-179 — Le budget de latence restant est calculé avant toute campagne réelle

**Statut** : figé et implémenté (Q51-A)

**Décision.** `B_L(c, h) = L_max_admissible(c, h) − L^LB_passive(c)`. `L_max_admissible` est
**déclarée** avec source et date, jamais déduite : elle dépend de `edge(L, h, c)`, qui exige
un signal.

**Conséquences.** La fixer après lecture de la borne mesurée reviendrait à choisir la
conclusion — le défaut déjà corrigé pour la bande d'avantages plausibles (ADR-116). Un budget
négatif signifie que l'horizon est exclu sans avoir rien mesuré du courtier.

---

## ADR-180 — La fraction capturable ancrée à la réception locale est une borne supérieure

**Statut** : **remplacé par l'ADR-185** · le principe tient, la typologie était incomplète

**Décision.** L'instant `t₀` de la phase 0 est déclaré, jamais implicite. Avec
`t₀ = réception locale`, le mouvement survenu **avant** la réception n'entre pas dans
l'échantillon de déplacement et n'est donc jamais compté comme perdu : la fraction capturable
en ressort surestimée. `CapturabilityInput` porte son ancrage et le signale.

**Conséquences.** L'asymétrie habituelle s'applique : une exclusion reste concluante — on
n'exclut pas moins en surestimant — mais une non-exclusion obtenue sous ancrage local est
plus faible encore que d'ordinaire. Seule une qualification Q57 de `B0 → B1` permet un
ancrage marché et retire cet optimisme.

> **Correction.** La dernière phrase est fausse. Qualifier `B0 → B1` donne l'ancre
> **fournisseur**, pas l'ancre marché : l'horodatage fournisseur ignore appariement,
> agrégation et délai interne précédant la publication. Il reste donc une borne optimiste,
> simplement moins lâche. L'ADR-185 introduit les trois ancres et les trois portées comme
> types distincts, ainsi que la politique de fin d'horizon que cette décision passait sous
> silence.

---

## ADR-181 — Un arrêt fondé sur l'incertitude observée exige une inférence anytime-valid

**Statut** : figé et implémenté (Q59-A) · **corrige et remplace le garde-fou de l'ADR-176**

**Décision.** Si la décision d'arrêter dépend de l'intervalle observé, un intervalle de
confiance classique calculé après l'arrêt ne conserve pas sa couverture nominale. Un
avertissement accompagnant le chiffre ne suffit pas : la combinaison produit
`SEQUENTIAL_INFERENCE_INVALID`, et il n'y a pas de chiffre à publier.

**Conséquences.** Le problème n'était pas « intervalle potentiellement optimiste » mais
« garantie statistique non valide sous cette règle d'arrêt ». Une simulation le confirme : un
intervalle normal recalculé en continu est franchi **48 %** du temps pour un niveau annoncé de
5 %, là où la séquence de confiance reste sous son α. `confidence_interval_is_optimistic`
subsiste comme diagnostic historique et n'a plus aucune valeur de protection.

---

## ADR-182 — Le mode d'inférence est déclaré avant la première observation

**Statut** : figé et implémenté (Q59-A)

**Décision.** Deux modes seulement. `FIXED_HORIZON` gèle la durée d'avance : la largeur
d'intervalle devient un **diagnostic** et ne peut ni déclencher ni retarder l'arrêt.
`ANYTIME_VALID` utilise une séquence de confiance dont la couverture est simultanée dans le
temps ; sa largeur peut alors légitimement décider.

**Conséquences.** Le constructeur refuse une politique `ANYTIME_VALID` sans `ρ` déclaré, et une
politique `FIXED_HORIZON` sans durée gelée — sans elle, l'arrêt ne peut être que dépendant des
données. La séquence retenue est le mélange normal de Robbins au niveau des **grappes**, avec
`σ² = 1/4` (Hoeffding). *(L'estimande que cette formulation implique — une moyenne par grappe —
est explicité et corrigé par l'ADR-195 : il ne coïncide pas avec la latence subie par un
événement.)* Elle est volontairement conservatrice, et son coût est asymétrique :
exclure demande une marge large donc peu de grappes ; conclure « non exclu » demande une marge
fine contre `q = 0,95`, donc un échantillon bien plus grand. Cette asymétrie est cohérente avec
le statut des deux verdicts, et `clusters_for_separation()` la rend chiffrable avant la campagne.

---

## ADR-183 — Q61 se sépare en budget signal-agnostique et budget propre à un moteur

**Statut** : figé et implémenté (Q61)

**Décision.** **Q61-A** est la borne oracle de la phase 0 : `U_capture(L, h, c)`, mouvement
encore capturable après latence, construit en offrant la direction connue d'avance et la
sortie parfaite. Si `U_capture ≤ C_floor`, la cellule est exclue — `LATENCY_COST_ORACLE_EXCLUDED`
— sans qu'aucun moteur prédictif n'existe.

> **Correction.** La séparation Q61-A / Q61-B tient. La **règle d'exclusion**, elle, était
> fausse : `U_capture` y était lu comme un quantile (p90), et un quantile sous le plancher
> n'établit rien sur la queue survivante — précisément là où vit une stratégie sélective.
> L'ADR-191 retire cette lecture et l'ADR-192 la remplace par trois impossibilités.
> `LATENCY_COST_ORACLE_EXCLUDED` n'existe plus comme verdict. **Q61-B** est le budget `L_max` d'un moteur validé,
dérivé de `edge_j(L, h, c)`.

**Conséquences.** Q61-B **ne bloque pas** le premier verdict réel. La phase 0 doit précisément
pouvoir éliminer des horizons avant qu'un signal soit inventé ; lui imposer un `Lmax` y
réintroduirait une croyance sur l'alpha, dans un test conçu pour en être indépendant.
L'argument oracle est en outre plus fort qu'un seuil arbitraire : même un détecteur
extrêmement favorable ne dispose plus d'un mouvement suffisant après la latence observée.

---

## ADR-184 — Aucun Lmax spécifique n'est inventé avant le signal correspondant

**Statut** : figé et implémenté (Q61-B)

**Décision.** `AdmissibleLatency` exige un `engine_id` nommé, en plus de sa source et de sa
date. Un budget sans moteur ne se construit pas.

**Conséquences.** Le budget est spécifique au moteur, à l'horizon, à la cellule, au régime et au
type d'ordre, et se fige dans le protocole du moteur avant son évaluation finale. Un `Lmax`
anonyme serait une croyance sur l'alpha déguisée en contrainte physique.

---

## ADR-185 — L'ancre et l'origine d'horizon sont des types, pas des champs libres

**Statut** : figé et implémenté (Q19 phase 0) · **remplace l'ADR-180**

**Décision.** Trois ancres — `MARKET_EVENT_ANCHOR`, `PROVIDER_EVENT_ANCHOR`,
`LOCAL_RECEIVE_ANCHOR` — et trois portées correspondantes — `END_TO_END_MARKET`,
`PROVIDER_TO_ACTION`, `POST_RECEIVE_ONLY`. Ce sont des **estimandes distincts** : ils ne se
fusionnent jamais dans une même distribution. Chaque portée impose son nom de publication ;
« capturabilité » tout court est interdit.

**Conséquences.** L'ADR-180 traitait l'ancre fournisseur comme équivalente à l'ancre marché.
C'est faux : l'horodatage fournisseur ignore appariement, agrégation et délai interne précédant
la publication, selon la sémantique de la source — il reste une borne optimiste. Par ailleurs
`horizon_end_policy` est explicite : déplacer l'ancre sans fixer la fin de l'horizon
prolongerait la fenêtre de `t_ancre − t_marché` et fabriquerait du mouvement capturable qui
n'existait pas dans la question posée.

---

## ADR-186 — Une exclusion post-réception conclut ; sa non-exclusion ne qualifie rien

**Statut** : figé et implémenté (Q19 phase 0)

**Décision.** `POST_RECEIVE_ONLY` est une borne optimiste : dissémination, trajet fournisseur et
réseau entrant sont offerts gratuitement au système. Si la seule latence interne suffit déjà à
éliminer l'horizon, **l'exclusion est forte**. Sa non-exclusion, en revanche, ne dit rien du
chemin de bout en bout.

**Conséquences.** `interpret()` produit deux phrases différentes selon le sens du résultat, et
la non-exclusion nomme systématiquement la portée dont elle relève. Un résultat annoncé sous le
nom « capturabilité » se lirait comme une mesure de bout en bout.

---

## ADR-187 — Le découpage temporel du régime calme est versionné et testé en sensibilité

**Statut** : figé et implémenté (Q51-A)

**Décision.** `BlockingChoice` porte durée, source et version. L'inférence est refaite sur
`{b/2, b, 2b}` avant tout verdict final, et `blocking_is_robust()` vérifie que tous les
découpages placent le seuil du même côté de l'intervalle.

**Conséquences.** Sans cela, la durée de bloc redevient une constante arbitraire oubliée dans le
code, et un verdict qui bascule entre `b/2` et `2b` décrit le découpage autant que la latence.
La valeur devra à terme être confrontée à l'autocorrélation des latences et du débit de ticks,
et à la durée des épisodes de file et de connexion.

---

## ADR-188 — La comparaison de cadence exige un flux apparié

**Statut** : figé et implémenté (Q43)

**Décision.** `PAIRED_REPLAY` et `SHADOW_EVALUATION` autorisent l'attribution ;
`UNPAIRED_DAYS` ne l'autorise pas et ne produit qu'un diagnostic.

**Conséquences.** « Event-driven lundi contre periodic mardi » ne permet pas d'attribuer l'écart
à la cadence : les marchés n'étaient pas les mêmes. Les deux politiques doivent voir le même
flux — rejoué, ou évalué en parallèle sans que les deux piles perturbent la production.

---

## ADR-189 — L'effet observateur est mesuré comme une distribution appariée

**Statut** : figé et implémenté (Q51-A) · précise l'ADR-176

**Décision.** Le surcoût `O = L_instrumenté − L_baseline` est mesuré sur un banc contrôlé apparié
et publié en p50, p95 et p99. Un surcoût arrondi à zéro alors que l'horloge a avancé lève une
erreur.

**Conséquences.** Sérialiser hors du chemin critique ne supprime ni la lecture d'horloge, ni la
création d'objet, ni l'allocation, ni la mise en file, ni la contention éventuelle. Comparer
deux séries de tailles différentes mesurerait aussi la différence d'échantillon, et le module
le refuse.

---

## ADR-190 — La phase 0 publie un état consolidé qui n'autorise jamais rien

**Statut** : figé et implémenté (Q19 phase 0)

**Décision.** Six états : exclusion par le coût, par la latence passive, par la capturabilité
oracle, non-exclusion, indétermination, mesure invalide. L'ordre de précédence suit la solidité —
une mesure invalide n'autorise rien, une exclusion par le coût ne se rattrape par aucune
amélioration de latence.

**Conséquences.** `PHASE0_NOT_EXCLUDED` ne signifie **jamais** qu'un bon trade est possible :
seulement qu'il reste physiquement et économiquement assez d'espace pour justifier la recherche
d'un signal. L'intersection publiée est
`D_cost ∩ D_passive_latency ∩ D_capturability`, et aucun de ses trois termes ne dépend d'un
signal.

---

> **Renumérotation.** Les décisions proposées ADR-189 à ADR-196 dans l'addendum « Oracle,
> estimand séquentiel et coût plancher » entrent en collision avec ADR-189 et ADR-190, déjà
> figées. Elles sont enregistrées sous ADR-191 à ADR-198 :
>
> | Proposé | Enregistré | Objet |
> | --- | --- | --- |
> | ADR-189 | **ADR-191** | un quantile oracle n'exclut jamais seul |
> | ADR-190 | **ADR-192** | trois niveaux d'exclusion oracle |
> | ADR-191 | **ADR-193** | politique de chevauchement des opportunités |
> | ADR-192 | **ADR-194** | Q63 est une borne inférieure, pas une estimation |
> | ADR-193 | **ADR-195** | trois estimandes nommés séparément |
> | ADR-194 | **ADR-196** | le regroupement ne change pas l'estimande |
> | ADR-195 | **ADR-197** | anytime-valid seulement si les hypothèses tiennent |
> | ADR-196 | **ADR-198** | repli vers l'horizon fixe plutôt qu'une garantie invalide |

---

## ADR-191 — Un quantile de capturabilité oracle n'exclut jamais à lui seul

**Statut** : figé et implémenté (Q61-A) · **corrige la règle d'exclusion introduite avec l'ADR-183**

**Décision.** `Q₀.₉₀(Capture_oracle) ≤ C_floor` ne permet pas de conclure à l'exclusion. Elle
permet seulement d'affirmer qu'au moins 90 % de la population étudiée ne possède pas assez de
mouvement selon cette définition de l'oracle. Les quantiles restent publiés — p50, p75, p90,
p95, p99 — comme **diagnostics**.

**Conséquences.** Les 10 % restants peuvent contenir exactement la stratégie sélective
recherchée. Si 90 % des situations sont impossibles mais que 10 % permettent à l'oracle de
gagner largement après frais, un moteur qui ne trade que ces 10 % conserve de la valeur.
Exclure sur un percentile supprimerait précisément le type de moteur que le projet cherche :
peu de trades, mais bons. Un quantile ne produit une exclusion que rattaché explicitement à une
exigence de fréquence — le quantile pertinent est alors lié à `1 − f_min/λ_opp`, jamais choisi
arbitrairement.

---

## ADR-192 — L'exclusion oracle repose sur trois impossibilités, jamais sur un percentile

**Statut** : figé et implémenté (Q61-A)

**Décision.** Trois niveaux, et un surplus défini par opportunité : `S_i = G_i − C_floor`,
`I_i = 1[S_i > δ_MEU]`.

| Niveau | Condition | Verdict |
| --- | --- | --- |
| A — impossibilité universelle | `sup_i S_i ≤ δ_MEU` | `ORACLE_UNIVERSALLY_NON_VIABLE` |
| B — impossibilité par fréquence | `f_oracle_rentable < f_min` | `ORACLE_FREQUENCY_NON_VIABLE` |
| C — impossibilité économique | `V_oracle_max < J_min` | `ORACLE_ECONOMIC_CAPACITY_NON_VIABLE` |

**Conséquences.** Le niveau A n'affirme jamais que le taux d'opportunités rentables est **nul** :
avec zéro succès sur `n` tirages, la borne de Clopper-Pearson vaut `1 − α^(1/n)` et ne descend
pas à zéro. Le niveau B utilise la borne **supérieure** du taux, de sorte que l'exclusion reste
conservatrice. Le niveau C compare la valeur sous plafond de capacité, avec une marge de
sécurité déclarée. `ORACLE_NOT_EXCLUDED` ne signifie jamais qu'un signal existe : seulement
qu'il reste assez d'espace pour le chercher.

---

## ADR-193 — Les opportunités oracle sont soumises à une politique de chevauchement

**Statut** : figé et implémenté (Q61-A)

**Décision.** `OpportunitySet` déclare horizon, cooldown, concurrence maximale, contrainte de
capital et politique de recouvrement. `DISJOINT_WINDOWS` résout exactement l'ordonnancement
pondéré d'intervalles ; `CAPACITY_CONSTRAINED_ORACLE` retient au plus
`concurrence × ⌊durée / (horizon + cooldown)⌋` positions.

**Conséquences.** Traiter chaque tick comme une opportunité indépendante puis sommer les profits
oracle gonflerait artificiellement `V_oracle_max` **et** `f_oracle_rentable` : un seul mouvement
peut produire 500 horodatages et 500 fenêtres alors qu'un système réel n'aurait pris qu'une
position. La sélection détermine **combien de tirages indépendants** le système obtient — elle
n'écarte pas les opportunités non rentables, sans quoi « zéro rentable sur N admissibles »
n'aurait plus de dénominateur.

---

## ADR-194 — Q63 est une borne inférieure du coût inévitable, par cellule et type d'ordre

**Statut** : figé et implémenté (Q63)

**Décision.** `C_floor` n'est ni le coût central estimé, ni le coût prudent. Pour que
l'exclusion tienne, `C_réel ≥ C_floor` doit être défendable. Un composant estimé entre par sa
borne inférieure. Les crédits sont **signés** : un swap ou une remise favorable rend un
composant négatif, et le plancher retient la convention la plus favorable compatible avec la
cellule.

**Conséquences.** Le plancher dépend du type d'ordre. Pour un ordre agressif il peut inclure
commission certaine, franchissement déjà nécessaire et observé, frais fixes et financement
inévitable. Pour un ordre **passif**, le spread ne peut pas y entrer automatiquement — un ordre
passif peut obtenir un prix différent du scénario agressif — et le plancher se réduit aux frais
réellement certains. La sélection adverse appartient au coût réel mais n'entre dans le plancher
que si une borne inférieure positive est démontrée. Transformer un crédit possible en coût
positif pour faciliter une exclusion est interdit, et le constructeur le refuse. Les deux côtés
de la comparaison partagent unité, taille, type d'ordre, prix de référence, aller-retour,
horizon, séance et instrument.

---

## ADR-195 — Event-weighted, cluster-weighted et session-weighted sont trois estimandes

**Statut** : figé et implémenté (Q59) · **corrige l'estimande implicite de l'ADR-182**

**Décision.** Les trois quantités sont nommées séparément et publiées séparément. Aucune ne
remplace silencieusement les autres.

**Conséquences.** L'écart est massif, pas marginal. Deux rafales — l'une de 10 événements tous
sous le seuil, l'autre de 1 000 événements à moitié sous le seuil — donnent 0,75 par grappe
contre 0,505 par événement. Pour une décision opérationnelle la grandeur naturelle est
généralement `EVENT_WEIGHTED`, conditionnée à la cellule ; mais si un moteur produit au plus une
décision par rafale, `CLUSTER_WEIGHTED` devient plus pertinent. La phase 0 publie les deux plutôt
que de choisir. La séquence par événement exige un plafond de taille de grappe déclaré à
l'avance, faute de quoi la variable n'est pas bornée et la frontière ne s'applique pas.

---

## ADR-196 — Le regroupement traite la dépendance, il ne change pas la population cible

**Statut** : figé et implémenté (Q59)

**Décision.** Séparation fondamentale : `estimand ≠ méthode de variance`. Le regroupement en
grappes sert à traiter la dépendance statistique ; il ne peut pas modifier la population étudiée
au seul motif de rendre les observations indépendantes.

**Conséquences.** La grappe reste l'unité d'**indépendance** — donc la taille d'échantillon de
l'inférence — sans devenir pour autant l'unité de **pondération**, qui relève de l'estimande
choisi séparément.

---

## ADR-197 — Anytime-valid n'est accordé qu'aux cellules dont les hypothèses tiennent

**Statut** : figé et implémenté (Q59-A) · précise l'ADR-182

**Décision.** Découper une série temporelle en blocs ne rend pas les blocs indépendants. Avant
qu'une grappe entre dans l'inférence séquentielle, `ClusterQualification` publie définition,
règle de réarmement, écart minimal, distributions de taille et de durée, et diagnostics
d'autocorrélation. Sans dépendance maîtrisée ni stationnarité vérifiée, le statut devient
`SEQUENTIAL_ASSUMPTIONS_UNVERIFIED`.

**Conséquences.** Deux blocs consécutifs peuvent partager charge processeur, file persistante,
régime de marché, connexion, événement macro ou volatilité. De bonnes simulations i.i.d. ne
rétablissent pas une garantie dont l'hypothèse est fausse. Les statuts séquentiels —
`SEQUENTIAL_VALID`, `SEQUENTIAL_ASSUMPTIONS_UNVERIFIED`, `SEQUENTIAL_INVALID` — sont
**orthogonaux** à la validité de la mesure : une excellente mesure peut porter une inférence
séquentielle non qualifiée. La non-stationnarité entre séances, régimes et versions logicielles
est une raison supplémentaire de conserver des cellules homogènes et versionnées.

---

## ADR-198 — Une cellule non qualifiée retombe sur l'horizon fixe, elle n'est pas perdue

**Statut** : figé et implémenté (Q59-A)

**Décision.** Lorsque les hypothèses de l'inférence séquentielle ne sont pas défendables, le
protocole bascule vers `FIXED_HORIZON` plutôt que d'émettre une garantie invalide. Q59-A devient
donc `ANYTIME_VALID_WHEN_QUALIFIED` avec repli, plutôt qu'un choix global.

**Conséquences.** Une cellule dont la dépendance ne permet pas encore de défendre la séquence
n'est pas éliminée : elle change de protocole. Le choix conservateur reste préférable — une
méthode plus grossière mais comprise vaut mieux qu'une méthode plus fine mal maîtrisée — mais il
s'applique cellule par cellule, pas à la campagne entière.
