# Parties indépendantes et migration melonDS

L'intégration conserve le modèle profil/partie et le backend DeSmuME. Une nouvelle
partie peut sélectionner melonDS lorsque son composant PCE est installé et que le
SHA-256 de son manifeste figure dans la liste des distributions vérifiées.
Un manifeste simplement ajouté auprès d'un exécutable ne suffit pas à l'autoriser.

Le Mode Jeu et la page **Connexion melonDS** affichent les états du suivi de
l'aventure sélectionnée. Le suivi démarre avec **Jouer** ; aucun script Lua n'est
à ouvrir pour melonDS. En cas de déconnexion, fermez melonDS puis relancez la
partie avec **Jouer**. Les boutons de connexion du diagnostic renvoient au Mode
Jeu afin de conserver l'association entre le processus et sa session. Une
connexion confirmée ne remplit jamais une équipe dont aucune lecture valide
n'a été reçue. Les aventures DeSmuME conservent leurs instructions Lua.

## Commandes dans le Mode Jeu

PCE ne pilote pas la vitesse ni le mapping de melonDS. Les boutons x1/x2/x4/MAX,
leurs raccourcis PCE et les exports de réglages DeSmuME sont désactivés pour une
aventure melonDS. Aucun changement de vitesse n'est annoncé comme appliqué.
Utilisez les menus de la fenêtre melonDS :

- **Config > Input and hotkeys** : clavier, manette et raccourcis natifs.
- **Config > Interface settings > Framerate** : cadence et avance rapide.
- **Config > Video settings** : réglages vidéo.
- **File > Save state / Load state** : création et chargement des états.

Ces chemins sont vérifiés dans `Window.cpp` et `InterfaceSettingsDialog.ui` du
[melonDS 1.1 épinglé](https://github.com/melonDS-emu/melonDS/tree/b86390e4428bf38ce4c1ce0e9ca446d6d25955e8/src/frontend/qt_sdl).
L'inventaire PCE consulte les fichiers `.mlN` sans les créer ni les charger ;
la politique du challenge reste déclarative. Le backup de batterie et le plein
écran PCE restent disponibles. **Organiser les fenêtres** utilise le placement
Windows sur l'unique fenêtre du PID et de l'exécutable lancés par PCE, sans
commande d'émulateur ni saisie clavier. Un résultat absent ou ambigu est refusé.

## Fichiers et sauvegardes

- DeSmuME utilise `runs/<id>/play/`. melonDS utilise `runs/<id>/play-melonds/`.
- Chaque environnement possède sa ROM, son exécutable et ses dépendances copiés,
  sa configuration, sa batterie, ses save states et ses backups.
- Le bouton **Copier cette aventure vers melonDS…**, dans les sauvegardes d'une
  partie, demande la fermeture de l'émulateur et copie la ROM sans la transformer
  à nouveau. L'identifiant, le seed, les règles et l'historique restent conservés.
- L'ancien environnement DeSmuME reste intact. Le nouveau dossier contient aussi
  la sauvegarde source copiée et `migration/source-run.json`, références précédentes
  conservées pour une récupération contrôlée. Il n'y a pas de retour automatique
  vers une ancienne progression après une session melonDS.
- Les save states DeSmuME ne sont pas convertis. La reprise utilise la dernière
  sauvegarde **dans le jeu**, pas l'état exact au moment de la fermeture.
- Les backups conservent l'extension `.dsv` ou `.sav`. Une restauration ne change
  jamais implicitement de format. Les slots `.ds0…9` et `.ml0…9` restent distincts.
- `Savestate.RelocSRAM` est désactivé : l'option native de batteries distinctes
  par save state déplacerait la progression hors du fichier suivi par PCE.
- BIOS externes, firmware Nintendo, cartes SD/DLDI et GDB ne sont pas activés.
  Les commandes, manettes, écrans et graphismes se règlent dans **Config** de
  melonDS ; l'export INI DeSmuME n'est pas appliqué au moteur melonDS.

L'import des anciennes données vers la distribution Windows recopie ces fichiers
sans remplacer une partie déjà présente. Il adapte les chemins des sorties dans
`melonDS.toml` et la recherche de backups ; il conserve les autres réglages ainsi
que les références historiques et la provenance des transformations.

## Conversion documentée

Le [format DSV officiel](https://github.com/TASEmulators/desmume/blob/master/desmume/doc/dsv.txt)
décrit une batterie brute suivie d'un pied de fichier.
[`BackupDevice::readFooter` et `ensure`](https://github.com/TASEmulators/desmume/blob/master/desmume/src/mc.cpp)
précisent sa lecture et son écriture. Le convertisseur PCE accepte seulement la
version 0, une batterie Gen V de 524 288 octets, un adressage de trois octets et le
pied de fichier actuel de 122 octets, terminé par le marqueur de 16 octets.
Il vérifie la taille écrite, la taille rembourrée et le marqueur avant de copier
les octets de la batterie, sans les réinterpréter ni les modifier.

Les destinations, la configuration portable et la convention des slots sont
documentées par les sources melonDS 1.1, commit
[`b86390e4428bf38ce4c1ce0e9ca446d6d25955e8`](https://github.com/melonDS-emu/melonDS/tree/b86390e4428bf38ce4c1ce0e9ca446d6d25955e8/src/frontend/qt_sdl),
notamment `main.cpp`, `Config.cpp`, `CLI.cpp` et `EmuInstance.cpp`.

## Niveau de vérification

Les tests automatisés couvrent les copies, l'absence d'écrasement, la protection
des ROM sources, la migration, les chemins, les sauvegardes disparues, les
configurations dangereuses, les formats de backup et le refus d'une nouvelle ROM
dérivée avec une ancienne sauvegarde. Les tests de pont utilisent des PK5 et des
frames synthétiques ; ils ne constituent pas une validation sur console émulée.

Le test natif `tests/test_melonds_native_config.py` compile un petit programme
C++ avec le parseur et le sérialiseur TOML du checkout melonDS épinglé. Il
reproduit le refus d'un parent `[DSi]` implicite lorsqu'un réglage scalaire est
ajouté, puis vérifie la sérialisation de la configuration PCE. Il ne lance pas
l'émulateur et n'ouvre aucune configuration utilisateur. Pour l'exécuter,
définissez `PCE_MELONDS_SOURCE` vers ce checkout et `PCE_CXX` vers son compilateur
`g++`, puis lancez `python -m pytest tests/test_melonds_native_config.py -q`.
Sans ces deux entrées locales explicites, ces tests sont marqués non exécutés.

Une copie du DSV réel de Pokémon Blanc a été convertie en batterie brute avec
vérification du hash inchangé de la source. Cela vérifie la conversion de ce
fichier, **pas encore sa reprise dans melonDS**. La validation de l'exécutable
natif, de la lecture effective de l'équipe et de la sauvegarde/reprise est une
étape distincte à consigner dans le rapport de vérification final.

Le lancement depuis PyInstaller rétablit temporairement la recherche Windows de
DLL lors de la création d'un processus externe, puis restaure celle de PCE avant
d'attendre le processus. Les variables Qt du parent ne sont pas transmises aux
émulateurs. Voir les [instructions officielles PyInstaller](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).
