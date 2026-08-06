# Dossier de preuve du calendrier

Chaque assertion du calendrier doit pouvoir être remontée jusqu'à un document conservé ici.
**Une règle sans preuve vérifiable n'est pas normative** — et le compilateur refuse de
produire un calendrier dont une assertion critique n'en a pas.

## Arborescence

| Dossier | Contenu | Source normative pour |
| --- | --- | --- |
| `exchange/` | horaires officiels de la place, avis de marché, spécification de contrat | horaires du marché listé |
| `broker/` | spécification du symbole sur le compte réel, horaires serveur, conditions | disponibilité du symbole à l'exécution |
| `provider/` | documentation du flux, statut de service, maintenances annoncées | diffusion des données |
| `holidays/` | calendriers fériés annuels, séances réduites | fermetures exceptionnelles |
| `maintenance/` | annonces de maintenance, courriers, messages de support | interruptions planifiées |
| `overrides/` | corrections manuelles, avec auteur, motif et preuve | événements non documentés ailleurs |

## Contenu attendu par acquisition

```
<dossier>/<source_id>/
├── raw.<ext>          contenu brut, ou capture si le brut n'est pas conservable
├── metadata.json      voir gabarit ci-dessous
├── excerpt.txt        extrait minimal portant l'assertion, avec sa localisation
└── assertions.json    assertions extraites, une par affirmation atomique
```

## Gabarit `metadata.json`

```json
{
  "source_id": "SRC-BROKER-A-XAUUSD-20260807",
  "source_type": "BROKER_SYMBOL_SPEC",
  "source_rank": "NORMATIVE_BROKER_SYMBOL",
  "location": "plateforme > symbole XAUUSD > spécification",
  "retrieved_at": "2026-08-07T00:00:00Z",
  "acquisition_method": "MANUAL_CAPTURE",
  "content_hash": "",
  "market_scope": ["BROKER_A:XAUUSD:RAW"],
  "scope": {
    "broker": "BROKER_A",
    "server": null,
    "account_type": "RAW",
    "symbol": "XAUUSD"
  },
  "mime_type": null,
  "language": null,
  "reviewer": null,
  "note": ""
}
```

Les champs de portée non applicables sont **explicitement nuls**, jamais omis : l'absence
déclarée se distingue de l'oubli, et c'est cette distinction qui empêche d'appliquer une règle
de compte de démonstration à un compte réel.

## Ordre de collecte

**Marché d'exécution XAU/USD** — spécification du symbole sur le compte réel, horaires du
serveur, pauses quotidiennes, calendrier férié, portage et jour multiplié, maintenances
annoncées, historique des changements.

**Marché de détection GC** — horaires officiels de négociation, jours fériés, séances réduites,
pauses, règles du fournisseur de données, interruptions exceptionnelles.

## Ce qui bloque la compilation

1. une assertion **critique** sans instantané de source, sans source normative, ou non revue ;
2. un **conflit normatif ouvert** entre deux sources de même spécificité ;
3. un **fuseau ambigu** ou une **date d'effet inconnue**.

Les types critiques sont : pause quotidienne, jour férié, maintenance, jour de portage
multiplié, heure de rollover, fuseau du serveur.
