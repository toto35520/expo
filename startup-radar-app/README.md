# Radar Startups

Ton espace privé pour suivre tes investissements et les startups en forte croissance :

- **Aujourd'hui** : ton brief du jour. Chaque matin, une IA (Claude) lit les dernières nouvelles de tes lignes et de ton radar sur le web, puis rédige 3 à 5 décisions : quoi acheter, combien, quand, et pourquoi. Chaque décision a ses arguments pour, ses risques, un plan d'achat et des liens sources vérifiés (un lien absent de la veille du jour est retiré). La veille complète est consultable.
- **Mon portefeuille** : tes lignes avec les cours du jour, ta plus ou moins-value, la courbe d'évolution, la part de ton patrimoine investie. Import du relevé Trade Republic en CSV.
- **Radar** : 24 startups et véhicules analysés (note sur 30, verdict, risques, comment y investir).
- **Actus & calendrier** : levées de fonds et actualité startups (Crunchbase, Maddyness, FrenchWeb, TechCrunch), IPO à venir.
- **Mes dossiers** : la grille des 8 vérifications avant d'investir dans une startup en crowdequity.

Tout se met à jour automatiquement chaque jour. Si une tâche du matin n'a pas tourné, l'app la rattrape d'elle-même quand tu l'ouvres. Le panneau « Mises à jour automatiques » (en bas de l'onglet Aujourd'hui) montre chaque passage et ce qui ne va pas.

> Ce n'est pas un conseil en investissement. Les recommandations sont produites par une IA à partir de données publiques qui peuvent être incomplètes ou fausses. Décide toujours toi-même.

---

## Mise en ligne sur Vercel (environ 15 minutes)

### 1. Ce qu'il te faut

- Un compte **Vercel** (gratuit) : https://vercel.com/signup
- Une **clé API Anthropic** : https://console.anthropic.com → *API Keys* → *Create Key*. Ajoute un peu de crédit (*Billing*) et fixe une limite de dépense mensuelle.
  Coût indicatif : une analyse par jour avec recherche web, compte **environ 5 à 15 € par mois** selon le nombre de lignes suivies. Pour réduire la facture, mets `CLAUDE_MODEL=claude-sonnet-5-5` (moins cher, un peu moins fin).
- **Node.js 20 ou plus** sur ton ordinateur si tu déploies en ligne de commande.

### 2. Envoyer le projet sur Vercel

**Option A, en ligne de commande (le plus simple avec le zip) :**

```bash
unzip radar-startups.zip
cd radar-startups
npx vercel            # connecte-toi, accepte les réglages proposés
```

**Option B, via GitHub :** crée un dépôt privé, envoie-y le contenu du dossier, puis sur vercel.com : *Add New → Project → Import* ce dépôt.

### 3. Ajouter la base de données (gratuite)

Dans ton projet sur vercel.com : **Storage → Create Database → Upstash (Redis)** → plan gratuit → *Connect* au projet.
Vercel ajoute tout seul les variables `KV_REST_API_URL` et `KV_REST_API_TOKEN`. L'app les reconnaît.

### 4. Ajouter tes variables secrètes

Dans **Settings → Environment Variables**, ajoute :

| Nom | Valeur |
|---|---|
| `APP_PASSWORD` | le mot de passe pour ouvrir ton app (long et unique) |
| `SESSION_SECRET` | une chaîne aléatoire d'au moins 32 caractères |
| `CRON_SECRET` | recommandé : une autre chaîne aléatoire. Vercel l'envoie avec chaque tâche planifiée pour prouver que c'est bien lui |
| `ANTHROPIC_API_KEY` | ta clé API Anthropic |

Pour générer une chaîne aléatoire : `openssl rand -hex 32` dans un terminal.

### 5. Redéployer

**Deployments → ⋯ → Redeploy** (ou `npx vercel --prod`). Ouvre l'adresse de ton projet, entre ton mot de passe : c'est prêt.

Les tâches planifiées sont déclarées dans `vercel.json` et visibles dans **Settings → Cron Jobs** :

| Heure (UTC) | Heure de Paris (été) | Étape |
|---|---|---|
| 3 h | 5 h | cours, taux de change, actus |
| 4 h | 6 h | veille web par l'IA (moins de 200 s) |
| 5 h | 7 h | recommandations argumentées (moins de 240 s) |
| 16 h | 18 h | cours et actus du soir |

Chaque étape tient dans la limite de 300 s des fonctions Vercel. Sur le plan gratuit, Vercel peut lancer une tâche n'importe quand dans l'heure prévue.

---

## Brancher ton compte Trade Republic

Trade Republic n'a **pas d'API officielle**. Les outils non officiels demandent ton numéro de téléphone, ton code PIN et une validation sur ton téléphone à chaque connexion : les stocker sur un serveur exposerait tout ton compte. L'app utilise donc l'**export CSV**, plus sûr :

1. Sur **app.traderepublic.com** depuis un ordinateur : Profil → Relevés / Transactions → exporter en CSV (l'emplacement peut changer selon les versions de Trade Republic).
2. Dans l'app : **Mon portefeuille → Importer depuis Trade Republic** → choisis le fichier.
3. Clique **Actualiser les cours** : les tickers sont retrouvés à partir des codes ISIN.

L'import reconnaît les colonnes en français, anglais ou allemand (date, type, nom, ISIN, quantité, prix, montant). Il additionne les achats et plans d'investissement, retire les ventes et ignore dividendes et virements. Refais un import quand tu achètes : il remplace les lignes importées précédemment, tes lignes ajoutées à la main restent.

Tu peux aussi ajouter une ligne à la main (nom, ticker Yahoo comme `SPCX`, `CBRS` ou `SMT.L`, quantité, montant investi).

---

## Si rien ne se met à jour

Ouvre l'onglet **Aujourd'hui** et descends jusqu'à **Mises à jour automatiques** :

- « ANTHROPIC_API_KEY manquante » : ajoute la clé dans Vercel puis redéploie.
- « Base Upstash non connectée » : ajoute Upstash Redis (étape 3) puis redéploie.
- « Aucune mise à jour automatique reçue » : vérifie **Settings → Cron Jobs** sur vercel.com. Les tâches ne tournent que sur le déploiement de production (`npx vercel --prod`).
- Une étape en rouge : le message dit pourquoi (clé invalide, crédit épuisé, étape trop longue…).

## Réglages importants

Dans l'onglet **Réglages**, renseigne :

- ton **patrimoine financier total** : la jauge et l'IA s'en servent pour ne pas te faire dépasser ta limite ;
- ton **argent disponible** : l'IA ne proposera jamais d'investir plus ;
- la **part maximale** en startups et actions de croissance (10 % par défaut).

Garde-fous intégrés à l'analyse :

- jamais plus que l'argent disponible, achats étalés dans le temps ;
- attendre au moins 30 jours après une introduction en bourse ;
- aucune recommandation d'achat ou de vente sur Anthropic, l'entreprise qui développe l'IA utilisée (conflit d'intérêts) ;
- 3 analyses lancées à la main par jour au maximum (`MAX_MANUAL_AI_RUNS`), plus un rattrapage automatique, pour maîtriser le coût ;
- seuls les liens réellement lus pendant la veille (ou présents dans tes actus et fiches) sont affichés comme sources.

---

## Sources des données

| Donnée | Source | Fréquence |
|---|---|---|
| Cours des actions | Yahoo Finance (secours : Stooq) | à chaque ouverture si plus de 6 h, et chaque matin |
| Taux de change | Banque centrale européenne (Frankfurter) | idem |
| Actus et levées | Flux RSS Crunchbase News, Maddyness, FrenchWeb, TechCrunch | idem |
| Recherche du jour et recommandations | Claude (Anthropic) avec recherche web | chaque matin |

Les cours peuvent avoir jusqu'à 15 minutes de retard ou dater de la dernière clôture.

---

## Développement local

```bash
cp .env.example .env.local   # remplis au moins ANTHROPIC_API_KEY
npm install
npm run dev                  # http://localhost:3000
```

Sans base Upstash, les données restent en mémoire et disparaissent au redémarrage.

## Structure

```
app/                 pages et routes API (Next.js)
  api/cron/*         tâches planifiées : cours, veille, decision
  api/refresh        mise à jour à la demande, étape par étape
  api/import         import CSV Trade Republic
components/          interface (Dashboard, Login)
lib/advisor.ts       recherche web + recommandations avec Claude
lib/market.ts        cours et taux de change
lib/news.ts          flux d'actus
lib/import-tr.ts     lecture du CSV de transactions
lib/seed.ts          radar et calendrier de départ (recherche du 29/09/2026)
```
