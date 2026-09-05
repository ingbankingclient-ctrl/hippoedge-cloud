# HippoEdge — application mobile d’analyse hippique indépendante

HippoEdge est un produit complet **mobile + API** conçu pour analyser automatiquement les réunions/courses PMU du jour et du lendemain en appliquant une méthode indépendante des cotes, favoris et pronostics externes.

La version **v6.9.12 — file chronologique + publication immédiate** prépare automatiquement les courses **une par une, dans l’ordre des départs**. HippoEdge termine d’abord les courses de **J0** ; dès qu’une course possède son snapshot complet, cette analyse devient immédiatement accessible à tous les utilisateurs, sans attendre les autres courses. Ce n’est qu’après avoir parcouru la file J0 que le moteur commence le travail lourd sur **J+1**. Les programmes J+1 peuvent rester importés en avance, mais leurs carrières/réseaux ne prennent jamais la priorité sur les pronostics du jour. Elle lit tout le tableau de carrière public que la source publie pour chaque cheval Geny identifié avec certitude, sans plafond local de 500 lignes, puis rouvre chaque ancienne course par son identifiant exact pour récupérer tous les partants et résultats. Les téléchargements sont dédupliqués, limités en débit, enregistrés course par course et repris automatiquement après une interruption de l’hébergeur. Une musique comme `1a2a3a` n'est jamais assimilée à trois courses détaillées et aucun choix public n’est produit lorsque les preuves minimales manquent.

## Ce qui est déjà livré

- Application mobile iPhone/Android via **Expo / React Native**.
- API **FastAPI**.
- Base SQLAlchemy : SQLite par défaut, PostgreSQL possible via `DATABASE_URL`.
- Import léger automatique **jour J + J+1** (programme, partants, résultats).
- Les carrières complètes, anciennes courses recroisées et scores lourds sont préparés automatiquement **course par course**. Chaque snapshot validé est publié immédiatement en base ; la page Course peut donc ouvrir R1C1 pendant que R1C2 est encore en calcul. La page Sélections affiche des choix provisoires fondés uniquement sur les courses déjà prêtes, puis les met à jour à chaque nouvelle course analysée.
- Accueil « Sélections du jour », menu mobile Réunion → Course et écran dédié aux arrivées provisoires/officielles.
- Programme → réunions → courses → partants → historique chevaux.
- Préparation complète avant ouverture : une course devient accessible quand son snapshot courant est prêt ; les faits déjà récupérés restent en base et sont réutilisés aux cycles suivants.
- Un paragraphe en français courant pour chaque cheval : contexte, performances vérifiées, forces, limites et conclusion. Les champs techniques sont traduits ou masqués pour un lecteur non spécialiste.
- Un badge de fiabilité distingue une base exploitable, une lecture partielle, un historique en cours et un dossier non classé. Les scores neutres d’attente ne sont pas présentés comme des choix.
- Cinq lectures par cheval :
  - Performance / Victoire
  - Profil Placé / Sécurité
  - Potentiel caché
  - Robustesse au scénario
  - Incertitude / volatilité
- Un sixième bloc entièrement séparé, « Réseau des adversaires », classe les chevaux à partir des confrontations historiques recroisées. Son poids est strictement nul dans les cinq notes principales et dans les sélections du jour.
- Paramètres spécifiques :
  - galop : poids, valeur, corde, distance, terrain, progression, aptitude piste/distance ;
  - trot attelé : chronos, autostart, position, départ, ferrure, faute, niveau, aptitude ;
  - trot monté : références monté, poids, chronos monté, fautes, parcours, régularité technique ;
  - obstacles : forme, classe, aptitude terrain/distance, poids et régularité.
- Règles méthodologiques renforcées :
  - la performance propre construit seule les classements principaux ;
  - les lignes directes et indirectes disposent de leur propre classement indépendant ;
  - un adversaire battu n’est valorisé que si son résultat est connu, puis sa répétition ultérieure est vérifiée dans un lot comparable ou supérieur ;
  - les chaînes indirectes vont jusqu’à `A→B→C→D`, avec une influence fortement décroissante à chaque liaison ;
  - comparaison du chrono au niveau réel du lot ;
  - DAI récente = pénalité de sécurité, mais n’efface pas automatiquement la valeur ;
  - régularité sur 2–3 courses plafonnée à cause du faible échantillon ;
  - progression des jeunes chevaux valorisée ;
  - bon numéro autostart seulement modérément valorisé sans preuve de vitesse/d’expérience ;
  - poids/corde/configuration favorables ne remplacent jamais la preuve de niveau ;
  - potentiel caché = ancienne valeur + forme masquée + conditions du jour ;
  - robustesse au scénario et volatilité traitées séparément.
- Snapshot pré-course **verrouillable** et verrouillage automatique avant le départ.
- Résultats post-course + statistiques sans réécriture rétroactive.
- Import permanent du programme et des résultats, **file chronologique J0 prioritaire puis J+1**, rafraîchissement périodique des profils devenus anciens, détection des changements de carte (non-partant, poids, corde, équipement, jockey/driver, etc.), cache persistant des anciennes courses et snapshots pré-calculés. Une course déjà prête s’ouvre sans téléchargement lourd.
- Tests automatiques du scoring et du pare-feu anti-pronostics.

## Pare-feu d’indépendance

Le connecteur de données passe toutes les réponses par `sanitize_objective_payload()`.

Sont supprimés avant stockage/scoring : cotes, favoris, popularité, Note IA, Cote BZH, value bets, pronostics, sélections, avis et classements externes.

Le moteur ne voit donc que la donnée objective autorisée. Le texte affiché par l’app confirme :

> Je confirme que le moteur n'utilise volontairement ni classements, ni pronostics, ni favoris, ni cotes, ni popularité, ni avis éditoriaux. La liste des partants provient de la fiche de course et les scores sont construits uniquement à partir des données objectives de course et de performance disponibles.

## Sources de données

Trois modes sont fournis :

### 1. `demo`
Fonctionne immédiatement, sans compte ni clé. Il permet de tester toute l’application de bout en bout.

### 2. `pmu` — mode recommandé
Connecteur officiel sans clé pour le programme, la fiche exacte de course, les partants, les non-partants et les arrivées. Le flux de performances détaillées PMU fournit aussi les anciennes courses reliables et les adversaires nommés visibles dans ces lignes. Les chevaux de trot sont enrichis en lecture seule depuis leurs performances publiques LeTROT : date, rang, nombre de partants, chrono, distance/recul, hippodrome, catégorie et spécialité.

La v6.9 utilise le flux factuel public qui alimente les fiches Geny. Une seule lecture renvoie le tableau complet de carrière disponible : identifiants du cheval et de la course, date, hippodrome/pays, spécialité, distance, terrain/surface, classe et allocation, rang ou incident, chrono, poids, corde/départ, équipement, jockey/driver, entraîneur et autres faits publiés. Elle couvre le galop français ainsi que les réunions étrangères de galop et de trot présentes dans la base Geny. Pour le trot, LeTROT reste prioritaire lorsqu’il répond et Geny complète les champs ou lignes absents. Pour le galop, Geny reste le complément public tant que les fiches France Galop imposent une connexion officielle.

La correspondance ne repose jamais sur un nom approchant : le nom complet normalisé de la fiche doit concorder et chaque performance doit conserver le même identifiant Geny. Chaque identifiant d’ancienne course est ensuite relu une seule fois, même si plusieurs chevaux du jour y ont participé. En cas de doute ou d’homonyme, aucune ligne n’est attachée. Les cotes, rapports, favoris, avis Geny, `noteFinDeCourse`, pronostics, synthèses de presse, classements et notes externes ne font pas partie de la liste des champs admis et sont bloqués une seconde fois par le pare-feu avant stockage.

Le bloc « Réseau des adversaires » parcourt toutes les lignes historiques conservées qui possèdent une liste d’adversaires vérifiable, sans limite artificielle aux huit dernières courses. Il compare les résultats directs, recherche si un cheval battu a ensuite gagné ou pris une place, distingue le niveau équivalent/supérieur et suit les chaînes jusqu’à `A→B→C→D`. La couverture réelle est affichée sous la forme « anciennes courses recroisées / courses de carrière ». Si le flux ne publie pas les participants d’une ancienne course, celle-ci reste visible dans l’historique mais n’est pas inventée dans le réseau. Un minimum de deux courses reliées, trois rivaux et quatre comparaisons est exigé ; sinon le cheval est « non classé » dans ce seul bloc.

Pour chaque cheval battu, le moteur recherche aussi ses rencontres ultérieures avec tous les partants de la course du jour. Il conserve les deux sens : `A bat B puis B bat C` renforce la passerelle d’A vers C ; `A bat B puis C bat B` montre que C possède lui aussi une ligne favorable sur le même rival. Les dates, le niveau relatif du lot et jusqu’à trois exemples lisibles sont affichés sous le paragraphe du cheval.

Pour les courses étrangères, la hiérarchie prévue est : source locale officielle lorsqu’elle est publiquement automatisable, puis Geny pour les courses intégrées au programme PMU. Les références de contrôle comprennent notamment Equibase (galop États-Unis), HKJC (Hong Kong), USTA Pathway (trot États-Unis), Svensk Travsport (trot Suède) et Standardbred Canada. Ces services ne sont pas présentés comme automatiquement connectés lorsqu’ils exigent un compte, un CAPTCHA, un abonnement ou une autorisation de réutilisation.

### 3. `turfbzh` — connecteur optionnel historique
Connecteur tiers conservé pour compatibilité, désactivé par défaut.

**Important :** même si le fournisseur expose aussi des cotes ou indicateurs propriétaires, ces champs sont supprimés par le pare-feu HippoEdge et ne participent pas aux scores.

L’architecture `RacingProvider` permet d’ajouter ensuite des connecteurs autorisés/licenciés France Galop, LeTROT ou d’autres bases internationales sans modifier le moteur.

## Démarrage rapide — mode démo

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows : .venv\\Scripts\\activate
pip install -r requirements.txt
cp ../.env.example ../.env
python run.py
```

API : `http://127.0.0.1:8000`
Swagger : `http://127.0.0.1:8000/docs`

### Mobile

```bash
cd mobile
npm install
npm start
```

Scannez le QR Expo Go sur iPhone/Android.

Sur un téléphone physique, dans l’onglet **Réglages**, remplacez `127.0.0.1` par l’IP locale de l’ordinateur, par exemple :

`http://192.168.1.25:8000`

## Activer les vraies courses

Copiez `.env.example` en `.env` puis :

```env
HIPPOEDGE_PROVIDER=pmu
```

Redémarrez l’API. Le scheduler maintient le programme, les partants et les arrivées de J/J+1, puis un worker séparé prépare les carrières, le réseau historique et les snapshots avant l’ouverture de l’application. Quand l’utilisateur ouvre une course, HippoEdge charge alors les carrières complètes de ses seuls partants, recroise leurs anciennes courses et calcule la méthode complète. Les faits récupérés sont persistés et réutilisés. Les anciennes courses exactes disposent aussi d’un cache PostgreSQL global par identifiant de course : une course déjà téléchargée pour un cheval ou une page est réutilisée pour les autres, y compris après redémarrage. La page Sélections ne lance aucun calcul lourd automatiquement : un bouton explicite traite les courses de la journée une par une. Quitter la page annule le traitement actif.

## Endpoints principaux

- `GET /health`
- `POST /api/refresh?day=2026-09-01`
- `GET /api/program/2026-09-01`
- `GET /api/tomorrow`
- `GET /api/day/{date}/selections` (lecture des sélections déjà calculées)
- `POST /api/day/{date}/analyze-selections` (calcul explicite de la journée, course par course)
- `GET /api/day/{date}/history-status`
- `POST /api/races/{race_id}/analyze` (analyse complète à la demande)
- `GET /api/races/{race_id}/analysis` (compatibilité ; applique aussi le mode à la demande)
- `POST /api/races/{race_id}/lock`
- `GET /api/stats`

## Déploiement gratuit — PC éteint

La livraison cloud fournit `render.yaml` pour deux services gratuits :

1. `hippoedge-api` : API FastAPI/Docker sur Render ;
2. `hippoedge-mobile` : version web installable sur l’écran d’accueil de l’iPhone ;
3. une base PostgreSQL externe gratuite, recommandée sur Supabase, afin que les analyses et snapshots survivent aux redémarrages.

Variables obligatoires :

```env
HIPPOEDGE_DATABASE_URL=postgresql://...
EXPO_PUBLIC_API_URL=https://hippoedge-api.onrender.com
```

Le code convertit automatiquement les URL `postgres://` et `postgresql://` vers le pilote Psycopg. En production, `run.py` utilise le port fourni par l’hébergeur et désactive le rechargement de développement.

Limite honnête du niveau gratuit : l’API Render s’endort après une période sans requête. La première ouverture peut donc prendre environ une minute, puis l’application fonctionne normalement. Comme le serveur ne travaille pas pendant son sommeil, utiliser **Actualiser** à l’ouverture pour récupérer le programme et les arrivées récents.

Consultez `CLOUD_DEPLOYMENT.md` pour la procédure complète sans offre payante.

## Qualité vérifiée

La liste de contrôle détaillée est conservée dans `AUDIT_CHECKLIST.md`.

Tests backend :

```bash
cd backend
PYTHONPATH=. pytest -q
```


### Accélération v6.9.2

Le recroisement exact des anciennes courses reste complet mais n'est plus strictement séquentiel : les connexions HTTP sont réutilisées, plusieurs réponses peuvent être attendues en parallèle sous un sémaphore borné, le départ des requêtes reste cadencé, et un lot entier est persisté dans une seule transaction. Le moteur ne recharge plus les 633 carrières et ne régénère plus toutes les analyses après chaque lot de 120 courses ; cette finalisation lourde n'a lieu qu'à la fin du recroisement. Cela réduit fortement le temps total sans supprimer une seule course ni raccourcir les chaînes A→B→C→D.

État au moment de la livraison v6.9.2 : le programme et les arrivées sont importés rapidement, chaque tableau de carrière est enregistré immédiatement, puis les anciennes courses sont recroisées par lots avec reprise persistante. Le cache utilise l’identifiant exact de course et évite de redemander une course commune à plusieurs chevaux. Deux courses distinctes disputées le même jour, sur le même hippodrome et la même distance restent séparées par leur identifiant. Les snapshots post-départ sont exclus des sélections et une arrivée officielle ne peut plus réécrire le snapshot pré-course. La suite contient **69 tests backend**, dont la carrière JSON complète, le contrôle d’identité, l’exclusion des cotes/avis, le cache des courses communes, la reprise des checkpoints, le seuil documentaire, le format PMU, les chaînes A→B→C→D, le cycle provisoire/officiel et l’indépendance mathématique du réseau. La méthode de calcul est `2026.09.04-v6.9.2-speed`.

## Limite honnête

Le code est fonctionnel de bout en bout. « Complet » signifie toutes les courses présentes dans le tableau public de la fiche exactement identifiée ; aucune source gratuite ne garantit à elle seule tous les chevaux ayant couru partout dans le monde. Une fiche absente ou une ancienne course sans participants reste donc explicitement incomplète. La version web installable évite les frais Apple et fonctionne sans Expo Go une fois mise en ligne. Une publication native dans l’App Store nécessiterait en revanche les certificats et le compte développeur du propriétaire de l’application.


### Mode v6.9.6 — à la demande

HippoEdge ne tente plus de recroiser les milliers de lignes historiques de toute la journée au chargement. Le programme reste léger. Un clic sur une course prépare uniquement les chevaux de cette course, conserve les faits en base, recroise leur réseau A→B→C→D puis calcule les scores. Quitter l’écran annule les requêtes encore actives. La page Sélections fonctionne de la même manière, mais uniquement après le bouton « Lancer les sélections du jour » et en traitant les courses séquentiellement afin de protéger la RAM et le pool PostgreSQL.


## Mode v6.9.7 — préchargement permanent et affichage instantané

- J0 et J+1 sont préparés automatiquement par un worker séquentiel afin de ne pas doubler la pression sur la source ou sur PostgreSQL.
- Les profils déjà contrôlés sont réutilisés ; ils sont re-vérifiés lorsqu’ils deviennent anciens selon `HIPPOEDGE_HISTORY_PROFILE_REFRESH_SECONDS`.
- Les anciennes courses exactes restent dans `historical_race_cache` et ne sont pas re-téléchargées pour un autre cheval ou un autre jour.
- Les snapshots de toutes les courses chargées sont calculés en arrière-plan avec la méthode complète. Le clic utilisateur sur une course lit le snapshot courant ; il ne lance plus le réseau historique.
- Tant que la journée n’est pas `ready`, l’interface affiche « Préparation automatique » et n’ouvre pas les analyses partielles.
- La page Sélections lit les snapshots déjà calculés et n’exécute plus un calcul lourd à la demande.
- `/api/day/{day}/dashboard` expose les compteurs persistants de courses/chevaux analysés, l’avancement historique, le nombre de profils vérifiés, le cache global et les engagements futurs connus.
- Le volet « Engagements futurs » compare les chevaux du jour aux programmes futurs déjà présents en base et affiche leur prochain engagement connu avec filtres J+3/J+7/J+14/J+30. Il ne transforme pas un engagement en intention d’entourage.
- L’application interroge le dashboard toutes les 30 secondes afin de basculer automatiquement de « mise à jour » à « journée prête » sans recalcul au clic.

Validation : **73 tests backend passent**. Syntaxe TypeScript de `App.tsx` et `src/api.ts` vérifiée.

Méthodologie : `2026.09.04-v6.9.7-preloaded-live`.

### v6.9.8 — Volet Finisseurs

Ajout d'un bloc indépendant « Top 3 — Finisseurs » dans chaque analyse de course. Le moteur utilise uniquement des faits de déroulement final disponibles (positions intermédiaires, places gagnées en fin de course, rangs de sectionnels). Le premier profil n'est publié que s'il constitue également une belle chance actuelle selon les scores principaux HippoEdge. Les données de marché, pronostics et notes éditoriales restent hors du moteur.

### v6.9.9 — Arguments joueurs + Progressif tardif

Les notes `/100` restent visibles comme repères internes, mais elles ne constituent plus l'explication principale affichée au joueur. HippoEdge produit désormais des arguments factuels par bloc et par cheval : dernières performances documentées, positions et marges, distance/hippodrome comparables, progression réelle, régularité, lignes d'adversaires et chaînes vérifiées, paramètres du jour et point de vigilance. Les textes sont assemblés exclusivement à partir des données objectives déjà admises par le pare-feu ; aucune cote, favori, pronostic, avis de presse ou commentaire éditorial n'est utilisé.

Le volet de fin de course distingue désormais deux comportements :
- **Finisseur pur** : gagne réellement des places ou produit un meilleur dernier tronçon dans la phase terminale ;
- **Progressif tardif / Late mover** : remonte nettement avant la toute dernière phase puis soutient cet effort jusqu'au poteau (exemple factuel `7e → 4e → 4e`).

Les deux listes sont indépendantes des scores principaux. Le n°1 de chaque Top 3 doit également constituer une belle chance actuelle HippoEdge ; sinon aucune tête de liste n'est forcée.

Validation v6.9.9 : **85 tests backend passent**. Méthodologie : `2026.09.05-v6.9.9-arguments-late-mover`.


### v6.9.11 — réseau des styles de fin de course
Ajout de la résistance aux finisseurs et des contre-preuves directes entre chevaux du jour. Les arguments de confrontation sont affichés avant les notes /100.


## v6.9.11 — FULL METHOD AUDITED

Cette version verrouille la présentation complète de chaque course : 18 blocs permanents contrôlés, arguments avant les notes, Top 3 Potentiel caché/Robustesse/Faible volatilité rendus explicitement, Finisseur/Late mover/Résistance séparés, Paramètres renforcés, et bloc Course ciblée / engagements calculé à partir de faits objectifs puis affiché après la Conclusion nette.

Le Bilan distingue les courses historiques uniques des lignes de performances et protège l'affichage contre les réponses HTTP anciennes qui pouvaient donner l'impression que l'avancement reculait.


## Accès direct aux 4 prochaines courses (v6.9.13)
L'onglet **À venir** mélange toutes les réunions de la journée par `scheduled_at` et affiche automatiquement les quatre prochains départs. Une analyse déjà prête s'ouvre immédiatement ; une course encore dans la file conserve son statut jusqu'à publication du snapshot. La liste se recalcule toutes les 15 secondes sans intervention de l'utilisateur.
