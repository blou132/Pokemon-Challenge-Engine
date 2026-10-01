# Gestionnaire de sauvegardes — V0.3.5

La page **Sauvegardes** sépare le fichier normal `.dsv`, les dix slots DeSmuME et
les backups créés par PCE. Le choix du jeu et du fichier est explicite : le nom
de la ROM ne suffit pas à identifier la sauvegarde réellement utilisée.

## Sauvegarde normale

Choisir le jeu, puis son fichier `.dsv`. La page affiche chemin, date, taille et
jeu associé. **Ouvrir le dossier** ouvre son emplacement ; **Créer un backup
manuel** copie le fichier sans modifier son contenu ni sa date de modification.
L'association au jeu est déclarée par l'utilisateur, pas déduite du contenu de
la sauvegarde. PCE ne vérifie pas la validité interne d'une sauvegarde Pokémon.

## Backups et rétention

Le dossier dédié est configurable par jeu. Les backups au lancement, à la
fermeture et périodiques sont désactivés par défaut et doivent être cochés puis
enregistrés. Ces déclencheurs concernent l'émulateur lancé par PCE ; une session
ouverte directement depuis RetroBat n'est pas suivie automatiquement. Fermer
PCE n'arrête pas DeSmuME et ne garantit pas un backup ultérieur à sa fermeture.

Chaque copie porte le nom `game_YYYY-MM-DD_HH-MM-SS.dsv`, en UTC. Un suffixe
numérique évite tout écrasement en cas de plusieurs copies dans la même seconde.
Le service compare les métadonnées avant et après copie, relit le fichier source
et vérifie le SHA-256 de la copie. Si le fichier change ou devient inaccessible,
la copie n'est pas publiée. Cette stabilité des octets ne garantit pas que le jeu
a déjà écrit en disque toutes ses modifications en mémoire.

La rétention (5, 10, 20, 50 ou valeur personnalisée entre 1 et 10 000) s'applique
par jeu au dossier choisi. Elle ne supprime que les copies reconnues par le
manifeste `pce-backups.json`, après vérification de leur empreinte. Les fichiers
étrangers, les sauvegardes originales et les save states ne sont jamais concernés.
Un backup externe ajouté au dossier n'est pas automatiquement adopté. Les liens
symboliques et jonctions sont refusés. Le manifeste est remplacé atomiquement ;
un verrou exclusif empêche deux opérations PCE simultanées sur le même dossier.
Sur un support ne permettant pas la publication exclusive par lien de fichier,
le service refuse la copie, au lieu de remplacer un fichier existant.

Un manifeste corrompu ou une copie altérée bloque l'opération. Les erreurs de
permissions sont affichées. Après une interruption brutale, un verrou résiduel
peut nécessiter une vérification manuelle du dossier ; ne pas effacer aveuglément
ses fichiers. Une panne pendant la rétention peut laisser des copies ou des
références à examiner : le gestionnaire privilégie la conservation de l'original.

## Restauration explicite

La restauration n'est jamais automatique. Sélectionner un backup puis demander
sa restauration affiche une confirmation, désactivée si la session PCE est en
cours. La détection d'autres instances est fournie par le gestionnaire de fenêtres
de l'application. Une détection en erreur refuse la restauration. L'utilisateur
doit également confirmer que toutes les instances de DeSmuME sont fermées.
Le service vérifie l'empreinte du backup, crée une copie de sécurité du fichier
actuel, vérifie que celui-ci est toujours stable, puis le remplace atomiquement.
Le fichier cible doit déjà exister et être hors du dossier des backups.

## Save states : source documentée

La convention vérifiée est `<nom>.ds0` à `<nom>.ds9` dans le dossier
**StateSlots**, qui est distinct du dossier **States** des sauvegardes manuelles.
Elle provient de [`scan_savestates` dans le code officiel DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/saves.cpp#L744)
et des [clés de chemins officielles](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/path.h#L74).
Le dossier et le nom commun sont choisis explicitement. Un dossier absent est
signalé comme indisponible, jamais comme dix slots vides.

L'inventaire lit seulement la présence, la date et la taille des fichiers. Il ne
valide pas leur contenu, ne crée pas de miniature et n'enregistre ni ne charge
aucun slot. Les politiques **Autorisé**, **Interdit**, **Autorisé hors combat**,
**Lecture seule** et **Non géré** sont des intentions affichées, sans blocage dans
DeSmuME. Le choix « Interdit » ne désactive pas ses raccourcis.

## Vérification

Les tests du service utilisent exclusivement des fichiers synthétiques :
conservation de l'original, empreintes, collisions, rétention par jeu, fichiers
étrangers, manifeste corrompu, chemins invalides, liens, verrou concurrent,
permissions refusées, fichier changeant pendant copie et restauration confirmée.
Les tests Qt couvrent les politiques, le consentement, les erreurs, l'inventaire,
les changements de jeu et les petites/grandes fenêtres.

Les essais avec une copie de sauvegarde et un véritable émulateur sont rapportés
séparément dans [verification.md](verification.md). Aucune donnée synthétique ne
constitue une validation d'une sauvegarde ou d'un slot réellement utilisé en jeu.
