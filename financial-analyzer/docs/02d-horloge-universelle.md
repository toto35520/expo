# 02d — Horloge universelle, sessions et calendriers

> Statut : **figé** (étape 2.4 de la spécification).
> Quatrième composante du socle. Transverse : conditionne les étages 1 à 12.

## 1. Le vrai problème n'est pas le stockage

Enregistrer en UTC est nécessaire et facile. Ce n'est pas là que le système se casse.

Le problème est que **les marchés et les publications sont définis en heure locale**, avec des
règles de changement d'heure qui diffèrent d'une juridiction à l'autre. La conversion n'est donc
pas un décalage constant : c'est une fonction du temps, discontinue, et dont les points de
discontinuité ne coïncident pas entre places.

L'exemple donné à l'étape 2.4 est exactement le bon. Une publication à 8 h 30 à New York tombe
à **13 h 30 UTC en hiver et 12 h 30 UTC en été**. Un système qui a mémorisé « 13 h 30 UTC » est
faux la moitié de l'année, sur la classe d'événements qui déplace le plus violemment l'or.

## 2. Règle fondatrice

**Les observations sont stockées en UTC. Les horaires sont stockés en heure locale, avec leur
fuseau, et convertis à la lecture.**

| Objet | Stockage | Motif |
| --- | --- | --- |
| Tick, transaction, événement de carnet | UTC, résolution native | c'est un fait daté, il ne bouge plus |
| Ouverture de séance, coupure, fermeture | heure locale + identifiant de fuseau | c'est une **règle**, elle suit le changement d'heure |
| Publication macro programmée | heure locale + identifiant de fuseau | idem |
| Fixings londoniens | heure locale de Londres + fuseau | idem |
| Affichage à l'opérateur | fuseau de l'opérateur, à la présentation | ne doit jamais entrer dans un calcul |

**Figer un horaire de marché en UTC est un défaut, pas une optimisation.** C'est la source
d'erreur la plus fréquente de cette couche, et elle ne se manifeste que deux fois par an — donc
longtemps après avoir été introduite.

## 3. Les fenêtres de désalignement saisonnier

L'Union européenne et les États-Unis ne changent pas d'heure aux mêmes dates : l'UE bascule le
dernier dimanche de mars et le dernier dimanche d'octobre, les États-Unis le deuxième dimanche
de mars et le premier dimanche de novembre.

Il existe donc chaque année deux fenêtres où **l'écart Londres ↔ New York n'est pas celui du
reste de l'année** :

- une fenêtre d'environ trois semaines en mars, les États-Unis ayant basculé avant l'Europe ;
- une fenêtre d'environ une semaine fin octobre, l'Europe ayant basculé avant les États-Unis.

Ces fenêtres tombent en pleine saison de publications macro majeures. Un système qui raisonne
en « décalage habituel » est faux pendant un mois par an, précisément sur les séances les plus
violentes.

**Corollaire** : aucune conversion de fuseau ne doit être écrite à la main dans le code.
Toutes passent par une base de fuseaux tenue à jour (§7), qui encode ces règles et leur
historique.

Fuseaux à suivre, avec leurs règles propres : Londres (marché physique et fixings), New York
(publications macro et séance), Chicago (séance du listé), et le fuseau de l'opérateur —
Portugal continental suivant les dates européennes, mais restant un fuseau distinct qu'il ne
faut pas confondre avec celui de Londres.

## 4. Précision, monotonie, ordonnancement

Trois règles, chacune corrigeant une erreur silencieuse.

**4.1 — L'horodatage ne suffit jamais à ordonner.** Deux événements peuvent porter le même
horodatage, y compris à la nanoseconde sur un flux agrégé. L'ordre est défini par le triplet
`(horodatage, numéro de séquence, index d'arrivée)`, jamais par l'horodatage seul. Un tri
instable sur des ticks produit un carnet reconstruit différemment à chaque exécution — et
détruit la rejouabilité (I2).

**4.2 — Les durées ne se mesurent pas sur l'horloge murale.** L'horloge UTC peut reculer :
correction de synchronisation, ajustement de seconde intercalaire, lissage. Une soustraction
de deux horodatages muraux peut donc produire une durée négative ou aberrante. Toute mesure de
latence, de fraîcheur ou de délai s'appuie sur une **horloge monotone locale** ; l'horloge
murale ne sert qu'à l'enregistrement. Ce point était déjà posé en `02-socle-donnees.md` §3 ; il
est ici généralisé à tout le système.

**4.3 — La résolution native est conservée.** Tronquer des horodatages nanoseconde en
milliseconde détruit l'ordre des événements à l'intérieur de la milliseconde — soit exactement
l'information que la microstructure exploite. Aucune troncature à l'ingestion ; les arrondis
éventuels sont faits à l'affichage.

## 5. Le calendrier de marché est un jeu de données, pas un fichier de configuration

Il doit couvrir, **par marché** :

- jours de fermeture complète ;
- **demi-séances** — journées à clôture anticipée ;
- coupure quotidienne du listé et fermeture de fin de semaine ;
- ouverture du dimanche ;
- jours de fixation et jours fériés londoniens ;
- interruptions non programmées : incidents techniques, suspensions de cotation.

Deux points que la liste de l'étape 2.4 laisse implicites et qui comptent :

**5.1 — Les jours fériés ne coïncident pas entre places.** Un jour férié britannique ferme le
marché physique londonien alors que le listé américain fonctionne, et réciproquement. Il existe
donc des séances **partiellement ouvertes**, où l'un des piliers du socle est légitimement
muet.

Sans cette connaissance, le contrôle qualité déclenche « flux londonien périmé » à chaque jour
férié britannique — et le système apprend à ignorer ses propres alarmes, ce qui est pire que de
ne pas en avoir.

**5.2 — Une demi-séance n'est pas une séance normale plus courte.** Sa liquidité, ses spreads
et sa volatilité ont une distribution propre. Elle constitue donc une **tranche de session
distincte** au sens de l'ADR-007, pas une journée ordinaire tronquée.

**5.3 — Fermeture programmée et interruption subie doivent rester distinguables.** Les deux
arrêtent la cotation, mais l'une est prévisible et l'autre est un événement de marché porteur
d'information. Les confondre efface un signal.

## 6. État de séance : une donnée calculée, datée, rejouable

L'état de séance n'est pas évalué à la volée au moment de décider — il est calculé, stocké et
horodaté comme toute autre feature :

```
MarketCalendarState(as_of) {
  par_marché {
    statut            OUVERT | FERMÉ | DEMI_SÉANCE | COUPURE | INTERROMPU
    tranche_session   creux asiatique | ouverture Londres | fixing | recouvrement
                      Londres–NY | rollover | fin de séance NY | ouverture dimanche
    prochaine_transition
    motif             programmé | incident
  }
  fenêtre_publication_macro   aucune | imminente | en cours | vient de s'écouler
  tzdata_version
  calendar_version
}
```

Le calendrier lui-même est **bitemporel** : les jours fériés et les horaires sont annoncés à
l'avance et parfois modifiés. Rejouer une décision passée exige le calendrier **tel qu'il était
connu à l'époque**, pas celui d'aujourd'hui. Même logique que l'ADR-015 sur les révisions.

## 7. Versionnement de la base de fuseaux

Les règles de changement d'heure sont modifiées par les États, parfois avec un préavis de
quelques semaines, parfois de façon rétroactive. La base de fuseaux est donc mise à jour
plusieurs fois par an.

**Règle** : la version de la base de fuseaux est un artefact versionné (I7), enregistrée dans
chaque enregistrement de décision. Sans elle, une conversion rejouée aujourd'hui peut différer
de celle effectuée à l'époque, et l'écart est invisible.

C'est la quatrième application du même principe : après la donnée (ADR-004), la transformation
(ADR-012), la connaissance (ADR-015), c'est ici la **règle de conversion** qui doit être datée.

## 8. Le calendrier macro

C'est la classe d'événements que l'exemple de l'étape 2.4 vise directement. Pour l'or, les
publications américaines de fin de matinée européenne et les décisions de banque centrale sont
les événements programmés les plus déplaçants.

Structure retenue :

```
ScheduledRelease {
  identifiant, libellé
  heure_prévue_locale, fuseau        jamais stocké en UTC (§2)
  importance_attendue
  heure_de_publication_effective     souvent différente de l'heure prévue
  valeur, consensus, révision_précédente, avec leurs dates de publication
  calendar_known_as_of               le calendrier lui-même est daté
}
```

Trois précisions :

- **l'heure prévue et l'heure effective diffèrent** — publications anticipées, retardées,
  embargos rompus. Le système enregistre les deux ; seule l'effective vaut disponibilité ;
- les valeurs publiées sont **révisées** — traitées selon l'ADR-015 ;
- la fenêtre de publication est un **état de risque**, pas une simple étiquette : elle doit
  pouvoir durcir ou bloquer la décision à l'étage 8, ce qui suppose de la connaître à l'avance
  et non de la constater après coup.

## 9. Il n'existe pas « une » bougie journalière

Conséquence peu intuitive de cette étape, et directement reliée aux faux niveaux du §7 de
`02b-futures-comex.md`.

La frontière de journée n'est pas universelle :

- la séance électronique du listé ouvre en fin d'après-midi heure de Chicago et court jusqu'au
  lendemain, avec une coupure quotidienne ;
- le spot OTC change de journée au rollover du broker, lui-même exprimé dans un fuseau serveur
  qui suit souvent un changement d'heure ne correspondant **ni** à celui de Londres **ni** à
  celui de New York.

Résultat : deux conventions produisent des **bougies journalières différentes**, donc des plus
hauts, plus bas et corps de bougie différents — et deux fois par an, un décalage d'une heure
change silencieusement le découpage.

Tout niveau extrait d'une bougie journalière hérite donc de la convention qui l'a produite.
Un plus-haut journalier n'est pas un fait de marché : c'est un fait *relatif à une frontière
de journée*.

**Règle** : la frontière de journée — et de semaine — est un **paramètre déclaré et versionné**
de toute agrégation. Deux séries agrégées selon des conventions différentes ne sont jamais
comparées ni fusionnées, et un niveau transporte la convention dont il est issu.

## 10. L'heure de l'opérateur

Le fuseau du Portugal appartient à une catégorie différente de celle des autres : c'est un
fuseau **de présentation**, pas de calcul. Alertes, journaux affichés et explications peuvent
y être rendus ; aucune règle de décision, aucune agrégation, aucun seuil n'y est exprimé.

Cette séparation évite le défaut classique où une heure d'affichage finit, par commodité, par
servir de borne à un calcul.

## 11. À vérifier avant implémentation

- horaires exacts d'ouverture, de coupure et de clôture du listé, et leur fuseau de référence ;
- calendrier officiel des jours fériés et des demi-séances, par marché ;
- convention de rollover journalier des fournisseurs spot retenus, et fuseau serveur de chacun —
  à demander explicitement, cette information est rarement documentée ;
- source du calendrier macro, sa latence de mise à jour et la disponibilité des heures de
  publication effectives ;
- politique de gestion des secondes intercalaires de l'infrastructure hôte.

## 12. Questions ouvertes

- **Q15** — les fournisseurs spot retenus ont-ils des frontières de journée différentes entre
  eux ? Si oui, aucune agrégation journalière multi-fournisseurs n'est possible sans
  re-découpage à partir des ticks, ce qui impose de conserver les ticks bruts sur toute la
  profondeur d'historique utile (lié à Q7).
- **Q16** — les niveaux journaliers et hebdomadaires servent-ils à la décision ? Si oui, la
  convention de frontière devient un paramètre de premier ordre à trancher explicitement, et
  non un héritage du graphique consulté.
