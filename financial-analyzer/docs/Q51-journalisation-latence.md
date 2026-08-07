# Q51 — Journalisation de latence de production

> Statut : **figé et implémenté**. Code : `feasibility/latency_journal.py`, 44 tests dédiés.
>
> Q51 ne cherche pas à démontrer qu'un signal est rentable. Il répond à : *lorsque le marché
> produit une information exploitable, combien de temps s'écoule réellement avant que
> l'infrastructure puisse agir — notamment pendant les rafales où cette information apparaît ?*

---

# Partie A — Protocole normatif

## 1. La latence est une distribution conditionnelle

La valeur utile à Q19 n'est ni la moyenne ni le centile marginal, mais le centile
**conditionnel aux états où les signaux apparaissent réellement** — session, rafale, type de
message, charge, courtier, état de connexion.

## 2. Deux familles d'horloges

**Horloge murale** pour relier des événements de systèmes différents ; **horloge monotone** pour
mesurer les durées locales. Une horloge murale peut sauter — synchronisation, correction
système, changement manuel, virtualisation, reprise après veille. Une horloge monotone ne
recule pas.

Toute durée locale est mesurée sur l'horloge monotone ; l'écart mural est conservé pour l'audit.
Une divergence au-delà du seuil crée `CLOCK_DISCONTINUITY`.

État de synchronisation par session : méthode, source, décalage estimé, incertitude, dernière
synchronisation, dérive. Statuts `SYNC_VERIFIED`, `SYNC_DEGRADED`, `SYNC_UNKNOWN`,
`CLOCK_UNSTABLE`. **Une latence inter-systèmes ne se revendique pas plus finement que
l'incertitude de synchronisation.**

## 3. Chronologie canonique

De l'événement de marché à la clôture complète, quinze instants possibles. Tous ne seront pas
disponibles. **Le journal ne les invente jamais** : une valeur absente est nulle, pas estimée.

Les horodatages fournis par le courtier sont stockés séparément, chacun avec sa **sémantique
exacte documentée** — « heure de création du message d'accusé », non « heure courtier ».

## 4. Décomposition observée, agrégée, ou non identifiable

Trois catégories, jamais confondues :

| Catégorie | Signification |
| --- | --- |
| **Observé** | mesuré entre deux horodatages fiables du même référentiel ; décomposable |
| **Agrégé seulement** | mesuré, mais somme de composantes que l'infrastructure ne sépare pas |
| **Non identifiable** | non mesurable avec cette API ; reste inconnu |

Deux applications directes :

- `provider → réception locale` contient appariement, agrégation, distribution, transport et
  tamponnage. **Il ne doit jamais être nommé « latence réseau ».**
- `émission → accusé` contient file locale, réseau aller, traitement courtier, réseau retour et
  rappel local. Sans horodatages du courtier, ces composantes sont **non identifiables**. Le
  rapport publie `SUBMIT_TO_ACK_LATENCY`, jamais une latence réseau ou courtier « pure ».

## 5. Cadence, calcul, décision

Le retard de cadence est mesuré événement par événement. L'approximation `cadence / 2` n'est
qu'un diagnostic théorique sous arrivée uniforme — les cotations arrivent en rafale et
s'alignent souvent sur des frontières rondes.

Le temps de calcul est mesuré par famille de features, version de moteur, volume traité et état
de rafale. **Une IA explicative ne se trouve jamais sur le chemin critique** si son temps de
génération n'est pas nécessaire à la décision numérique.

## 6. Identité, retries, journal

`logical_order_id` et `submission_attempt_id` sont séparés : un retry ne crée pas silencieusement
un nouvel ordre logique, et l'idempotence devient vérifiable.

Journal **append-only**, chaîné par empreintes. Les états courants sont reconstruits depuis les
événements ; aucune réécriture historique. Les événements capables de créer un état réel chez le
courtier sont persistés **avant ou au moment de l'action** — sinon un incident laisse un ordre
réel sans trace locale de son origine.

Le moteur n'impose **pas** `submit_return < ack_receive` : une API peut délivrer le rappel avant
le retour de l'appel. Seules les relations garanties par la sémantique du connecteur sont
imposées.

## 7. Conditionnement

État de rafale **au déclenchement** et **à l'accusé**, conservés séparément. En plus des classes,
les variables continues — cadences à 100 ms, 1 s, 5 s, vitesse de prix, spread, percentile de
spread — permettent de tracer la latence en fonction de l'intensité plutôt que de seuils
arbitraires.

Les mesures sont conditionnées par l'état de connexion : un accusé reçu juste après une
reconnexion ne se mélange pas aux mesures nominales.

## 8. Échantillonnage

Une campagne ne doit pas n'émettre que pendant les périodes calmes — Q19 sous-estimerait la
latence conditionnelle. Couverture par session, quartile de cadence, p95, p99, spread normal et
élevé. **La probabilité de sélection est conservée** pour repondérer les distributions.

Les probes ne sont pas supprimés autour des publications macro : ils forment une cellule
distincte. Si la politique de risque interdit tout ordre réel dans ces fenêtres, la
journalisation passive reste active et mesure quand même la dégradation de l'infrastructure.

## 9. Trois phases

| Phase | Contenu | Prérequis |
| --- | --- | --- |
| **A — passive** | cotations, évaluations, charge, connexion, rafales, horloges | **aucun** — démarre immédiatement |
| **B — messagerie** | émission→accusé, annulation→accusé, rejets, stabilité | Q42 si un ordre réel peut être créé |
| **C — micro-exécutions** | latence d'exécution, exécutions partielles, glissement, sélection adverse | Q42 résolue |

La phase B mesure la messagerie. Elle **ne mesure pas** correctement la latence d'exécution, la
position en file, la sélection adverse, le glissement agressif ni l'impact.

> « Éloigné du marché » ne signifie pas « impossible à exécuter ». Un mouvement extrême reste
> possible — d'où budget, distance minimale, taille minimale, coupe-circuit et nombre maximal
> d'ordres actifs avant toute activation sur compte réel.

## 10. Règle d'asymétrie

```
borne inférieure observable déjà trop lente  → LATENCY_NON_VIABLE, concluant
borne inférieure suffisamment rapide         → LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER
```

Une bonne latence de messagerie ne démontre pas que l'exécution réelle sera assez rapide.

Toute observation dont la latence dépasse l'horizon compte comme **mouvement entièrement
consommé** — jamais comme donnée manquante. C'est la règle qui a corrigé le biais de sélection
détecté à la phase 0 de Q19.

## 11. Distributions et grappes

Par cellule : p50, p75, p90, p95, p99, maximum, effectif, **nombre de grappes indépendantes**.
Publiées séparément pour chaque intervalle nommé. Les observations d'une même rafale ne sont pas
indépendantes : les intervalles de confiance utilisent les grappes appropriées.

## 12. Effet observateur et stockage

La campagne peut elle-même allonger la latence qu'elle mesure. Le journal mesure son propre
coût en comparant des périodes contrôlées ; un surcoût significatif est publié.

Journal critique — ordre, accusé, rejet, annulation, exécution, connexion, discontinuité —
**jamais échantillonné**. Les métriques haute fréquence peuvent être agrégées ou échantillonnées
selon une politique déclarée, à condition que les horodatages nécessaires à Q19 restent assez
précis.

---

# Partie B — Implémentation

## B1 — L'agrégat est une contrainte de type

Le point central est encodé dans `LatencyInterval` : un intervalle `AGGREGATE_ONLY` **doit**
déclarer au moins deux composantes qu'il ne sépare pas, sinon le constructeur lève une erreur.
Sans cette liste, rien n'empêcherait de renommer l'aller-retour d'émission en « latence
réseau » ou « latence courtier ».

Symétriquement, un intervalle `NOT_IDENTIFIABLE` ne peut pas porter de durée : une valeur
absente reste absente. Et `decomposable_into()` retourne faux pour toute composante d'un agrégat.

`submit_to_ack()` bascule d'`AGGREGATE_ONLY` à `OBSERVED` **uniquement** si les horodatages du
courtier sont disponibles. `broker_side_split()` renvoie trois composantes inconnues sans eux —
et même avec, les trajets aller et retour restent des agrégats, la file locale et le réseau ne
se séparant pas.

## B2 — Un recul d'horloge est un signe, pas une magnitude

Défaut trouvé par un test : un recul de l'horloge murale de 1 ms passait sous le seuil de
tolérance de 50 ms et n'était pas signalé.

Or **un recul de l'horloge murale pendant que l'horloge monotone avance est une discontinuité
quelle que soit son amplitude**. Un seuil de magnitude laisse passer les petites corrections de
synchronisation — précisément les plus fréquentes. La détection combine désormais le signe et
la magnitude.

## B3 — La borne inférieure ignore l'inconnu, et c'est ce qui la rend concluante

Ce qui n'est pas observable n'est pas compté — donc la latence réelle ne peut qu'être
supérieure. C'est cette asymétrie qui permet à un verdict négatif d'être concluant sans
campagne d'exécution : si la borne inférieure dépasse déjà l'horizon, la compléter ne peut
qu'aggraver le constat.

> **Correction apportée par Q57/Q58 (ADR-168).** La première version de
> `observable_lower_bound_ns` **additionnait les intervalles**. Or `submit→ACK` contient déjà
> le traitement courtier : les sommer produisait un total supérieur à la durée réellement
> vécue — une « borne inférieure » qui n'en était plus une. La borne se construit désormais à
> partir des **frontières** du chemin critique (`LatencyPath`), et `LatencyObservation` refuse
> de se construire si deux de ses intervalles recouvrent le même mécanisme. Voir
> `Q57-Q58-contrat-observabilite.md`, partie C.

## B4 — Ce que le module refuse

- une durée locale mesurée à l'horloge murale (durée négative → erreur explicite) ;
- un agrégat sans liste de composantes ;
- une composante non identifiable portant une valeur ;
- un événement créateur d'ordre non persisté durablement ;
- un probe capable de créer un ordre réel sans budget ni coupe-circuit — **la journalisation
  passive, elle, démarre sans condition**.

## B5 — Ce qu'il ne fait pas

Il ne se branche à aucun connecteur courtier : les points d'appel `SUBMIT_STARTED`,
`SUBMIT_RETURNED`, `BROKER_ACK`, `BROKER_REJECT`, `CANCEL_REQUESTED`, `CANCEL_ACK` sont à câbler
dans l'adaptateur d'exécution. Il ne mesure pas non plus la charge système — profondeur de file,
retard de boucle d'événements, charge processeur — dont les champs existent et attendent d'être
alimentés par l'hôte réel.

---

## Ce qui démarre maintenant

**Q51-A** ne dépend de rien : ni Q42, ni Q52, ni un modèle. Journaliser cotations, évaluations,
charge, connexion, rafales et horloges permet déjà de mesurer trois des composantes —
`provider → réception`, attente de cadence, temps de calcul — donc de produire une première
borne inférieure.

Combinée à Q50, elle donne les deux flux réels du projet : **Q50 mesure le marché, Q51 mesure la
capacité à agir dessus.** Leur intersection est le premier domaine de recherche qui ne repose
plus sur des hypothèses synthétiques.
