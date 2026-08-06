# 02 — Le socle de données (XAU/USD spot)

> Statut : **figé** (étape 2 de la spécification).
> Couvre les étages 1 et 2 du pipeline (`01-architecture.md` §3) : flux de données,
> normalisation et contrôle qualité.

## 1. Ce que « OTC » implique concrètement

Le XAU/USD spot n'a **pas de tape consolidée**. Il n'existe donc aucun « vrai prix » de
référence contre lequel valider un flux. Trois conséquences structurantes :

1. le prix de référence est une **construction du système**, pas une donnée reçue — il doit
   être défini, versionné et rejouable comme n'importe quel autre calcul ;
2. la détection d'anomalie est nécessairement **croisée** : un fournisseur seul est
   invérifiable, deux fournisseurs qui divergent ne disent pas lequel a tort ;
3. l'absence de volume échangé consolidé prive le système d'un capteur de liquidité standard.
   Le **spread** et la **dispersion inter-fournisseurs** en tiennent lieu, ce qui les rend
   doublement critiques : ce sont à la fois des indicateurs de qualité et des features de
   marché.

## 2. Le tick canonique

Toute cotation entrante est normalisée dans cet enregistrement, append-only, jamais réécrit :

```
Quote {
  provider_id            identifiant du fournisseur
  symbol                 XAUUSD
  bid, ask               niveaux
  bid_size, ask_size     tailles, si le fournisseur les transmet
  depth[]                profondeur par niveau, si disponible
  last                   dernier prix imprimé par le fournisseur (indicatif, non consolidé)
  t_provider             horodatage annoncé par le fournisseur
  t_received             horodatage local de réception  ← seule base temporelle de confiance
  seq                    numéro de séquence du fournisseur, si fourni
  dedup_key              (provider_id, seq) ou empreinte du contenu à défaut
  connection_epoch       identifiant de la session de connexion en cours
  feed_version           version du connecteur ayant produit l'enregistrement
}
```

Champs dérivés, calculés et stockés (jamais recalculés à la volée au moment de décider) :

```
mid        = (bid + ask) / 2
spread     = ask - bid
latency    = t_received - t_provider - offset_estimé(provider)
```

`connection_epoch` existe pour une raison précise : après une reconnexion, beaucoup de
fournisseurs rejouent une file d'attente de cotations périmées. Sans marqueur d'époque, ce
replay est indiscernable d'une activité normale et empoisonne la médiane.

## 3. Discipline d'horloge

**`t_provider` n'est jamais une base temporelle de confiance.** Les horloges des fournisseurs
dérivent, certains horodatent à l'émission, d'autres à la mise en file. Règles :

- l'**instant de disponibilité** au sens de l'invariant I1 (bitemporalité, ADR-004) est
  `t_received`, jamais `t_provider`. Une donnée n'existe pour le système qu'à partir du moment
  où il l'a reçue ;
- `t_provider` sert uniquement à **mesurer la latence** et à détecter la désynchronisation :
  on estime en continu un décalage par fournisseur (médiane glissante de `t_received - t_provider`),
  et on surveille sa dérive ;
- les mesures de durée s'appuient sur une horloge monotone locale ; l'horloge murale, disciplinée
  NTP, ne sert qu'à l'enregistrement ;
- une dérive d'horloge fournisseur au-delà d'un seuil est une **pathologie à part entière**
  (§5), pas un détail d'ingénierie : elle fausse silencieusement tout classement chronologique
  des événements.

## 4. Le prix de référence

### 4.1 Quorum

Une médiane sur deux fournisseurs est une moyenne, et une moyenne ne permet aucune détection
d'aberration. Le système exige donc un **quorum minimal de 3 fournisseurs sains** pour
produire un prix de référence exploitable.

| Fournisseurs sains | État | Conséquence |
| --- | --- | --- |
| ≥ 3 | nominal | prix de référence produit, décision autorisée |
| 2 | dégradé | prix produit et affiché, **décision interdite** (aucune détection d'aberration possible) |
| ≤ 1 | aveugle | pas de prix de référence, suivi des positions ouvertes en mode conservateur |

### 4.2 Construction

Le prix de référence est une **médiane des `mid`**, et non des `last` : en OTC, `last` est
propre au broker et n'est pas comparable d'un fournisseur à l'autre.

Sont exclus du calcul, avant la médiane :

- tout fournisseur dont la dernière cotation est plus ancienne que la **fenêtre de fraîcheur**
  applicable à la session en cours (§6) ;
- tout fournisseur en quarantaine (§5) ;
- tout fournisseur dans sa période de carence post-reconnexion.

La médiane est calculée sur un **instantané aligné** : l'état de chaque fournisseur tel que
connu à l'instant `t`, et non « le dernier tick de chacun quel que soit son âge ». Sans cet
alignement, on calcule la médiane de prix appartenant à des instants différents — un biais qui
grandit avec la dispersion des latences.

Grandeurs publiées à chaque instant d'évaluation :

```
ref_mid              médiane des mid sains
ref_spread           médiane des spreads sains
dispersion           max(mid) - min(mid) sur les fournisseurs sains
dispersion_robuste   MAD des mid sains (résistante à un fournisseur aberrant)
n_sains              taille du quorum effectif
velocity             dérivée de ref_mid, jamais d'un flux individuel
```

`velocity` (la « vitesse de déplacement » de l'étape 2) est calculée **sur la série de
référence**, jamais sur un flux isolé : un tick aberrant unique produit sinon une accélération
fictive, qui déclencherait exactement les décisions qu'on cherche à éviter.

## 5. Pathologies de flux

Le point commun de ces défauts : la détection naïve échoue sur chacun.

| Pathologie | Détection naïve | Pourquoi elle échoue | Détection retenue |
| --- | --- | --- | --- |
| **Flux en retard** | latence > seuil fixe | la latence normale varie par fournisseur et par session | latence vs quantile glissant propre au fournisseur |
| **Flux gelé** | absence de tick | un flux peut ticker en répétant la même cotation | cotation inchangée alors que `ref_mid` s'est déplacé de plus de N fois la dispersion normale |
| **Replay post-reconnexion** | aucune | les cotations rejouées ressemblent à du trafic normal | changement de `connection_epoch` → carence obligatoire avant réintégration au quorum |
| **Biais persistant** | écart ponctuel | un décalage stable ne déclenche aucune alerte instantanée | déviation médiane signée non nulle sur fenêtre longue → recalibrage ou exclusion |
| **Horloge désynchronisée** | confiance en `t_provider` | l'erreur est invisible dans les prix | dérive du décalage estimé au-delà du seuil |
| **Spread anormal** | seuil absolu | le spread normal varie d'un ordre de grandeur selon l'heure | rang quantile conditionnel (§6) |
| **Divergence idiosyncratique** | écart brut | confond fournisseur défaillant et marché tendu | déviation d'**un** fournisseur vs médiane robuste |
| **Divergence systémique** | idem | ce n'est pas un défaut de données | dispersion **globale** élevée → signal de stress, pas mise en quarantaine |
| **Sous-quorum** | aucune | le système continue de produire un prix qui semble valide | comptage explicite des fournisseurs sains (§4.1) |

Distinction essentielle entre les deux dernières lignes : **un fournisseur qui s'écarte est un
problème de données ; tous les fournisseurs qui s'écartent en même temps sont un état de
marché.** Le premier cas met un flux en quarantaine, le second alimente le détecteur de régime
— et conduit tout de même à l'abstention, mais pour une raison différente, qui doit être
tracée comme telle.

## 6. Normalité conditionnelle du spread et de la fraîcheur

Un seuil absolu sur le spread est faux dans les deux sens : trop permissif en séance liquide,
trop strict au rollover quotidien, à l'ouverture du dimanche et sur publication macro. Idem
pour la fraîcheur : quelques secondes sans tick sont une panne en séance européenne et un état
parfaitement normal en creux asiatique.

**Règle : aucun seuil absolu sur le spread ni sur la fraîcheur.** Les deux sont évalués par
rang quantile dans une distribution conditionnelle à `(fournisseur, tranche de session,
régime de volatilité)`, estimée empiriquement sur l'historique du système lui-même.

Tranches de session à distinguer pour le XAU/USD (à confirmer par la mesure) :

- creux asiatique ;
- ouverture de Londres ;
- fixings LBMA (10:30 et 15:00 heure de Londres) — pics de liquidité prévisibles ;
- recouvrement Londres–New York, la fenêtre la plus liquide ;
- rollover quotidien (~21:00–22:00 UTC) — élargissement structurel du spread, à ne jamais
  traiter comme une anomalie ;
- fin de séance new-yorkaise ;
- ouverture du dimanche — gap structurel ;
- marché fermé (week-end, jours fériés du calendrier applicable).

Le **calendrier est une dépendance de premier ordre**, pas un raffinement : sans lui, le gap
du dimanche soir est lu soit comme une anomalie de données, soit — bien pire — comme un
mouvement exploitable.

## 7. Ancrage externe (optionnel, recommandé)

Le spot XAU/USD est OTC, mais sa découverte de prix est largement pilotée par les contrats à
terme COMEX. Comparer `ref_mid` au spot impliqué par le future actif fournit un **ancrage
indépendant du panel de brokers** : si tous les fournisseurs dérivent de concert, seule une
référence extérieure peut le révéler. À traiter comme un capteur de qualité supplémentaire, et
non comme une source de prix pour la décision.

## 8. Contrat de sortie : le verdict qualité

L'étage 2 produit, à chaque instant d'évaluation, un verdict qui **conditionne toute la
chaîne aval** (arête « veto qualité » de `01-architecture.md` §2) :

```
DataQualityVerdict {
  as_of                    instant d'évaluation
  state                    NOMINAL | DEGRADED | BLIND
  n_sains, quorum_atteint
  ref_mid, ref_spread, dispersion, dispersion_robuste, velocity
  spread_rank              rang quantile conditionnel du spread de référence
  providers[] {            état par fournisseur
    id, healthy, reasons[], latency, deviation, quarantined_until
  }
  blocking_reasons[]       vide ⇒ décision autorisée
  session, calendar_state
}
```

`blocking_reasons` non vide ⇒ sortie forcée `NoTrade` à l'étage 9, avec le motif exact
conservé dans l'enregistrement de décision. Motifs bloquants retenus :

1. quorum non atteint ;
2. un ou plusieurs flux en retard au-delà du seuil conditionnel ;
3. divergence inter-fournisseurs anormale (idiosyncratique **ou** systémique) ;
4. spread au-delà de son quantile conditionnel critique ;
5. fournisseur en carence post-reconnexion réduisant le quorum sous 3 ;
6. dérive d'horloge non résolue ;
7. marché fermé ou fenêtre de rollover ;
8. verdict lui-même périmé — un verdict qualité a une durée de validité, et un verdict trop
   ancien est aussi bloquant qu'un flux trop ancien.

Les points 1 à 4 formalisent les quatre interdits énoncés à l'étape 2. Les points 5 à 8 sont
des ajouts : ce sont des cas où le système croit ses données valides alors qu'elles ne le
sont pas.

## 9. À calibrer empiriquement — aucun seuil inventé

Les valeurs suivantes ne sont **pas** fixées dans cette spécification. Les inscrire ici
« au jugé » reviendrait à faire exactement ce que l'ADR-002 interdit au LLM : produire des
nombres plausibles non calculés. Elles seront estimées sur les données réelles du panel, puis
versionnées comme artefacts (I7) :

- distribution du spread par fournisseur et par tranche de session ;
- distribution de la latence par fournisseur ;
- dispersion inter-fournisseurs normale, par tranche de session ;
- durée de la carence post-reconnexion ;
- durée de validité d'un `DataQualityVerdict` ;
- quantiles retenus comme seuils de blocage et taux de fausse alarme associé.

Un point de méthode : ces seuils arbitrent entre **abstentions inutiles** et **décisions sur
données corrompues**. Ils doivent donc être réglés à partir d'un objectif explicite de taux de
fausse alarme, pas à l'intuition.

## 10. Questions ouvertes

- **Q5** — liste effective des fournisseurs et modalités d'accès (WebSocket, FIX, REST) ;
  le quorum de 3 n'est atteignable que si au moins 3 flux indépendants existent. Deux flux
  revendus par le même agrégateur ne comptent que pour **un** : l'indépendance des sources est
  une condition de validité, pas un détail contractuel.
- **Q6** — profondeur de carnet réellement disponible chez chacun (souvent absente en retail),
  ce qui détermine si la liquidité peut être mesurée autrement que par le spread.
- **Q7** — horizon de conservation des ticks bruts : il conditionne la capacité à rejouer une
  décision ancienne (I2) et le volume de stockage.
- **Q8** — accès ou non à une référence future COMEX pour l'ancrage du §7.
