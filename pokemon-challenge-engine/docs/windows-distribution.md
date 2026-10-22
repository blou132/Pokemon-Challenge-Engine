# Distribution Windows

La distribution `onedir` lance `Pokemon-Challenge-Engine.exe` sans console et sans
Python installé par l'utilisateur. Le dossier `_internal` doit rester près de
l'EXE. L'icône géométrique est celle de l'application ; la version est issue de
`app.__version__`, sans modification automatique du numéro de version.
La version numérique courante est `0.5.0` ; l’interface indique explicitement
« en validation », sans présenter cette étape comme une validation achevée.

## Données personnelles

Les ressources `data`, `lua` et `tools/randomizer` sont immuables. L'application
Python continue d'utiliser son dossier existant. L'EXE utilise par défaut
`%LOCALAPPDATA%/Pokemon-Challenge-Engine` pour les parties, les copies ROM,
sauvegardes, states, backups, profils, préférences et journaux tournants.
Une mise à jour de l'EXE ne remplace pas ce stockage.

`--data-dir` permet un chemin absolu explicite. Un dossier non inscriptible,
un lien/jonction ou une destination dans `_internal` produit une erreur ; aucun
repli silencieux vers un dossier vide ne masque les anciennes parties.

`Enable-Portable-Mode.vbs` crée facultativement `pce-portable.json` contenant
`{"schema_version":1}` près de l'EXE. Le stockage devient `user-data` au même
emplacement. Les données précédentes restent conservées dans LOCALAPPDATA.
Le marqueur peut aussi être créé avec un éditeur de texte si les scripts VBS
sont désactivés par Windows. Le dossier portable doit être disponible hors ligne
et inscriptible. Lors des mises à jour, conserver `user-data` et le marqueur.

L'import dans **Paramètres → Données et anciennes parties** affiche le nombre
de parties, modèles et préférences avant confirmation. Il copie vers un staging
local, vérifie les empreintes et la stabilité des sources, puis publie les
dossiers nouveaux sous le verrou de parties. Toute collision est refusée ; les
préférences déjà présentes sont conservées. Une erreur pendant la publication
peut laisser les dossiers déjà importés, sans remplacer les originaux. Le message
d'erreur ne prétend donc pas annuler une publication déjà accomplie.

Les environnements DeSmuME `play` et melonDS `play-melonds` actifs sont
relocalisés dans leurs copies : chemins ROM/sauvegarde/states/backups,
INI ou TOML et clé de recherche des backups. Les fichiers de provenance,
l'historique et un ancien environnement DeSmuME conservé après migration ne sont
pas réécrits. Les sources, ROM externes et sauvegardes originales ne sont
jamais modifiées. Fermer l'ancien PCE et les émulateurs avant l'import, puis
redémarrer la nouvelle application.

**Déplacement d'un dossier portable existant :** les chemins de parties sont
absolus ; déplacer `user-data` seul ne les répare pas automatiquement.
Démarrer PCE avec un dossier de données neuf (`--data-dir`), puis utiliser
**Paramètres → Données et anciennes parties** pour importer le dossier
déplacé. L'ancien emplacement n'a pas besoin d'exister : son ancrage est déduit
uniquement des chemins cohérents `runs/<UUID>/play` ou `play-melonds`, puis
vérifié avec les manifestes, identités et empreintes des fichiers copiés.
Aucune ROM ni sauvegarde n'est ouverte à son ancien chemin. Un espace non
reconnu, des chemins mélangés ou externes, une empreinte modifiée ou une
sauvegarde attendue absente interrompent l'import avant publication. Le dossier
déplacé reste intact ; une collision dans la destination n'est jamais écrasée.

## Construction reproductible

Depuis la racine du dépôt, avec un Python Windows existant :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r pokemon-challenge-engine\packaging\windows\requirements-build.txt
.\.venv\Scripts\python.exe pokemon-challenge-engine\packaging\windows\fetch_qt_sources.py --output runtime\qt-sources
.\.venv\Scripts\python.exe pokemon-challenge-engine\packaging\windows\build_windows.py --output runtime\windows-build --qt-sources runtime\qt-sources
```

Le dossier de sortie doit être nouveau. Le script refuse de supprimer ou
d'écraser un ancien build. Il produit l'EXE, le ZIP, son SHA256 et un inventaire
SHA256 des fichiers avec les versions des dépendances. La recette fixe
PyInstaller 6.22.3, ses dépendances et PySide6 6.11.2. Le contrôle initial a
utilisé CPython 3.13.7 x64. Il ne promet pas des octets identiques entre deux
versions de Python ou de Windows.

Seuls les catalogues JSON, le Lua, les sources Java et notices attendues sont
embarqués. Les outils externes locaux, configurations, ROM et sauvegardes sont
exclus. L'analyse de bibliothèques Windows vient du runtime Python et des wheels
officiels ; aucun dossier d'émulateur de l'utilisateur n'est parcouru.

Les modules Qt inutilisés PDF/Quick/VirtualKeyboard sont exclus en retirant leurs
plugins optionnels. Le build bloque si un module Qt supplémentaire n'a pas de
source correspondante dans le périmètre déclaré. Les archives sources officielles
Qt Base, SVG, Image Formats, Translations et PySide/Shiboken sont livrées avec les
notices, leurs URL et SHA256 vérifiés sur le serveur Qt. Les bibliothèques restent
dynamiques et remplaçables ; les sources PCE et la recette sont aussi incluses.

Sources primaires : [PyInstaller onedir et windowed](https://pyinstaller.org/en/stable/usage.html),
[chemins à l'exécution](https://pyinstaller.org/en/stable/runtime-information.html),
[licences Qt](https://doc.qt.io/qt-6/licensing.html),
[sources Qt 6.11.2](https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/),
[sources PySide 6.11.2](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/).

## Composants tiers optionnels

Ajouter `--component CHEMIN` à la construction pour inclure un composant déjà
compilé et vérifié. Il est copié dans `third-party/<name>` près de l'EXE, avec son
manifeste. Le composant melonDS utilise `name: "melonDS"` ; son chemin est donc
`resolve_app_paths().installation / "third-party" / "melonDS"`.
Les nouvelles parties présélectionnent melonDS uniquement si son composant est
vérifié. DeSmuME reste sélectionnable et reste le défaut sans composant valide.
Le moteur des parties et profils existants n’est pas modifié.

`component-manifest.json` doit contenir `name`, `version`, `source_url` HTTPS,
`license_file` et `files` (chemins relatifs POSIX associés à leur SHA256). Les
fichiers non listés sont exclus. Traversées, liens, empreintes incorrectes,
licence absente et extensions ROM/sauvegarde/firmware sont refusés. Les empreintes
prouvent la concordance avec ce manifeste ; la validation du composant et de sa
provenance doit avoir lieu avant sa remise au builder.

Les dépendances de melonDS conservent leurs notices et sources correspondantes.
`fetch_msys_sources.py` récupère les archives sources exactes publiées par MSYS2
et vérifie leurs signatures avec le keyring local pacman. `--curl` peut utiliser
le curl Windows existant lorsque le magasin de certificats Python échoue ; TLS
reste vérifié. Les sources peuvent être distribuées dans une annexe clairement
identifiée avec le paquet melonDS. Aucune installation système n'est effectuée.

L'annexe préparée est `runtime/Pokemon-Challenge-Engine-melonDS-dependency-sources.zip`
(SHA256 `e7f2937a5908e05d87e1ec3c46386a1b36622f9e30472a322132e3230643082c`).
La joindre à côté du ZIP principal dans la livraison et les redistributions qui
incluent melonDS. Ses 14 sources exactes, signatures et notices complémentaires
sont inventoriées dans son README et ses manifestes. L'annexe est indépendante
du manifeste runtime immuable de melonDS ; elle n'est pas copiée dans les parties.

Le composant Randomizer peut être préparé par
`packaging/windows/prepare_randomizer_component.py --output DOSSIER_NEUF --cache DOSSIER_CACHE --curl CHEMIN_CURL --zx-jar CHEMIN_JAR_ZX`.
Le script télécharge Eclipse Temurin OpenJDK **21.0.12.1+1** Windows x64 et ses
sources complètes depuis la release officielle Adoptium, vérifie leurs SHA256
publiés et inclut le JAR ZX officiel **4.6.1** uniquement si son empreinte est
exacte. Les sources ZX du commit fixé sont également embarquées. Il lance le JDK
avec PATH Windows uniquement et contrôle la version et `jdk.compiler`.
Il ne modifie ni JAVA_HOME, ni PATH, ni le registre, et n'installe rien globalement.

Passer ce dossier au builder avec un second `--component` l'installe dans
`third-party/randomizer`. Les outils sont alors trouvés automatiquement, y compris
par la préparation ROM lorsqu'aucune configuration locale n'existe. Une
configuration utilisateur existante, même invalide, est conservée sans substitution.
Les anciens fichiers ne sont pas réécrits pour pointer vers le JDK livré.
Sans ce composant, l'installation explicite d'un JDK 11+ et du JAR reste disponible.
Aucun Oracle JDK local ni firmware Nintendo n'est collecté.

Références : [licence et redistribution Temurin](https://adoptium.net/docs/faq/),
[release exacte](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1).

## Vérification de l'EXE

```powershell
.\.venv\Scripts\python.exe pokemon-challenge-engine\packaging\windows\check_executable.py --exe runtime\windows-build\dist\Pokemon-Challenge-Engine\Pokemon-Challenge-Engine.exe --output runtime\exe-check
```

Le pilote démarre deux fois le véritable EXE depuis un dossier TEMP neuf hors du
dépôt, avec PATH limité à Windows et sans PYTHONPATH, PYTHONHOME ni environnement
virtuel. Il utilise des données de contrôle neuves dans un chemin avec espaces
et accents. Il vérifie la fenêtre Qt, la navigation, les catalogues et ressources,
la configuration, puis la même identité de partie et les trois badges synthétiques
après redémarrage. Il produit deux captures et des rapports JSON.

Cette vérification n'émule pas un jeu, n'utilise aucune ROM personnelle et ne
constitue pas un essai sur une installation Windows vierge. Les marqueurs
portables et migrations DeSmuME sont également couverts par pytest avec fixtures
synthétiques, sans présentation comme preuve de jeu réel. Les contrôles
melonDS/jeux et la suite complète relèvent de la validation finale intégrée.
