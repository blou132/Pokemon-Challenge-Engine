# Adaptateur externe ZX 4.6.1

`PceRandomizer.java` est un adaptateur PCE publié sous **GPL-3.0-or-later**,
avec la licence complète [COPYING](COPYING). Il utilise l'API publique de
[Universal Pokémon Randomizer ZX 4.6.1](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/releases/tag/v4.6.1),
également GPL-3.0-or-later. PCE ne redistribue ni le JAR, ni Java, ni ROM.
La source de ZX correspondant à cette intégration est le commit
`7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c`.

Le backend vérifie l'empreinte SHA-256 de `PokeRandoZX.jar` extrait de la release
officielle : `380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8`.
L'archive officielle `PokeRandoZX-v4_6_1.zip`, téléchargée le 13 octobre 2026,
avait l'empreinte `26051fe8a6665ea0582dfcd4d1c3e4889da42a2f731f5fc530fff0cb691a43fd`.
Il s'agit d'empreintes constatées lors du téléchargement HTTPS, pas d'une
signature publiée par l'auteur. Aucun téléchargement automatique n'est exécuté
par l'application.

Un **JDK 11 ou supérieur** local est nécessaire au lancement du fichier source
Java. L'essai Windows a utilisé Java 25.0.4.1 déjà installé. Aucun changement de
PATH ou installation globale n'est effectué.

La CLI originale de ZX ne propose pas d'argument de seed. L'adaptateur appelle
la surcharge vérifiée `Randomizer.randomize(filename, log, long seed)` ; le
paramètre `--seed` ci-dessous appartient seulement à **l'outil Python PCE**.

Depuis le dossier de l'application, avec les chemins choisis par l'utilisateur :

```powershell
python -m tools.randomize_rom --source "C:\chemin\source.nds" --destination "C:\chemin\nouvelle-derivee" --game white --java "C:\chemin\jdk\bin\java.exe" --jar "C:\chemin\PokeRandoZX.jar" --seed 5122026 --categories wild starters trainers --balanced
```

Les huit catégories réellement intégrées sont `wild`, `starters`, `trainers`,
`movesets`, `abilities`, `field_items`, `evolutions`, `types`. `trainers` inclut
les champions : aucun réglage indépendant « champions seulement » n'est exposé.
`movesets` concerne les capacités apprises, pas toutes les CT/tuteurs. Les objets
sont les objets de terrain ordinaires, pas un remplacement global de tous les
objets. `--balanced` applique les options de puissance similaire aux rencontres,
dresseurs et évolutions sélectionnés. Cela ne garantit pas un challenge équilibré.

L'adaptateur accepte séparément IRBF, IRAF, IREF et IRDF, FR révision 0. Il vérifie
les CRC de ROM originale définis par ZX avant la transformation ; les hacks ou
ROM déjà transformées ne sont pas acceptés comme entrées. Chaque résultat est
rechargé par ZX, ses catégories sont comparées aux structures sources et les
types/évolutions effectifs sont extraits. Les empreintes, paramètres exacts et
seed figurent dans `manifest.json` ; les données relues dans `report.json`.

Seule une destination nouvelle est acceptée. Java reçoit une copie exclusive
`source.nds`, jamais la source RetroBat. Une erreur conserve un dossier local
`.pce-transform-…` portant `owner.json` et `failed.json` ; il n'est jamais associé
automatiquement à une aventure. La ROM originale reste présente. Un essai ultérieur
utilise une autre destination. Le délai Java maximal est de dix minutes.

La vérification structurelle n'est **pas** une validation DeSmuME/Lua, d'un combat,
d'une sauvegarde ou d'une reprise. Le manifeste indique ces essais comme non
exécutés jusqu'à une validation réelle distincte. Les limites du suivi Monotype
et des familles doivent être calculées depuis les tables de la dérivée, jamais
depuis les seules tables d'origine quand ces catégories changent.

Aucune modification du taux shiny n'est fournie : les valeurs personnalisées
restent indisponibles. Le taux original est conservé. Les
[codes BW étudiés](https://github.com/TylerD007/The_Shiny_Pokemon_Code_Repository/blob/main/BW.txt)
sont des codes Action Replay pour les versions US et écrivent en mémoire ; ils ne
constituent pas un patch ROM vérifié FR. Ils ne sont ni exécutés ni transposés.
Les routines dépendent aussi de la catégorie de rencontre et des verrous shiny :
une simple comparaison modifiée ou une rencontre shiny ne valide pas une probabilité.

Sources primaires de l'API et des contrôles :

- [Randomizer.java](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/Randomizer.java)
- [Settings.java](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/Settings.java)
- [CliRandomizer.java](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/cli/CliRandomizer.java)
- [Gen5RomHandler.java](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/romhandlers/Gen5RomHandler.java)
- [Profils Gen V distincts](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/config/gen5_offsets.ini)
