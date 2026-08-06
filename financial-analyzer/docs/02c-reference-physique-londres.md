# 02c — Référence physique et marché londonien

> Statut : **figé** (étape 2.3 de la spécification).
> Troisième composante du socle, après le spot OTC (`02-socle-donnees.md`) et le listé
> (`02b-futures-comex.md`).

## 1. Ce qu'est réellement le marché londonien

Point de vocabulaire qui n'est pas anodin pour l'architecture : **le « spot XAU/USD » de
l'étape 2.1 *est* le marché londonien.** Ce que cotent les brokers est du *loco London* — de
l'or détenu dans les coffres londoniens, sous forme de barres de bonne livraison, échangé de
gré à gré selon les conventions de place.

Trois implications :

- **Londres n'est pas une source de prix concurrente du spot, c'en est le référentiel.** Un
  écart durable entre le prix de référence construit en 2.1 et la réalité londonienne n'est
  pas une opportunité d'arbitrage : c'est le signe que le panel de brokers dérive.
- Le règlement loco London suit une convention à quelques jours ouvrés. Le « spot » porte donc
  une composante de financement implicite, ce qui interdit de traiter la base
  spot/futures comme un pur coût de portage sans en tenir compte.
- **Non alloué et alloué ne sont pas la même marchandise.** Le non alloué est une créance sur
  une banque de métal ; l'alloué porte sur des barres identifiées. En régime normal l'écart
  est négligeable ; sous tension, il s'ouvre. C'est le capteur de tension physique le plus
  profond dont dispose le système, et le plus difficile à obtenir.

## 2. Le benchmark LBMA : un processus, pas un point de données

Administré par ICE Benchmark Administration, fixé deux fois par jour à 10 h 30 et 15 h, heure
de Londres.

### 2.1 Ce que l'enchère révèle, au-delà du prix

Le mécanisme est une **enchère électronique par tours** : un prix d'ouverture est proposé, les
participants déclarent leurs volumes acheteurs et vendeurs, et le prix n'est arrêté que lorsque
le déséquilibre passe sous une tolérance. Sinon un nouveau tour s'ouvre à un prix ajusté.

Le prix final est donc la partie la moins informative de l'événement. Sont conservés :

```
FixingEvent {
  session                   AM | PM
  auction_start             heure d'ouverture (connue à l'avance)
  auction_end               heure de résolution (variable)
  publication_time          instant de disponibilité effective  ← référence I1
  rounds_count              nombre de tours nécessaires
  imbalance_path[]          déséquilibre déclaré à chaque tour, avec son signe
  final_price
  currency
  licence_class             classe de redistribution (§8)
}
```

**Un nombre de tours élevé signale un désaccord marqué entre participants** — donc une
information sur la conviction du marché physique, indisponible ailleurs. Un fixing résolu en un
tour et un fixing résolu en huit ne décrivent pas le même état de marché, alors qu'ils peuvent
produire le même prix.

### 2.2 L'heure de publication n'est pas l'heure de fixation

Piège direct sur I1 : l'enchère **commence** à une heure connue mais se **résout** à une heure
variable. Utiliser « le fixing de 10 h 30 » comme s'il était connu à 10 h 30 fait entrer dans
le système une information qui n'existait pas encore — parfois plusieurs minutes plus tôt que
sa disponibilité réelle, ce qui est considérable à l'échelle des mouvements de la fenêtre.

**Règle** : l'instant de disponibilité d'un fixing est `publication_time`, jamais l'heure
nominale de l'enchère. Conforme à l'ADR-008.

### 2.3 Le fixing comme événement de calendrier

C'est l'un des rares événements structurels de l'or **prévisibles à la seconde près**. Une
partie significative du flux (fonds indiciels, raffineurs, producteurs couvrant leur
production, institutionnels indexés) s'exécute *au* fixing, ce qui crée une pression
mécanique dans la fenêtre qui le précède.

Le système en tire un état de session explicite — `PRE_FIXING`, `EN_ENCHÈRE`, `POST_FIXING` —
qui alimente les distributions conditionnelles de l'ADR-007 : spread, fraîcheur et volatilité
n'ont pas la même normalité dans ces trois états qu'en séance ordinaire.

**Mise en garde à inscrire dès maintenant** : cet effet est ancien, documenté, connu de tous
les participants, et a fait l'objet d'enquêtes réglementaires par le passé. Il doit être traité
comme un **effet de calendrier à modéliser**, jamais comme un gisement de rendement acquis.
Toute stratégie qui en dépendrait devra être justifiée par la mesure de l'étage 12, régime par
régime, avec le même niveau d'exigence que n'importe quel autre signal — et probablement
davantage, la concurrence sur cette fenêtre étant maximale.

### 2.4 Ce que le fixing n'est pas

- **Ce n'est pas un prix traitable** pour la majorité des participants. Construire une décision
  qui suppose une exécution à ce prix est une erreur de modèle.
- **Ce n'est pas un point d'une série de prix continue.** L'agréger avec des ticks pour
  calculer un rendement ou une volatilité mélange deux objets de nature différente. Le fixing
  est conservé comme série propre, à sa fréquence propre.

## 3. Le pont entre marchés : mesurer l'écart avec le bon instrument

L'étape 2.3 demande de suivre « les éventuels écarts entre spot, Londres et COMEX ». La
soustraction naïve de deux prix ne mesure rien d'exploitable : elle mélange coût de portage,
décalage temporel et bruit de cotation.

L'écart entre le listé et le physique londonien a un **prix coté** : celui de l'échange
futures contre physique, qui permet de convertir une position à terme en métal loco London.
C'est cet écart, et non une différence de prix brute, qui constitue le capteur.

Son intérêt : en régime normal il reflète le coût de portage et évolue lentement ; lorsque la
logistique physique se grippe — transport, raffinage, disponibilité des barres au bon
format — il se disloque violemment. Un épisode de ce type s'est produit lors des perturbations
logistiques de 2020, et c'est le signal le plus net qu'un système puisse capter d'une tension
physique réelle, par opposition à un simple mouvement directionnel.

### 3.1 Le résidu de cohérence

Plutôt que de surveiller trois prix séparément, le système maintient **un résidu unique** :

```
résidu = prix_référence_spot − prix_listé_traduit_par_la_base
```

évalué avec les fixings comme troisième point d'ancrage aux instants où ils existent.

Ce résidu a une distribution normale mesurable, conditionnelle à la session. Sa sortie de
plage est traitée exactement selon la logique de l'ADR-009 :

- **un seul marché s'écarte** → problème de données ou de connectivité sur ce marché →
  quarantaine de la source, motif technique ;
- **les trois se disloquent ensemble** → tension réelle → aucune quarantaine, signal transmis
  au détecteur de régime, et abstention pour motif de marché.

Cette distinction n'est pas une subtilité : elle sépare le cas où il faut réparer une
connexion du cas où il faut réduire l'exposition.

## 4. Capteurs de tension physique

| Capteur | Ce qu'il révèle | Fréquence / latence réelle |
| --- | --- | --- |
| Écart futures / physique londonien | tension logistique et de disponibilité | intraday, si accessible |
| Taux de prêt du métal (déduits de la courbe à terme) | rareté du métal empruntable ; historiquement, des niveaux anormaux signalent une tension | quotidienne |
| Écart alloué / non alloué | défiance sur le risque de contrepartie bullion | rare, difficile d'accès |
| Stocks COMEX, part réellement livrable | couverture des positions ouvertes par du métal disponible | quotidienne, différée |
| Détentions des véhicules indiciels | flux d'investissement financier | quotidienne, différée |
| Détentions des coffres londoniens | stock physique de place | mensuelle, latence importante |

La colonne de droite est la plus importante de ce tableau. **Ces capteurs ne partagent ni
fréquence ni latence**, et c'est ce qui les rend dangereux au montage.

## 5. Primes et décotes régionales

Écart entre le prix local et le loco London, sur les grandes places de demande physique. Une
prime durable signale une demande physique excédant l'offre locale ; une décote, l'inverse.

Ces séries sont **quotidiennes au mieux**, souvent hebdomadaires ou mensuelles pour les
données douanières et de flux, avec des latences de publication allant de quelques heures à
plusieurs semaines, et des **révisions fréquentes**.

Elles constituent un **contexte de régime**, pas un signal d'entrée. Aucune décision intraday
ne peut légitimement en dépendre — non par prudence, mais parce que leur fréquence rend
l'information déjà incorporée au prix au moment où elle devient disponible.

## 6. La règle qui protège tout : publication contre période de référence

C'est le point critique de cette étape.

Ces séries basse fréquence portent **deux dates** : la période à laquelle elles se rapportent,
et le moment où elles ont été publiées. L'écart entre les deux va de quelques minutes à
plusieurs semaines.

Le mode d'échec est mécanique : on prolonge une valeur mensuelle sur une série intraday, en
la faisant commencer à sa **période de référence** plutôt qu'à sa **publication**. Le backtest
utilise alors, pendant des semaines, un chiffre que personne ne connaissait. Le résultat
s'améliore, et rien ne le signale.

**Règles :**

1. toute série basse fréquence est prolongée à partir de sa **date de publication**, jamais de
   sa période de référence ;
2. les **révisions sont conservées**, pas écrasées : la valeur connue à l'instant `t` est celle
   publiée à `t`, même si elle a été corrigée depuis. Une décision passée se rejoue avec les
   chiffres faux de l'époque — c'est la seule reconstitution honnête ;
3. toute feature dérivée de ces séries hérite de leur latence et la déclare : un agent doit
   savoir qu'il travaille sur une information vieille de trois semaines.

Cette règle prolonge l'ADR-004 et l'ADR-012 : après la donnée, puis la transformation, c'est
ici la **connaissance qu'on en avait** qui doit être datée.

## 7. Rôle dans le pipeline : conditionner et bloquer, jamais déclencher

L'étape 2.3 le formule bien : ces données ne déclenchent pas d'exécution rapide. Cette
restriction est traduite en contrainte structurelle plutôt qu'en intention.

| Autorisé | Interdit |
| --- | --- |
| conditionner les scénarios (étage 6) | produire un signal d'entrée |
| pondérer la fusion probabiliste selon le régime physique (étage 7) | déterminer un niveau d'entrée, de stop ou de cible |
| durcir les contraintes du moteur de risque (étage 8) | augmenter une taille de position |
| ajouter un motif de blocage au verdict qualité | lever un motif de blocage existant |
| alimenter l'explication et la détection de contradictions | — |

La dernière ligne de la colonne de droite est une application de la monotonie des vetos (I5) :
une prime physique favorable ne peut pas autoriser un trade que le reste du système refuse.

## 8. Licence et frontière de redistribution

L'étape 2.3 signale à juste titre que l'usage du benchmark est soumis à licence. La
conséquence architecturale dépasse la question contractuelle.

Le système comporte une couche qui **produit du texte destiné à être lu** — les explications de
l'étage 12 et de la frontière IA (ADR-002). Rien n'empêche structurellement une valeur sous
licence de se retrouver citée dans une explication publiée. C'est une fuite de redistribution,
et elle serait involontaire.

**Règle** : chaque source porte une classe de redistribution, transportée avec la donnée
jusqu'à la sortie. La frontière de sortie filtre les valeurs non redistribuables — elles
peuvent être *utilisées* dans le calcul et *citées en interne* dans l'enregistrement de
décision, mais pas apparaître dans une sortie publiable. Ce filtre s'ajoute au contrôle
d'ancrage numérique de l'ADR-002, au même endroit de la chaîne.

## 9. À vérifier avant implémentation

Aucune de ces valeurs n'est fixée ici de mémoire :

- conditions exactes de licence pour l'usage, le stockage et la redistribution du benchmark,
  selon l'usage visé (interne, produit, affichage) ;
- disponibilité réelle des données de déroulement de l'enchère (tours, déséquilibres) et non
  seulement du prix final ;
- convention de règlement loco London en vigueur ;
- source actuellement publiée pour la courbe à terme et les taux de prêt du métal — la
  référence historiquement utilisée a été discontinuée et remplacée ; il faut identifier ce qui
  est publié aujourd'hui, à quelle fréquence, et sous quelle licence ;
- calendrier des jours de fixation, et comportement les jours fériés londoniens.

## 10. Questions ouvertes

- **Q12** — quelles sources physiques sont réellement accessibles dans le budget du projet ?
  Le tableau du §4 va de la donnée quasi publique à la donnée institutionnelle coûteuse. Un
  système qui n'a accès qu'aux stocks publics et aux détentions indicielles reste viable, mais
  son capteur de tension physique est nettement plus grossier — ce qui doit être **su et
  déclaré**, pas découvert plus tard.
- **Q13** — l'écart futures/physique est-il obtenable en continu, ou seulement par
  reconstruction à partir des prix ? La réponse détermine si la tension physique est un
  capteur intraday ou seulement quotidien.
- **Q14** — les explications produites par le système sont-elles destinées à un usage
  strictement personnel, ou seront-elles diffusées ? La réponse change la nature de la
  contrainte du §8 : filtre de confort ou obligation contractuelle.
