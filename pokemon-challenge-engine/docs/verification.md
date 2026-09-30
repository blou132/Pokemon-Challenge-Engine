# Vérification de la V0.2 et historique V0.1

## Extension aux quatre jeux Gen V — 30 septembre 2026

Le catalogue, les paramètres, le launcher, le protocole v1, la préparation Lua
et la page Connexion DeSmuME acceptent `black`, `white`, `black2` et `white2`.
Les profils français de révision 0 sont séparés :

| Jeu | Code | Profil | Compteur / début de l'équipe |
| --- | --- | --- | --- |
| Noir | `IRBF` | `black_fr_rev0` | `0x02234930` / `0x02234934` |
| Blanc | `IRAF` | `white_fr_rev0` | `0x02234950` / `0x02234954` |
| Noir 2 | `IREF` | `black2_fr_rev0` | `0x0221E408` / `0x0221E40C` |
| Blanc 2 | `IRDF` | `white2_fr_rev0` | `0x0221E428` / `0x0221E42C` |

Les décalages Blanc/Blanc 2 sont explicites dans les branches françaises de
PokeLua, avec sources épinglées dans [memory-map.md](memory-map.md).
Ils ne proviennent pas d'une supposition d'égalité entre versions.

La suite complète a réussi : **598 tests, aucun ignoré**, en 37,67 s,
avec Python 3.13.7, PySide6 6.11.2 et la DLL Lua 5.1 locale. La compilation et
le démarrage natif Qt (`tools.verify_ui --entrypoint`) ont aussi réussi.
Les quatre cartes d'accueil sont lisibles à 1060×640 et 1366×768.

Les tests synthétiques couvrent les quatre codes, les 32 permutations du PID
sur chaque profil, le transport Lua → JSON → Python et les douze associations
avec un profil étranger. Ces associations sont refusées avant toute lecture
d'équipe. Le protocole refuse aussi une identité dont `game_code` et `game_id`
se contredisent. Les anciens messages valides Noir/Noir 2 restent acceptés.
Les configurations V0.1 sont chargées sans réécriture, leurs chemins conservés
et les deux nouveaux chemins initialisés en mémoire. Les profils de challenge
restent au schéma `0.1.0`.

### Essai réel de Pokémon Blanc

Une copie de la ROM personnelle et une copie de la sauvegarde `.dsv` existante
ont été chargées dans un DeSmuME x64 isolé sous `runtime/white-validation/`.
L'exécutable et les DLL sont ceux de l'essai Noir 2 décrit plus bas ; la
configuration Battery/States/Lua de cette copie ne vise que ce dossier.
Le script et les services de production sont utilisés sans injection de
messages simulés. L'instrumentation locale de test utilise seulement
`joypad.set` pour les menus et `gui.gdscreenshot` pour lire les écrans rendus,
API documentées dans le
[moteur Lua DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/lua-engine.cpp).
Cette instrumentation ne fait pas partie des scripts distribués.

Le pont a reçu `hello`, `heartbeat`, puis `party_update` et identifié
`white / IRAF / FR / 0`, avec `white_fr_rev0`. Les données d'équipe effectivement
reçues depuis la RAM sont :

| Place | Espèce, identifiant national | Niveau | PV actuels / maximum |
| --- | --- | --- | --- |
| 1 | Feuillajou, `511` | 15 | 6 / 42 |
| 2 | Gruikui, `498` | 14 | 45 / 45 |

**La comparaison visuelle a réussi** : le menu Pokémon du jeu montre exactement
ces deux espèces, ces niveaux et ces PV. Les noms associés aux identifiants
nationaux sont confirmés par
[la table française PKHeX](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/text/other/fr/text_Species_fr.txt#L499-L512).
La page Qt de production a ensuite reçu trois nouveaux messages du même
producteur DeSmuME réel et affiché cette équipe, le code `IRAF`, la révision 0
et le profil `white_fr_rev0`. Aucune valeur n'a été injectée dans le protocole
pour obtenir ce résultat.

Le statut du profil Blanc est donc **`real_sample_verified`** : un échantillon
réel comparé. Les trois autres profils conservent **`source_documented`**.
Les tests synthétiques restent un contrôle distinct et ne changent pas à eux
seuls ces statuts.

Après la fermeture du test, les **empreintes SHA-256 et dates de modification**
de l'archive ROM Blanc, de sa sauvegarde `.dsv` originale et de la configuration
DeSmuME d'origine sont inchangées. Le processus isolé a été arrêté. Les écrans
du jeu, le nom du joueur, les ROM et sauvegardes restent exclus de Git.
Les traces locales sont dans `runtime/white-validation/` : `result.json`,
`ui_result.json`, `party-real.png` et `ui-real-white-top.png`/`bottom.png`.

Le premier essai avait été interrompu par un verrou Windows/OneDrive sur
l'export de diagnostic `latest_state.json` du banc de test. Ce fichier n'est
pas le transport de production, qui emploie des noms de snapshots inédits.
Après correction de l'export du banc, l'essai complet ci-dessus a réussi.

Ces observations concernent cette ROM et cette équipe. Elles ne valident pas
toutes les situations de jeu, toutes les sauvegardes, les révisions différentes
ou les ROM modifiées. Noir, Noir 2 et Blanc 2 restent, pour leur **équipe réelle**,
**En attente de validation sur la machine utilisateur.** Noir 2 dispose déjà
d'une validation réelle du transport et de l'identité, détaillée ci-dessous.
La branche de travail reste `feat/v0.2-desmume-bridge` ; aucune fusion dans `main`.

## Historique V0.2 initiale — contrôles avant l'extension Blanc

Branche : `feat/v0.2-desmume-bridge`. Base V0.1 : `ac1fa31`, déjà publiée
sur `main`. Aucune fusion automatique dans `main`.

État à la date de ce premier essai, avant la validation Blanc décrite ci-dessus :
**transport réel et identification de Noir 2 validés. Lecture d'une équipe,
des niveaux et des PV : En attente de validation sur la machine utilisateur.**
Le décodeur d'équipe est expérimental ; la V0.2 n'est pas déclarée entièrement
validée pour ces lectures. Aucun mécanisme strict Nuzlocke n'est ajouté.

| Contrôle | Résultat observé |
| --- | --- |
| Suite complète, incluant les 191 tests V0.1 | **453 tests réussis**, aucun ignoré, 31,56 s |
| Compilation `python -m compileall -q app tools` | Réussie |
| Point d'entrée `python -m tools.verify_ui --entrypoint` | Fenêtre Windows, boucle Qt et fermeture propres, code 0 |
| Protocole/service/CLI | Types, versions, JSON incomplet, doublons, taille, sessions, timeout, reconnexion et arrêt couverts |
| Producteur Lua et décodeur | Lua 5.1 exécuté avec RAM synthétique ; comparaison aux attentes Python ; aucune preuve d'équipe réelle déduite de ces tests |
| DeSmuME → script de production → BridgeService | `hello`, puis heartbeat reçus ; identité `black2 / IREF / FR / 0` |
| Fermeture forcée de l'émulateur isolé | `disconnected` après 3,3 s sans message ; équipe absente |
| Redémarrage de ce DeSmuME, même session | Reconnexion ; séquence continue de 5 vers 6 puis 9 |
| Arrêt demandé par Python | Marqueur `stop` consommé ; `emulator_closing`, séquence 10 |
| CLI réel, surveillance de 12 s | Code 0 ; 40 messages, dont 39 heartbeat ; fréquence reçue d'environ 4,10/s sur cet essai |
| Interface Qt avec vrai producteur DeSmuME | « Connectée au script Lua », « Pokémon Noir 2 », `FR / IREF`, révision 0, équipe « Non disponible » après quatre messages |
| Panel diagnostic Qt | Rendu et défilement contrôlés aux résolutions 1366×768 et 1920×1080 |
| Intégrité des originaux | SHA-256 **et dates de modification inchangés** pour cinq fichiers contrôlés avant/après les essais |

### Installation et isolation du test réel

Le test utilise une copie de l'exécutable local
`DeSmuME-VS2022-x64-Release.exe`, renommée pour l'essai. Son empreinte SHA-256
est `34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
Le binaire n'expose pas de version produit exploitable : aucune version
DeSmuME non vérifiée ne lui est attribuée.

Les DLL Lua x64 `lua51.dll` et `lua5.1.dll` viennent de
[l'archive du dépôt officiel DeSmuME épinglée](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/lua/lua.7z).
Elles ont été placées uniquement à côté de la copie de test. L'installation
RetroBat originale, qui ne contenait pas ces DLL, n'a pas été modifiée.

Une copie `.nds` a été extraite de l'archive personnelle existante de Noir 2
français. Aucun jeu n'a été téléchargé. Le code `IREF` et la révision `0`
ont été lus d'abord dans son en-tête, puis réellement dans la RAM DeSmuME.
L'identité concorde ; cela ne certifie pas tous les octets d'une ROM ou d'un hack.

Le dossier ignoré `runtime/probe/` contient l'émulateur isolé, cette copie,
ses propres dossiers Battery/States et sa propre configuration. Le mécanisme
DeSmuME `[Scripting] AutoLoad=1` charge le Lua portant le nom de la ROM dans
le dossier Lua de **cette copie uniquement**. La prise en charge provient de
[main.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L3026).
Le launcher de l'application conserve la procédure manuelle documentée ;
aucune option CLI `--lua` n'a été inventée.

Les cinq originaux contrôlés sont l'archive de Noir 2, la configuration
DeSmuME d'origine et les trois fichiers de sauvegarde DS déjà présents.
Leurs chemins et leurs empreintes de sauvegarde restent dans les traces
locales ignorées, sans être publiés. Les processus de test ont été arrêtés.
La passerelle ne contient aucune écriture mémoire ; seules ses propres
configurations, séquences et publications JSON sont écrites par le pont.

### Limites observées et reproduction

Aucune sauvegarde Noir 2 contenant une équipe n'était disponible pour cet
essai. Au démarrage, le lecteur a rencontré un compteur nul et signalé
« Equipe non initialisee ou aucun Pokemon ». Il a publié `party_size: null`
et `party: null`, sans prétendre avoir mesuré une équipe vide. Aucun niveau,
PV ou identifiant d'espèce réel n'a donc été validé. Pokémon Noir et les
autres régions n'ont pas été testés dans un émulateur réel.

Pour terminer cette validation, suivre [la procédure de connexion](desmume-bridge.md),
ouvrir une partie française de révision 0 avec une équipe, puis comparer le
nombre de Pokémon, leurs niveaux et leurs PV affichés dans le jeu et dans
l'application. Relever le code/révision, le build d'émulateur et le profil
mémoire ; consigner les résultats sans publier la ROM ni la sauvegarde.
Une erreur doit rester une lecture indisponible, pas être remplacée par une
valeur supposée. Les sources et limites de révision sont dans
[la cartographie mémoire](memory-map.md).

Les essais CLI et interface ont utilisé le **script et les services de
production**, sans injection de faux messages. Le rendu Qt de cette page
a été capturé hors écran avec les messages du vrai DeSmuME. Le contrôle
séparé du point d'entrée a utilisé le plugin Windows natif.

Les preuves brutes de cette machine restent localement dans le dossier
ignoré `runtime/probe/` : `production_result.json`, `cli_result.jsonl`,
`ui_result.json` et `ui_real_bridge.png`. Elles peuvent être inspectées ici ;
elles ne sont pas requises pour lancer l'application et ne sont pas versionnées.

Les tests Lua nécessitent un moteur Lua 5.1 de l'architecture du Python de
test (`PCE_LUA51_DLL`). Sur cette machine, la DLL officielle a été utilisée :
aucun test n'a été ignoré. Sans cette DLL sur une autre machine, pytest indique
explicitement les cas ignorés ; un résultat avec des skips ne prouve pas
l'exécution du décodeur.

## Historique : vérification de la V0.1

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

## Limites de la vérification V0.1 d'origine

Aucune ROM personnelle et aucun émulateur réel n'ont été utilisés. La création du
processus DeSmuME est testée avec un substitut ; le chargement effectif d'un jeu devra
être confirmé après configuration des chemins de l'utilisateur.

Aucune application stricte des règles, communication Lua, écriture mémoire ou
randomisation de ROM n'est implémentée. La sauvegarde d'un profil est atomique par
fichier, sans transaction globale entre ses trois fichiers.
