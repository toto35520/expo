# Adaptateur de données courtier

> Statut : **figé et implémenté**. Code : `feasibility/adapter.py`, `feasibility/contract.py`,
> `feasibility/quality.py`. 30 tests dédiés.
>
> L'adaptateur **ne produit aucun verdict**. Son livrable n'est pas la courbe kappa : c'est la
> **preuve que l'export permet de la mesurer**.

---

# Partie A — Protocole normatif

## 1. Données minimales

Par cotation : horodatage fournisseur, horodatage local de réception, bid, ask, symbole,
source, numéro de séquence si disponible. Dérivés : `mid`, `spread`, éventuellement spread
relatif.

**Ne jamais partir des seules bougies.** Elles ne permettent de connaître ni le spread au
déclenchement, ni la densité réelle, ni les changements intrabar, ni les séquences bid/ask, ni
les rafales, ni les arrivées tardives. Les bougies sont des **vues dérivées**, produites ensuite.

## 2. Horodatages et horloges

Deux horodatages obligatoires. Leur différence donne
`L_dissémination+transport`, **exploitable seulement si les horloges sont synchronisées**.

Publiés : `clock_sync_method`, `clock_offset_estimate`, `clock_offset_uncertainty`. Sans
synchronisation fiable, la latence absolue est marquée indisponible — **mais l'ordre temporel
local reste utilisable pour les coûts**. Les deux conclusions sont distinctes.

Toutes les données persistées sont en UTC ; le fuseau du courtier, son décalage serveur et sa
politique de changement d'heure sont conservés comme métadonnées. Les sessions ne sont jamais
déterminées par une heure fixe naïve.

## 3. Métadonnées de symbole

`broker`, `account_type`, `symbol`, `underlying`, `quote_currency`, `contract_size`,
`tick_size`, `tick_value`, `minimum_volume`, `volume_step`, barème de commission, portage long
et court, politique de portage triple, mode d'exécution. **Ces valeurs proviennent des
spécifications réelles du compte, jamais d'une convention générique supposée.**

## 4. Conversion du spread en coût

Le code ne produit **jamais** `spread × 2` par défaut. Le facteur dépend de la référence de
performance, du spread de sortie, du type d'ordre et de la convention d'aller-retour — supposer
l'un d'eux est le mode d'échec le plus courant.

## 5. Ordre temporel, doublons, lacunes

Statuts d'ordre : `ORDERED`, `DUPLICATE`, `OUT_OF_ORDER`, `SEQUENCE_GAP`,
`TIMESTAMP_CONFLICT`. Les ticks hors ordre ne sont pas simplement triés puis oubliés : leur
arrivée tardive est une information sur la qualité du flux. `raw_arrival_order` et
`normalized_event_order` sont conservés séparément.

Déduplication par priorité décroissante : numéro de séquence, identifiant d'événement,
`(horodatage fournisseur, bid, ask)`, `(horodatage de réception, empreinte)`. Une **répétition
réelle** de cotation n'est pas une duplication technique.

Lacunes classées `MARKET_CLOSED`, `EXPECTED_INACTIVITY`, `DATA_OUTAGE`, `UNKNOWN_GAP`. Les
fenêtres traversant les deux dernières sont censurées.

## 6. Densité et saturation (Q48)

Par horizon : nombre de fenêtres, fenêtres sans mise à jour, avec une seule, quantiles du nombre
de ticks, nombre de prix distincts, part de rendements nuls, part de mouvements d'un seul pas.

Statuts : `DENSITY_VALID`, `DENSITY_SPARSE`, `DENSITY_QUANTIZED`, `DENSITY_INVALID`.

**Aucun verdict économique n'est produit sur un horizon dominé par la quantification.**

## 7. Cotations anormales

`ask < bid` ⇒ `CROSSED_QUOTE`. Le spread négatif n'est **jamais** remplacé silencieusement par
zéro : il signale un réordonnancement, un flux composite mal synchronisé, une erreur de source,
ou une situation de marché particulière — quatre causes qu'il faut distinguer.

Valeurs aberrantes : `VALID_EXTREME`, `SUSPECTED_BAD_TICK`, `CONFIRMED_BAD_TICK`. **Seuls les
mauvais ticks confirmés quittent le chemin principal** ; les suspects restent disponibles pour
les analyses de sensibilité.

## 8. Sessions et rafales

Attributs **non exclusifs** : session principale, appartenance au recouvrement, fenêtre macro.
Un champ unique mutuellement exclusif perdrait une superposition économiquement pertinente.

Cadence sur plusieurs fenêtres ; état de rafale par quantile **calculé séparément par session** —
sans quoi une cadence normale de Londres serait classée en rafale au seul motif qu'elle dépasse
la cadence asiatique.

## 9. Cadence d'évaluation

`cadence / 2` n'est exact que sous arrivée uniforme indépendante de la cadence. Les cotations
arrivent en rafale et s'alignent souvent sur des frontières rondes : **le délai se mesure sur les
horodatages, il ne se déduit pas**.

## 10. Rapport de qualité obligatoire

Période, effectifs, sessions, taux de duplication, taux hors ordre, lacunes inexpliquées, part
censurée, quantiles de spread, cadence par session, densité par horizon, part d'amplitudes
dominées par le tick, qualité de synchronisation.

**La carte de faisabilité ne s'affiche jamais seule.** Elle est toujours précédée du diagnostic
qui dit si elle est interprétable.

## 11. Premier branchement recommandé

1. exporter plusieurs journées de cotations bid/ask horodatées ;
2. récupérer les spécifications exactes du compte ;
3. faire tourner uniquement validation temporelle, densité, distribution des spreads, `σ(h)`,
   `κ(h)` ;
4. **ne pas encore intégrer** sélection adverse, simulation d'exécution, impact, glissement
   agressif — ils restent inconnus et sont déclarés tels ;
5. comparer trois cartes : optimiste (coûts certains seuls), centrale, prudente (bornes
   supérieures sur les coûts non mesurés).

---

# Partie B — Ce que l'implémentation a apporté

## B1 — Les unités sont typées, pas documentées

Sur XAU/USD, confondre « par once » et « par lot » est un facteur cent, et l'erreur est
silencieuse : les deux nombres restent plausibles. La documentation ne protège de rien ici.

Le paquet porte donc l'unité **sur la valeur** : additionner une grandeur en unité de cotation
et une grandeur en monnaie du compte lève une erreur. La seule voie entre les deux passe par la
spécification de contrat, qui connaît la taille du contrat.

## B2 — Une lacune se classe par ce qui se passe pendant, pas à ses bornes

Défaut trouvé par le rapport lui-même : sur vingt-cinq journées, **vingt-quatre coupures
nocturnes étaient classées `DATA_OUTAGE`** et 83 % de la période déclarée censurée.

La cause : une coupure nocturne va de la clôture de New York à l'ouverture de Londres, et
**aucune de ses deux bornes n'est en session fermée**. Tester les extrémités ne pouvait donc
jamais reconnaître une nuit.

Correction : la classification échantillonne l'intérieur de la lacune. Après correction, les
vingt-quatre lacunes deviennent `MARKET_CLOSED` et la part censurée tombe à zéro.

Ce défaut aurait rendu tout export réel inexploitable — la nuit représente la majorité du temps
calendaire.

## B3 — La cadence « après » ne se mesure pas en regardant en arrière

Second défaut trouvé par un test : la classification comparait la cadence avant et après la
lacune, mais les deux étaient calculées sur la fenêtre **précédant** chaque cotation. Le premier
tick suivant une lacune a donc, par construction, une cadence nulle — c'est la lacune elle-même.

Conséquence : une vraie coupure entre deux périodes actives était classée `UNKNOWN_GAP` au lieu
de `DATA_OUTAGE`. Corrigé par une cadence prospective distincte.

## B4 — La résolution d'horodatage se mesure

Point non couvert par la spécification et qui décide de la validité de la latence
conditionnelle : une résolution à la milliseconde suffit à quinze cotations par seconde et
**perd tout l'ordre interne d'une rafale à cinq cents**. Or la rafale est précisément le régime
qui compte.

Le paquet infère la granularité effective — le plus petit écart non nul réellement observé — et
la compare à l'inter-arrivée en rafale. Si elle est insuffisante, une réserve est publiée : la
mesure reste possible, l'ordre interne des rafales ne l'est pas.

## B5 — Les coûts inconnus sont des scénarios, jamais des zéros

Trois cartes sont produites — optimiste, centrale, prudente. La carte optimiste ne contient que
les coûts certains ; la prudente ajoute les bornes supérieures sur glissement, impact et
sélection adverse.

**L'écart entre les deux cartes mesure directement ce que l'absence de campagne d'exécution
coûte en certitude.** C'est un chiffre utile en soi : il dit combien vaut Q42.

## B6 — Le refus est explicite

`build_calculation_inputs` échoue plutôt que de produire du plausible lorsque : les tableaux ne
sont pas alignés, le contrat n'est pas versionné, la bande d'avantages n'est pas préenregistrée,
le marché d'exécution de la cellule ne correspond pas au contrat chargé, ou **aucun horizon
n'est mesurable**.

Le dernier cas est le plus important : sans horizon mesurable, le calcul tournerait et
produirait des verdicts qui ne seraient que des artefacts de discrétisation.

## B7 — Ce que le paquet ne fait toujours pas

- **le calendrier de marché est un espace réservé**, pas un calendrier. Jours fériés,
  demi-séances et changements d'heure exigent le calendrier versionné de l'ADR-021. En son
  absence, certaines fermetures seront lues comme des interruptions de données ;
- sélection adverse, impact et glissement agressif **ne sont pas estimés** — ils exigent une
  campagne d'exécution (Q42) ;
- la latence absolue n'est pas mesurable sans horodatage fournisseur **et** horloges
  synchronisées.

---

## Exécuter

```bash
python3 -m feasibility.report          # rapport de qualité, puis les trois cartes
python3 -m feasibility.report --raw-arrays   # chemin direct, sans diagnostic
python3 -m pytest tests/ -q            # 69 tests
```

## Ce qu'il faut maintenant collecter

**Pour Q40** — un export de cotations **bid/ask horodatées**, plusieurs journées. Une liste
historique de spreads ne suffit pas : amplitude, densité, rafales et coûts doivent être calculés
sur la **même chronologie**, et un spread sans son instant n'est rattachable à rien.

**Pour Q19** — journaliser dès maintenant, sur l'infrastructure réelle, les horodatages
d'émission, d'accusé de réception et d'annulation. **Ces données ne se reconstruisent pas après
coup** : chaque journée sans journalisation est une journée définitivement perdue pour la mesure
de latence.
