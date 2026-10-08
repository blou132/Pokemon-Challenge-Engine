# Détection et préparation locales — V0.4.1

Ces services lisent une installation existante. Ils ne téléchargent jamais de
ROM, de sauvegarde ou de contenu Nintendo et ne modifient pas les originaux.
Le [premier démarrage](first-run.md) décrit leur orchestration avec le diagnostic
DeSmuME et l'installation séparée du [runtime Lua](lua-runtime.md).

## Parcours normal

`AutoSetupService.automatic_setup()` utilise les services de découverte dès le
démarrage de PCE. L'interface présente le résultat dans **Mes parties**, **Paramètres**
et **Installation & diagnostic**. Aucun clic sur **Tester les chemins** ni aucune
étape **Préparer et enregistrer** n'est nécessaire lorsque les choix sont uniques.

La recherche retrouve RetroBat, les exécutables DeSmuME, leur architecture et
leur support Lua, puis les jeux `.nds`/`.zip`, leur identité d'en-tête et les
sauvegardes. Elle lit l'INI voisin de l'exécutable et vérifie la provenance et le
cache PCE existants. L'INI n'est pas créé ni modifié par cette détection.

Chaque jeu possède son propre état :

| État | Signification |
| --- | --- |
| Prêt | Environnement du jeu vérifié sur disque ; la connexion Lua reste à confirmer lors du lancement |
| Jeu non trouvé | Ajouter une copie locale à RetroBat ou utiliser les choix manuels avancés |
| Choix nécessaire | Plusieurs émulateurs, jeux ou sauvegardes crédibles, ou association à confirmer |
| Support Lua requis | Jeu préparé, support Lua à installer ou réparer avec consentement |
| À vérifier | Fichier inaccessible, cache altéré, identité non prise en charge ou autre contrôle incomplet |

L'installation est prête dès qu'un jeu est prêt. L'absence des trois autres ne
bloque pas ce jeu et ne déclenche pas de popup d'erreur globale. Avant **Jouer**,
la vérification des références et des sauvegardes porte sur la partie demandée.

La priorité est : choix explicite valide, configuration déjà vérifiée, candidat
unique trouvé, puis choix utilisateur. Les modifications manuelles enregistrées
s'appliquent uniquement aux chemins édités ; elles préservent contrôles, backups,
vitesse et autres préférences. Les fichiers locaux illisibles ne sont pas écrasés.

## Vérifications légères et changements

La vérification est relancée au démarrage, à l'ouverture de **Mes parties**, après
un changement de configuration ou une installation Lua et avant le lancement.
Les fichiers et répertoires connus conservent des signatures locales : une
vérification inchangée réutilise le rapport, sans recalculer les empreintes complètes
des ROM ni parcourir le disque. Une modification des fichiers, des dossiers de
bibliothèque ou des préférences invalide ce rapport. **Relancer la détection**
force la recherche bornée.

Une vérification des signatures est également demandée toutes les 30 secondes
tant que PCE reste ouvert, pour détecter un changement de disque ou de fichiers
sans changer de page. Elle réutilise le rapport si rien n'a changé, attend la fin
d'une session de jeu active et ne cumule pas les workers. Une erreur arrête cette
surveillance jusqu'à une nouvelle recherche demandée par l'utilisateur.

Une source disparue est recherchée dans ces mêmes emplacements. Si une seule copie
retrouvée conserve l'empreinte de la source précédente, sa référence peut être
réparée. Une copie différente ou plusieurs candidats nécessitent un choix. Le
cache existant ne masque pas la disparition de sa source. Pour une partie déjà
créée, ses références encore valides et son empreinte de ROM restent prioritaires ;
sa sauvegarde liée n'est pas remplacée par celle d'une autre configuration.

## Automatique : recherche bornée

`RetroBatDiscoveryService` vérifie les chemins déjà configurés et leurs quatre
parents au maximum, puis `<lecteur>:\RetroBat` sur les lecteurs présents. Il exige
les dossiers réels `roms` et `emulators` : le nom « RetroBat » ne suffit pas.
Les installations multiples restent des candidats distincts. Aucun disque n'est
parcouru récursivement. Les liens symboliques et jonctions sont refusés.

`GameDiscoveryService` examine les enfants directs des dossiers configurés,
notamment `RetroBat/roms/nds`, ainsi que les fichiers explicitement choisis.
Limites : 32 dossiers, 128 fichiers explicites et 2 048 entrées par dossier.
Une limite ou un accès refusé produit un avertissement. Les en-têtes `.nds` et
des membres `.nds` de ZIP identifient séparément jeu, code, région et révision.
Le nom du fichier ne sert pas à identifier le jeu. Une région inconnue reste
`unknown` ; détecter une ROM ne garantit pas un profil mémoire compatible.

Les quatre préfixes de jeux proviennent du `GameDetector` existant. Le code
de quatre octets est lu à `0x0C`, la révision à `0x1E`, conformément à la
[structure d'en-tête DS dans DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/NDSSystem.h#L135).
Une identité d'en-tête n'est pas une preuve d'authenticité ou d'intégrité de ROM.

## Semi-automatique : choix des archives ambiguës

Un ZIP contenant une seule ROM `.nds` reconnue peut être préparé directement.
S'il contient plusieurs `.nds`, un membre doit être choisi explicitement, même
si les autres membres ne sont pas des jeux Pokémon reconnus. Deux sources du
même jeu restent deux choix ; elles ne sont pas fusionnées par génération.
L'archive et sa propre extraction gérée par PCE sont présentées comme une seule
source grâce au manifeste. Le cache n'est pas rescanné comme une bibliothèque.

## Cache immuable, préparé automatiquement

Une source compatible unique est préparée automatiquement. Si plusieurs sources
ou membres d'archive restent possibles, la préparation attend la résolution de ce
choix. Aucune extraction manuelle n'est demandée pour un ZIP simple.

`RomPreparationService` utilise un cache dédié :

```text
runtime/extracted-roms/<game_id>/<sha256-archive>/<16-premiers-caractères-sha256-membre>/
  <nom-original-du-membre>.nds
  manifest.json
```

Le basename de la ROM est conservé pour ne pas changer l'association de nom de
sauvegarde de DeSmuME. L'archive n'est ni remplacée ni déplacée. Le manifeste
contient propriétaire, version, état complet, chemin et empreinte de l'archive,
taille, date, membre choisi, CRC, identité, taille et SHA-256 de la ROM extraite.
L'empreinte complète du nom de membre figure dans le manifeste ; seul le nom du
dossier est raccourci pour limiter la longueur Windows. Une collision du préfixe
est refusée par comparaison du membre et de son empreinte complète, sans écrasement.
Le chemin final est limité à 259 unités UTF-16 pour les buffers Win32 de DeSmuME.
S'il est trop long, PCE demande un emplacement plus court avant toute extraction.

L'extraction se fait dans un dossier temporaire voisin, avec verrou exclusif.
CRC ZIP, taille décompressée, identité d'en-tête et empreintes source/copie sont
vérifiés avant publication du dossier complet. Les écritures sont synchronisées
avant publication. La source doit rester stable pendant l'opération.

Un lancement suivant vérifie les empreintes et réutilise le cache sans extraire.
Un contenu d'archive différent produit un nouveau dossier ; l'ancien reste intact.
Un cache incomplet ou altéré est conservé et refusé, jamais réparé par écrasement
silencieux. Stockage local PCE ne supprime que les caches reconnus et intacts,
après confirmation. Un cache altéré nécessite une vérification manuelle de son
emplacement dans `runtime/extracted-roms` ; conservez-le à part avant de relancer
la préparation. La ROM ou l'archive source reste intacte.

Les ZIP fractionnés, chiffrés, ZIP64, liens, fichiers spéciaux, chemins traversants,
noms Windows dangereux et noms dupliqués sont refusés. Seuls les modes Stored et
Deflate sont pris en charge. Les bornes sont : archive 2 Gio, ROM 1 Gio, table
centrale 4 Mio, 2 048 membres, somme décompressée 2 Gio et rapport de compression
maximal 2 000. L'espace libre est contrôlé avant copie ; les erreurs de droits,
verrouillage et disque plein sont remontées sans publication d'une ROM partielle.
La préparation d'une `.nds` existante vérifie son identité et son empreinte sans
copie ni écriture dans le fichier.

## Sauvegardes proposées, sans prétendre qu'elles sont chargées

`SaveDiscoveryService` examine les dossiers existants RetroBat de sauvegarde DS,
les dossiers configurés, le voisinage de la source ROM et le chemin `Battery`
de `desmume.ini`. Il expose aussi `StateSlots`. Les valeurs relatives sont
résolues depuis le dossier de l'exécutable, conformément à
[`ReadKeyW` et `SwitchPath` dans DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/path.cpp#L233).
La sauvegarde normale est nommée `<basename-ROM>.dsv` dans ce dossier selon le
[code Windows de DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L3056).

Un unique `.dsv` non vide de nom exact est sélectionné automatiquement lorsque la
recherche complète donne une forte confiance. Une
copie au nom voisin, plusieurs emplacements crédibles, un ancien chemin disparu
ou une recherche incomplète imposent un choix. La date la plus récente ne suffit
pas à sélectionner une sauvegarde. Les `.srm` sont seulement signalés comme
candidats à importer manuellement dans DeSmuME ; aucune conversion n'est faite.
La présence et l'association de nom ne prouvent ni le contenu Pokémon ni le
chargement de cette sauvegarde par l'émulateur. Aucun fichier n'est restauré ou
écrasé par cette découverte ; les garanties du [gestionnaire de sauvegardes](save-manager.md)
restent applicables.

Si aucune sauvegarde n'existe, l'interface indique **Aucune sauvegarde existante
trouvée** ; ce n'est pas bloquant pour une nouvelle partie. Une sauvegarde associée
mais disparue exige en revanche une vérification. Une sauvegarde trouvée à un autre
emplacement que celui réellement attendu par DeSmuME ne devient pas « prête » par
sa seule présence : PCE ne la déplace ni ne l'importe silencieusement.

Une configuration déjà préparée sans sauvegarde associée conserve ce choix,
y compris après l'effacement manuel de l'association. Les fichiers découverts
restent proposés dans le diagnostic pour une association explicite ultérieure.

## Non disponible et validation

Les archives ROM `.7z` ne sont pas prises en charge par ces services. L'archive
officielle Lua `.7z` relève d'un installateur distinct et ne constitue pas un
support général des ROM `.7z`.

Les tests synthétiques couvrent installations absentes/multiples, limites de
scan, quatre identités Gen V, archives ambiguës/corrompues, CRC, traversée de
chemins, taille excessive, cache réutilisé/obsolète/altéré, permissions, disque
plein et sauvegardes ambiguës/verrouillées. Les essais réels sur copies isolées
sont consignés séparément dans [verification.md](verification.md).

Les tests de l'ajout V0.4.1 utilisent des ROM, ZIP, exécutables PE et sauvegardes
**synthétiques** : démarrage sans intervention, un seul jeu disponible, aucun jeu,
ambiguïtés, ZIP intact, choix manuels conservés, déplacement de source, cache de
rapport et contrôle ciblé d'une seule partie. Ils ne prouvent pas le chargement
d'une sauvegarde réelle ni la réception d'un heartbeat. Le rapport de vérification
consigne séparément les résultats exécutés et les essais réels.
