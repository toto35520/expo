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
