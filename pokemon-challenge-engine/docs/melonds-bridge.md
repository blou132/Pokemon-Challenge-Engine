# Passerelle melonDS : lecture et commandes natives

La base est la version officielle stable **1.1**, commit
`b86390e4428bf38ce4c1ce0e9ca446d6d25955e8`, publiée le 18 novembre 2025.
Sources : [release officielle](https://github.com/melonDS-emu/melonDS/releases/tag/1.1),
[annonce](https://melonds.kuribo64.net/comments.php?id=240).
Le composant modifié actuel est identifié **1.1-pce.2**. Le protocole des
instantanés conserve son identifiant `1.1-pce.1` pour compatibilité. Le binaire officiel non modifié
ne contient pas cette passerelle et ne doit pas être présenté comme capable de suivi.

## Choix technique et limites

Cette version amont ne fournit pas de moteur Lua. Le débogueur GDB amont existe,
mais son [serveur](https://github.com/melonDS-emu/melonDS/blob/b86390e4428bf38ce4c1ce0e9ca446d6d25955e8/src/debug/GdbStub.cpp#L123)
écoute toutes les interfaces et accepte notamment des commandes d'écriture.
Le build PCE le désactive à la compilation (`ENABLE_GDBSTUB=OFF`).

L'ajout C++ dans `native/melonds/PCEBridge.h` est appelé immédiatement après
`RunFrame()` dans le thread d'émulation. Il copie uniquement les plages bornées
des profils JSON, à partir du pointeur `NDS::MainRAM` et de son masque documentés
dans [NDS.h](https://github.com/melonDS-emu/melonDS/blob/b86390e4428bf38ce4c1ce0e9ca446d6d25955e8/src/NDS.h#L296).
Il n'utilise ni offset de processus hôte, ni recherche de pointeur, ni accès GDB.
Il ne modifie aucune RAM, sauvegarde, entrée de manette ou donnée de jeu.
La lecture se fait en fin de frame ; aucun thread d'émulation ne peut changer
l'équipe pendant la copie. Seule l'instance locale numéro zéro publie.

Toutes les 200 ms au maximum, `QSaveFile` remplace atomiquement un fichier de
session. L'interface ne bloque pas le thread d'émulation ; aucun acquittement
réseau ou lecteur externe n'est attendu. Un échec de remplacement conserve le
fichier précédent et entraîne ensuite le délai normal de déconnexion côté PCE.
La fréquence et l'impact de ces écritures nécessitent une mesure réelle ; aucune
amélioration de performances sur DeSmuME n'est revendiquée.

Le décodeur Python `app/bridge/melonds.py` vérifie version du producteur, session,
code et révision de cartouche, copie RAM de l'en-tête, mode DS et profil exact.
Il déchiffre chaque PK5, vérifie sa somme de contrôle, sa taille et ses bornes,
puis réutilise le protocole PCE v2 et les calculs shiny existants (PID/OTID).
Il publie espèce, forme stockée, identité, niveau et PV. Un heartbeat seul ne
publie aucune capacité de lecture de l'équipe. Un fichier inchangé ne prolonge
pas artificiellement la connexion.

Les quatre profils français révision zéro restent distincts. Les preuves
DeSmuME antérieures sont conservées telles quelles ; elles ne valident pas
automatiquement melonDS. Les adresses documentées de carte concernent Noir et
Blanc seulement. Noir 2 et Blanc 2 n'ont pas d'adresse de carte retenue. Les
rencontres, combats actifs, fuites et captures directes au PC restent inconnus
avec ces profils. Aucun tampon ennemi ou changement d'équipe ne vaut preuve de
capture. Les événements d'évolution peuvent être déduits par les services PCE
uniquement lorsque l'identité individuelle permet une comparaison fiable.
Les transformations temporaires en combat ne sont pas couvertes par la forme PK5.

## Contrat de lancement

Le lanceur prépare une session `BridgeService` isolée, puis passe au processus :

```text
PCE_BRIDGE_DIR=<répertoire absolu de la session>
PCE_BRIDGE_SESSION=<identifiant de session de 32 caractères hexadécimaux>
```

Le lancement de la ROM reste celui de melonDS : `melonDS.exe <copie.nds>`.
Le fichier `stop` arrête les publications. La fermeture ou la pause de
l'émulateur interrompt les frames et mène à la déconnexion après le délai PCE.
Le fichier natif `melonds-frame.json` contient les enregistrements PK5 chiffrés
strictement nécessaires au suivi, sans copie de ROM ou de sauvegarde entière.
Il reste dans les données locales privées de la partie et ne fait pas partie
des journaux publics ni des artefacts de distribution.

Le worker utilise :

```python
reader = MelonDSBridgeReader(session_dir, session_id, game_code, revision)
reader.poll()
state = bridge.poll()
```

Les erreurs `ValueError`/`OSError` doivent être affichées et ne doivent jamais
être transformées en une équipe ancienne ou un heartbeat fabriqué. Le worker
peut retenter une frame ultérieure. Les observations de carte sont conservées
dans le journal PCE jusqu'à leur acquittement après persistance.

## Reproduction du build Windows

Les outils sont locaux, sans installation système ni changement permanent de
PATH. La distribution MSYS2 et ses paquets proviennent des dépôts officiels,
avec contrôle de l'archive et vérification des signatures par pacman.
Paquets UCRT64 : `gcc`, `cmake`, `ninja`, `pkgconf`, `qt5-base`,
`qt5-multimedia`, `qt5-svg`, `SDL2`, `libarchive`, `zstd`, `faad2`, `enet`.
Chaque nom porte le préfixe `mingw-w64-ucrt-x86_64-`.

```powershell
git clone --branch 1.1 --depth 1 https://github.com/melonDS-emu/melonDS.git <source>
<python> tools/prepare_melonds_source.py <source>
./tools/build_melonds.ps1 -SourceDir <source> -MsysRoot <msys64> -Jobs 4
```

Le préparateur refuse tout autre commit et tout checkout déjà modifié. Il
génère `PCEProfiles.h` depuis les JSON existants : aucune adresse nouvelle n'est
inventée. Qt5 est une option présente dans ce tag ; la compilation a révélé trois
metatypes de pointeurs manquants dans les dialogues de codes. Le préparateur
ajoute leurs déclarations explicites uniquement pour Qt5, sans changer le
comportement des dialogues. Le build conserve le JIT,
les interfaces et fonctionnalités natives de melonDS ; l'extension est
dormante en l'absence des deux variables de session.

La licence amont est GPL-3.0-or-later. Les sources correspondantes du composant
modifié, les fichiers de préparation/build, les licences des DLL redistribuées
et leurs sources doivent accompagner la redistribution. Les DLL Qt dynamiques
doivent rester remplaçables. Aucun BIOS, firmware Nintendo, ROM ou sauvegarde
utilisateur ne doit être ajouté à la distribution.

## Validation automatisée

`tests/test_melonds_bridge.py` vérifie les 32 permutations PID, les formes,
l'identité/shiny, les checksums, les quatre profils, les rejets de mauvaise
session/région/révision, le timeout, l'absence d'événements supposés et le journal
avec acquittement. Ces tests utilisent des données synthétiques explicitement
construites ; ils ne prouvent pas le fonctionnement réel dans Pokémon. Les
essais réels et le résultat de compilation sont rapportés séparément.

Validation du 20 octobre 2026 : build Windows x64 exécuté avec GCC 16.2.0,
CMake 4.4.4 et Qt 5.15.19 ; correction des metatypes ci-dessus nécessaire.
`melonDS.exe --help` renvoie zéro et annonce `melonDS 1.1-pce.1` avec un PATH
réduit à Windows System32, sans Python, Qt de développement ni MSYS2 accessibles
par PATH. Les 118 fichiers du manifeste du composant ont été revérifiés par
SHA-256. L'EXE a pour empreinte
`bc370af7d893f1ecf40f76dfbe51935443ec2df999b3f1aefe5ab93d25932c98`.
Les 283 tests ciblés passerelle/protocole/service passent ; ils restent
synthétiques. Cette étape ne valide pas encore une partie réelle ni une
installation Windows vierge. Les essais de ROM sont coordonnés séparément.

Les archives des sources des dépendances sont livrées dans une annexe commune,
afin de ne pas recopier plusieurs centaines de Mo dans chaque partie. Les
notices non installées dans `share/licenses` par MSYS2 (ENet, FAAD2, LZ4 et la
notice ICU située dans `share/icu/78.3/LICENSE`) doivent également être présentes
dans cette annexe. Le manifeste `pce-bridge.json` ne référence que les fichiers
immuables utiles à l'exécution ; `component-manifest.json` couvre aussi l'archive
des sources modifiées de melonDS.

## Essais de jeu après le build natif

Les essais des 21–22 octobre ont ensuite vérifié l'équipe et la migration /
sauvegarde / reprise sur Blanc FR0, ainsi qu'une équipe réelle sur Noir 2 FR0.
Le [rapport d'intégration](v0.5-melonds-validation.md) détaille les preuves et
les échecs rencontrés, notamment le correctif TOML indispensable au vrai démarrage.
Noir et Blanc 2 conservent un statut synthétique pour cette passerelle.


## Commandes natives 1.1-pce.2

Le Mode Jeu active ses boutons de vitesse après réception de la capacité native
et vérification du processus lancé, de la session, du nonce d'instance, du SHA-256
de la ROM chargée et du dossier de states. L'onglet **melonDS** donne accès aux
vitesses x1/x2/x4/MAX, à la disposition naturelle/verticale/horizontale/hybride et
aux slots 1 à 8. Les boutons clavier/manette et graphismes ouvrent les fenêtres
natives de cette instance ; ils n'émulent pas de clics ou de raccourcis Windows.
Les mappings Qt des douze boutons sont lus dans la configuration native.
L'ancien composant pce.1 conserve son suivi et ses menus, sans déclarer ces capacités.

`PCECommands.h` traite un seul fichier atomique `melonds-command.json` à la fois,
avec PID, session, nonce, SHA-256 de ROM, séquence strictement croissante et date
limite de cinq secondes. Les commandes expirées ou rejouées ne sont pas exécutées.
La fenêtre zéro de l'instance zéro traite les actions sur le thread UI, en passant
par les messages synchronisés d'`EmuThread` pour la sérialisation des states.
Un changement ou un échec de chargement de cartouche invalide les commandes
jusqu'à une nouvelle session. Aucun chemin de state n'est fourni par le message.
Les liens/jonctions et chemins sortant du dossier configuré sont refusés.

`melonds-command-result.json` confirme le résultat retourné par l'API native.
PCE distingue la commande en attente du réglage appliqué et d'un résultat
non confirmé. La vitesse est un réglage cible, pas une mesure de FPS ni une
garantie de multiplicateur sur toutes les machines. Ce réglage de vitesse ne
modifie que la session courante.

La sauvegarde d'un slot est d'abord sérialisée dans un fichier temporaire du
même dossier, puis remplacée par `QSaveFile` ; un échec conserve l'ancien slot.
Le chargement et l'enregistrement sont refusés si Relocate savefile est activé.
PCE demande confirmation avant remplacement ou chargement et conserve l'historique
du challenge lorsque le jeu revient en arrière. Les politiques forbidden et
read_only interdisent ces actions depuis PCE ; outside_battle exige une absence
de combat confirmée et reste donc refusée sans lecteur fiable. Les menus melonDS
restent accessibles : ces politiques ne constituent pas un verrouillage du jeu.
Aucune ROM ni sauvegarde d'origine n'est ciblée par les commandes.

Pour les validations automatisées, `input_pulse` utilise `NDS::SetKeyMask` au
point d'entrée des boutons natifs, sans accès RAM arbitraire ni dépendance au focus
Windows. Le masque actif haut comprend A=1, B=2, Select=4, Start=8, droite=16,
gauche=32, haut=64, bas=128, R=256, L=512, X=1024, Y=2048. Une impulsion dure
1 à 60 frames exécutées et expire au plus tard après deux secondes monotones.
Elle conserve les boutons physiques simultanés. L'accusé de succès est émis
après les frames demandées et une frame de relâchement ; une pause trop longue
produit un échec, et la reprise reçoit le masque relâché. Cette API n'offre ni
entrée maintenue sans limite, ni écriture mémoire, ni chemin de fichier arbitraire.

Les tests `test_melonds_commands.py` et `test_melonds_commands_native.py` couvrent
le transport, les refus, les accusés, les politiques et les entrées bornées.
Le test natif compile les en-têtes livrés et nécessite `PCE_CXX` pointant vers le
compilateur local du build melonDS (Qt5 installé dans ce même préfixe). Ces tests
sans ROM ne remplacent pas les essais de jeu, de save states réels ou de manette.
