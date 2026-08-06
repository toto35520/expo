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
