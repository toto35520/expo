# Gold Order Flow Engine v0.5 — cBot cTrader

Un score microstructure `[-100, +100]` construit sur le carnet et le flux de ticks, qui
**valide** les entrées et **libère** les sorties — au lieu d'empiler un oscillateur de plus.

---

## 1. Ce que dit vraiment la recherche

> Cont, Kukanov & Stoikov, *The Price Impact of Order Book Events*, arXiv:1011.6402

Sur horizon très court, la variation de prix est approximativement **linéaire en Order Flow
Imbalance**, et le coefficient est **inversement proportionnel à la profondeur** :

```
dP  ≈  beta · OFI / profondeur
```

L'OFI est la **variation** des tailles en file aux meilleures limites entre deux événements
de carnet — **pas** un ratio statique `bid/(bid+ask)` :

```
e_n =  1{Pb_n ≥ Pb_n-1}·qb_n  −  1{Pb_n ≤ Pb_n-1}·qb_n-1
     − 1{Pa_n ≤ Pa_n-1}·qa_n  +  1{Pa_n ≥ Pa_n-1}·qa_n-1
```

Le ratio statique est une quantité différente et plus faible. Ce moteur calcule **les deux**,
pondérés séparément.

## 2. Trois raisons que l'effet publié ne transfère peut-être pas ici

**a) L'échelle.** CKS mesurent l'impact **en ticks**, sur des actions où un tick **est** le
spread. Sur XAUUSD, un spread de 0,9 pip couvre 9 incréments de prix. Le signal doit donc
prédire environ un ordre de grandeur de plus avant de payer l'aller-retour. **C'est le vrai
obstacle, pas la qualité du carnet.**

**b) Le carnet est celui d'un LP, pas du marché.** Une échelle de profondeur CFD montre ce
que les LP de ton courtier acceptent de coter. Un LP long or élargit son ask pour se
délester : l'imbalance y est en partie de la **gestion d'inventaire**, donc le **signe** de
la relation n'a aucune raison de correspondre à la littérature actions.

**c) Ce n'est pas la tape CME.** Pas de côté agresseur, pas de volume exécuté au bid vs à
l'ask, pas de footprint, pas de vrai cumulative delta. Tout ici est **inféré des changements
de cotation**, ce qui est strictement moins d'information.

## 3. Donc le moteur se mesure lui-même

À chaque seconde, il apparie l'OFI normalisé courant avec le **mouvement du mid réalisé sur
l'horizon suivant**. Au résumé de session, il régresse le second sur le premier :

```
--- order flow regression on YOUR feed ---
dMid(pips over 10s) = alpha + beta * (OFI / depth)
n 4182 | beta 0.0412 pips per unit | t 3.71 | R2 0.0033
Round-trip spread is 0.91 pips. At this beta, the signal must reach OFI/depth of 22.09 just to cover it.
VERDICT: beta is positive and significant. Now check the magnitude above:
significance is not the same as clearing the spread.
```

Trois verdicts possibles, écrits par le bot :

| Résultat | Ce que ça veut dire |
|---|---|
| `|t| < 2` | L'effet publié n'apparaît pas sur ce flux. **Ne trade pas ce score.** |
| `beta < 0` significatif | Le flux précède le prix **à l'envers** ici — cohérent avec du skew d'inventaire LP. Il faudrait inverser le signe, et le revérifier sur données fraîches. |
| `beta > 0` significatif | Regarde la magnitude. Significatif ≠ franchit le spread. |

**`Measure only` est activé par défaut.** Le bot score et enregistre sans passer le moindre
ordre. Laisse-le tourner quelques sessions, lis la régression, **puis** décide.

## 4. Les six composantes du score

| Composante | Poids | Signé | Ce qu'elle mesure |
|---|---|---|---|
| Order flow imbalance | 30 | oui | CKS, variation des files, normalisé par la profondeur |
| Depth imbalance | 20 | oui | ratio statique sur les 5 premiers niveaux |
| Microprice | 15 | oui | `(bid·askSize + ask·bidSize)/(total)` vs mid, en unités de spread |
| Direction des ticks | 15 | oui | ratio hausse/baisse sur les 50 derniers ticks |
| Absorption | 10 | oui | flux fort à sens unique **qui ne fait pas bouger le mid** → signal **contre** le flux |
| Qualité du spread | 10 | non | **multiplie** la conviction ; un carnet qui s'élargit n'est pas un signal |

Si le carnet n'est pas disponible, les quatre composantes DOM sont retirées et les poids
renormalisés sur les ticks seuls — le bot le dit et refuse d'entrer (`no depth ladder`).

## 5. Entrée et sortie

```
score ≥ 55  ET  contexte M5 d'accord (EMA + DMI + ADX ≥ 18)
    ↓
ENTRÉE, stop 1,0 × ATR, TP 2,5R

PENDANT LA POSITION
    flux toujours d'accord et près du TP   →  le TP est RETIRÉ, le runner continue
    score s'inverse de −35 contre nous     →  SORTIE immédiate
    hold max 300 s                         →  SORTIE
```

C'est ta deuxième idée, et c'est la meilleure des deux : le flux sert autant à **tenir** qu'à
entrer. Un trade peut dépasser 2,5R tant que le carnet reste du bon côté.

## 6. Installation et compatibilité

1. cTrader → Automate → New cBot → `GoldOrderFlow`, coller, Build.
2. Instance sur **XAUUSD M1**, `Measure only = Oui`.
3. Vérifier dans le journal : `Depth ladder available: N bid levels, M ask levels`.
   Si ça n'apparaît jamais, ton courtier ne diffuse pas de profondeur via l'API et
   **tout le volet DOM est inutilisable** — le bot te le dira au lieu de scorer du vide.

| Si le build échoue sur | Correctif |
|---|---|
| `'MarketDepthEntry' ne contient pas 'Volume'` | remplacer `entry.Volume` par `entry.VolumeInUnits` (2 occurrences dans `OnDepthUpdated`) |
| `'Updated' ne peut pas être utilisé comme méthode` | changer la signature en `private void OnDepthUpdated(object sender, EventArgs e)` |

## 7. Ce qui n'est PAS là-dedans, et pourquoi

**L'arbitrage de latence.** Tu as raison de le sortir du périmètre, et j'ajoute une raison de
plus : même en mesurant un retard réel, le LP applique du *last look*. Il peut rejeter ou
requoter l'ordre précisément dans les cas où ton signal avait raison. L'edge mesuré sur les
graphiques est alors capté par le LP, pas par toi — et le taux de rejet n'apparaît nulle part
dans un backtest.

**Le vrai order flow GC.** C'est le bon projet suivant, et il est séparé : flux CME avec côté
agresseur, footprint, delta cumulé, détection d'icebergs — signal directeur sur GC, exécution
sur XAUUSD. Ça demande un abonnement données et un pont hors cTrader. À faire **après** avoir
lu la régression ci-dessus : si le DOM CFD ne prédit rien, ce sera l'argument le plus net pour
payer le flux institutionnel.
