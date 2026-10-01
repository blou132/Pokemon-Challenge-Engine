# Architecture V0.3.5

## Séparation des responsabilités

- `app/models/` : dataclasses de jeu, règle, challenge et profil ; validation des données persistées.
- `app/core/catalog.py` : lecture et validation des catalogues JSON et de leurs références.
- `app/core/rule_engine.py` : dépendances, conflits et prise en charge des jeux.
- `app/core/random_selector.py` : énumération bornée des combinaisons compatibles, cache et tirage déterministe.
- `app/core/challenge_engine.py` : orchestration des règles, paramètres et Monotype, sans dépendance Qt.
- `app/core/monotype.py` : ensemble des 17 types Gen V et sélection reproductible.
- `app/core/profile_manager.py` : persistance des profils et récupération contrôlée des données partielles.
- `app/events/` : observations nullables et événements structurés sans dépendance Qt.
- `app/core/nuzlocke_tracker.py` : zones, rencontres, résultats et Species Clause optionnelle.
- `app/services/tracking_service.py` : profil actif, identité compatible et persistance du suivi.
- `app/core/game_detector.py` : détection optionnelle depuis 16 octets de l'en-tête d'une ROM, en lecture seule ; non utilisée par le launcher V0.1.
- `app/services/config_service.py` et `launcher_service.py` : configuration des chemins et création du processus DeSmuME, conservées de la V0.1.
- `app/bridge/protocol.py` : décodage JSON strict, versions, capacités et validation des messages.
- `app/bridge/state.py` : état de connexion sans dépendance Qt.
- `app/services/bridge_service.py` : sessions locales, réception des instantanés, séquences et expiration.
- `app/services/emulator_service.py` : préparation des fichiers Lua locaux et vérification facultative de l'en-tête ROM, en lecture seule.
- `app/services/bridge_controller.py` : adaptation Qt, préparation et polling dans un worker dédié.
- `lua/common/` : producteur des instantanés, encodeur JSON et lecteur mémoire Gen V.
- `app/ui/` : pages Qt, signaux, roue, présentation des erreurs et navigation.
- `app/main.py` : chargement, journalisation, thème et démarrage.

Les règles et jeux sont définis dans `data/`. Les identifiants sont stables, les noms
affichés sont français. Les quatre jeux Gen V pris en charge sont `black`, `white`,
`black2` et `white2`. Chaque entrée conserve son code attendu, sa région et sa
révision de référence. Le statut catalogue `supported` permet la préparation et
le lancement ; il ne certifie pas une validation des lectures sur une partie réelle.
Les autres jeux ont le statut `planned` et ne peuvent pas être générés ou lancés.

## Versions indépendantes

| Élément | Version | Rôle |
| --- | --- | --- |
| Application | `0.3.5` | Version du frontend livré |
| Scripts Lua | `0.3.0` | Lecteurs et transport conservés |
| Format sérialisé des challenges/profils | `0.1.0` | Compatibilité des profils existants |
| Progression | `2` | Migration additive conservant le suivi manuel |
| Protocole de passerelle | `2` | Observations nullables ; réception v1 conservée |

Le champ `version` du challenge reste indépendant de `schema_version` dans la
progression. La migration des anciens suivis se fait en mémoire sans réécriture
à la consultation. Les événements alimentent le seul profil actif compatible,
si Nuzlocke est sélectionné. Les champs de combat des profils livrés restent
inconnus : seul le moteur synthétique couvre actuellement les résultats.

## Génération

Le nombre demandé inclut les obligations et leurs dépendances. Une interdiction est
toujours respectée, même si une règle obligatoire exige la règle interdite : la demande
est alors refusée avec une explication. Les conflits sont vérifiés dans les deux sens.

Le générateur examine un espace fini de sous-ensembles. Il choisit uniformément parmi
les combinaisons valides du nombre demandé. Les résultats et les types sont ordonnés
de façon stable avant le choix par seed. Il n'existe aucune boucle de relance non bornée.
Le maximum affiché dépend des règles compatibles, et les totaux réalisables sont listés.
Cette approche convient au catalogue V0.1 ; l'expansion importante du catalogue demandera
une stratégie de résolution plus adaptée.

En mode personnalisé, seules les obligations et leurs dépendances sont actives.
En partie normale, aucune règle n'est active. La date de création est une métadonnée :
la reproductibilité concerne les règles, types et réglages, pas l'horodatage ni l'identifiant
unique du profil.

Le moteur choisit le type avant l'animation ; `QPropertyAnimation` ne fait que présenter
ce choix. Le pointeur final est calculé à partir du même index de secteur. La seed, le
pool autorisé et l'index de relance sont conservés.

## Données locales

`config.json`, `logs/`, `profiles/` et `runtime/bridge/` se trouvent dans le dossier du projet. Le répertoire
doit être accessible en écriture. Les chemins utilisateur sont absents du dépôt.
Les profils sont stockés dans des répertoires distincts avec :

- `challenge.json` : jeu, version, mode, règles, états, paramètres, Monotype, seed, date, nom et identifiant du profil.
- `progress.json` : champs manuels conservés, plus `schema_version: 2` et `nuzlocke` contenant zones, rencontre active, espèces et curseurs de déduplication.
- `history.json` : liste d'événements, initialement vide.

Une création produit un nouvel identifiant même si le nom existe déjà. La mise à jour du
suivi demande confirmation dans l'interface. Les fichiers sont remplacés via des fichiers
temporaires ; une erreur doit être présentée, jamais masquée. Ce n'est pas une base
transactionnelle multi-utilisateur : utiliser une seule instance pour modifier un profil.

Un catalogue invalide bloque proprement le démarrage, plutôt que de générer des règles
inconnues. Une configuration locale invalide utilise des chemins vides ; une sauvegarde
explicite conserve une copie du fichier invalide. Un profil dont le challenge est illisible
est signalé et ignoré. Un suivi absent ou corrompu peut être consulté avec des valeurs
vides en mémoire ; une corruption existante n'est pas écrasée silencieusement.

## Frontière avec l'émulateur

Le launcher valide des chemins puis crée un processus avec une liste d'arguments et
`shell=False`. Il ne lit ni n'écrit le contenu d'une ROM ou d'une sauvegarde. Le démarrage
d'un processus ne garantit pas que DeSmuME a chargé le jeu. DeSmuME reste responsable
de ses propres sauvegardes lorsque l'utilisateur joue.

La préparation Lua est une action distincte du lancement. Si une ROM est configurée,
`EmulatorService` lit son en-tête pour vérifier le code du jeu et sa révision, puis crée
les fichiers de connexion dans `runtime/bridge/`. Le script exact `connect.lua` est
affiché dans l'interface et chargé manuellement dans DeSmuME. Aucun argument CLI Lua
non vérifié n'est ajouté au launcher.

## Transport et interface

Le trajet d'une lecture est : **RAM DeSmuME → lecteur Lua → protocole →
observations/événements → NuzlockeTracker → ProfileManager → signaux Qt → panneau**.
`BridgePage` ne décide pas du résultat d'une rencontre. Les widgets ne contiennent
aucune adresse mémoire et n'effectuent pas de lecture de la passerelle.

Chaque préparation crée un identifiant de session et un dossier dédié. Lua termine
l'écriture d'un fichier temporaire avant de le renommer en instantané JSON. Le protocole
porte notamment l'identifiant de session, la séquence, l'événement, le jeu, la région,
la révision, les capacités et les données d'équipe éventuellement disponibles.
La validation rejette les versions incompatibles, les messages mal formés et les
données qui ne correspondent pas à la session attendue. Les doublons ne maintiennent
pas artificiellement une connexion en vie.

Le controller crée son `QThread` à la sélection d'un profil ou au démarrage demandé. Le worker prépare la
session puis utilise son propre `QTimer` pour effectuer le polling. Les signaux
mettent les widgets à jour sur le thread principal. La fermeture de la fenêtre
arrête le timer dans le worker puis attend la fin du thread.

Le journal local `observation-<sequence>.json` conserve les observations différentes
jusqu'à leur traitement et leur persistance. Le worker acquitte ensuite les entrées.
Une erreur de sauvegarde conserve les fichiers pour réessai. Les curseurs et
identifiants de rencontre persistés rendent ce réessai idempotent. Les règles
de migration, de récupération atomique et les limites de reconnexion sont
décrites dans [Suivi Nuzlocke](nuzlocke-tracking.md).

Les états distinguent une session arrêtée, l'attente, la connexion Lua, la réception
de données d'équipe, la déconnexion et une erreur. Une connexion Lua ou un PID de
processus ne prouve pas la disponibilité de l'équipe. Les données absentes restent
nulles dans le protocole et sont affichées **Non disponible**. En cas de déconnexion,
l'interface retire l'équipe précédemment affichée.

## Limites de la lecture mémoire

Les profils de `data/memory_profiles.json` sélectionnent explicitement le jeu, la
région et la révision. Les profils Noir, Noir 2 et Blanc 2 portent le statut
`source_documented` : leurs sources sont identifiées, leur fonctionnement sur
une équipe réelle n'est pas présenté comme validé. Le transport réel, son cycle de connexion et l'identité
`IREF / FR / 0` ont été vérifiés avec les scripts et services de production.
Pour l'équipe de ces trois jeux, les espèces, les niveaux et les PV :
**En attente de validation sur la machine utilisateur.**

Le profil Blanc `white_fr_rev0` porte `real_sample_verified` : le 30 septembre
2026, deux Pokémon d'une partie réelle `IRAF / FR / 0` ont été comparés à
l'écran du jeu, puis reçus par l'interface Qt de production. Feuillajou (ID 511,
niveau 15, PV 6/42) et Gruikui (ID 498, niveau 14, PV 45/45) correspondaient.
Ce statut décrit un échantillon réel vérifié, pas une compatibilité universelle.

Le lecteur reconnaît le jeu depuis l'en-tête RAM : `IRB` → `black`, `IRA` →
`white`, `IRE` → `black2`, `IRD` → `white2`. Les profils français de révision 0
sont distincts : `black_fr_rev0`, `white_fr_rev0`, `black2_fr_rev0` et
`white2_fr_rev0`. Les adresses de Blanc et Blanc 2 sont calculées d'après les
décalages explicitement fournis par PokeLua, puis stockées dans leurs propres
profils. Aucun profil n'est choisi par proximité ou par famille de jeu : le jeu,
le code complet, la région et la révision doivent tous correspondre avant une
lecture d'équipe. Une incompatibilité ne déclenche aucune lecture aux adresses
d'un autre jeu. Les messages `black` et `black2` déjà produits restent acceptés
dans le protocole `1`, étendu aux identifiants `white` et `white2`.

La validation réelle prioritaire de Blanc (`IRAF / FR / 0`) dispose donc d'un
premier échantillon comparé. Les essais
et leurs limites sont conservés dans le rapport de vérification ; le statut des
sources, les tests synthétiques et les observations dans DeSmuME sont distincts.

Le lecteur vérifie notamment les bornes, la somme de contrôle des blocs et la
cohérence de l'instantané. Une mémoire d'équipe non initialisée ne produit pas
de fausse équipe vide. Aucun de ces contrôles ne remplace une comparaison avec
les données visibles dans le jeu. Les tests Lua sur mémoire synthétique sont
distincts des essais réels.

[Protocole, utilisation et dépannage](desmume-bridge.md) ·
[Adresses et sources mémoire](memory-map.md) · [Preuves de vérification](verification.md)

## Frontend V0.3.5

`MainWindow` conserve ses six pages et ouvre `GameModeWindow`. Celui-ci partage
le `BridgeController` existant : il ne crée pas un second consommateur de journal.
`GameModePage` présente les instantanés ; la sélection de jeu/profil est verrouillée
pendant une session. Les événements de suivi restent traités par le moteur V0.3.

`GameModeConfigStore` migre les chemins historiques en mémoire dans quatre profils
de lancement, conserve les choix d'interface et les raccourcis locaux, refuse les
versions inconnues et détecte une modification externe avant toute sauvegarde.
`GameModeService` détient le processus lancé, le temps de session PCE (pauses du jeu
incluses), l'intention de vitesse et les options de backup figées pour cette session.
Fermer PCE arrête ses automatismes sans tuer DeSmuME. Les backups de fermeture
nécessitent donc que PCE observe réellement la fin du processus.

`EmulatorCapabilities` identifie le binaire par SHA-256 ; `EmulatorSettingsService`
parse l'INI réel, conserve commentaires/clés inconnues, refuse les conflits et
l'écriture pendant l'exécution, puis crée un backup avant remplacement atomique.
Les capacités documentées ne valent pas mesure des FPS ni validation visuelle de
chaque option. Aucun argument CLI supplémentaire n'est inventé.

`SaveManagerService` sépare métadonnées DSV, inventaire des slots et copies gérées.
Un manifeste local avec empreintes SHA-256 identifie les seuls backups soumis à la
rétention. La restauration explicite sauvegarde d'abord la destination existante.
Les sauvegardes source et les ROM ne participent jamais à la rétention.

`EmulatorWindowManager` isole les API Windows : énumération des processus, résolution
de leur exécutable, recherche de fenêtre par PID + chemin exact et placement sans
activation ni changement d'ordre des fenêtres. Aucune injection, saisie simulée,
modification de RAM ou intégration native de DeSmuME. L'adaptateur pourra évoluer
indépendamment des règles et du transport Lua. Sources :
[Tool Help](https://learn.microsoft.com/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot),
[EnumWindows](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-enumwindows),
[SetWindowPos](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos).
