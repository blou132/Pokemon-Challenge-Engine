# Vérification de la V0.1

Contrôles exécutés le 29 septembre 2026 sous Windows, avec Python 3.13.7,
PySide6 6.11.2 et pytest 9.1.1.

## Reprise et publication de la V0.1

Le 29 septembre 2026, la V0.1 a été réauditée dans le dossier de travail renommé.
La suite a de nouveau réussi (**191 tests**, 13,46 s), ainsi que la compilation et
l'ouverture/fermeture du véritable point d'entrée Windows. Le code V0.1 a été conservé.
Les exclusions Git racine couvrent aussi les secrets, les ROM en majuscules, les
save states DeSmuME et les configurations placées hors du sous-dossier applicatif.
`python -m tools.audit_repository` vérifie ces exclusions et les fichiers déjà suivis
sans afficher de contenu sensible. Aucun fichier interdit ni format de secret usuel
n'a été détecté dans les fichiers suivis avant publication.

## Résultats

| Contrôle | Résultat |
| --- | --- |
| Suite complète `python -m pytest -q --tb=short` | **191 tests réussis**, 10,98 s |
| Compilation des modules `python -m compileall -q app tools` | Réussie |
| Point d'entrée réel `app.main`, plugin Qt `windows` | Fenêtre visible, boucle d'événements exécutée, fermeture propre, code 0 |
| Parcours Qt natif | Génération de 5 règles, sauvegarde, rechargement et navigation réussis |
| Roue Monotype | Animation terminée ; type sous le pointeur identique au résultat logique |
| Chemins invalides | Message français, aucun processus lancé |
| Fichiers ROM/sauvegarde sentinelles | Octets et date de modification inchangés après le test du launcher |
| Lecture de contenu par le launcher | Aucune ouverture de ROM ou de sauvegarde |
| Corruptions JSON | Erreurs contrôlées, données existantes préservées ; Unicode invalide et imbrications excessives couverts |

Les tests Qt utilisent `QApplication`, `QTest` et `QSignalSpy`, sans dépendance pytest-qt.
Les animations sont attendues par leur signal de fin, avec une échéance maximale.
Les profils des tests et du parcours de démonstration sont créés dans des dossiers temporaires.

## Résolutions et captures

La fenêtre a été vérifiée en **1280×700 de surface cliente**, adaptée à un écran
1366×768 avec les bordures Windows, et en **1880×980**, adaptée à 1920×1080.
Les pages longues utilisent le défilement vertical ; aucun débordement horizontal
de page n'a été détecté. Le dialogue Monotype tient dans 850×650.

Le parcours natif utilise le plugin Qt Windows. Le grand rendu utilise le plugin
Qt offscreen, car le bureau disponible borne la taille des fenêtres natives.
Les polices Segoe UI et Segoe UI Symbol sont chargées pour les captures offscreen.

- [Accueil, petit écran](screenshots/accueil-1366.png)
- [Accueil, grand écran](screenshots/accueil-1920.png)
- [Création du challenge](screenshots/challenge-1366.png)
- [Aperçu et sauvegarde](screenshots/challenge-apercu-1366.png)
- [Catalogue des règles](screenshots/regles-1366.png)
- [Profils](screenshots/profils-1366.png)
- [Paramètres](screenshots/parametres-1366.png)
- [Roue Monotype](screenshots/monotype.png)

## Reproduire les contrôles

Dans `pokemon-challenge-engine`, avec l'environnement livré dans le parent :

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m compileall -q app tools
..\.venv\Scripts\python.exe -m tools.verify_ui --entrypoint
..\.venv\Scripts\python.exe -m tools.verify_ui --offscreen
..\.venv\Scripts\python.exe -m tools.verify_ui
```

Le dernier outil ouvre brièvement l'interface, crée des captures dans `docs/screenshots`
et ferme ses fenêtres. Il ne lance pas DeSmuME et ne configure pas de chemin de jeu.

## Limites de la vérification

Aucune ROM personnelle et aucun émulateur réel n'ont été utilisés. La création du
processus DeSmuME est testée avec un substitut ; le chargement effectif d'un jeu devra
être confirmé après configuration des chemins de l'utilisateur.

Aucune application stricte des règles, communication Lua, écriture mémoire ou
randomisation de ROM n'est implémentée. La sauvegarde d'un profil est atomique par
fichier, sans transaction globale entre ses trois fichiers.
