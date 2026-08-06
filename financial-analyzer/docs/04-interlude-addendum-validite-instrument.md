# Addendum au gate des fondations — Validité de l'instrument expérimental

> Statut : **figé**. Complète `04-interlude-gate-fondations.md`.
> Objet : rendre le gate capable de conclure positivement, négativement, **ou de reconnaître
> qu'il ne sait pas**.

---

# Partie A — Protocole normatif

## 1. Ce que le dispositif doit démontrer sur lui-même

Avant de juger les moteurs, le gate doit prouver qu'il sait : détecter un effet économiquement
utile quand il existe · rendre un résultat nul quand aucune information n'existe · distinguer
absence d'effet et manque de puissance · préserver un échantillon réellement indépendant ·
tenir compte des dépendances temporelles, de l'exposition et des risques concurrents.

Sans ces garanties, il pourrait conserver un moteur inutile, éliminer un moteur utile, fabriquer
un effet par mauvais appariement, surestimer sa confiance, ou consommer progressivement son jeu
réservé.

## 2. Effet minimal économiquement utile

`δ_MEU = C_total + M_sécurité`, avec
`C_total = C_spread + C_commission + C_slippage + C_latence + C_base + C_financement`, et
`M_sécurité` couvrant l'incertitude d'estimation et la dégradation entre recherche et production.

Le seuil est défini **dans l'unité économique finale**. Une amélioration de probabilité n'est
pertinente que convertie : `ΔEV = Δp × (G_moyen + L_moyenne)`, et seulement si `ΔEV > C_total`.
**Une baisse de log-loss sans conséquence économique mesurable ne valide aucun moteur de
production.**

## 3. Unité réellement indépendante

Le nombre de lignes n'est pas la taille d'échantillon. Regroupement obligatoire par
`event_cluster_id`, `session_cluster_id`, `zone_cluster_id`, `macro_event_cluster_id`.

Approximation `N_eff ≈ N / (1 + 2Σρ_k)`, mais l'estimation principale utilise des méthodes
respectant les blocs : Monte-Carlo par blocs, bootstrap par clusters, bootstrap par blocs mobiles
ou stationnaire, simulation de risques concurrents, variance robuste par clusters, permutation
temporellement contrainte. **Aucune formule supposant l'indépendance sur des données qui ne le
sont pas.**

## 4. Rapport de puissance obligatoire

Publié avant le gate : effet minimal utile, niveau alpha, puissance cible, puissance disponible,
observations brutes, nombre de clusters, taille effective estimée, taux de censure, déséquilibre
entre groupes, hypothèses de variance, méthode de calcul.

**La puissance cible est fixée avant consultation du résultat et n'est jamais réduite après coup
pour rendre le test recevable.**

## 5. Test d'équivalence

Échouer à rejeter `H₀ : Δ = 0` ne prouve rien. Conclure à l'inutilité exige de démontrer
`−δ_MEU < Δ < +δ_MEU`, l'intervalle de confiance devant être **entièrement contenu** dans cette
zone.

## 6. Verdicts

| Verdict | Signification | Autorise |
| --- | --- | --- |
| `PASS_USEFUL_EFFECT` | effet supérieur au seuil utile, puissance et validation suffisantes | poids de production |
| `FAIL_EQUIVALENT_TO_ZERO` | effet démontré inférieur au seuil utile | `production_weight = 0`, moteur réfuté |
| `INDETERMINATE_UNDERPOWERED` | puissance insuffisante pour trancher | `production_weight = 0`, **spécification conservée** |
| `INDETERMINATE_WIDE_INTERVAL` | puissance théorique suffisante, incertitude finale trop large | idem |
| `PROTOCOL_INVALID` | contrôle négatif, appariement, qualité ou invariants en échec | **aucun résultat interprétable** |
| `HOLDOUT_COMPROMISED` | résultat existant mais jeu réservé non indépendant | confiance dégradée et publiée |

`FOUNDATION_FAILED` exige simultanément : `FAIL_EQUIVALENT_TO_ZERO`, contrôle négatif réussi,
puissance vérifiée, intégrité du jeu réservé intacte.

> **Poids nul par prudence ≠ moteur réfuté.** Un `INDETERMINATE` met le poids à zéro sans jamais
> constituer une preuve d'absence, et ne justifie pas la suppression de la spécification.

## 7. Contrôle négatif

Étiquette sans information par construction, produite par permutation par blocs, réattribution de
pivots entre instants comparables, ou pseudo-zones de mêmes caractéristiques mais positionnées
sans information future.

**Le contrôle négatif doit conserver tout ce que le protocole prétend contrôler** — autocorrélation,
saisonnalité intraday, grappes de volatilité, nombre de contacts, régime, occasions d'exposition —
et ne détruire que l'information spécifique de l'étiquette testée. Une permutation totalement
aléatoire casserait la structure et rendrait le contrôle trop facile à passer.

Pipeline complet exécuté jusqu'au verdict. Effet détecté sur étiquette vide ⇒
`NEGATIVE_CONTROL_FAIL`, `protocol_state = INVALID`, et **suspension de tous les résultats positifs
obtenus avec le même pipeline**. Causes à rechercher : fuite temporelle, mauvais appariement,
exposition déséquilibrée, dépendances ignorées, sélection après observation, erreurs de censure,
réutilisation du jeu réservé, coûts asymétriques, double comptage.

## 8. Audit de l'appariement

Balance mesurée sur toutes les variables d'appariement : différence moyenne standardisée, rapport
de variances, recouvrement des distributions, taille effective, distance maximale de paire, taux
de non-appariés, balance d'exposition, balance de clusters. **Seuils préenregistrés.** Mauvaise
balance ⇒ `MATCHING_INVALID` ; le modèle de résultat ne sert jamais à corriger silencieusement un
appariement défaillant.

**Positivité** : sans contrôle comparable, `COMMON_SUPPORT_FAILURE` et exclusion de la population
d'identification. La conclusion précise alors sa population réelle.

**Sensibilité** : estimer la force qu'aurait dû avoir un facteur non observé pour expliquer
l'effet. Un résultat fragile à un faible biais résiduel ne reçoit pas le poids d'un résultat
robuste.

## 9. Jeu réservé

`EXPLORATION_SET` pour tout — primitifs, correctifs, appariement, contrôles négatifs, choix de
modèles, courbes de seuil, puissance, gates intermédiaires, décisions de conception.
`RESERVED_FINAL_SET` **uniquement** pour le verdict final sur la chaîne figée.

Ouverture après gel de : définition des objets, population, horizons, coûts, métriques,
contrôles, modèles, seuils de décision, politique de censure, versions logicielles. Événement
d'audit obligatoire (identifiant, horodatage, empreinte de commit, version de données, version de
protocole, motif autorisé).

**Une seule ouverture pour la chaîne entière** — pas une par étage. Les résultats par
sous-composant appartiennent au même événement expérimental.

Seconde ouverture ⇒ `holdout_integrity = DEGRADED`, publication du nombre d'ouvertures, des
informations consultées, des modifications ultérieures, de la justification et de l'impact estimé.
**Dette de holdout** effaçable uniquement par un jeu temporel jamais observé, une réplication sur
une autre source, une période future, ou un marché comparable défini à l'avance.

## 10. Courbe de seuil d'acceptation

Le balayage n'est pas une collection d'hypothèses parmi lesquelles choisir la meilleure. Le
résultat est une **fonction** `g(θ_A)`, examinée sur sa forme globale, sa régularité, sa dérivée,
sa monotonie éventuelle, sa stabilité entre périodes et entre régimes, la largeur de ses **bandes
de confiance simultanées** et le nombre d'événements restant à chaque valeur.

Un pic isolé, absent des périodes voisines, est présumé artefact de sélection.

Seuil opérationnel choisi **après** analyse, en optimisant un critère préspécifié —
`θ* = argmax EV_net(θ)` — sous contraintes de puissance minimale, nombre minimal d'événements,
perte maximale, stabilité entre périodes et calibration acceptable. **Jamais choisi pour
maximiser un chiffre affiché.**

## 11. Cas C et propagation

`FOUNDATION_FAILED` sur les pivots **ne se propage pas mécaniquement** aux objets définissables
sans pivots. Un résultat « pivots négatifs, déséquilibre positif » signifierait que les
**événements** portent une information que les **niveaux** ne portent pas — conclusion recevable,
qui oriente vers une pondération des événements.

Le protocole vérifie alors si l'effet provient de la vitesse du déplacement, de la faible densité
d'exécution, du déséquilibre de flux, d'une surprise macro, d'un changement de régime ou de la
volatilité — **et non du label lui-même**.

## 12. Doctrine

Quatre situations à distinguer :

```
1. ceci apporte une information utile                → poids calibré
2. ceci n'apporte rien d'économiquement utile        → réfuté, poids nul
3. je n'ai pas assez d'information pour décider      → poids nul, recherche non résolue
4. mon protocole n'est pas fiable                    → tous résultats liés suspendus
```

**Seule la deuxième est une preuve d'absence.** L'objectif n'est pas d'éliminer le maximum
d'idées, mais uniquement celles dont l'inutilité est démontrée — sans confondre manque de preuve,
manque de puissance et défaillance de l'instrument.

---

# Partie B — Trois compléments

## C1 — Un seuil d'effet sans plancher de fréquence est incomplet

`δ_MEU` fixe l'amplitude minimale par occurrence. Il manque la **fréquence**.

Un effet de grande amplitude survenant deux fois par an n'est ni exploitable ni validable :
l'intervalle de confiance sur quelques dizaines de cas dépassera toujours l'effet, et le capital
immobilisé entre deux occurrences a un coût. Inversement, un effet minuscule à haute fréquence
peut être parfaitement viable.

**Règle** : chaque gate déclare, avec `δ_MEU`, une **fréquence minimale d'occurrence** `f_min`,
et le critère de passage porte sur le produit — l'espérance nette **par unité de temps**, pas par
occurrence. Un moteur qui franchit `δ_MEU` mais pas `f_min` reçoit `PASS_USEFUL_EFFECT` avec la
mention **`FREQUENCY_LIMITED`**, et son poids est plafonné par sa contribution réelle au flux de
décisions.

Ce plancher a un second usage : il est calculable **avant** tout test, à partir du seul historique
d'occurrences du motif. Un motif dont la fréquence est déjà sous `f_min` peut être écarté sans
mesurer son effet — c'est le test le moins coûteux de tout le protocole.

## C2 — Le jeu réservé doit être postérieur, pas aléatoire

La partie A impose l'ouverture unique mais ne dit pas **comment le jeu réservé est constitué**.

Un tirage aléatoire de lignes ou de journées est insuffisant : l'autocorrélation, les grappes de
volatilité et le chevauchement de régimes font fuir l'information du jeu d'exploration vers le jeu
réservé. Un modèle ajusté sur mardi « connaît » déjà mercredi.

**Règle** : le jeu réservé est une **période contiguë postérieure** à tout le jeu d'exploration,
séparée par un **intervalle tampon** au moins égal à la plus longue dépendance modélisée —
horizon maximal, fenêtre de volatilité la plus lente, durée de vie maximale d'une zone. La forme
la plus solide reste une **période future non encore survenue** au moment du gel, ce qui rend la
fuite matériellement impossible.

## C3 — Le gate microstructure ne peut pas conclure négativement à partir d'un signal grossier

La partie A note à juste titre que ce gate peut être conduit avant l'ontologie complète. Une
précaution s'impose.

Mesurer une décroissance suppose un signal, or les définitions fines relèvent de `03a` à `03f`.
Le gate utilisera donc des versions grossières. Mais **un signal grossier est plus bruité, ce qui
raccourcit sa décroissance apparente** : un verdict négatif obtenu ainsi peut être un artefact de
qualité de signal, pas une propriété du marché.

**Asymétrie retenue :**

| Résultat sur signal grossier | Verdict autorisé |
| --- | --- |
| Effet résiduel **positif** après latence et coûts | `LATENCY_VIABLE` — conclusif, un raffinement ne peut qu'améliorer |
| Effet résiduel **négatif** | `LATENCY_INDETERMINATE` — sauf si le pré-test du protocole Q19 conclut |

L'unique exception est le pré-test décrit dans le protocole Q19 : il ne dépend d'**aucune
définition de signal** et peut donc, lui, conclure négativement.
