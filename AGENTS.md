# Bibliothèque personnelle Pokémon Challenge Engine

L'application Python et ses tests se trouvent dans `pokemon-challenge-engine/`.

## Invariants de stockage

- La bibliothèque personnelle Windows est `%LOCALAPPDATA%\Pokemon-Challenge-Engine\library`.
  Elle est commune au développement, aux EXE, au mode portable et aux futurs builds.
  Ne pas la déplacer dans le dépôt, un dossier temporaire, un cache ou un dossier de compilation.
- Les neuf jeux locaux ont déjà été importés. Ne pas les réimporter pour chaque version.
  Utiliser `RomLibraryService` et la découverte de bibliothèque existante.
- Ne jamais supprimer, remplacer ou modifier les archives dans `roms sources`,
  les ROM maîtresses, ni leur manifeste pendant une mise à jour, un nettoyage ou un build.
- Chaque nouvelle aventure vérifie le SHA-256 de la maîtresse et crée une copie indépendante.
  Les outils de transformation reçoivent uniquement une copie privée. Une empreinte
  différente interdit la génération. La suppression d'une aventure reste bornée à son dossier.
- Les versions publiques, ZIP et commits restent sans ROM, sauvegardes et manifeste
  de bibliothèque personnelle. Conserver les exclusions et les contrôles du packager.

## Validation

- Les tests automatiques utilisent des racines temporaires explicites et des données synthétiques.
  Le mode `--self-test` garde une bibliothèque isolée. Un essai avec les vrais jeux
  lit la bibliothèque permanente et crée uniquement des aventures de validation séparées.
- Après un essai réel, vérifier les empreintes des sources et des maîtresses, conserver
  un rapport local et fermer uniquement les processus lancés pour cet essai.
- Gen IV : classique melonDS uniquement tant que les profils mémoire et transformations
  correspondants ne sont pas développés et validés. Ne pas présenter les structures Gen V
  comme un suivi d'équipe Gen IV.

Le fonctionnement et l'inventaire sont décrits dans
`pokemon-challenge-engine/docs/personal-library-2026-11-05.md`.
