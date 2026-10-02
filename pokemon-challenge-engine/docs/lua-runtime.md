# Support Lua local — V0.3.6

Le diagnostic trouve DeSmuME dans les dossiers proposés par la détection RetroBat
ou déjà configurés. Il inspecte le contenu PE de l'exécutable sans le charger :
architecture, type EXE/DLL, SHA-256, marqueurs DeSmuME et référence à `lua51.dll`.
Le nom du fichier ne suffit jamais. La recherche ne descend pas récursivement dans
les disques ; ses dossiers et nombres d'entrées sont bornés.

Pour le binaire déjà validé, l'empreinte permet d'afficher
`DeSmuME 0.9.14 git#a779eb7 x64-JIT SSE2`. Sur un autre binaire, les ressources de
version sont lues si elles existent ; sinon la version reste inconnue. Une
identification par marqueurs n'est pas une validation réelle du build.

## Source unique du téléchargement

L'installation utilise exclusivement le fichier du dépôt officiel
[TASEmulators/desmume, lua.7z](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/lua/lua.7z),
révision `1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a`.

URL de téléchargement épinglée :
`https://raw.githubusercontent.com/TASEmulators/desmume/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/lua/lua.7z`.

L'archive réellement téléchargée et inspectée fait **166 260 octets**, avec SHA-256
`3814c8c1b884170176ea336cebf03da4e32908dc66394b238959df02a5d1e4a3`.

`TrustedDownloadService.download_lua()` n'accepte aucune URL fournie par un jeu ou
par l'utilisateur. Il emploie HTTPS, refuse les redirections, limite la taille à
1 Mio, utilise un timeout réseau et un fichier temporaire. La taille exacte et
l'empreinte doivent correspondre avant publication dans le cache. Un cache
existant est recontrôlé avant réutilisation. Un téléchargement incomplet ne devient
pas une archive installable. Cette fonction ne télécharge ni ROM, ni BIOS, ni
sauvegarde.

## Empreintes effectivement observées

| Architecture PE | Membre officiel | Taille en octets | SHA-256 |
|---|---|---:|---|
| x64 (`0x8664`) | `x64/lua51.dll` | 11 776 | `a85ced1c2078348684b74bcc20074f63a73d02881e5dcd002581ed757d8adf86` |
| x64 (`0x8664`) | `x64/lua5.1.dll` | 314 880 | `23719300fa4ae3116e97c313b838945bb2c1e02094daee8165939059aaad82c5` |
| x86 (`0x014c`) | `win32/lua51.dll` | 11 264 | `b2ba19343691f22d1af1417f9a7cbaeae74ba820a2a412f5a6cdea271cc1a7b0` |
| x86 (`0x014c`) | `win32/lua5.1.dll` | 167 936 | `26384c6ee7d50863e3fb65fdc1bad452d9311f34d782390401de9bb130eecc4a` |

Les quatre membres ont été extraits réellement et leurs en-têtes PE examinés.
L'architecture vient du champ COFF `Machine`, avec cohérence de l'en-tête optionnel,
et le drapeau DLL doit être présent. Le parseur vérifie les bornes des en-têtes et
sections ; il ne charge jamais un binaire trouvé pour l'identifier. Référence :
[format PE Microsoft](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format).

L'extraction privilégie `tar.exe` du dossier système Windows, dont la lecture de
cette archive 7z/LZMA/BCJ2 a été testée réellement. 7-Zip installé dans Program Files
constitue le repli. Le service demande uniquement les deux membres attendus via
la sortie standard de l'outil, sans extraire les chemins de l'archive dans le
système de fichiers. Chaque résultat est à nouveau contrôlé par taille, hash et
architecture. `lua51.lib` n'est pas installé : il ne sert pas à l'exécution.

## Installation explicite et réversible

Le bouton d'installation ou de réparation appelle `LuaRuntimeInstaller.install`.
Cette opération exige un DeSmuME identifié, une architecture x64 ou x86 et l'arrêt
de l'émulateur. Elle installe seulement les deux DLL à côté de l'exécutable ; elle
ne modifie ni PATH système, ni registre, ni configuration RetroBat, ni INI.

Une DLL déjà conforme reste intacte. Une DLL absente est ajoutée. Une DLL différente
ou d'une autre architecture exige une **confirmation de remplacement distincte**.
L'API refuse le remplacement par défaut et renvoie les chemins concernés via
`LuaReplacementRequired.paths`. Le diagnostic expose également
`EmulatorCandidate.replacement_required`.

Avant chaque remplacement autorisé, une copie exacte est créée sous
`lua51.dll.pce-backup` ou `lua5.1.dll.pce-backup`. Si ce nom existe, un suffixe
numérique libre est choisi. Aucun ancien backup n'est écrasé ou supprimé.
Les fichiers préparés sont synchronisés sur disque puis remplacés atomiquement
un par un. Le processus et le contenu des destinations sont revérifiés avant les
copies. Les liens symboliques et destinations non régulières sont refusés.

Si une copie échoue, les changements déjà effectués sont annulés lorsque la
destination correspond encore au fichier installé par PCE. Une modification
externe ne sera pas écrasée pour tenter une restauration. Si la restauration
échoue aussi, le message signale les backups à utiliser. Les deux DLL ne constituent
pas une transaction atomique face à une coupure de courant ; le diagnostic suivant
identifiera une installation partielle et proposera sa réparation.

La réinstallation de deux DLL déjà conformes est sans effet. Les permissions
refusées, fichiers verrouillés ou manque d'espace sont remontés à l'interface.
PCE n'élève pas ses privilèges et ne désactive aucune protection Windows.

## Journal et niveaux de validation

Le service reçoit un callback `journal(event, **details)` commun au diagnostic.
Sans callback, il écrit son journal JSONL dans son cache local. Les événements
comprennent téléchargement démarré/vérifié, installation démarrée, backups,
installation vérifiée ou échec. Ils précisent les chemins concernés, la source et
les empreintes, jamais le contenu d'une ROM ou d'une sauvegarde. Ces journaux et
téléchargements restent ignorés par Git.

| État | Ce qui est effectivement connu |
|---|---|
| Détecté | Le fichier existe et son en-tête est lisible. |
| Fichiers Lua vérifiés | Les deux DLL ont les empreintes officielles et l'architecture du binaire. |
| Console / API non testée | Aucun chargement dans cet émulateur n'a encore été observé. |
| Connexion réellement reçue | La passerelle a reçu des messages du script dans DeSmuME. |

`LuaDiagnostic.ready` signifie **fichiers vérifiés**, avec
`console_status="not_tested"`. L'installation seule ne prétend pas avoir appelé
`memory.readbyte` ou `emu.frameadvance`. Un heartbeat et des lectures réelles sont
nécessaires pour annoncer la connexion en fonctionnement.

## Chargement du script : capacité étudiée

Le frontend Windows appelle `LoadLibrary("lua51.dll")` dans
[DemandLua](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L1618).
Il possède aussi un autoload : `[Scripting] AutoLoad` active la recherche d'un
script `<nom-ROM-sans-extension>.lua` dans `[PathSettings] Lua` lors du chargement
de la ROM. Voir
[la branche AutoLoad](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L3026).

Cette étude n'autorise aucune modification silencieuse d'un INI existant ni le
remplacement d'un script personnel. L'installateur de DLL n'active pas l'autoload.
Le parcours de connexion retenu est décrit dans [first-run.md](first-run.md) :
la session est préparée par PCE, avec accès direct à son dossier et au chemin du
script ; l'étape Run reste manuelle lorsque l'autoload n'a pas été configuré et
testé explicitement. Aucune option CLI Lua inventée n'est utilisée.

## Vérifications réalisées

Les tests synthétiques couvrent PE x86/x64, faux exécutables, fichiers tronqués,
identification indépendante du nom, présence/absence de l'INI, installation
complète ou partielle, DLL d'une mauvaise architecture, refus du remplacement,
backup déjà existant, copie verrouillée, rollback, réinstallation idempotente,
téléchargement interrompu, redirection, mauvaise empreinte et cache corrompu.

Sur une **copie isolée** du DeSmuME connu, l'installation réelle est passée de DLL
absentes à deux DLL officiellement vérifiées ; un second appel n'a rien réécrit.
L'exécutable original a conservé son hash et sa date de modification. L'archive
officielle et les quatre DLL ont été examinées réellement ; l'exécution x86 dans
DeSmuME n'a pas été testée. Les essais de lancement et connexion Pokémon Blanc
sur copie sont rapportés séparément dans [verification.md](verification.md).
