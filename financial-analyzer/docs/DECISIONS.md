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
