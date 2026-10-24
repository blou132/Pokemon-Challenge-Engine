# Pokemon Challenge Engine — V0.5.0 en validation

Application Windows en français pour préparer et suivre des challenges Pokémon
Noir, Blanc, Noir 2 et Blanc 2. **Mes parties** rassemble la création d’une aventure
classique, depuis un modèle ou avec des règles personnalisées, ainsi que la reprise
et la progression. Les profils restent des modèles réutilisables ; chaque partie
conserve ses règles, sa ROM indépendante, ses sauvegardes et son historique.

Le [guide de l’application](pokemon-challenge-engine/README.md) présente les
parcours disponibles. La branche de travail est `feat/melonds-integration` ;
aucune fusion dans `main` n’est annoncée.

## Lancer la version Windows

Extraire entièrement `Pokemon-Challenge-Engine-0.5.0-windows-x64.zip`, puis
ouvrir `Pokemon-Challenge-Engine.exe` par double-clic. Garder `_internal` et
`third-party` près de l’exécutable. Le paquet contient les dépendances Python/Qt,
le composant melonDS PCE et les outils Randomizer Java/ZX ; aucun jeu, BIOS
ou fichier de sauvegarde personnelle n’est fourni.

Les données sont conservées dans `%LOCALAPPDATA%/Pokemon-Challenge-Engine`
par défaut. Le mode portable adjacent et l’import explicite d’anciennes données,
y compris d’un dossier déjà déplacé, sont décrits dans le
[guide Windows](pokemon-challenge-engine/docs/windows-distribution.md).
Conserver l’annexe `Pokemon-Challenge-Engine-melonDS-dependency-sources.zip`
avec le ZIP principal lors d’une redistribution.

## Suivi et limites

melonDS est présélectionné pour les nouvelles parties si son composant vérifié
est disponible. Les anciennes aventures DeSmuME restent accessibles ; leur
[migration explicite](pokemon-challenge-engine/docs/melonds-migration.md) copie
la progression sans remplacer l’environnement précédent. La passerelle native
melonDS et la passerelle Lua DeSmuME lisent le jeu sans écrire dans sa RAM.
Les ROM et sauvegardes sources restent intactes.

Le Randomizer transforme uniquement une copie de ROM, avec catégories, seed
et provenance enregistrées. Les contrôles Shiny Only, Monotype, Level Cap et les
autres règles affichent leurs capacités et limites. Les captures et badges
restent manuels ; aucune utilisation d’objet, de soin ou de Pokémon en combat
n’est déduite d’une simple présence dans l’équipe. Le taux shiny personnalisé
reste désactivé faute de transformation validée.

La migration, la lecture d’équipe et la sauvegarde/reprise de Blanc FR rev0 ont
été exécutées avec melonDS ; une équipe réelle de Noir 2 FR rev0 a aussi été lue.
Cela ne valide pas les quatre jeux ni toutes les règles. Le
[rapport V0.5](pokemon-challenge-engine/docs/v0.5-melonds-validation.md) distingue
jeu réel, tests synthétiques, vérification de l’EXE et limites restantes.

[Contrôles par règle](pokemon-challenge-engine/docs/gen5-rule-observation.md) ·
[Transformations Randomizer](pokemon-challenge-engine/docs/rom-transformations.md) ·
[Sources mémoire](pokemon-challenge-engine/docs/memory-map.md) ·
[Vérifications historiques](pokemon-challenge-engine/docs/verification.md)

## Développement Python

Le code, les tests et les instructions d’installation sont dans
[`pokemon-challenge-engine/`](pokemon-challenge-engine/README.md).
Avec l’environnement de développement déjà préparé à la racine du dépôt :

```powershell
cd .\pokemon-challenge-engine
..\.venv\Scripts\python.exe -m app.main
```
