# Réglages DeSmuME — V0.3.5

PCE importe les commandes clavier et propose des réglages graphiques pour un
binaire Windows identifié par SHA-256. Une version inconnue ne reçoit aucune
capacité d'export par déduction de son nom de fichier. Les pages restent utilisables
pour préparer des profils locaux. Aucun réglage ne modifie la RAM, une ROM ou une
sauvegarde Pokémon.

## Identification et niveau de preuve

Le binaire reconnu a l'empreinte
`34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
La fenêtre de l'exemplaire testé s'annonce comme
`DeSmuME 0.9.14 git#a779eb7 x64-JIT SSE2`.

Le format est documenté dans les sources officielles DeSmuME, révision épinglée
`1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a`. La présence des noms des réglages dans le
binaire a également été vérifiée. Cette provenance explique la capacité
`documented_source_and_binary` : elle ne signifie pas que tous les rendus, toutes
les cartes graphiques ou toutes les fréquences ont été testés réellement. Le
compte rendu des essais sur copie figure dans [verification.md](verification.md).

`supports_speed_control` reste faux : PCE n'envoie aucun raccourci d'accélération
à une fenêtre externe. `supports_speed_config` indique uniquement la possibilité
d'enregistrer le limiteur avant un prochain lancement. `supports_lua` requiert
le binaire reconnu et la présence de `lua51.dll` et `lua5.1.dll` ; c'est une
détection de prérequis, pas un heartbeat. Shaders et remappage des manettes ne sont
pas déclarés disponibles.

## Commandes et raccourcis

La page **Contrôles** lit les douze valeurs de `[Controls]` : `Up`, `Down`, `Left`,
`Right`, `A`, `B`, `X`, `Y`, `L`, `R`, `Start`, `Select`. Ce sont des codes clavier
Windows, pas des caractères saisis ni des scancodes inventés. Les valeurs absentes
reprennent les défauts de DeSmuME : flèches, A=X, B=Z, X=S, Y=A, L=Q, R=W,
Start=Entrée, Select=Maj droite. Sources :
[défauts inputdx.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/inputdx.cpp#L229),
[lecture et écriture](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/inputdx.cpp#L484).

**Réinitialiser** et **Charger le brouillon** modifient seulement les champs de
PCE. **Exporter vers DeSmuME** est l'action explicite qui écrit le fichier INI,
avec backup préalable. Les profils nommés résident dans `controls.local.json`,
ignoré par Git, et peuvent être sélectionnés dans un profil de lancement.

Les raccourcis simples FastForward, FastForwardToggle, IncreaseSpeed,
DecreaseSpeed, Pause et FrameLimitToggle sont éditables. Les raccourcis comportant
un champ ` MOD` non nul sont affichés indisponibles pour l'édition et restent
intacts. L'export ne réécrit que les raccourcis explicitement changés dans les
champs de PCE. Les autres commandes et modificateurs restent dans le fichier.
Le format `[Hotkeys]`, clé et clé suivie de ` MOD`, est défini par
[LoadHotkeyConfig/SaveHotkeyConfig](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/inputdx.cpp#L412).

Les conflits des touches simples sont refusés, y compris avec les raccourcis de
chargement d'état et de sélection de slot documentés, ainsi qu'avec les valeurs
présentes dans la section Hotkeys. Les raccourcis de PCE sont distincts, facultatifs
et actifs seulement lorsque sa fenêtre a le focus. Les combinaisons PCE dupliquées
sont refusées. Un avertissement invite à choisir un modificateur pour une touche
simple déjà utilisée par DeSmuME.

Une affectation manette déjà présente est montrée comme un code DeSmuME, avec
périphérique non vérifié. PCE ne prétend ni détecter le modèle ni connaître son
ordre DirectInput. Configurez la manette dans DeSmuME ; l'export de ces codes par
PCE est refusé.

## Vitesse : demandé et confirmé

Les choix x1, x2, x4 et MAX du Mode Jeu sont des **états demandés**. Ils ne sont
jamais présentés comme une cadence mesurée. Changer ce choix en cours de jeu ne
pilote pas DeSmuME.

| Réglage documenté | Signification | Traitement PCE |
|---|---|---|
| `[FrameLimit] FrameLimit=1` | Active le limiteur | Export x1 avant lancement |
| `[FrameLimit] FrameLimit=0` | Désactive le limiteur | Export MAX avant lancement |
| `[Video] FPS Scaler Index=5` | Index du multiplicateur x1 | Export avec x1 |
| Index 1 / 0 | Multiplicateur x2 / x4 dans les fonctions d'accélération | Pas d'export promettant son application au démarrage |
| `[Video] FrameSkip` | Saut d'affichage de certaines images | Conservé, jamais utilisé comme multiplicateur |

Le code initialise `desiredfps` à la fréquence native. L'index INI est chargé
séparément, et `IncreaseSpeed` / `DecreaseSpeed` appliquent effectivement son
facteur. Écrire uniquement l'index ne prouve donc pas une vitesse x2 ou x4 au
prochain lancement. Un profil demandant leur export reçoit une erreur lisible,
sans écrire l'INI. Utilisez les raccourcis DeSmuME importés pour régler ces vitesses
dans l'émulateur. FastForward maintenu suspend le limiteur ; sa vitesse dépend du
matériel, ce n'est pas une garantie x2 ou x4.

Sources :
[throttle.cpp, facteurs et changement de fréquence](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/throttle.cpp#L36),
[limiteur et FastForward dans la boucle](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L1363),
[raccourcis d'accélération](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/hotkey.cpp#L683).

## Graphismes vérifiés dans les sources

| Option | Section / clé | Valeurs |
|---|---|---|
| Résolution interne 3D | `3D / PrescaleHD` | 1 à 16 dans le format ; choix 1 à 4 dans PCE |
| VSync | `Video / VSync` | 0 / 1 |
| Interpolation de sortie OpenGL | `Video / Display Method Filter` | 0 / 1 |
| Proportions | `Video / Window Force Ratio` | 0 / 1 |
| Mise à l'échelle entière | `Video / Window Pad To Integer` | 0 / 1 |
| Disposition DS | `Video / LCDsLayout` | 0 verticale, 1 horizontale, 2 un écran |
| Rotation | `Video / Window Rotate` et `Window Rotate Set` | 0, 90, 180, 270 degrés |

Sources :
[lecture des options vidéo](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L1963),
[résolution interne](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L2295),
[plage 1–16](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L5704).

Les presets ne font que préparer ces valeurs : Original = résolution 1,
interpolation désactivée, proportions conservées ; Net ajoute l'échelle entière ;
HD choisit la résolution interne 2 ; Performance revient à résolution 1,
interpolation et VSync désactivées. Ils ne remplacent ni les textures ni les sprites
2D. L'interpolation de sortie dépend du moteur OpenGL déjà choisi dans DeSmuME ;
PCE ne change pas le moteur de rendu. Aucun shader non vérifié n'est proposé.

## Identification du fichier, backup et écriture

Le service exige un `desmume.ini` existant à côté de l'exécutable reconnu. Si
l'exécutable réside dans le dossier temporaire Windows, l'emplacement peut dévier
vers le dossier utilisateur : PCE refuse cette situation ambiguë. Les fichiers
symboliques sont refusés. Source de la résolution et du BOM Unicode :
[winutil.cpp / GetINIPath](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/winutil.cpp#L36).

Avant un export, PCE vérifie que l'émulateur est fermé. Il prépare un fichier
temporaire, préserve l'encodage et les fins de ligne, puis crée un backup exact
avant le remplacement atomique. Le premier backup se nomme
`desmume.ini.pce-backup`, les suivants `.pce-backup.1`, `.pce-backup.2`, etc.
**Aucun backup n'est écrasé ou supprimé automatiquement.** Les commentaires,
sections et clés inconnues restent conservés. Des sections ou clés dupliquées,
un fichier trop grand ou des valeurs connues invalides arrêtent l'export.

Le contenu de l'INI et l'état du processus sont revérifiés avant le remplacement.
En cas de fichier verrouillé, d'accès refusé ou de modification concurrente,
l'original reste conservé. Fermez également les outils externes qui éditent ce
fichier pendant l'export. Une relecture du fichier après export confirme les
valeurs enregistrées, pas l'état matériel du rendu en cours.

## Tests et limites

Les tests synthétiques couvrent les encodages ANSI et UTF avec BOM, commentaires,
doublons, valeurs invalides, refus de version inconnue, défauts clavier, profils,
conflits, modificateurs conservés, backups successifs, erreurs d'écriture,
émulateur encore lancé, presets et interfaces Qt. Ils n'imitent pas une validation
réelle de DeSmuME. Pour les graphismes et raccourcis de la configuration utilisateur :
**En attente de validation sur la machine utilisateur.**
