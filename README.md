# HippoEdge — application mobile d’analyse hippique indépendante

HippoEdge est un produit complet **mobile + API** conçu pour analyser automatiquement les réunions/courses PMU du jour et du lendemain en appliquant une méthode indépendante des cotes, favoris et pronostics externes.

La version **v6.9.2 — Carrières complètes et recroisement accéléré** lit tout le tableau de carrière public que la source publie pour chaque cheval Geny identifié avec certitude, sans plafond local de 500 lignes, puis rouvre chaque ancienne course par son identifiant exact pour récupérer tous les partants et résultats. Les téléchargements sont dédupliqués, limités en débit, enregistrés course par course et repris automatiquement après une interruption de l’hébergeur. Une musique comme `1a2a3a` n'est jamais assimilée à trois courses détaillées et aucun choix public n’est produit lorsque les preuves minimales manquent.

## Ce qui est déjà livré

- Application mobile iPhone/Android via **Expo / React Native**.
- API **FastAPI**.
- Base SQLAlchemy : SQLite par défaut, PostgreSQL possible via `DATABASE_URL`.
- Import automatique **jour J + J+1**.
- Accueil « Sélections du jour », menu mobile Réunion → Course et écran dédié aux arrivées provisoires/officielles.
- Programme → réunions → courses → partants → historique chevaux.
- Analyse automatique de chaque course.
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
- Import rapide du programme et des résultats ; carrière complète puis anciennes courses détaillées récupérées en arrière-plan, avec sauvegarde cheval par cheval et course par course.
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

Redémarrez l’API. Le scheduler importe d’abord rapidement aujourd’hui et demain avec les partants et les arrivées, puis récupère les carrières complètes et recroise chaque ancienne course en arrière-plan. Le compteur de l’application indique la progression réelle. Les analyses sont recalculées dès qu’une preuve objective arrive et les snapshots sont verrouillés juste avant le départ.

## Endpoints principaux

- `GET /health`
- `POST /api/refresh?day=2026-09-01`
- `GET /api/program/2026-09-01`
- `GET /api/tomorrow`
- `GET /api/day/{date}/selections`
- `GET /api/day/{date}/history-status`
- `GET /api/races/{race_id}/analysis`
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
