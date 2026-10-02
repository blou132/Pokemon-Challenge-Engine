# Connexion DeSmuME / Lua — V0.3 en cours

La V0.3.6 ajoute [Installation & diagnostic](first-run.md), les ZIP locaux et la
réparation Lua confirmée. **Jouer** prépare la session pour les jeux configurés ;
le chargement du script et **Run** restent manuels. **Copier le chemin** et
**Ouvrir le dossier** donnent accès au script courant.

**Reconnecter** arrête la session précédente puis génère un nouveau script lié
à une configuration immuable. Un ancien script marqué stop ne récupère jamais
silencieusement la nouvelle session. Le verrouillage du jeu explique désormais
son origine et propose l'arrêt confirmé de Lua ; un DeSmuME encore lancé doit
être fermé séparément pour changer de jeu.

Sur Blanc FR rev0, le test utilisateur confirme équipe, soins et zones hors combat.
Les valeurs d'équipe sont garanties après synchronisation de la structure principale,
notamment en fin de combat. Les PV en temps réel pendant le combat restent hors
périmètre ; aucun offset d'équipe ou de combat n'est changé en V0.3.6.

La V0.3 ajoute un sélecteur de profil actif et le panneau **Suivi Nuzlocke**.
Choisir ce profil avant de préparer la connexion ; arrêter la connexion avant
d'en changer. Sans profil, les observations restent un diagnostic sans écriture
de progression. Une identité incompatible suspend le suivi.

Les lecteurs de carte Noir/Blanc FR rev0 sont documentés ; les lectures de
combat/capture/fuite restent **indisponibles faute de sources suffisantes**.
Un heartbeat ou une carte lisible ne valide donc pas le suivi d'une rencontre.
**En attente de validation sur la machine utilisateur.**
Voir [le périmètre et la procédure Nuzlocke](nuzlocke-tracking.md).

La passerelle transmet à Python des instantanés lus par un script Lua dans
DeSmuME. Le lancement d'un processus DeSmuME ne prouve pas que cette connexion
existe : seuls des messages acceptés par le service font évoluer son état.
La passerelle ne modifie ni la RAM, ni les ROM, ni les sauvegardes Pokémon.
Elle n'applique pas les règles du challenge au jeu.

Les quatre jeux proposés sont Noir (`black`), Blanc (`white`), Noir 2 (`black2`)
et Blanc 2 (`white2`). Leurs profils d'équipe français de révision 0 ont des
sources documentées et des tests synthétiques. Noir, Noir 2 et Blanc 2 portent
le statut `source_documented`, sans validation visuelle d'équipe réelle.
Blanc porte `real_sample_verified` pour l'échantillon comparé le 30 septembre
2026 ; ce statut ne garantit pas toutes les équipes ou ROM.
Les adresses, le déchiffrement et ces limites
sont décrits dans [memory-map.md](memory-map.md). Les résultats d'essais réels
doivent être consignés séparément dans [verification.md](verification.md) ;
ce guide décrit le fonctionnement prévu et ne constitue pas un compte rendu
d'exécution en émulateur.

## Préparer DeSmuME

Utiliser DeSmuME standalone pour Windows avec sa console Lua. Un cœur DeSmuME
intégré à un autre frontend ne fournit pas nécessairement cette console.
Les distributions officielles sont référencées sur la
[page de téléchargement DeSmuME](https://desmume.org/download/).

Le script exige Lua 5.1, `memory.readbyte` et `emu.frameadvance`. Il utilise
`emu.registerexit` quand cette fonction est disponible. Ces API sont définies
dans le [moteur Lua de DeSmuME, version source épinglée](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/lua-engine.cpp).
Les fonctions standard `io.open`, `os.rename`, `os.remove` et `os.time` servent
au transport local. LuaSocket n'est pas requis : sa présence n'est pas garantie
dans les distributions DeSmuME, d'où le choix de fichiers locaux.

| Transport évalué | Décision V0.2 |
| --- | --- |
| Fichiers JSON locaux | Retenu : API standard Lua réellement testée, publications complètes renommées, aucune dépendance réseau. |
| TCP localhost | Non retenu : bibliothèque sockets supplémentaire à installer et à qualifier pour chaque build Lua. |
| UDP localhost | Non retenu : même dépendance et gestion supplémentaire des pertes de datagrammes, sans bénéfice pour ces petits instantanés. |

Si la console indique que `lua51.dll` manque, vérifier les DLL Lua placées à côté
de l'exécutable. Le frontend Windows recherche ce nom dans
[DemandLua, source DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp).
L'[archive Lua du dépôt officiel](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/lua/lua.7z)
fournit les bibliothèques utilisées par ce projet DeSmuME. Avec cette archive,
conserver **`lua51.dll` et `lua5.1.dll`** de la même architecture que l'émulateur :
x64 pour un exécutable x64, win32 pour un exécutable 32 bits. Le nom du fichier
ne suffit pas à garantir une architecture compatible. Ces binaires restent
locaux et ne sont pas ajoutés au dépôt Pokemon Challenge Engine.

## Connexion depuis l'application

1. Dans **Paramètres**, renseigner si possible le chemin de la ROM `.nds` du jeu.
   La préparation ne lit que son en-tête pour vérifier le code et la révision.
   Sans chemin de ROM, le jeu sélectionné reste contrôlé lors de la réception.
2. Ouvrir **Connexion DeSmuME**, choisir Noir, Blanc, Noir 2 ou Blanc 2 et cliquer sur
   **Préparer la connexion**.
3. Copier le chemin exact affiché. Il désigne
   `runtime/bridge/<session_id>/connect.lua`, créé pour cette préparation.
4. Dans DeSmuME, ouvrir la ROM puis **Tools > Lua Scripting > New Lua Script**.
   Sélectionner ce `connect.lua` et cliquer sur **Run**.
5. Laisser le jeu s'exécuter. Vérifier le jeu détecté, le code, la région, la
   révision, le profil mémoire, le compteur d'instantanés et les éventuelles erreurs.

Le chargement Lua est manuel. Le launcher du projet ne suppose pas l'existence
d'une option DeSmuME `--lua`. Les fichiers `lua/common/*.lua` sont des modules :
c'est le **`connect.lua` indiqué par la préparation** qu'il faut ouvrir.

**Arrêter la connexion** remet l'état Python à `stopped` et crée un marqueur
local `stop`. Le script actif le détecte lorsque les frames reprennent et tente
de publier `emulator_closing` avant de terminer. Aucune session n'est effacée
automatiquement. Une fermeture brutale de l'émulateur peut empêcher ce dernier
message ; le délai de déconnexion couvre ce cas.

Après un arrêt, préparer une nouvelle connexion puis charger le nouveau
`connect.lua` et cliquer sur **Run**. Une préparation crée toujours un nouvel
identifiant de session. Un script encore actif peut aussi détecter une nouvelle
configuration du même jeu au passage suivant ; ne pas dépendre de cela si la
console est déjà arrêtée. Pour changer de jeu, arrêter puis préparer le jeu voulu.

## Validation prioritaire : Pokémon Blanc

Le test prioritaire concerne **Pokémon Blanc français**. Un échantillon réel a
été comparé le **30 septembre 2026**, sur des copies isolées de DeSmuME, de la ROM
et de la sauvegarde : Feuillajou (ID 511, niveau 15, PV 6/42) et Gruikui (ID 498,
niveau 14, PV 45/45), soit deux Pokémon. Le code `IRAF`, la région `FR`, la
révision `0`, les heartbeat et l'équipe ont été reçus par les services et
l'interface Qt de production. Les fichiers originaux contrôlés sont restés
inchangés. Voir les [preuves et limites](verification.md#essai-réel-de-pokémon-blanc).

Les étapes ci-dessous permettent de reproduire la comparaison sur sa propre
partie. Elles vérifient trois résultats distincts : le transport, l'identité
puis les valeurs de l'équipe. L'échantillon déjà vérifié ne prouve pas la
compatibilité de toutes les situations, régions ou révisions.

1. Renseigner la ROM `.nds` de **Pokémon Blanc** dans les paramètres, préparer la
   connexion pour ce jeu et charger son `connect.lua` dans DeSmuME.
2. Laisser les frames s'exécuter et vérifier que les instantanés reçus augmentent
   et que des événements `heartbeat` sont reçus.
3. Vérifier l'identité réelle dans l'interface : **Pokémon Blanc**, code **`IRAF`**,
   région **`FR`**, révision **`0`**, profil **`white_fr_rev0`**. Un autre code
   nécessite sa propre vérification ; ne pas sélectionner Noir pour contourner
   une incompatibilité.
4. Charger sa partie normalement dans DeSmuME et ouvrir l'équipe. Comparer son
   nombre de Pokémon et, pour chaque place, l'espèce, le niveau, les PV actuels
   et les PV maximaux. L'application affiche actuellement l'espèce par son
   identifiant, pas par son nom. Noter séparément les valeurs du jeu et celles
   de l'application, ainsi que toute donnée **Non disponible**.
5. Noter le build DeSmuME, l'architecture, la version Lua, le code et la révision,
   le profil reçu et le résultat des comparaisons. Seules ces observations
   peuvent compléter la validation réelle dans [verification.md](verification.md).

Un heartbeat seul n'atteste pas une lecture d'équipe. Au menu de démarrage, un
compteur RAM nul signifie que la lecture n'est pas prête ; l'interface conserve
**Non disponible**. Une validation de Blanc ne valide pas automatiquement Noir,
Noir 2 ou Blanc 2, qui utilisent des profils séparés.

## Diagnostic en ligne de commande

Depuis le dossier contenant `app/`, avec l'environnement Python du projet :

```powershell
python -m tools.bridge_diagnostic --game white --duration 60
```

Cette commande prépare une session et affiche immédiatement le chemin du Lua
à charger manuellement dans DeSmuME. Elle ne lance pas l'émulateur. `--game`
accepte `black`, `white`, `black2` ou `white2`. `--duration` est une durée positive et finie, de
60 secondes par défaut. Une ROM locale peut être vérifiée en lecture seule :

```powershell
python -m tools.bridge_diagnostic --game white --rom "D:\Mes jeux\Blanc.nds" --duration 60
```

`--base-dir "D:\Diagnostic PCE"` choisit un autre emplacement pour les fichiers
locaux. Les modules Lua et le registre mémoire restent ceux de l'installation.
Utiliser un autre dossier permet de séparer ce diagnostic d'une session déjà
préparée par l'interface. Deux préparations du même jeu dans le même dossier
remplacent sa configuration `current-<game_id>.lua`.

Avec `--json`, la sortie contient un objet JSON par ligne : `prepared`, `state`,
`summary` ou `error`. Elle indique notamment l'identité reçue, les capacités,
le profil mémoire, les erreurs, le nombre de messages acceptés et la fréquence
de réception. Cette fréquence est calculée entre le premier et le dernier
instantané acceptés ; elle ne compte pas les instantanés sautés entre deux lectures.

| Code de sortie | Signification |
| --- | --- |
| `0` | Au moins un événement `heartbeat` accepté avec la capacité correspondante, au moins deux messages acceptés et connexion encore active à la fin. |
| `1` | Aucun heartbeat accepté, activité insuffisante ou connexion perdue en fin de surveillance. |
| `2` | Arguments invalides ou échec de préparation/lecture signalé par la commande. |
| `130` | Interruption au clavier. |

Un `hello` isolé, un fichier figé ou la simple présence de DeSmuME ne suffit pas
à obtenir le code `0`. Ce succès mesure le transport et la réception ; il ne
valide pas les adresses mémoire, les valeurs d'une équipe, toutes les ROM d'une
région ou l'application des règles. Le diagnostic n'a aucun mode simulé.
Les tests automatisés du CLI utilisent explicitement un producteur simulé.
À la fin de la commande, y compris après une interruption, la session reçoit
le marqueur d'arrêt.

## Transport et cadence

Python crée `runtime/bridge/<uuid>/` et une configuration locale
`runtime/bridge/current-<game_id>.lua`. Le Lua publie des fichiers JSON complets
`snapshot-0000000001.json`, puis `snapshot-0000000002.json`, etc. Il écrit d'abord
un fichier `.tmp`, ferme le descripteur puis le renomme vers un nom inédit dans
le même dossier. En fonctionnement normal, il conserve les deux derniers
instantanés ; `sequence.txt` permet de reprendre la numérotation lors du
rechargement du script dans la même session.

Si `sequence.txt` est tronqué ou corrompu lors d'un arrêt brutal, Lua refuse
de repartir à zéro : préparer une nouvelle connexion puis recharger son
script. Cela évite d'écraser ou de réutiliser des instantanés existants.
Un dossier par préparation est conservé pour le diagnostic ; les anciens
dossiers de session peuvent être retirés manuellement lorsque les scripts
et l'application sont arrêtés.

Python ne lit que l'instantané au numéro le plus élevé. Il ignore les `.tmp`,
borne une lecture à 65 537 octets pour détecter un dépassement de 64 Kio et
limite l'énumération du dossier à 512 entrées. Un fichier incomplet, mal formé
ou trop grand est signalé sans planter le service. Chaque événement contient
tout l'état disponible : manquer le premier `hello` n'empêche pas la connexion.

En protocole v2, les observations différentes sont aussi écrites dans
`observation-<sequence>.json`. Python les traite dans l'ordre, même si leurs
snapshots ont disparu, puis les retire seulement après sauvegarde réussie du
profil (ou traitement en diagnostic sans profil applicable). `ack.txt` confirme
la dernière séquence traitée. Une erreur de persistance conserve le journal.
Les identifiants et curseurs persistés empêchent de doubler un événement après
réessai. Un rechargement Lua conserve les fichiers en attente de la session.
Un journal plein suspend le suivi ; il n'est pas tronqué silencieusement.

Cela protège les observations effectivement échantillonnées, pas un événement
RAM qui surviendrait entièrement entre deux lectures. Une future lecture de
résultat devra donc utiliser un état suffisamment durable ou un indicateur
documenté. Une nouvelle préparation crée une autre session et ne réimporte pas
les anciens journaux non acquittés ; conserver ces dossiers en cas d'erreur.

La boucle Lua examine la session toutes les 12 frames. Les publications normales
sont plafonnées à **5 par seconde civile** par `os.time`; la notification finale
de fermeture est distincte. Il n'existe aucune garantie d'une période exacte de
200 ms : la vitesse d'émulation et les pauses influencent la cadence. Python
interroge le service toutes les 200 ms, dans un worker dédié pour l'interface.

Après **3 secondes** sans nouveau message accepté, le service devient
`disconnected` et efface l'équipe et sa taille. Ce délai utilise l'horloge
monotone Python, pas l'horodatage fourni par Lua. Un doublon ou une séquence
ancienne ne repousse jamais le délai. Un message ultérieur de la même session,
avec une séquence supérieure et une identité compatible, permet la reconnexion.

Une pause DeSmuME qui bloque `emu.frameadvance` bloque également les heartbeat :
une déconnexion après trois secondes est alors attendue. Reprendre les frames
permet au script encore actif de publier à nouveau. Si le script s'est terminé,
le relancer via la procédure de préparation.

## États exposés à l'interface

| État | Signification |
| --- | --- |
| `stopped` | Aucun répertoire de session actif côté Python ; données de connexion réinitialisées. |
| `waiting` | Session préparée, aucun message accepté pour l'instant. |
| `connected` | Message accepté, sans taille d'équipe disponible. |
| `receiving` | Message accepté avec `party_size` disponible ; la liste détaillée peut rester absente. |
| `disconnected` | Délai dépassé ou réception de `emulator_closing`. |
| `error` | Message refusé, erreur d'accès local ou événement `bridge_error`. |

Les données d'équipe sont effacées en cas d'erreur, de fermeture ou de délai
dépassé. La dernière identité reçue peut rester visible comme diagnostic.
`connected` et `receiving` sont les seuls états dont la propriété `connected`
vaut vrai. Un message peut inclure une erreur de lecture d'équipe tout en
maintenant la connexion ; une lecture indisponible n'est pas remplacée par zéro.

## Protocole JSON v1

Ce format historique reste accepté pour les scripts `0.2.0`. Les scripts
livrés `0.3.0` produisent le format v2 décrit après cette section.

Le validateur de référence est [app/bridge/protocol.py](../app/bridge/protocol.py).
Un message doit contenir exactement les **16 champs** suivants. L'ordre des
champs est libre, les champs supplémentaires ou manquants sont refusés.

| Champ | Type et contrainte |
| --- | --- |
| `protocol_version` | Entier `1`. |
| `session_id` | Texte de 32 caractères hexadécimaux minuscules, identique à la session préparée. |
| `sequence` | Entier supérieur ou égal à `1`, identique au numéro du nom de fichier. |
| `event` | `hello`, `heartbeat`, `party_update`, `bridge_error` ou `emulator_closing`. |
| `timestamp` | Entier positif ou nul : secondes Unix issues de `os.time()`. |
| `emulator` | Texte `desmume`. |
| `script_version` | Texte `0.2.0` pour cette version du lecteur. |
| `game_id` | `black`, `white`, `black2`, `white2` ou `null`. |
| `game_code` | Quatre caractères ASCII majuscules ou chiffres, ou `null`. |
| `game_region` | `FR`, `EN`, `DE`, `IT`, `ES`, `JP`, `KO` ou `null`. |
| `rom_revision` | Entier de `0` à `255`, ou `null`. |
| `capabilities` | Liste sans doublons, parmi les capacités décrites ci-dessous. |
| `memory_profile` | Identifiant textuel de 120 caractères maximum, ou `null`. |
| `party_size` | Entier de `0` à `6`, ou `null` si la lecture est indisponible. |
| `party` | Liste de zéro à six objets Pokémon, ou `null`. |
| `error` | Texte de 500 caractères maximum, ou `null`. |

Les capacités admises sont `heartbeat`, `game_identity`, `party_size`,
`party_level`, `party_hp` et `party_species`. Une donnée non nulle exige sa
capacité : par exemple, publier un niveau exige `party_level`. Une lecture
d'équipe exige une identité complète, une révision connue et un profil mémoire
non vide. Une identité disponible exige `game_identity`.

Chaque objet de `party` contient exactement `slot`, `level`, `species_id`, `hp`
et `max_hp`. Les places sont contiguës, de 1 à la taille de la liste. Le niveau
vaut de 1 à 100, l'espèce de 1 à 649, les PV de 0 à 9999 et les PV maximaux de
1 à 9999 ; chaque donnée autre que `slot` peut être `null`. Les PV actuels ne
peuvent pas dépasser les PV maximaux quand ces deux valeurs sont connues.
La longueur de `party`, lorsqu'elle est présente, doit être égale à `party_size`.

`null` signifie indisponible. Le protocole accepte une taille réellement connue
égale à zéro, mais le lecteur Gen V actuel traite un compteur RAM nul comme
`not_ready` et publie `party_size: null` : il ne peut pas encore distinguer une
équipe vide d'une mémoire non initialisée. `party: null` permet aussi de publier
un compteur sans inventer les détails de Pokémon.

Le JSON doit être UTF-8, de 65 536 octets maximum. Les booléens à la place
d'entiers, les clés dupliquées, `NaN`, les infinis et les chaînes Unicode
invalides sont refusés. Le service refuse aussi un autre identifiant de session,
un jeu différent ou, si une ROM a été renseignée, un code ou une révision
différents. Les instantanés d'une session antérieure ne sont jamais relus par
une nouvelle session.

L'ajout de Blanc et Blanc 2 conserve les 16 champs et le numéro de protocole `1`.
Les messages existants de Noir et Noir 2 restent acceptés. Chaque session continue
de refuser l'identifiant ou le code d'un autre jeu.

## Versions et limites de validation

### Extension JSON v2

Le message conserve les 16 champs ci-dessus, avec `protocol_version: 2`,
`script_version: "0.3.0"`, et ajoute exactement un champ `observation`.
Il vaut `null` lorsque le lecteur n'est pas disponible. Sinon la capacité
`tracking` et l'identité complète sont exigées. Les 20 champs de l'observation
sont présents et nullables :

- carte : `map_id`, `capture_zone_id`, `zone_name` ;
- combat : `battle_active`, `battle_type`, `encounter_kind`, `battle_id` ;
- adversaire : `species_id`, `level`, `hp`, `max_hp`, `encounter_slot` ;
- cycle et résultat : `outcome`, `wild_encounter`, `encounter_started`,
  `encounter_ended`, `capture_detected`, `capture_success`, `fainted_wild`, `fled`.

`battle_type` accepte `wild`, `trainer`, `double`, `scripted`, `unknown`.
`encounter_kind` accepte les huit classifications du [modèle Nuzlocke](nuzlocke-tracking.md).
`outcome` accepte `captured`, `fainted`, `escaped`, `player_fled`,
`battle_ended_unknown`. `fled` vaut `player`, `wild`, `unknown` ou `null`.
Un résultat `captured` exige `capture_success: true` et `capture_detected: true`.
Le lecteur livré n'émet aucun de ces résultats faute d'adresses documentées.
L'équipe avant/après n'est pas utilisée comme preuve de capture : elle manquerait
notamment les captures envoyées aux boîtes.

Les formats sont stricts : v1 avec observations, v2 sans le nouveau champ,
version inconnue ou paire script/protocole incompatible sont refusés.

| Version | Valeur | Rôle |
| --- | --- | --- |
| Application | `0.3.0` | Version de Pokemon Challenge Engine. |
| Script Lua | `0.3.0` | Producteur v2 ; anciens scripts 0.2.0 acceptés en v1. |
| Protocole | `2` | Structure et validation des échanges JSON ; réception v1 conservée. |
| Schéma des profils de challenge | `0.1.0` | Champ `version` des challenges persistés ; les profils V0.1 restent compatibles. |
| Progression | `2` | Migration additive, état Nuzlocke et déduplication. |

Les identifiants ci-dessous désignent des profils mémoire, pas des versions du
schéma de sauvegarde des challenges. Chaque profil a ses propres adresses et ses
sources ; aucun profil Noir n'est réutilisé pour Blanc, ni Noir 2 pour Blanc 2.

| Jeu | Identifiant | Code | Région | Révision | Profil mémoire |
| --- | --- | --- | --- | --- | --- |
| Pokémon Noir | `black` | `IRBF` | `FR` | `0` | `black_fr_rev0` |
| Pokémon Blanc | `white` | `IRAF` | `FR` | `0` | `white_fr_rev0` |
| Pokémon Noir 2 | `black2` | `IREF` | `FR` | `0` | `black2_fr_rev0` |
| Pokémon Blanc 2 | `white2` | `IRDF` | `FR` | `0` | `white2_fr_rev0` |

Seules ces identités disposent actuellement de profils documentés.
Une autre identité peut recevoir des heartbeat sans données
d'équipe. Le choix conservateur de la révision 0 n'est pas une preuve de
validation de cette révision par les sources utilisées.

Pour les équipes de Noir, Noir 2 et Blanc 2 : **En attente de validation sur la
machine utilisateur.** La validation de l'échantillon Blanc n'est pas étendue
aux trois autres profils.

Pour une validation réelle, conserver le build et l'architecture DeSmuME,
la version Lua, le code et la révision de ROM, le profil choisi, les événements
reçus et les valeurs comparées visuellement dans le jeu. Distinguer trois
résultats : transport, identification du jeu, puis lecture d'équipe. Les tests
JSON et fichiers simulés valident les contrats Python ; les tests Lua sur RAM
synthétique valident le décodeur. Aucun des deux ne prouve à lui seul qu'une
équipe réelle est correctement lue dans DeSmuME.
