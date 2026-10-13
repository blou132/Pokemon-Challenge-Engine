# Fichiers propres à une aventure — V0.4.1

La préparation conserve `runs/<uuid>/run.json` et ajoute `play/`. La ROM porte
le jeu et l'UUID ; DeSmuME dispose de son exécutable, de ses DLL Lua locales
vérifiées et de son INI. Battery, States, StateSlots et les nouveaux backups
ont chacun une destination propre à la partie. L'installation RetroBat n'est
jamais copiée par récursion.

## Sources documentées

Ces références sont épinglées au commit officiel DeSmuME
`1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a`. Le build Windows reconnu est
identifié par empreinte dans `app/services/emulator_capabilities.py`.

| Comportement | Source officielle |
| --- | --- |
| L'INI se trouve près de l'exécutable ; TEMP déclenche une redirection particulière | [GetINIPath](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/winutil.cpp#L33) |
| Battery, States et StateSlots relatifs sont résolus depuis le module | [path.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/path.cpp#L265) |
| Battery/nom-ROM.dsv est chargé ; un .sav peut être essayé si le .dsv manque | [BackupDevice](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/mc.cpp#L203) |
| Les slots utilisent StateSlots/nom-ROM.ds0 à .ds9 ; leurs backups restent dans ce dossier | [saves.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/saves.cpp#L744) |
| L'autoload utilise le nom de la ROM dans le dossier Lua configuré | [main.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L2844) |

Changer seulement le nom ou le dossier de la ROM ne suffit pas à établir
l'isolation. La préparation refuse TEMP, les chemins trop longs, les liens et
les builds non reconnus.
Le support Lua doit être vérifié avant la copie. Si une DLL manque, réparez-le
dans **Installation & diagnostic**, puis reprenez la partie ; aucun environnement
incomplet n'est publié.

## Création, import et reprise

**Nouvelle aventure** commence sans sauvegarde copiée et sans `.dsv` fabriqué
par PCE. **Importer une sauvegarde existante** copie uniquement le fichier choisi
après confirmation. Les copies sont comparées par SHA-256 ; les sources restent
intactes. Un backup de lancement demandé avant le premier `.dsv` est différé
jusqu'à sa présence, sans désactiver l'option.

Une ancienne partie garde ses références jusqu'à **Préparer des copies
indépendantes**. Cette action copie aussi les slots et le state manuel portant
le nom de sa ROM dans les dossiers configurés. Les autres noms ne sont pas
associés par supposition. Règles, sessions, historique et anciens backups sont
conservés.

`play/isolation.json` permet de contrôler identité, empreintes et chemins avant
lancement. Une copie manquante ne déclenche pas de réassociation avec RetroBat.
Un `.dsv` importé, ou déjà observé lors d'une vérification, ne peut pas disparaître
silencieusement : PCE demande une restauration. Un marqueur `save-observed.json`
mémorise cette observation sans écrire dans le fichier du jeu.
Cette présence est aussi constatée à la fermeture du processus, même lorsque
les backups automatiques sont désactivés.

## Fermeture et suppression

Le changement de partie demande confirmation, puis une fermeture normale du
processus suivi. Après son arrêt, Lua est arrêté avant activation du nouvel UUID.
La fermeture utilise [WM_CLOSE](https://learn.microsoft.com/windows/win32/winmsg/wm-close),
sans terminaison forcée ; une confirmation de DeSmuME doit être traitée dans sa
fenêtre. Enregistrez dans le jeu avant de confirmer le changement.

La suppression exige une session arrêtée, la sauvegarde finale du suivi et son
détachement. Le dossier, les fichiers et les références externes conservées sont
présentés dans la confirmation. L'inventaire et les empreintes sont revérifiés.
Une modification, un lien, un processus ouvert ou une référence entrante d'une
autre partie bloque la suppression. Un échec disque peut laisser une suppression
partielle : le message le signale, sans annoncer de retour arrière complet.
L'archivage conserve tous les fichiers.

## Portée des vérifications

Les tests automatisés utilisent des ROM et sauvegardes synthétiques pour les
copies, conflits, erreurs, imports et suppressions. Ils ne prouvent pas le
chargement d'une sauvegarde par un vrai jeu. Les essais réels et leurs limites
sont consignés séparément dans [verification.md](verification.md).

PCE ne bloque pas les commandes utilisées directement dans DeSmuME. Les règles
de challenge restent distinctes de l'isolation : aucune écriture RAM ni
modification du contenu d'une ROM n'est ajoutée.
