# Détection et préparation locales — V0.3.6

Ces services lisent une installation existante. Ils ne téléchargent jamais de
ROM, de sauvegarde ou de contenu Nintendo et ne modifient pas les originaux.
Le [premier démarrage](first-run.md) décrit leur orchestration avec le diagnostic
DeSmuME et l'installation séparée du [runtime Lua](lua-runtime.md).

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

## Automatique après choix : cache immuable

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

Un unique `.dsv` non vide de nom exact peut être proposé automatiquement. Une
copie au nom voisin, plusieurs emplacements crédibles, un ancien chemin disparu
ou une recherche incomplète imposent un choix. La date la plus récente ne suffit
pas à sélectionner une sauvegarde. Les `.srm` sont seulement signalés comme
candidats à importer manuellement dans DeSmuME ; aucune conversion n'est faite.
La présence et l'association de nom ne prouvent ni le contenu Pokémon ni le
chargement de cette sauvegarde par l'émulateur. Aucun fichier n'est restauré ou
écrasé par cette découverte ; les garanties du [gestionnaire de sauvegardes](save-manager.md)
restent applicables.

## Non disponible et validation

Les archives ROM `.7z` ne sont pas prises en charge par ces services. L'archive
officielle Lua `.7z` relève d'un installateur distinct et ne constitue pas un
support général des ROM `.7z`.

Les tests synthétiques couvrent installations absentes/multiples, limites de
scan, quatre identités Gen V, archives ambiguës/corrompues, CRC, traversée de
chemins, taille excessive, cache réutilisé/obsolète/altéré, permissions, disque
plein et sauvegardes ambiguës/verrouillées. Les essais réels sur copies isolées
sont consignés séparément dans [verification.md](verification.md).
