# HippoEdge v6.9.12 — Audit anti-oubli + publication course par course

Une course n'est considérée complète que si les 18 blocs suivants sont présents dans le snapshot, même lorsqu'un bloc conclut « aucune preuve suffisante ».

1. Conditions de course
2. Cheval par cheval / historique et arguments
3. Performance / Victoire
4. Placé / Sécurité
5. Potentiel caché
6. Robustesse au scénario
7. Incertitude / Volatilité
8. Convergence
9. À ne pas négliger
10. Réseau des adversaires + A→B→C→D
11. Finisseur pur
12. Progressif tardif / Late mover
13. Résistance aux finisseurs / confrontation des styles
14. Sélection élargie jusqu'à 8
15. Paramètres renforcés
16. Conclusion nette
17. Course potentiellement ciblée
18. Prochains engagements connus

## Garanties techniques

- `REQUIRED_ANALYSIS_BLOCKS` est exposé par le backend.
- `method_complete=true` uniquement lorsque le contrat complet est publié.
- Tests automatiques vérifient le manifeste, le bloc course ciblée et les engagements futurs.
- Les blocs Finisseur, Late mover, Résistance et Course ciblée ont un poids mathématique nul dans les scores principaux.
- Les cotes, favoris, pronostics, classements presse, popularité et commentaires éditoriaux restent exclus du calcul.
- Le résultat d'une course ne réécrit jamais rétroactivement un snapshot pré-course.
- Le Bilan sépare les anciennes courses uniques des lignes de performances afin d'éviter les doubles comptes.


## Contrat de publication v6.9.12

- Le moteur lourd travaille **une seule course à la fois**.
- Les courses non encore analysées sont traitées dans l’ordre chronologique des départs.
- **J0 est toujours parcouru avant J+1**.
- Le snapshot d’une course est visible dès son commit : aucune attente de fin de journée.
- Les sélections du jour peuvent être affichées provisoirement à partir des courses déjà prêtes et évoluent à chaque nouveau snapshot.
- Une course déjà partie sans snapshot pré-course n’est jamais reconstruite rétroactivement comme pronostic.
- Les profils déjà prêts sont recontrôlés selon la fenêtre de fraîcheur et une modification de carte officielle force un recalcul ciblé.
- Le cache historique, les engagements futurs, les compteurs quotidiens et les 18 blocs permanents restent inchangés.
