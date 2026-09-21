# Analyseur Or Live — XAU/USD

Un analyseur de marche **en direct** sur l'or, deployable sur Vercel. Il se connecte a
votre compte cTrader, lit le flux de cotation de votre broker en continu, et vous dit
en francais **ce qu'il voit** : tendance, structure, momentum, niveaux — puis il signale
chaque opportunite d'achat ou de vente des qu'un setup se valide.

L'analyseur est **en lecture seule**. Il ne passe aucun ordre, ne modifie aucune position :
il lit, il analyse, il vous previent. La decision de trader reste la votre.

---

## Ce qu'il fait

**Lecture de marche continue.** Le panneau « Ce que je vois en direct » traduit l'etat
technique en phrases : *« Tendance H1 haussiere, le prix evolue au-dessus de l'EMA200
(3 412,50 $). Repli en cours vers l'EMA20 sur M15, RSI refroidi a 46 sans rupture.
Liquidite non prise sur le plus haut de la seance asiatique. »*

**Cinq strategies evaluees a chaque tick**, avec pour chacune le detail de ce qui est
reuni et de ce qui manque :

| Strategie | Famille | Principe |
|---|---|---|
| Pullback de tendance | Suivi de tendance | Repli vers l'EMA20/50 ou la zone Fibonacci 38-62 % dans le sens de la tendance superieure, entree sur la bougie de reprise |
| Cassure de range + retest | Cassure | Compression (Bollinger resserrees) → cassure franche → entree sur le **retest tenu**, pas sur la cassure |
| Prise de liquidite | Retournement | Meche au-dela d'un plus haut/bas de reference (veille, jour, seance asiatique) puis retour sous le niveau |
| Retour a la moyenne | Retournement | Exces de Bollinger + RSI + divergence, **uniquement** quand le contexte superieur est plat |
| Range d'ouverture | Seance | Cassure des 30 premieres minutes de Londres (07:00 UTC) ou New York (13:30 UTC) |

**Signaux complets.** Chaque signal porte l'entree, le stop (structurel, avec plancher
en ATR), trois objectifs, le rapport rendement/risque, et la **taille de position calculee
depuis votre risque accepte** — pas l'inverse. Les signaux sont ensuite suivis tick par
tick jusqu'au stop ou a l'objectif, avec statistiques de reussite.

**Filtres de diffusion.** Aucun signal n'est emis si le spread est trop large, si la
volatilite est insuffisante, hors session, ou si le score du setup est sous votre seuil.
L'interface dit toujours *pourquoi* elle se tait.

---

## Deploiement sur Vercel

### 1. Creer l'application cTrader

Sur [openapi.ctrader.com](https://openapi.ctrader.com), espace developpeur → Applications :
creez une application et notez le **Client ID** et le **Client Secret**.

Dans la fiche de l'application, ajoutez l'URI de redirection **exactement** telle qu'elle
sera en production :

```
https://<votre-domaine>.vercel.app/api/ctrader/callback
```

cTrader compare cette URI caractere pour caractere — une barre oblique en trop et
l'autorisation est refusee.

### 2. Deployer

Ce dossier est un projet autonome. Sur Vercel, a la creation du projet, reglez
**Root Directory** sur `gold-live-analyzer`. Le framework (Next.js) est detecte seul.

### 3. Variables d'environnement

Dans Vercel → Settings → Environment Variables :

| Variable | Obligatoire | Role |
|---|---|---|
| `CTRADER_CLIENT_ID` | oui | Identifiant de votre application cTrader |
| `CTRADER_CLIENT_SECRET` | oui | Secret de l'application — **ne quitte jamais le serveur** |
| `CTRADER_REDIRECT_URI` | recommande | URI de redirection figee ; sans elle, elle est deduite de la requete |
| `GOLD_SYMBOL` | non | Forcer le symbole si votre broker le nomme `XAUUSD.m`, `GOLD#`, etc. |

Redeployez apres avoir ajoute les variables.

### 4. Connecter le compte

Ouvrez l'application, panneau **Connexion cTrader** → « Connecter mon compte reel ».
Vous etes redirige vers cTrader, vous autorisez, vous revenez. Choisissez ensuite le
compte a analyser dans la liste : le flux demarre immediatement.

---

## En local

```bash
cd gold-live-analyzer
npm install
cp .env.example .env.local     # renseignez CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET
npm run dev
```

Ajoutez `http://localhost:3000/api/ctrader/callback` aux URI de redirection de votre
application cTrader pour pouvoir vous connecter en local.

```bash
npm test         # 25 tests sur les indicateurs, la structure, le risque et le moteur
npm run build    # build de production
npx tsc --noEmit # verification de types
```

---

## Architecture

```
Navigateur (moteur d'analyse)
    │  EventSource  /api/ctrader/stream   ← ticks + bougies live
    │  fetch        /api/ctrader/history  ← amorcage M1/M5/M15/H1/H4
    ▼
Routes Vercel (Node)  ← detiennent clientSecret + tokens OAuth
    │  WebSocket JSON  wss://live.ctraderapi.com:5036
    ▼
Proxy cTrader Open API → votre broker
```

**Pourquoi le pont est-il cote serveur ?** L'authentification applicative cTrader
(`ProtoOAApplicationAuthReq`, payload 2100) exige le `clientSecret`. Si le navigateur
ouvrait lui-meme la WebSocket, le secret serait expose a quiconque ouvre l'inspecteur.
Le pont serveur-a-serveur le garde confine : le navigateur ne recoit que des cotations.
Les tokens OAuth vivent dans un cookie `httpOnly` et ne sont jamais lisibles en JavaScript.

**Pourquoi du SSE et pas une WebSocket vers le navigateur ?** Les fonctions Vercel ont une
duree d'execution bornee. La route de flux se coupe proprement avant la limite et emet un
evenement de rotation ; `EventSource` se reconnecte tout seul. L'etat du moteur (bougies,
signaux, statistiques) vit dans la page et survit aux rotations — la coupure est invisible.

**Ou tourne l'analyse ?** Dans votre navigateur, sur les donnees recues. Les indicateurs,
la structure, les strategies et le calcul de risque sont du TypeScript pur sans dependance
(`src/lib/`), ce qui les rend testables isolement — c'est l'objet de `tests/engine.test.ts`.

### Structure du code

```
src/lib/ctrader/   protocole Open API (payload types, decodage), session WebSocket, OAuth
src/lib/market/    types, indicateurs, agregation de bougies, structure, niveaux, sessions
src/lib/strategies/ les cinq strategies + helpers communs
src/lib/engine/    analyseur multi-timeframe, risque, carnet de signaux, redaction francaise
src/app/api/       routes serveur (OAuth, comptes, historique, flux SSE, source de secours)
src/components/    interface (graphique canvas, panneaux, reglages)
```

---

## Details techniques utiles

**Prix.** Le protocole cTrader transmet les prix en entiers au 1/100 000e d'unite, et les
bougies en deltas depuis le plus bas (`open = low + deltaOpen`). Le decodage est centralise
dans `src/lib/ctrader/protocol.ts` et couvert par les tests.

**Detection des swings.** La comparaison est stricte a gauche et large a droite. Sans ce
detail, les sommets egaux — doubles sommets, plateaux de liquidite, exactement les zones
qui comptent sur l'or — ne produiraient aucun swing detecte.

**Taille de position.** `lots = risque accepte / (distance au stop x 100)`, le contrat
standard XAU/USD valant 100 onces (1 $ de mouvement = 100 $ par lot). Le stop a un plancher
en ATR pour ne pas se faire sortir par le bruit.

**Source de secours.** Sans compte connecte, l'application interroge une cotation publique
de reference pour que l'interface et le moteur tournent quand meme. Ces donnees sont
**indicatives** (pas de bid/ask reel, pas le flux de votre broker) et l'interface l'indique
clairement. L'analyse qui compte est celle sur le flux cTrader.

---

## Limites — a lire

- Les signaux sont le resultat de **regles techniques automatiques** appliquees aux cours.
  Ce ne sont pas des conseils en investissement et rien ne garantit leur resultat.
- L'analyse ne connait **que le prix**. Elle ignore le calendrier economique, les
  declarations de banques centrales et les chocs geopolitiques — qui sont precisement ce
  qui fait bouger l'or le plus violemment. Un signal techniquement parfait peut etre balaye
  par une publication macro.
- Les statistiques affichees portent sur les signaux emis pendant que la page est ouverte.
  Ce n'est pas un backtest, et ce n'est pas une mesure de performance future.
- Le pont de flux est borne par la duree d'execution des fonctions Vercel. La reconnexion
  est automatique, mais une poignee de ticks peut manquer a chaque rotation.
- Testez sur un compte demo avant d'engager de l'argent reel.
