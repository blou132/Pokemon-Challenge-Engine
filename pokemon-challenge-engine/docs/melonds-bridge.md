# Passerelle melonDS en lecture seule

La base est la version officielle stable **1.1**, commit
`b86390e4428bf38ce4c1ce0e9ca446d6d25955e8`, publiée le 18 novembre 2025.
Sources : [release officielle](https://github.com/melonDS-emu/melonDS/releases/tag/1.1),
[annonce](https://melonds.kuribo64.net/comments.php?id=240).
Le composant modifié est identifié **1.1-pce.1**. Le binaire officiel non modifié
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
