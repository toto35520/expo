# 04c — Moteur de déséquilibre : ICT_FVG et EXECUTION_VOID

> Statut : **figé** (étape 4.3, spécification détaillée).
> Cette version **remplace** la première rédaction de l'étape 4.3. L'historique est dans git.
> Repose sur `04a-swings.md` et `04b-bos-choch-mss.md`.

## 0. Décision fondamentale

Un déséquilibre n'est pas un objet unique. Deux objets distincts coexistent :

| Objet | Fondement | Dépendances |
| --- | --- | --- |
| **`ICT_FVG`** | séquence de trois bougies | **dépend de la convention d'agrégation** |
| **`EXECUTION_VOID`** | zone réellement traversée avec peu de transactions, peu de temps passé, peu de liquidité | données de marché réelles |

Ils peuvent se superposer. **Ils ne sont jamais équivalents**, et le recouvrement entre les deux
est une grandeur mesurée (§19), pas une hypothèse.

---

# Partie A — Spécification normative

## 1. Définition mathématique de l'`ICT_FVG`

Sur trois bougies consécutives `C_{i-1}, C_i, C_{i+1}`, chacune portant `O, H, L, C` :

**Haussier** — existe si `H_{i-1} + ε < L_{i+1}`

- zone : `Z_bull = [H_{i-1}, L_{i+1}]`
- borne distale : `H_{i-1}` · borne proximale : `L_{i+1}`
- au moment de la confirmation, le prix est au-dessus de la zone ; un retour baissier est une
  tentative de remplissage.

**Baissier** — existe si `L_{i-1} − ε > H_{i+1}`

- zone : `Z_bear = [H_{i+1}, L_{i-1}]`
- au moment de la confirmation, le prix est sous la zone ; un retour haussier est une tentative
  de remplissage.

**Égalité interdite** : `largeur ≥ pas de cotation réellement négociable`, avec
`ε ≥ pas de cotation`. Une différence inférieure au pas ne crée jamais de déséquilibre — cela
écarte les faux motifs dus aux arrondis numériques.

**Symétrie** : les logiques haussière et baissière sont mathématiquement symétriques
(test d'acceptation §31).

**Bougies dégénérées** : si `H_i = L_i`, les efficacités du §16 sont indéfinies. Ces bougies
sont marquées et exclues du calcul d'efficacité, jamais complétées par une valeur par défaut
(ADR-025).

## 2. Horodatage et disponibilité

| Champ | Définition |
| --- | --- |
| `origin_timestamp` | **début de la bougie centrale** — convention fixée, non ambiguë (§ correction C7) |
| `availability_timestamp` | `close_time(C_{i+1})` |

**Avant `availability_timestamp`, le déséquilibre n'existe pas pour le moteur de décision**,
même si un graphique l'affiche plus tôt. Règle indispensable contre la fuite de données futures
(ADR-053, I1).

Pour l'`EXECUTION_VOID`, cette règle ne s'applique pas telle quelle : sa disponibilité est
définie séparément (§ correction C6).

## 3. Dépendance aux bougies : identifiant d'agrégation complet

Un même chemin de prix produit des `ICT_FVG` différents selon l'unité de temps, l'heure
d'ancrage, le fuseau, le fournisseur, le type de prix, les ticks manquants et la méthode de
construction. Stocker `timeframe = M5` est donc insuffisant.

```json
{
  "bar_type": "time", "bar_size": "5m",
  "anchor_timezone": "UTC", "anchor_offset": "00:00",
  "price_basis": "trade", "market": "COMEX_GC",
  "data_provider": "provider_id", "aggregation_version": "BAR_SCHEMA_3.1"
}
```

**Deux déséquilibres issus de conventions différentes sont deux objets différents**, même si
leurs zones sont proches. Conforme à ADR-022 et ADR-036.

## 4. Base de prix

`price_basis` est obligatoire : `TRADE | LAST | MID | BID | ASK | MEDIAN_COMPOSITE`.

- **futures GC** : détection principale sur `TRADE` ;
- **spot XAU/USD** : détection sur `MEDIAN_COMPOSITE` issu de plusieurs fournisseurs (ADR-006) ;
- **validation d'entrée ou de remplissage** : prix exécutable du broker — `ask` à l'achat,
  `bid` à la vente.

Un prix médian qui touche la zone alors que le prix exécutable ne la touche pas **ne déclenche
jamais d'entrée réelle**.

## 5. Largeur

`W = U − L` · `W% = (U−L)/P_création` · `W_σ = (U−L)/σ_t`, avec `σ_t` estimateur robuste
**disponible à la création**.

Conservés séparément : `width_price`, `width_ticks`, `width_percent`, `width_atr`,
`width_realized_volatility`.

**La largeur seule n'est pas une mesure de qualité.** Un déséquilibre immense peut être une
impulsion institutionnelle, une publication macro, un manque de liquidité, un spread anormal ou
une erreur de cotation.

## 6. Volatilité de normalisation

L'ATR est conservé pour compatibilité, mais complété par volatilité réalisée, volatilité
médiane, volatilité bipower, percentile de volatilité et vitesse du mouvement.

L'ATR réagit avec retard lors d'une expansion brutale : un déséquilibre créé pendant une
publication paraîtrait artificiellement gigantesque en unités d'ATR (`04a` §7).

Publiés : `volatility_regime_at_creation`, `normalization_reliability`.

## 7. Consequent Encroachment

`CE = (L+U)/2`. Stockés : `ce_price`, `ce_touched`, `ce_first_touch_timestamp`,
`ce_first_executable_touch_timestamp`.

**Le CE n'est pas un niveau de réaction, c'est une propriété géométrique.** Sa valeur prédictive
est testée contre 25 %, 50 %, 75 %, remplissage complet et niveaux aléatoires contrôlés.

## 8. Remplissage

Haussier : `F_bull = clip((U − P_min)/(U − L), 0, 1)`
Baissier : `F_bear = clip((P_max − L)/(U − L), 0, 1)`

Lecture : `0 %` borne proximale non pénétrée · `50 %` CE atteint · `100 %` zone entièrement
parcourue.

Conservés : `maximum_fill_ratio` (jamais décroissant) et `current_excursion_fill_ratio`.

## 9. Contact réel et spread

Zone touchée uniquement lorsqu'un prix **réellement exploitable** y entre : `ask` pour un
déséquilibre haussier recherché à l'achat, `bid` pour un baissier recherché à la vente.

Conservés séparément : `analytical_touch` et `executable_touch`.

Si le contact n'est causé que par un élargissement anormal du spread :
`touch_quality = SPREAD_DISTORTED`. Un tel contact n'est pas une mitigation normale.

## 10. Cycle de vie

États : `PROVISIONAL` (troisième bougie non clôturée — **jamais utilisable pour un ordre**),
`ACTIVE_NEW`, `ACTIVE_TOUCHED`, `ACTIVE_PARTIAL`, `ACTIVE_CE_REACHED`, `FULLY_FILLED`,
`MITIGATION_CANDIDATE`, `MITIGATED_CONFIRMED`, `INVALIDATED`, `EXPIRED`, `DATA_INVALID`.

> **Correction structurante** : ces états ne sont pas mutuellement exclusifs et sont
> réorganisés en trois axes indépendants (§ correction C1).

## 11. Remplissage, mitigation et invalidation sont trois notions distinctes

Un déséquilibre peut être **entièrement rempli sans que le scénario soit invalidé** : le prix
traverse la zone, prend la liquidité sous la borne distale, réintègre, puis produit un
déplacement haussier.

Inversement il peut n'être **pas rempli et avoir perdu toute pertinence** : structure supérieure
basculée, régime changé par une publication, zone testée trop souvent, prix durablement accepté
de l'autre côté.

La politique d'invalidation appartient à la stratégie : maintien sous la borne distale,
profondeur au-delà d'un seuil, durée d'acceptation supérieure à τ, rupture structurelle opposée,
expiration.

## 12. Mitigation

« Mitigé » ne désigne jamais un simple contact. Une mitigation confirmée exige une **réaction
postérieure au contact** :

`reaction = (P_max, post-touch − P_référence) / σ_t`

confirmée si `reaction ≥ reaction_threshold` dans `horizon ≤ reaction_horizon`, sans
franchissement de l'invalidation.

Au moment du contact, le moteur ne connaît que `MITIGATION_CANDIDATE`. Les valeurs
`MITIGATED_CONFIRMED` / `MITIGATION_FAILED` sont attribuées **plus tard** et ne sont jamais
utilisées rétroactivement comme information disponible au contact (ADR-038).

`P_référence` et l'instant d'évaluation de `σ_t` doivent être fixés explicitement
(§ correction C3).

## 13. Comptage des contacts

Distingués : `touch_count`, `penetration_count`, `ce_cross_count`, `full_fill_count`.

Un contact se termine lorsque le prix sort de la zone d'une distance de réinitialisation
`d_reset ≥ kσ`. Sans elle, plusieurs ticks au même niveau compteraient comme plusieurs contacts.

## 14. Âge

`age_seconds`, `age_market_events`, `age_bars`, `age_sessions`, `age_traded_volume`, plus
`sessions_crossed`, `major_events_crossed`, `regime_changes_since_creation`.

L'âge en bougies seul est insuffisant : vingt bougies de séance calme et vingt bougies pendant
une publication ne sont pas comparables.

## 15. Contexte de création

Tranches : `ASIA`, `LONDON_PRE_OPEN`, `LONDON_OPEN`, `LONDON_SESSION`, `NEW_YORK_PREMARKET`,
`COMEX_OPEN`, `NEW_YORK_SESSION`, `LONDON_FIX_AM`, `LONDON_FIX_PM`, `SESSION_CLOSE`,
`OVERNIGHT`.

Plus `seconds_since_session_open`, `seconds_until_next_macro_event`, `created_during_news`,
`created_during_rollover`, `created_during_spread_anomaly`.

## 16. Bougie de déplacement

`B_i = |C_i − O_i|` · `R_i = H_i − L_i` · `E_body = |C_i−O_i|/(H_i−L_i)` ·
`E_direction = (C_i−L_i)/(H_i−L_i)` pour un déplacement haussier ·
`D_σ = |C_i−O_i|/σ_t` · `V_move = |C_i−O_i|/Δt_i`.

Ces attributs sont conservés **sans décider arbitrairement** qu'un déséquilibre est bon ou
mauvais.

## 17. Volume du déplacement

`total_volume`, `aggressive_buy_volume`, `aggressive_sell_volume`, `delta`, `relative_volume`,
`volume_percentile`, `order_flow_imbalance`.

Un mouvement rapide à faible volume peut être un manque de liquidité, un retrait des vendeurs,
un repricing réel ou une anomalie de données. **Le volume faible n'est pas automatiquement
négatif.**

## 18. `EXECUTION_VOID`

Zone `Z` telle que `densité_volume(Z) < q_v`, `densité_temps(Z) < q_t`,
`vitesse_traversée(Z) > q_s`, seuils exprimés relativement au régime courant.

Mesurés : `executed_volume_per_tick`, `time_spent_per_tick`, `number_of_trades`,
`average_trade_size`, `order_book_depth`, `traversal_speed`, `revisit_frequency`.

> **Correction** : une conjonction de trois seuils est fragile ; une intensité continue est
> retenue en parallèle (§ correction C2).

## 19. Relation entre les deux objets

`O_void = surface du FVG recouverte par un execution void / surface totale du FVG`

Le backtest détermine si ce recouvrement apporte une valeur prédictive supplémentaire.

## 20. Relations avec la structure

Stockés : `associated_swing_id`, `associated_break_id`, `associated_displacement_id`,
`associated_liquidity_event_id`, `associated_regime_id`.

**Déplacement, BOS et FVG issus du même mouvement ne sont pas trois confirmations
indépendantes.** Ils sont regroupés en une famille causale unique,
`STRUCTURAL_DISPLACEMENT_CLUSTER`, conformément à ADR-035.

## 21. Position dans le range

`R_p = (P_FVG − L_range)/(H_range − L_range)`, publiée pour `daily_range_position`,
`h4_equivalent_range_position`, `session_range_position`, `impulse_range_position`.

**Valeur exacte et identifiant du range**, jamais l'étiquette « discount » ou « premium » seule.

## 22. Zones imbriquées et chevauchantes

Identifiant immuable `fvg_id`, relations `parent_fvg_id`, `child_fvg_ids`,
`overlapping_fvg_ids`, `same_displacement_group_id`.

Fusion possible à l'affichage ; **les objets analytiques restent séparés**, et aucune fusion ne
modifie rétroactivement les statistiques historiques.

## 23. Déséquilibres opposés et BPR

Un chevauchement entre déséquilibre haussier et baissier crée un objet nouveau,
`BPR_CANDIDATE`, portant `source_bullish_fvg_id`, `source_bearish_fvg_id`,
`overlap_lower_bound`, `overlap_upper_bound`. **Les objets sources ne disparaissent pas.**

## 24. Hiérarchie multi-échelle

Aucune conclusion automatique du type « unité de temps supérieure = meilleure qualité ». La
comparaison porte sur largeur normalisée, volume, déplacement, âge, régime, structure, nombre de
contacts, performance historique et **coût du stop associé**.

Un grand déséquilibre peut être structurellement important mais trop large pour une entrée
précise ; un petit peut être précis mais statistiquement fragile.

## 25. Score de qualité

Variables brutes stockées d'abord ; un modèle calibré estime ensuite
`probability_of_first_touch`, `probability_of_rejection_after_touch`,
`probability_of_full_fill`, `probability_of_ce_reaction`, `probability_of_continuation`,
`expected_adverse_excursion`, `expected_favorable_excursion`.

Le score final est une **présentation synthétique de probabilités mesurées**, jamais un barème
inventé (ADR-037).

## 26. Deux hypothèses à ne pas confondre

| Hypothèse | Question testée |
| --- | --- |
| **Attraction** | le prix touchera-t-il la zone avant l'expiration ? |
| **Réaction** | le prix produira-t-il une réaction suffisante après le premier contact ? |

Un déséquilibre peut avoir une forte probabilité d'être revisité et une faible probabilité de
provoquer une réaction exploitable. **Ce ne sont pas les mêmes modèles.**

> Une troisième hypothèse est ajoutée (§ correction C5).

## 27. Étiquettes d'apprentissage

- **retour** : 1 si touché dans l'horizon H, 0 sinon ;
- **remplissage** : 0 non touché · 1 touché sous 50 % · 2 CE atteint · 3 rempli à 100 % ;
- **réaction** : 1 si objectif atteint avant invalidation et avant barrière temporelle.

Formulation type : *après le premier contact avec un déséquilibre haussier, un objectif de
+1,5 volatilité est-il atteint avant une invalidation de −0,75 volatilité et avant 90 minutes ?*
Cette précision interdit l'énoncé vague « le FVG a bien réagi ».

## 28. Groupe de contrôle

Zones témoins appariées sur largeur, âge, session, volatilité, distance au prix, déplacement
préalable et position dans le range. Comparaison également avec : milieu d'impulsion, VWAP,
niveaux de retracement standards, zones de faible volume, zones de momentum simple.

## 29. Apport incrémental

> Une fois connus le momentum, la volatilité, le régime et la rupture structurelle, le fait
> qu'une zone soit un déséquilibre ajoute-t-il encore une information prédictive ?

Si non : le déséquilibre reste utile pour la visualisation et l'exécution, mais **ne reçoit
aucun poids autonome**.

## 30. Non-repeinture

Immuables après confirmation : `lower_bound`, `upper_bound`, `direction`, `origin_timestamp`,
`availability_timestamp`, `aggregation_id`.

Évolutifs : `status`, `fill_ratio`, `touch_count`, `age`, `reaction_metrics`.

Une correction de donnée historique ne modifie jamais l'objet silencieusement : elle crée
`data_revision_event`, `fvg_version`, `superseded_by_fvg_id` (cohérent avec ADR-012, ADR-015).

## 31. Tests d'acceptation

Déterminisme (deux implémentations indépendantes, mêmes objets) · équivalence batch/streaming ·
absence de fuite temporelle · symétrie haussier/baissier · pas de motif sous le pas de cotation ·
signalement des bougies issues d'un flux incomplet · contact faussé par le spread non assimilé à
un contact normal · **aucun déséquilibre valide issu d'un gap de rollover** · changement d'heure
sans modification silencieuse des conventions · tous paramètres versionnés.

---

# Partie B — Corrections, compléments et lacunes

Ce qui suit modifie ou complète la partie A. Chaque point est numéroté pour être discutable
séparément.

## C1 — Le statut est un vecteur, pas un état unique

**Le §10 se contredit avec le §11.** Le §11 établit qu'un déséquilibre peut être *entièrement
rempli sans être invalidé*, et *non rempli mais devenu non pertinent*. Or l'énumération du §10
place `FULLY_FILLED`, `INVALIDATED` et `MITIGATION_CANDIDATE` dans un champ unique, donc
mutuellement exclusifs — ce qui rend précisément ces deux situations inexprimables.

C'est exactement le défaut corrigé pour les statuts de données en `02e` §2 (ADR-024).

**Trois axes indépendants :**

```
remplissage   NEUF | TOUCHÉ | PARTIEL | CE_ATTEINT | COMPLET
mitigation    SANS_OBJET | CANDIDATE | CONFIRMÉE | ÉCHOUÉE
validité      ACTIVE | INVALIDÉE | EXPIRÉE | DONNÉES_INVALIDES
```

Plus l'état de confirmation `PROVISOIRE | CONFIRMÉ`, qui est un quatrième axe puisqu'il ne
concerne pas la zone mais sa disponibilité.

Le cas décrit au §11 devient alors exprimable : `remplissage = COMPLET`, `validité = ACTIVE`,
`mitigation = CONFIRMÉE`. Impossible à écrire avec un champ unique.

## C2 — L'`EXECUTION_VOID` ne doit pas être une conjonction de trois seuils

Le §18 exige simultanément trois conditions seuillées. C'est le même piège que la conjonction
du MSS (ADR-059) : trois seuils à régler, rareté de la conjonction, intervalle de confiance du
taux de base plus large que l'effet, et tentation d'assouplir jusqu'à obtenir « assez » de
détections.

**Retenu** : une **intensité continue de vide**, agrégeant les trois dimensions en une grandeur
normalisée par régime, la conjonction seuillée n'étant qu'un découpage déclaré de cette
intensité. Le recouvrement `O_void` devient alors une **intégrale d'intensité** plutôt qu'un
rapport de surfaces binaires — plus informatif à coût égal.

## C3 — Deux grandeurs indéfinies dans la formule de mitigation

Le §12 laisse deux points ouverts qui changent le résultat :

- **`P_référence`** — prix de contact, borne proximale, ou prix effectivement exécutable ? Les
  trois diffèrent d'au moins un spread. Retenu : **le prix exécutable au moment du contact**,
  cohérent avec le §9 ;
- **instant d'évaluation de `σ_t`** — à la création ou au contact ? Retenu : **au contact**,
  seul instant où la valeur est disponible pour décider.

Même remarque pour le remplissage du §8 : `P_min` et `P_max` doivent être mesurés sur une base
de prix déclarée. Un remplissage mesuré sur le prix médian et une entrée validée sur le prix
exécutable peuvent différer d'un spread entier — ce qui suffit à franchir ou non le CE.

## C4 — Détection sur le listé, exécution sur le spot : la base manque

Le §33 de ta rédaction affiche `Marché : GC / XAU/USD` avec une zone unique `4 018,4–4 021,1`.
**Ces deux marchés ne partagent pas la même échelle de prix** : ils diffèrent de la base, qui
évolue avec les taux et le coût de portage (`02b` §1).

Une zone détectée sur GC n'est pas une zone sur le spot. Champs manquants :

```
detection_market, execution_market
basis_at_creation, basis_at_touch
translated_bounds { lower, upper }      bornes traduites, avec leur incertitude
basis_staleness
```

Sans cela, chaque contact est décalé de la base — erreur systématique, silencieuse, et de
l'ordre de grandeur de la largeur des petites zones.

Par ailleurs, l'`EXECUTION_VOID` exige volume et activité par niveau de prix : il est
**calculable sur le listé uniquement**. Sur le spot, `execution_void_overlap_ratio` doit valoir
`INDISPONIBLE`, jamais `0` — l'absence de mesure n'est pas une absence de vide.

## C5 — Une troisième hypothèse manque

Le §26 distingue attraction et réaction. Il en manque une, et c'est la plus robuste :

**Hypothèse d'invalidation** — la borne distale fournit-elle un meilleur emplacement de
protection qu'un stop de volatilité équivalente ?

Cette hypothèse peut être vraie même si les deux autres sont fausses, et elle a une valeur
économique directe : elle agit sur l'espérance nette par le dimensionnement, pas par la
direction. C'est la même conclusion que pour l'absorption (ADR-040) et la quantité cachée
(ADR-048) — dans cette famille, **le niveau survit souvent au signal**.

## C6 — Disponibilité de l'`EXECUTION_VOID` non définie

Le §2 définit la disponibilité comme la clôture de la troisième bougie. L'`EXECUTION_VOID` n'a
pas de troisième bougie : il est constitué par une traversée.

**Retenu** : sa disponibilité est l'instant où la traversée est achevée **et** où la fenêtre de
mesure de densité est complète — donc strictement postérieure à la traversée. À défaut, le vide
serait « détecté » pendant sa formation, ce qui est une fuite.

## C7 — Ambiguïtés mineures à fixer

- `origin_timestamp` : le §2 dit « commence ou se termine ». Fixé au **début de la bougie
  centrale** (§2 partie A), sans quoi tous les âges se décalent d'une bougie.
- Bougies dégénérées `H_i = L_i` : division par zéro au §16. Marquées, exclues du calcul
  d'efficacité, jamais complétées (ADR-025).
- `expected_adverse_excursion` / `expected_favorable_excursion` (§25) : ces distributions sont
  fortement asymétriques et à queue épaisse ; **la moyenne en est un mauvais résumé**. Publier
  des quantiles, pas seulement l'espérance.
- Bougie issue d'un flux incomplet : le §31 demande de la « signaler ». Renforcé — elle ne doit
  produire **aucun objet sur le chemin de décision** (ADR-025), pas seulement un avertissement.

## C8 — Expiration et plafond de densité : maintenus

La spécification détaillée conserve le statut `EXPIRED` mais **ne définit ni règle d'expiration
ni plafond du nombre de zones actives**. Les deux restent obligatoires (ADR-064, inchangé) :

sans plafond, la carte se couvre de zones et **tout prix se trouve en confluence avec quelque
chose** ; l'attribut de confluence mesure alors la densité du détecteur, pas une coïncidence.

## C9 — Budget de recherche

Le §25 liste sept probabilités, le §27 trois familles d'étiquettes, le §28 six critères
d'appariement, le §24 neuf dimensions de comparaison — le tout multiplié par les horizons et les
grilles de paramètres. On dépasse largement le millier de tests implicites.

La discipline de l'ADR-034 s'applique intégralement : grille déclarée à l'avance, configurations
comptées, fraction d'historique matériellement réservée, et toute exploration postérieure
enregistrée comme telle.

## C10 — Ce qui reste vrai de la première rédaction

Deux points de la version précédente ne sont pas couverts par la spécification détaillée et
restent en vigueur :

1. **exclusion des écarts de fermeture** (ADR-062, inchangé) — ouverture du dimanche, coupure
   quotidienne, férié d'une place. Ce sont des **absences**, pas des inefficiences, et ce sont
   les plus grands écarts de l'or : un détecteur naïf les classerait en tête de son palmarès de
   qualité. Le test d'acceptation « rollover » du §31 couvre le roll, pas les fermetures ;
2. **plafond de densité** (ADR-064, inchangé) — voir C8.

## 32. Schéma de données

Le schéma de la spécification détaillée est adopté, augmenté des champs issus des corrections :

```json
{
  "fvg_id": "FVG-GC-5M-20260806-143500-BULL-001",
  "type": "ICT_FVG", "direction": "BULLISH",
  "lower_bound": 4018.4, "upper_bound": 4021.1, "ce_price": 4019.75,
  "width_price": 2.7, "width_ticks": 27,
  "width_atr": 0.42, "width_realized_volatility": 0.37,
  "origin_timestamp": "2026-08-06T14:30:00Z",
  "availability_timestamp": "2026-08-06T14:40:00Z",
  "price_basis": "TRADE", "aggregation_id": "GC-TIME-5M-UTC-V3",

  "status_confirmation": "CONFIRMÉ",
  "status_fill": "PARTIEL",
  "status_mitigation": "CANDIDATE",
  "status_validity": "ACTIVE",

  "maximum_fill_ratio": 0.36, "current_fill_ratio": 0.21,
  "fill_price_basis": "TRADE",
  "touch_count": 1, "ce_touched": false,

  "detection_market": "COMEX_GC", "execution_market": "SPOT_XAUUSD",
  "basis_at_creation": 1.85, "translated_bounds": {"lower": 4016.55, "upper": 4019.25},
  "basis_staleness_seconds": 3,

  "execution_void_intensity": 0.74,
  "execution_void_overlap_ratio": 0.81,
  "associated_break_id": "BREAK-...", "associated_liquidity_event_id": "SWEEP-...",
  "causal_family_id": "STRUCTURAL_DISPLACEMENT_CLUSTER-...",
  "market_regime_at_creation": "TREND_UP",
  "closure_overlap_checked": true,
  "density_rank": 3,
  "data_quality_score": 98, "data_quality_decomposition": [],
  "model_version": "FVG_ENGINE_1.0"
}
```

## 33. Sortie utilisateur

La sortie de la spécification détaillée est adoptée, avec deux modifications : les bornes sont
présentées **dans le marché d'exécution**, et le recouvrement du vide affiche `INDISPONIBLE`
lorsqu'il n'est pas calculable.

L'avertissement final est conservé tel quel — il énonce exactement l'ADR-070 :

> Le FVG, le déplacement et le BOS proviennent du même événement structurel et ne sont pas
> comptés comme trois confirmations indépendantes.

## 34. La question de recherche

> À déplacement, volatilité, régime, session, structure et largeur comparables, une zone
> qualifiée de déséquilibre améliore-t-elle réellement la probabilité ou l'espérance d'un trade
> par rapport à une zone de contrôle ?

Réponse positive hors échantillon → information exploitable. Réponse négative → outil de
présentation et d'exécution, sans poids autonome dans l'analyseur.

**Un ajout** : cette question doit être posée séparément pour les trois hypothèses du §26 et de
C5. Il est parfaitement possible que l'attraction soit nulle, la réaction faible, et
l'invalidation utile. Une réponse globale négative masquerait alors un usage valable.
