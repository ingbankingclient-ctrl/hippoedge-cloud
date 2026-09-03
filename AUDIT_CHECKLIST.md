# Audit HippoEdge — v6.9.0

Contrôle effectué avant livraison selon la méthode fusionnée des conversations « Historique complet cheval » et « Reprendre un ancien chat ».

## Contrôle fonctionnel

- [x] Pare-feu indépendant avant stockage et scoring : cotes, favoris, popularité, pronostics, sélections externes, avis, rapports, ratings et variantes anglaises supprimés récursivement.
- [x] Programme, partants, non-partants et résultats normalisés depuis le flux PMU public ; aucun compte n’est requis pour ce flux.
- [x] Historiques trot : LeTROT prioritaire, Geny complémentaire, identité exacte, dédoublonnage et priorité des faits officiels ; un refus 403 coupe les nouvelles tentatives LeTROT du traitement courant sans bloquer Geny.
- [x] Galop français et étranger : France Galop reste une frontière officielle protégée ; Geny ne complète que lorsque l’identité est vérifiée.
- [x] Galop/trot étrangers : les lignes Geny objectives sont admissibles pour les courses présentes au programme ; aucune source à compte, CAPTCHA ou abonnement n’est aspirée silencieusement.
- [x] Le flux public Geny lit le tableau de carrière complet de la fiche vérifiée, jusqu’à 500 courses, et non seulement les cartes visibles dans le HTML.
- [x] Chaque ancienne course Geny est identifiée exactement puis relue pour récupérer tous ses partants/rangs ; une course commune à plusieurs chevaux n’est téléchargée qu’une fois.
- [x] Checkpoint course par course, trois tentatives maximum et reprise automatique ; couverture exacte exposée par l’API et l’application.
- [x] Chaque partant actif reçoit cinq notes indépendantes et un paragraphe factuel ; les références objectives visibles sont conservées dans le détail mobile.
- [x] Chaque partant reçoit aussi un dossier « Réseau des adversaires » : duels historiques, répétitions ultérieures, niveau de confirmation, chaînes A→B→C→D atténuées et couverture réelle.
- [x] Un cheval battu puis opposé à un partant du jour est relié dans les deux sens ; une victoire de B sur C et une victoire de C sur B sont distinguées et expliquées.
- [x] Le Réseau des adversaires a un poids nul dans Performance, Placé et les sélections ; un dossier trop peu relié reste non classé dans ce bloc.
- [x] L’écran traduit les statuts de preuve en français courant, masque le score neutre des dossiers non classés et explique la signification des cinq repères.
- [x] Musique officielle visible comme information provisoire mais jamais utilisée pour rendre un cheval sélectionnable sans historique détaillé.
- [x] Aucun choix de course, réunion ou journée si moins de 70 % du lot possède un historique détaillé enregistré.
- [x] Checkpoint persistant avant chaque profil : après une veille ou un redémarrage Render, les états `pending`/`loading` sont repris sans perdre les chevaux déjà enregistrés.
- [x] Réutilisation inter-cartes uniquement sur identifiant officiel strictement identique ; le cache reste marqué en attente jusqu’au rafraîchissement et ne copie pas un ancien score de réseau.
- [x] Faible échantillon, progression, fautes, chronos, aptitude, poids/valeur, corde/départ, ferrure, potentiel caché, robustesse et volatilité traités séparément.
- [x] Cheval du jour, meilleur placé, outsider, tocard et cheval de cœur calculés séparément par réunion et sur l’ensemble de la journée ; aucune diversité artificielle.
- [x] Snapshot pré-course identifié et verrouillable ; une arrivée ne recalcule ni ne rétrograde une analyse officielle.
- [x] Arrivées provisoires et officielles affichées, y compris lorsqu’un ordre provisoire est encore vide.
- [x] Navigation mobile : Sélections → Réunions → Courses → Analyse détaillée → Arrivées/Bilan/Réglages.
- [x] Import rapide du programme et des résultats ; récupération historique lente isolée en arrière-plan pour éviter les erreurs réseau pendant l’actualisation.

## Vérifications exécutées

- Suite backend : **65 passed**.
- Compilation Python de tous les modules et tests : OK.
- TypeScript mobile (`tsc --noEmit`) : OK.
- Build web Expo (`npm run build:web`) : OK.
- Test réel en lecture seule : Jabalpur, 52/52 courses de carrière lues ; ancienne course test, 12/12 partants lus ; Native de Bozouls, 1/1 course et 15/15 partants ; Abbey Road, 5/5 courses et 10/10 partants.
- Contrôle sur les réponses réelles : aucun champ de cote, rapport, pronostic ou commentaire éditorial dans les données mappées.

Les accès privés, clés de licence et mots de passe ne sont pas enregistrés dans le projet.
