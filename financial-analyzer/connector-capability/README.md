# Fiches de capacité — Q57 et Q58

Deux fiches, remplies **uniquement avec ce qui est démontré**. Elles ne décrivent pas la
performance de l'infrastructure : elles fixent ce qui peut être *revendiqué* à son sujet.

| Fichier | Question | Objet |
| --- | --- | --- |
| `host-clock-capability.json` | Q57 | ce que les horloges de l'hôte permettent d'affirmer |
| `broker-connector-capability.json` | Q58 | ce que chaque événement du connecteur signifie réellement |

Les deux sont livrées **vides**, tout déclaré inconnu. C'est volontaire :

> une fiche déclarant tout inconnu produit des bornes honnêtes ;
> une supposition produit des verdicts faux.

Leur croisement (`feasibility.observability.build_matrix`) donne la **seule décomposition
que Q19 est autorisé à utiliser**. Aucune métrique de latence ne peut être plus fine.

## Remplir la fiche Q57

Par instrumentation de l'hôte **qui exécutera réellement l'analyseur** — pas de la machine
de développement. Une VM et un ordinateur portable ne se comportent pas comme un serveur.

Les champs qui décident du statut :

- `monotonic_resolution_ns` — plus petit écart **non nul réellement observé**, pas la
  précision affichée par l'API ;
- `wall_mono_samples` — nombre de lectures appariées ; sans elles, le couple n'est pas
  instrumenté et Q57 n'est pas résolue ;
- `measured_uncertainty_ns` — mesurée, jamais recopiée de la documentation du serveur de
  synchronisation ;
- `intersystem_uncertainty_declared_unknown` — à mettre à `true` seulement après avoir
  cherché. Ne pas avoir mesuré et avoir constaté qu'on ne peut pas mesurer ne se valent
  pas, et c'est cette distinction qui décide si Q57 est résolue.

## Remplir la fiche Q58

Chaque entrée de `events` doit porter un `evidence_id`. Le nom d'un rappel n'a aucune
valeur probatoire : `on_order_accepted()` ne démontre pas qu'un ordre est actif.

Types de preuve, du plus fort au plus faible :

```
OFFICIAL_DOCUMENTATION · API_SCHEMA · BROKER_SUPPORT_CONFIRMATION
CONTROLLED_TEST · PACKET_TRACE · CONNECTOR_SOURCE_CODE
OBSERVATIONAL_INFERENCE   ← ne suffit jamais seule
```

Une grande partie de la fiche se remplit **sans émettre le moindre ordre** : lecture de la
documentation et du code du connecteur, observation des rappels de connexion,
instrumentation, chronologie d'une session sans trading. Le reste attend Q42.

Déclarer un événement inobservable **est** une qualification valide. C'est l'ambiguïté non
documentée qui bloque, pas l'ignorance déclarée.

## Versionnement

Toute mise à jour du connecteur crée une nouvelle qualification : un changement de SDK peut
modifier rappels, tamponnage, ordre des événements, horodatages et reprises. Les
conclusions précédentes ne sont **pas** supposées valables — `invalidated_by()` le vérifie.
