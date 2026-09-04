# Méthode HippoEdge — v2026.09.03-v6.9.0

## Carrières complètes et verrou documentaire v6.9.0

- La musique officielle reste un signal provisoire mais n'est jamais comptée comme un historique détaillé.
- Aucun cheval du jour, placé, outsider, tocard ou cheval de cœur n'est publié avec `history_rows = 0`.
- Un cheval exige normalement trois performances détaillées. Deux lignes ne suffisent que si une preuve objective exceptionnelle est présente.
- Une course entière doit atteindre 70 % de partants possédant au moins une ligne détaillée avant de produire une hiérarchie publique.
- Les états `pending`, `loading`, `unavailable` et les tentatives sont persistés afin qu'un hébergeur interrompu puisse reprendre cheval par cheval.
- Les métadonnées du réseau d'adversaires sont conservées lors de chaque actualisation du programme.
- L'application expose la couverture réelle ; elle n'assimile plus le nombre de résultats lisibles dans la musique au nombre de courses documentées.
- Le tableau public complet de la fiche Geny est lu sans plafond local : toutes les lignes publiées par la source sont conservées, puis chaque identifiant d’ancienne course est recroisé pour obtenir son champ complet et son arrivée.
- La progression « anciennes courses recroisées / courses de carrière » reste visible et reprend après une veille Render.

Cette version fusionne les réglages permanents des conversations « Historique complet cheval » et « Reprendre un ancien chat ».

## 1. Indépendance absolue

Aucune cote, position de favori, popularité, classement éditorial, avis de presse, pronostic, tipster, sélection externe, Note IA ou Cote BZH n’entre dans le calcul. Les partants et conditions viennent des fiches officielles ; les scores viennent exclusivement de faits de course et de performances vérifiables. Les champs interdits sont supprimés avant stockage et scoring.

## 2. Analyse exhaustive de chaque cheval

Chaque partant reçoit un paragraphe individuel fondé sur tout ce qui est objectivement disponible : historique complet, résultats récents et anciens, lignes directes, évolution ultérieure des adversaires, chronos/vitesse, niveau réel des lots, hippodrome, piste, distance, terrain, surface, corde ou position de départ, poids, valeur handicap, âge, sexe, taille/gabarit seulement si fiable, discipline et expérience, jockey/driver, entraîneur, ferrure/équipement, gains, forme, progression/régression et qualité de l’engagement. Les données manquantes sont signalées ; elles ne sont jamais inventées.

Chaque cheval reçoit cinq notes indépendantes :

1. Performance / Victoire /100
2. Profil Placé / Sécurité /100
3. Potentiel caché /100
4. Robustesse au scénario /100
5. Incertitude / volatilité /100

Le modèle Performance ne doit jamais être remplacé par le modèle Placé. Le Placé estime la capacité à terminer dans les trois par la régularité, la propreté, l’expérience et la répétabilité. La convergence ou divergence entre les deux est affichée.

## 3. Hiérarchie des preuves

- Performance propre, chrono et résultat dans une catégorie comparable : priorité maximale.
- Confrontation directe et ligne indirecte confirmée : publiées dans le classement séparé « Réseau des adversaires », jamais injectées dans Performance ou Placé.
- Chrono brut : toujours comparé au niveau réel du lot, à la distance et à l’écart au vainqueur/Top 3.
- Avis extérieur ou cote : poids nul.

Une performance récente sur la distance exacte peut passer devant une confrontation directe plus ancienne. Chez un jeune cheval, une progression rapide et récente peut faire passer le profil devant un cheval plus robuste mais moins évolutif.

## 4. Galop

Poids, valeur handicap, corde contextualisée, distance, terrain, surface, niveau de lot, aptitude piste-distance-terrain, progression/régression, ancienne valeur masquée, lignes directes/indirectes, jockey et entraîneur comme facteurs secondaires. Une combinaison poids très bas + bonne corde/configuration + ancienne valeur ou forme masquée + amélioration récente est renforcée, surtout sur faible historique.

## 5. Trot attelé

Réduction kilométrique, chrono comparé au lot, ferrure/déferrage comparée aux configurations des meilleures performances, fautes, régularité de fond, autostart et numéro seulement avec preuve d’aptitude, première/seconde ligne, départ volté, recul 25/50 m, gains et échelon, distance/piste, progression et ancienne valeur masquée. Une DAI récente pénalise la sécurité mais n’efface pas automatiquement une performance propre antérieure.

## 6. Trot monté

Références monté séparées de l’attelé, chronos monté, poids, régularité technique, fautes, recul, piste/distance, capacité à répéter l’effort et expérience réelle du monté.

## 7. Potentiel caché

Rechercher une valeur supérieure à la musique récente : ancienne performance solide, dernière sortie explicable, DAI après une bonne performance, retour aux conditions favorables, ferrure/équipement déjà associé à de bonnes sorties, régularité de fond sans victoire, petit poids/configuration favorable, jeune cheval encore peu exposé. Ne jamais transformer ce module en excuse pour une longue régression.

Une longue absence ne déclasse pas automatiquement un cheval. Si elle s’accompagne d’un poids favorable, d’un pilote solide, d’une valeur handicap basse et d’une ancienne valeur démontrée, le cheval peut entrer comme joker spéculatif de potentiel caché, avec volatilité élevée et sans être qualifié de sûr.

## 8. Robustesse au scénario

Mesurer la capacité à répéter sa valeur malgré différents déroulements : rythme, positionnement, trafic, nécessité de contourner, ouverture tardive, mauvais départ, risque d’enfermement, fautes et aptitude à plusieurs configurations. La robustesse est distincte de la performance maximale.

## 9. Incertitude / volatilité

Elle augmente avec seulement 2–4 courses, historique incomplet, longue absence, changement de discipline, fautes répétées ou jeune cheval peu exposé. Elle n’est ni un bonus ni une pénalité de valeur : elle indique la confiance possible dans la mesure.

- 0–30 : faible
- 31–59 : moyenne
- 60–100 : forte

Une forte volatilité interdit d’appeler le cheval « sûr », notamment pour le Simple Placé.

Un faible nombre de courses n’exclut jamais automatiquement un cheval. Il réduit seulement la certitude accordée aux notes. Une amélioration calculée sur une seule transition est ramenée vers une valeur neutre ; elle ne devient forte que si le résultat récent apporte lui-même une preuve de niveau. Ainsi, `0p → 6p` constitue une amélioration mesurée, mais jamais une progression exceptionnelle. À l’inverse, un cheval peu expérimenté ayant déjà produit une performance de haut niveau dans une catégorie comparable reste pleinement éligible.

## 10. Présentation obligatoire de chaque course

1. Présentation et conditions de course
2. Tableau complet de tous les chevaux : numéro, cheval, paragraphe factuel, Performance, Placé, Potentiel caché, Robustesse, Volatilité
3. Top 3 — Modèle complet / Performance-Victoire
4. Top 3 — Spécial Simple Placé
5. Convergence
6. Un ou deux chevaux « À ne pas négliger »
7. Réseau des adversaires : classement indépendant, couverture et paragraphe pour chaque cheval
8. Sélection élargie jusqu’à 8
9. Choix gagnant
10. Choix placé
11. Synthèse exacte : 🏆 Top 3, 🛡️ Placé, 💎 Potentiel caché, 🔥 Convergence, 🔗 Réseau indépendant, 🎟️ Sélection 8
12. Conclusion nette : cheval à battre, danger principal, choix rationnel pour une place, verdict final chiffré, compléments éventuels
13. Seulement ensuite : bloc indépendant « Course potentiellement ciblée / objectif visé par la maison »

Le bloc maison étudie séparément habitudes de préparation, changements de pilote/ferrure/équipement, qualité d’engagement et autres engagements déclarés. Il ne modifie jamais scores, Top 3, Simple Placé, « À ne pas négliger », classement ou conclusion.

## 11. Sélections par réunion et journée — indices approfondis

Pour chaque réunion : meilleur cheval, meilleur placé, outsider analytique, tocard spéculatif et cheval de cœur. Pour la journée : tous les chevaux de toutes les courses sont réexaminés ensemble afin de désigner cheval du jour, meilleur placé du jour, outsider du jour, tocard du jour et cheval de cœur du jour.

Le cheval du jour n’est plus le simple maximum du score Performance. Son indice transversal confronte la Performance réajustée par la profondeur documentaire avec la forme, la classe, l’aptitude, la robustesse, le potentiel caché et la confiance issue de la volatilité. Le meilleur placé utilise un indice séparé donnant davantage de poids à la régularité, à la robustesse, à l’expérience et à la confiance. Un échantillon de deux ou trois courses reste admissible, mais la note revient davantage vers 50/100 tant que les résultats ne prouvent pas eux-mêmes un niveau supérieur.

Chaque désignation expose son indice spécifique, le nombre de courses documentées, la confiance documentaire et un paragraphe expliquant les critères examinés. Le même cheval peut légitimement être Cheval du jour et Meilleur placé seulement s’il domine séparément les deux indices approfondis ; aucune diversité artificielle n’est imposée.

Une désignation du jour ou d’une réunion n’est publiée que si elle repose sur un snapshot correspondant à la version actuelle de la méthode, sur des performances détaillées enregistrées et sur une course dont au moins 70 % du lot est documenté. La musique officielle PMU peut rester visible comme information provisoire, mais elle ne rend jamais un cheval sélectionnable. Si l’historique certain manque, l’application affiche « en attente » plutôt que de choisir arbitrairement un cheval.

« Outsider » et « tocard » sont définis exclusivement par la position interne dans le modèle, le potentiel caché, la robustesse et la volatilité. Ils ne correspondent jamais à une cote ou à la popularité du marché.

## 12. Réseau indépendant des adversaires

Pour chaque partant, le moteur parcourt toutes les performances conservées auxquelles une liste nominative d’adversaires et des résultats objectifs peut être rattachée. Il reconstitue les courses communes, compare chaque arrivée exploitable et recherche quatre types de preuves : confrontations directes, adversaires battus ayant ensuite gagné ou pris une place, confirmation dans un lot au moins équivalent, et chaînes indirectes jusqu’à `A→B→C→D`. Une pondération de récence et de niveau évite de traiter de la même manière une petite course ancienne et une référence récente de classe supérieure.

Le graphe est calculé sur l’ensemble des partants de la course du jour et de leurs anciennes courses reliées. Deux chevaux du jour déjà opposés sont donc comparés directement ; les adversaires communs servent également de points de raccordement. Les chaînes sont plafonnées à trois liaisons : `A a battu B`, puis `B a battu C`, puis `C a battu D`. La liaison vers D compte moins de la moitié d’une liaison vers C, exige une course comparable ou une confirmation ultérieure et reste affichée séparément. Toute propagation au-delà de D est ignorée car elle deviendrait trop spéculative.

Chaque adversaire battu B est ensuite recherché dans les anciennes courses de tous les autres partants du jour. Si B a ultérieurement devancé un partant C présent aujourd’hui, la passerelle `A > B > C` est enregistrée comme soutien. Si C a devancé B, ce résultat est également conservé : il indique que C dispose lui aussi d’une ligne favorable sur le même cheval et empêche de raconter seulement le côté positif pour A. Chaque exemple précise les chevaux, les dates et si la seconde course était d’un niveau au moins équivalent.

La note du réseau revient vers 50 lorsque le volume de preuves est faible. Elle n’est publiée comme classement qu’à partir de deux courses reliées, quatre comparaisons objectives et trois adversaires différents. En dessous, le paragraphe indique « non classé ». L’application affiche aussi le nombre de courses reliées sur le nombre total de performances connues : une course sans participants publiés ne devient jamais une fausse preuve.

Ce bloc a un poids mathématique strictement nul dans Performance, Placé, Potentiel caché, Robustesse, Volatilité, Cheval du jour et Meilleur placé. Son ordre peut donc contredire le Top Performance : c’est une lecture complémentaire que l’utilisateur confronte lui-même aux autres analyses.

## 13. Apprentissage post-course

Le snapshot pré-course reste intact. Après l’arrivée, comparer la prévision et le résultat, diagnostiquer l’erreur et n’ajouter une règle que si le signal était observable avant le départ. Ne jamais forcer une explication lorsqu’une donnée antérieure était insuffisante. Les enseignements déjà confirmés (progression récente sur distance exacte, potentiel masqué, reprise après absence sous conditions, etc.) s’appliquent aux courses suivantes sans réécrire le passé.

## 14. Présentation mobile et arrivées

L’écran d’accueil présente d’abord les cinq sélections de la journée, puis les repères de chaque réunion. L’onglet Courses propose un menu horizontal de réunions puis un menu horizontal de courses afin d’ouvrir rapidement une fiche sans reproduire une page de programme de bureau. Chaque fiche conserve la présentation exhaustive cheval par cheval et les paragraphes factuels.

L’interface traduit les codes de source en français courant et affiche un statut de preuve visible. Un score neutre lié à un historique vide est présenté comme « non classé », jamais comme une recommandation ; les clients peuvent donc distinguer immédiatement une conclusion fondée d’une lecture encore incomplète.

L’onglet Arrivées affiche les résultats dès qu’un ordre est publié. Le statut est explicitement `PROVISOIRE` ou `OFFICIELLE` selon le flux source. Une arrivée provisoire est remplacée par la version officielle à la prochaine actualisation ; elle ne modifie jamais le snapshot pré-course ni les choix affichés dans l’analyse.

## 15. Historiques objectifs et cascade internationale

En mode `pmu`, le programme, les partants, les non-partants et les résultats viennent du flux public officiel PMU. Les performances détaillées PMU ajoutent immédiatement les anciennes courses et adversaires qu’elles nomment. Les chevaux de trot sont aussi enrichis en lecture seule depuis leurs performances publiques LeTROT, avec correspondance exacte du nom et sans plafond local sur le nombre de courses publiées par cheval. Si LeTROT refuse temporairement l’accès, un seul refus est enregistré pour le traitement courant : les autres chevaux passent directement au complément Geny. La limitation reste visible dans les métadonnées. Les colonnes d’avis entraîneur et de rapport probable ne sont jamais lues.

L’exhaustivité signifie ici « toutes les lignes objectivement disponibles dans les sources chargées », et non une promesse de reconstituer une course dont aucun flux accessible ne publie les participants. Le nombre de lignes reliées et la couverture sont toujours affichés. Cette distinction empêche une absence de données de devenir une conclusion positive ou négative.

Les fiches chevaux France Galop demandent actuellement une connexion officielle. HippoEdge signale donc `official_login_required` et n’essaie jamais de contourner cette protection.

Geny est utilisé comme complément factuel en lecture seule. L’identifiant numérique est résolu depuis le répertoire de la journée et le nom affiché doit correspondre exactement après normalisation ; chaque performance doit conserver ce même identifiant. Le flux public de la fiche fournit tout son tableau `performances`, pas seulement les lignes visibles à l’écran. HippoEdge conserve toutes les courses publiées et leur identifiant exact, puis appelle le champ de chaque ancienne course afin de récupérer tous les partants et rangs. Une course partagée est téléchargée une seule fois, chaque résultat est sauvegardé avant le suivant et le traitement reprend automatiquement après interruption.

Le parseur Geny conserve uniquement des faits : identité, date, hippodrome/pays, nom et identifiant de course, discipline, distance, terrain/surface, catégorie, allocation, rang/incident, chrono, poids, valeur handicap, corde/départ, équipement, jockey/driver, entraîneur, propriétaire et participants. Il ignore explicitement `cote`, `cotePmu`, `coteGeny`, rapports, Quinté, `pronostic`, favoris et `noteFinDeCourse`. Le pare-feu commun supprime une seconde fois toutes les familles de marché, d’avis et de sélection avant stockage.

Pour l’étranger, la priorité reste la source hippique officielle du pays lorsqu’elle offre un accès public, automatisable et autorisé. Exemples de contrôle : Equibase pour le galop américain, HKJC pour Hong Kong, USTA Pathway pour le trot américain, Svensk Travsport pour le trot suédois et Standardbred Canada pour le trot canadien. Une source avec CAPTCHA, connexion, paiement ou restriction de réutilisation n’est pas aspirée silencieusement. Si aucune donnée certaine n’est disponible, l’historique reste incomplet, la volatilité augmente et le paragraphe du cheval le signale explicitement.
