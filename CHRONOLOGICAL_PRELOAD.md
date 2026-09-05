# HippoEdge v6.9.12 — File chronologique

Objectif : fournir les pronostics exploitables le plus tôt possible sans réduire la méthode.

## Ordre

1. J0 : courses sans snapshot, ordre chronologique.
2. Publication du snapshot dès qu’une course est terminée.
3. J0 : rafraîchissements ciblés des courses déjà prêtes si les profils sont anciens ou la carte a changé.
4. J+1 seulement après le passage J0.

## Lecture utilisateur

- `ready_race_ids` : courses ouvrables immédiatement.
- `pending_race_ids` : courses encore dans la file.
- `next_pending_race` : prochaine course qui doit être préparée.
- `/api/day/{date}/queue` est volontairement léger et peut être interrogé fréquemment sans recalculer les historiques.
- `/api/day/{date}/dashboard` conserve les compteurs lourds et les engagements.

## Fraîcheur

Une course prête est recalculée si :
- un profil dépasse la fenêtre de fraîcheur ;
- le statut d’historique redevient transitoire ;
- la carte factuelle change (partant/non-partant, poids, corde, équipement, ferrure, position de départ, jockey/driver, entraîneur, forme affichée, distance, surface, terrain, classe, allocation, départ ou horaire).

## Intégrité

Le moteur de calcul reste `generate_analysis()` avec le contrat 18/18 blocs. Aucun raccourci de carrière, de réseau A→B→C→D, de potentiel caché, robustesse, volatilité, Finisseur, Late mover, Résistance aux finisseurs, Course ciblée ou engagements n’est introduit par cette orchestration.


## Accès direct aux 4 prochaines courses (v6.9.13)
L'onglet **À venir** mélange toutes les réunions de la journée par `scheduled_at` et affiche automatiquement les quatre prochains départs. Une analyse déjà prête s'ouvre immédiatement ; une course encore dans la file conserve son statut jusqu'à publication du snapshot. La liste se recalcule toutes les 15 secondes sans intervention de l'utilisateur.
