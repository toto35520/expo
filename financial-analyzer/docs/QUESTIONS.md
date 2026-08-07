# Questions ouvertes — registre consolidé

Toutes les questions soulevées au fil des étapes, regroupées par thème. Elles ne bloquent pas
l'avancement de la spécification ; elles bloqueront l'implémentation. Ce fichier est mis à jour
à chaque étape et sera livré consolidé à la fin.

**Légende d'impact** : 🔴 bloque l'implémentation · 🟠 change une décision d'architecture ·
🟡 change un réglage ou un coût.

---

## A. Décisions de projet

| # | Question | Impact | Origine |
| --- | --- | --- | --- |
| **Q1** | Emplacement du code et pile technique. Le dépôt hôte est TypeScript/React Native ; les étages 5, 7 et 12 (régime, fusion, calibration) vivent naturellement en Python. Service autonome, tout en TS, ou noyau numérique séparé ? | 🔴 | ADR-005 |
| **Q4** | Mode cible : alerte à l'opérateur, ou exécution automatique ? L'étage 10 change de nature selon la réponse. | 🔴 | 01 §6 |
| **Q3** | Horizons visés. Ils déterminent la structure des coûts, donc le seuil d'espérance, donc le taux d'abstention. *(la classe d'actif est résolue : XAU/USD spot)* | 🔴 | 01 §6 |
| **Q11** | Exécution sur le spot, sur le listé, ou les deux ? Si le signal vient du listé et l'exécution du spot, la base devient un coût de décision à modéliser, pas une approximation. | 🟠 | 02b §12 |
| **Q14** | Les explications produites seront-elles diffusées, ou strictement personnelles ? Détermine si le filtre de redistribution est contractuel ou de confort. | 🟡 | 02c §10 |

## B. Accès aux données

| # | Question | Impact | Origine |
| --- | --- | --- | --- |
| **Q5** | Liste effective des fournisseurs spot, protocoles, et **combien sont réellement indépendants**. Deux flux d'un même agrégateur comptent pour un (ADR-006). | 🔴 | 02 §10 |
| **Q9** | Mode d'accès aux données listées : événementiel par ordre, carnet agrégé, ou différé. Conditionne toute la famille microstructure. Contrainte de coût et de licence. | 🔴 | 02b §12 |
| **Q28** | Donnée **par ordre** accessible, même sur historique limité ou en différé ? Change la nature du moteur d'icebergs et ouvre la **seule fenêtre de vérité terrain** de la famille microstructure. | 🟠 | 03e §11 |
| **Q6** | Profondeur de carnet réellement disponible chez les brokers spot (souvent absente en retail). | 🟠 | 02 §10 |
| **Q20** | Le carnet spot est-il exploitable, ou la microstructure repose-t-elle intégralement sur le listé ? | 🟠 | 03a §13 |
| **Q29** | La détection de quantité cachée a-t-elle un sens sur le spot, ou est-elle déclarée listé uniquement ? | 🟡 | 03e §11 |
| **Q8** | Accès à une référence future COMEX pour l'ancrage externe du prix spot. | 🟠 | 02 §10 |
| **Q12** | Quelles sources physiques sont dans le budget ? Du quasi public à l'institutionnel coûteux. Un capteur de tension physique grossier reste viable, mais doit être **su et déclaré**. | 🟠 | 02c §10 |
| **Q13** | L'écart futures/physique est-il obtenable en continu, ou seulement reconstruit ? Détermine si la tension physique est un capteur intraday ou quotidien. | 🟡 | 02c §10 |
| **Q30** | **Données inter-marchés** (dollar, taux réels, argent) disponibles ? Nécessaires pour qualifier une impulsion de news par simultanéité — absentes du socle actuel. | 🟠 | 03f §4 |

## C. Historique et stockage

| # | Question | Impact | Origine |
| --- | --- | --- | --- |
| **Q7** | Horizon de conservation des ticks bruts. Conditionne la rejouabilité (I2) et le volume de stockage. | 🟠 | 02 §10 |
| **Q10** | Profondeur d'historique pour les futures et la surface d'options. Conditionne les distributions conditionnelles (ADR-007) et la calibration (étage 12). | 🔴 | 02b §12 |
| **Q21** | Profondeur d'historique de carnet conservée. Sans historique événementiel, ni demi-vie ni distributions conditionnelles ne sont estimables — le moteur reste bloqué en veto. | 🔴 | 03a §13 |
| **Q24** | L'historique événementiel permet-il un taux de base **par régime** ? Un motif rare mesuré sur peu de cas donne un intervalle plus large que l'effet cherché. | 🟠 | 03c §13 |
| **Q31** | Capture systématique de l'état du carnet **avant** événement : coût de stockage acceptable ? C'est la référence qui distingue trou de liquidité et déplacement réel. | 🟠 | 03f §3 |
| **Q15** | Les fournisseurs spot ont-ils des frontières de journée différentes ? Si oui, aucune agrégation journalière multi-fournisseurs sans re-découpage depuis les ticks. | 🟠 | 02d §12 |

## D. Conventions à obtenir des fournisseurs

| # | Question | Impact | Origine |
| --- | --- | --- | --- |
| **Q22** | Convention d'agrégation des transactions documentée ? Sans elle le delta cumulé n'est pas interprétable, et l'information est rarement fournie spontanément. | 🔴 | 03b §15 |
| **Q16** | Les niveaux journaliers et hebdomadaires servent-ils à la décision ? Si oui, la frontière de journée devient un paramètre de premier ordre. | 🟠 | 02d §12 |

## E. Réglages et comportements

| # | Question | Impact | Origine |
| --- | --- | --- | --- |
| **Q19** | **Latence de bout en bout** mesurable sur l'infrastructure cible ? Détermine à elle seule le rôle du moteur de microstructure, et ne dépend d'aucun modèle. | 🔴 | 03a §13 |
| **Q18** | Comportement par défaut en mode dégradé **avec position ouverte** : réduction, sortie, ou alerte ? Dépend de Q4, à trancher avant l'étage 8. | 🔴 | 02e §12 |
| **Q23** | Quelle fraction d'historique est réservée à la validation finale, et **qui garantit matériellement** qu'elle n'est pas consultée avant ? | 🟠 | 03b §15 |
| **Q2** | Placement du régime : après les agents (version retenue) ou en entrée des agents ? | 🟠 | 01 §6 |
| **Q26** | L'épuisement peut-il déclencher la **sortie** d'une position, et pas seulement bloquer une entrée ? Usage bien plus défendable qu'une entrée à contre-sens. | 🟠 | 03d §13 |
| **Q25** | Les zones d'absorption sont-elles conservées entre séances, ou expirent-elles à la clôture ? Dépend de Q3. | 🟡 | 03c §13 |
| ~~**Q27**~~ | ~~Définition partagée d'« impulsion »~~ — **résolue à l'étape 4.1** : une impulsion est une jambe de la décomposition par changement de direction, à un niveau déclaré (ADR-056). | ✅ | 03d §13 |
| **Q17** | Score de qualité visible en continu ou seulement en cas de dégradation ? Un indicateur permanent est ignoré au bout de quelques jours. | 🟡 | 02e §12 |
| **Q32** | Combien de niveaux de décomposition θ, et quelles valeurs ? Paramètre le plus porteur de tout l'étage 4 : il redessine blocs d'ordres, déséquilibres et ruptures de structure. | 🟠 | 04a §9 |
| **Q33** | Rupture **immédiate** ou **retenue** après fenêtre de maintien ? Ce sont deux signaux distincts, avec des taux de base différents ; l'arbitrage entre force du signal et coût du retard en prix d'entrée se calcule, il ne se devine pas. | 🟠 | 04b §6 |
| **Q34** | Combien de zones de déséquilibre actives au maximum par niveau ? Sans plafond, la confluence est garantie par construction et cesse de mesurer quoi que ce soit. | 🟠 | 04c C8 |
| **Q35** | Quelles conventions d'agrégation exactement ? Chaque couple (unité, ancrage, fuseau, base de prix, fournisseur) crée un **jeu d'objets distinct** : le nombre de conventions retenues multiplie directement le coût de calcul, de stockage et de validation. | 🟠 | 04c §3 |
| **Q36** | Politique d'invalidation et **horizons opérationnels officiellement supportés**. Sans cette décision : fenêtre d'acceptation, expiration, barrière temporelle de réaction, profondeur d'invalidation, distance de réinitialisation et définition d'un retest distinct restent tous non fixables. | 🔴 | 04c §11 · 04d |
| **Q37** | L'intensité d'acceptation : formule déterministe, modèle calibré, ou les deux ? *Recommandation retenue* : vecteur brut obligatoire + score déterministe reproductible + probabilité calibrée facultative — le déterministe garantit le test de double implémentation, le calibré est seul autorisé à s'exprimer en pourcentage (ADR-037). | 🟠 | 04d |
| **Q38** | Quelle fraction de la largeur d'une zone l'incertitude de traduction peut-elle représenter avant suspension ? À tester par horizon et par largeur de zone. | 🟠 | 04d §12 |
| ~~**Q39**~~ | ~~Séquencement du projet~~ — **résolue à l'interlude 4** : gel de 4.5, priorité Q19 → Q36 → Q1 → contrôles négatifs → puissance → gates (ADR-087, ADR-101). | ✅ | 04d C9 |
| **Q40** | **Définition canonique de** `δ_MEU`, puissance cible, unité de cluster, politique d'équivalence — **et plancher de fréquence** `f_min`. À définir par horizon et par type de décision. Sans ces valeurs, aucun gate ne peut distinguer « n'apporte rien » de « je n'ai pas les moyens de le savoir ». | 🔴 | Addendum C1–C2 |
| **Q41** | **Gouvernance du jeu réservé** : frontière temporelle, source, taille, intervalle tampon, conditions d'ouverture, gestion de la dette, procédure de réplication. Le cadre est fixé (ADR-098) ; les valeurs doivent l'être avant tout usage. | 🔴 | Addendum C5 |
| **Q42** | **Campagne de mesure sur compte réel** acceptée, et son budget ? La question a changé de nature : elle n'est plus « faut-il mesurer le courtier ? » mais « **le segment inconnu tient-il dans le budget résiduel `B_L` ?** » (ADR-178, ADR-179). Elle ne se pose que pour les cellules survivant à Q40 **et** à la borne passive — donc à financer après la campagne Q51-A, pas avant. | 🟠 *(décalée)* | Q19 §5 · Q51-A §25 |
| ~~**Q43**~~ | ~~Cadence d'évaluation cible~~ — **devenue observable** : `B3 − B2` est mesuré événement par événement par la campagne passive, jamais approximé par `période / 2`. Cette approximation supposait des arrivées uniformes ; les cotations arrivent en rafale. Reste à **choisir** entre `EVENT_DRIVEN` et `PERIODIC`, choix que la campagne peut désormais trancher par comparaison directe. | ✅ mesurable · 🟡 choix | Q19 §2 · Q51-A §7 |
| **Q44** | **Barème complet du courtier** : spread effectif observé par tranche de session (pas le spread annoncé), commission, portage overnight et son éventuelle multiplication hebdomadaire. Ce sont les trois quarts de `C_total`, et ils sont obtenables aujourd'hui. | 🔴 | Q40 §9 |
| **Q45** | **Convention de comptage du spread** : aller-retour complet, ou rendements de mi-prix à mi-prix ? Les deux se défendent ; les mélanger fausse toute comparaison. À déclarer une fois pour tout le projet. | 🟠 | Q40 §3 |
| **Q46** | **Bande d'avantages prédictifs plausibles**, déclarée à l'avance, nécessaire pour lire `h_min` sur la courbe `κ(h)`. La déclarer après avoir vu la courbe reviendrait à choisir la conclusion. | 🟠 | Q40 §5 |
| **Q47** | **Fiscalité applicable** aux résultats. Hors périmètre technique, mais elle affecte l'espérance nette finale et doit venir d'une source compétente plutôt que d'une supposition. | 🟡 | Q40 §10 |
| **Q48** | **Grille d'horizons** à figer avant lecture des résultats, et **densité de ticks** disponible à chaque horizon. Un horizon dont l'amplitude sature sur le pas de cotation mesure la discrétisation et non le marché (ADR-121). | 🔴 | Q40 phase 0 · B1 |
| **Q49** | **Contribution cible par unité de temps** et coûts fixes journaliers (données, infrastructure, capital immobilisé) : ils déterminent le plancher de fréquence économique, donc peuvent exclure une famille avant tout test prédictif. | 🟠 | Q40 phase 0 §9 |
| **Q50** | **Export de cotations bid/ask horodatées**, plusieurs journées. Une liste de spreads sans chronologie ne suffit pas : amplitude, densité, rafales et coûts doivent être calculés sur la même timeline (ADR-123). | 🔴 | Adaptateur §1 |
| **Q51** | **Journalisation de latence** — le **moteur** est implémenté (ADR-149 à 160, 44 tests). Ce qui manque : brancher les points d'appel du connecteur courtier et **démarrer la phase passive**. Ces données ne se reconstruisent pas après coup. | ✅ moteur · 🔴 branchement | Adaptateur · Q19 §5 · Q51 |
| **Q61** | **Latence maximale admissible** `L_max_admissible(c, h)`, à déclarer avec source et date **avant** lecture de la borne mesurée. Elle dépend de `edge(L, h, c)`, donc d'un signal : elle ne peut pas être calculée aujourd'hui, mais sans elle aucun verdict passif ni budget `B_L` ne se calcule (ADR-179). | 🔴 | Q51-A §26 |
| **Q62** | **Ancrage de la capturabilité** : accepte-t-on de conclure sous ancrage `LOCAL_RECEIVE` ? Il surestime la fraction capturable — une exclusion reste concluante, une non-exclusion est faible. Lever l'optimisme exige de qualifier `B0 → B1`, donc une horloge Q57 qualifiée pour l'inter-systèmes (ADR-180). | 🟠 | Q51-A §21 |
| **Q57** | **Qualification d'horloge** — le **moteur** est implémenté (ADR-161 à 163 et 167 à 170, 48 tests avec Q58). Ce qui manque : **instrumenter l'hôte qui exécutera réellement l'analyseur** — murale, monotone, dérive, discontinuités, synchronisation, résolution effective. Fiche : `connector-capability/host-clock-capability.json`. Une synchronisation médiocre n'empêche pas la résolution ; elle réduit le domaine mesurable (ADR-170). | ✅ moteur · 🔴 mesure | Q51 §4 · Q57 §38 |
| **Q58** | **Sémantique de l'API courtier** — le **moteur** est implémenté (ADR-164 à 167). Ce qui manque : **remplir la fiche** `connector-capability/broker-connector-capability.json` avec ce qui est démontré. Une grande partie se qualifie **sans émettre d'ordre** : documentation, code du connecteur, rappels de connexion, chronologie d'une session sans trading. Le reste attend Q42. | ✅ moteur · 🔴 contenu | Q51 §14 · Q58 §39 |
| **Q59** | **Politique d'échantillonnage** — le **moteur** est implémenté (`StoppingPolicy`, ADR-176). Ce qui manque : les **valeurs**, à déclarer avant la première observation. Le module refuse une politique postérieure. Aucun seuil arbitraire n'est proposé : la suffisance dépendra de la variance et du nombre de grappes réellement obtenus (ADR-175). | ✅ moteur · 🔴 valeurs | Q51 §28 · Q51-A §15 |
| **Q60** | **Surcoût maximal acceptable** du journal. Le collecteur **mesure** désormais son propre coût par événement et signale un coût nul comme suspect plutôt que rassurant. Reste à fixer le seuil au-delà duquel la campagne est jugée modifier l'objet qu'elle mesure. | 🟡 | Q51 §38 · Q51-A §14 |
| **Q52** | **Calendrier de marché versionné** — le **moteur** est implémenté (ADR-129 à 138, 30 tests) ; ce qui manque est le **contenu réel** : horaires, fériés, demi-séances et maintenances du courtier et de la place, avec leurs sources. | 🔴 | Adaptateur B7 · Q52 |
| ~~**Q53**~~ | ~~Sources de calendrier~~ — **protocole et compilateur implémentés** (ADR-139 à 148, 35 tests, dossier `calendar-sources/`). Reste à **collecter** : spécification du symbole sur le compte réel, horaires serveur, fériés, maintenances, avec leurs preuves. | ✅ moteur · 🔴 contenu | Q52 §19 · Q53 |
| **Q54** | **Seuil de temps inconnu**, désormais à distinguer en deux causes : `UNKNOWN_CALENDAR_RULE` (aucune règle) et `UNKNOWN_SOURCE_AUTHORITY` (règle non normative). À définir **par cellule** — une minute inconnue au milieu d'une entrée est plus grave qu'une heure inconnue hors période analysée. **À ne pas fixer avant d'avoir vu la géométrie réelle des inconnues sur le premier export Q50.** | 🟠 | Q52 §31 · Q53 §38 |
| **Q55** | **Horloge des horizons** : temps calendaire ou temps de marché, par famille de labels ? Les deux sont légitimes, les mélanger ne l'est pas (ADR-137). | 🟠 | Q52 §26 |
| **Q56** | **Gouvernance des overrides** : qui peut créer, valider et retirer un override manuel de calendrier ? Le moteur exige auteur, motif et preuve ; il ne peut pas exiger une autorité. | 🟡 | Q52 §20 |

---

## Les cinq questions qui bloquent le plus

Si une seule séance est consacrée à répondre, dans cet ordre :

1. **Q1** — pile technique. Rien ne s'implémente avant.
2. **Q19** — latence de bout en bout. Fixe le rôle de toute la famille microstructure, sans dépendre d'aucun modèle.
3. **Q9 / Q21** — classe de données listées et profondeur d'historique de carnet. Décident si les moteurs 3.1 à 3.6 sont mesurables ou restent en veto permanent.
4. **Q4 / Q18** — alerte ou exécution, et conduite en mode dégradé avec position ouverte.
5. **Q5** — indépendance réelle des fournisseurs spot. En dessous de trois sources indépendantes, aucune décision n'est autorisée (ADR-006).

---

## Ce qui n'attend plus qu'une mesure

Cinq questions ont désormais leur **moteur implémenté et testé**, et attendent uniquement des
données que personne d'autre que l'infrastructure réelle ne peut fournir :

| # | Moteur | Ce qui manque |
| --- | --- | --- |
| **Q50** | adaptateur | export bid/ask horodaté, plusieurs journées |
| **Q51** | journal de latence | brancher les points d'appel, démarrer la phase passive |
| **Q52 / Q53** | calendrier + chaîne de preuve | horaires, fériés, maintenances, avec leurs sources |
| **Q57** | qualification d'horloge | instrumenter l'hôte réel |
| **Q58** | sémantique du connecteur | remplir la fiche avec ce qui est démontré |

Q51 et Q57 partagent une propriété qu'aucune autre question du registre ne possède : **leurs
données ne se reconstruisent pas après coup.** Une latence non journalisée au moment où elle
s'est produite est perdue définitivement ; une horloge non instrumentée pendant une session
ne peut pas être requalifiée rétrospectivement.

Q57 et Q58 se qualifient en grande partie **sans risque financier** — instrumentation locale,
documentation, code du connecteur, chronologie d'une session sans trading.

Une fois Q19 alimenté par ces mesures, l'embranchement suivant est déterminé par un seul
chiffre : si la borne de latence élimine déjà les horizons microstructurels, financer Q42
est inutile ; sinon, Q42 devient la prochaine dépense rationnelle.
