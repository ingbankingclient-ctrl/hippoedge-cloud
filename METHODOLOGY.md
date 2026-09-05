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

## 10. Présentation obligatoire de chaque course — contrat anti-oubli

Une analyse HippoEdge n'est considérée complète que si **tous** les blocs permanents existent. Un bloc sans preuve doit afficher « données insuffisantes / aucun signal démontré » ; il ne doit jamais disparaître silencieusement. Le backend expose un manifeste `required_blocks`, `completed_blocks`, `missing_blocks` et `method_complete`, vérifié automatiquement par les tests.

Ordre obligatoire :

1. Présentation et conditions de course.
2. Tableau complet cheval par cheval : paragraphe factuel avant les notes, historique complet disponible, Performance, Placé, Potentiel caché, Robustesse, Volatilité.
3. Réseau des adversaires indépendant : confrontations directes, performances ultérieures des adversaires et chaînes jusqu'à A→B→C→D.
4. Finisseurs purs — bloc indépendant.
5. Progressifs tardifs / Late movers — bloc indépendant.
6. Résistance aux finisseurs — bloc indépendant et confrontation des styles.
7. Top 3 Performance / Victoire avec arguments avant les /100.
8. Top 3 Simple Placé / Sécurité avec arguments avant les /100.
9. Top 3 Potentiel caché avec arguments.
10. Top 3 Robustesse au scénario avec arguments.
11. Top 3 Faible volatilité / confiance avec arguments.
12. Convergence Performance + Placé avec arguments.
13. Un ou deux chevaux « À ne pas négliger » avec arguments.
14. Sélection élargie jusqu'à 8, avec un argument joueur pour chaque cheval.
15. Bloc « Paramètres renforcés » : réseau A→B→C→D, potentiel caché, robustesse, volatilité et styles de fin de course rapprochés sans fusionner leurs scores.
16. Synthèse exacte et choix gagnant / choix placé.
17. Conclusion nette : cheval à battre, danger principal, choix rationnel pour une place, verdict final chiffré, compléments éventuels.
18. **Seulement après la conclusion** : bloc indépendant « Course potentiellement ciblée / engagements ».

Le bloc Course ciblée / engagements étudie séparément les répétitions objectives de programme (même intitulé si publié, même hippodrome/distance/catégorie), continuité récente de distance, changements factuels d'équipement et prochains engagements déjà déclarés, y compris J+0 lorsque le cheval est recouru plus tard le même jour. Il ne prétend jamais connaître une intention privée de l'entourage. Il ne modifie jamais Performance, Placé, Potentiel caché, Robustesse, Volatilité, Top 3, Simple Placé, sélection 8 ou conclusion.

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


## v6.9.7 — mode de calcul préchargé

Le moment du calcul change, pas la méthode. HippoEdge prépare J0/J+1 en arrière-plan, conserve les faits déjà vérifiés et ne recalcule une course que lorsqu’une donnée factuelle utile a changé ou qu’une nouvelle version méthodologique l’exige. Les cinq notes principales, le réseau d’adversaires séparé et les chaînes A→B→C→D restent inchangés.

Une journée n’est déclarée `ready` que lorsque les profils ne sont plus en état `pending/loading`, que les anciennes courses identifiées ne sont plus en attente de recroisement et que chaque course chargée possède un snapshot de la version méthodologique courante. Les débutants peuvent être « vérifiés » sans historique : ils restent visibles mais non transformés en choix s’ils n’atteignent pas les seuils de preuve.

Le volet « Engagements futurs » est informatif et indépendant des classements. Un cheval retrouvé dans un programme ultérieur est signalé avec son prochain engagement connu, mais cette information ne modifie aucune note principale sans preuve factuelle supplémentaire sur un objectif d’entourage.

## Volet Finisseurs — indépendant (v6.9.8)

HippoEdge publie désormais, lorsque les preuves le permettent, un **Top 3 Finisseurs** séparé des classements Performance/Victoire et Placé/Sécurité.

Règles :
- un cheval n'est jamais déclaré finisseur à partir de sa seule place à l'arrivée ;
- le moteur recherche des **positions intermédiaires**, des **places gagnées dans la phase finale** et/ou un **rang de dernier tronçon/sectionnel** publiés comme faits de course ;
- les cotes, favoris, pronostics, avis de presse, recommandations et **notes éditoriales de fin de course** sont exclus ;
- un signal répété sur plusieurs courses est nécessaire pour le statut « finisseur confirmé » ; un seul signal peut rester « à confirmer » ;
- le **n°1 du Top 3 Finisseurs doit obligatoirement être aussi une belle chance actuelle** selon les propres scores HippoEdge et les seuils de fiabilité ;
- si aucun finisseur détecté ne remplit cette condition, aucun Top 3 n'est forcé ;
- ce volet a un poids **nul** dans Performance/Victoire, Placé/Sécurité et dans tous les autres classements principaux.

Le but est de reconnaître un vrai comportement de fin de course, pas de transformer un bon résultat passé en style de course supposé.

## Arguments joueurs et Progressif tardif (v6.9.9)

La présentation donne désormais la priorité aux **preuves lisibles par le joueur** avant les notes. Pour chaque cheval retenu dans un bloc, HippoEdge doit expliquer ce qui justifie sa présence avec des faits disponibles avant la course : résultats récents avec contexte, marges, distance et hippodrome, régularité, progression, lignes directes/indirectes, comportement dans le parcours, configuration du jour et risque principal. Les `/100` restent affichés, mais comme repères secondaires.

Le moteur ne transforme jamais une note interne en argument. Une phrase doit pouvoir être rattachée à un fait enregistré ou à une relation objective calculée à partir de ces faits. Les commentaires éditoriaux, cotes, favoris, pronostics et verdicts externes restent interdits, même s'ils décrivent correctement le cheval après coup.

Le volet de fin de course est scindé en deux profils :

1. **Finisseur pur** : gain de places ou sectionnel supérieur dans la phase terminale. Une bonne place finale seule ne suffit pas.
2. **Progressif tardif / Late mover** : gain d'au moins deux places dans la partie tardive précédant la phase finale, puis position maintenue ou encore améliorée jusqu'au poteau. Un cheval qui remonte puis s'effondre de plus d'une place dans la phase terminale n'est pas validé dans ce sous-volet.

Un cheval peut appartenir aux deux profils s'il commence sa remontée avant le sprint final et continue ensuite à gagner du terrain. Les deux sous-volets restent indépendants de Performance/Victoire et Placé/Sécurité. Le premier cheval publié dans chacun d'eux doit également passer le filtre « belle chance actuelle » ; aucun choix n'est forcé lorsque cette condition manque.


## Forces de fin de course — v6.9.10

Trois profils indépendants sont distingués sans cotes, favoris, pronostics ni commentaires éditoriaux :

- **Finisseur pur** : gain de places / meilleur dernier tronçon objectivement mesuré dans la phase terminale.
- **Progressif tardif / Late mover** : remontée avant la toute dernière phase puis effort soutenu jusqu’au poteau.
- **Résistance aux finisseurs** : un cheval n’obtient ce signal que s’il a terminé devant un finisseur présent dans le lot **dans la même course qui constitue une preuve objective de finish pour ce rival**. Une simple victoire passée sur ce rival, dans une autre course, ne suffit pas.

Lorsque plusieurs finisseurs sont présents, la répétition et le nombre de finisseurs distincts contenus renforcent la preuve. Les contre-signaux sont conservés. Ces blocs restent indépendants des scores principaux et leurs arguments factuels sont affichés avant les notes /100.


## v6.9.11 — Full Method Audited

- Arguments joueurs affichés avant les notes /100 dans tous les classements principaux et renforcés.
- Course ciblée / engagements calculée objectivement et affichée systématiquement après la conclusion.
- Finisseur pur, Late mover et Résistance aux finisseurs restent trois profils séparés ; plusieurs chevaux peuvent être classés dans chaque sous-réseau.
- Le compteur du Bilan sépare désormais **courses historiques uniques** et **lignes de performances**. Une même ancienne course partagée par plusieurs chevaux n'est plus comptée plusieurs fois dans le compteur « courses uniques ».
- Le client empêche un vieux rafraîchissement HTTP de faire visuellement reculer le compteur persistant de courses historiques déjà recroisées.
- Le manifeste anti-oubli rend les 18 blocs permanents vérifiables automatiquement.


## v6.9.12 — orchestration chronologique sans attente de journée complète

Cette version **ne modifie aucun des 18 blocs méthodologiques ni leurs règles d’indépendance**. Elle change uniquement l’ordre d’exécution du moteur lourd.

1. Le programme officiel J0/J+1 reste importé et rafraîchi en continu.
2. Le moteur sélectionne les courses de J0 qui n’ont pas encore de snapshot courant, triées par heure de départ.
3. Pour la première course, il charge/actualise les profils complets, recroise toutes les anciennes courses utiles, construit le réseau A→B→C→D, calcule les 18 blocs et **enregistre immédiatement le snapshot**.
4. Cette course devient consultable immédiatement, même si toutes les autres sont encore en attente.
5. Le moteur passe ensuite à la course suivante de J0.
6. Après avoir parcouru J0, il traite J+1 selon le même principe.
7. À chaque cycle, les courses déjà prêtes sont recontrôlées si leurs profils sont devenus anciens ou si la carte factuelle a changé (non-partant, poids, corde, équipement, jockey/driver, conditions, etc.).
8. Une course déjà partie sans snapshot pré-course n’est pas transformée rétroactivement en pronostic.

La page Sélections peut donc être **provisoire** : elle compare uniquement les courses déjà analysées, puis se recalcule à mesure que la file chronologique avance. Les choix deviennent complets lorsque la file J0 est terminée.
