# Architecture V0.2

## Séparation des responsabilités

- `app/models/` : dataclasses de jeu, règle, challenge et profil ; validation des données persistées.
- `app/core/catalog.py` : lecture et validation des catalogues JSON et de leurs références.
- `app/core/rule_engine.py` : dépendances, conflits et prise en charge des jeux.
- `app/core/random_selector.py` : énumération bornée des combinaisons compatibles, cache et tirage déterministe.
- `app/core/challenge_engine.py` : orchestration des règles, paramètres et Monotype, sans dépendance Qt.
- `app/core/monotype.py` : ensemble des 17 types Gen V et sélection reproductible.
- `app/core/profile_manager.py` : persistance des profils et récupération contrôlée des données partielles.
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
affichés sont français. Les deux jeux pris en charge sont `black` et `black2`.
Les autres jeux ont le statut `planned` et ne peuvent pas être générés ou lancés.

## Versions indépendantes

| Élément | Version | Rôle |
| --- | --- | --- |
| Application et scripts Lua | `0.2.0` | Version du logiciel livré |
| Format sérialisé des challenges/profils | `0.1.0` | Compatibilité des profils existants |
| Protocole de passerelle | `1` | Structure des messages échangés |

La V0.2 ne migre pas les profils et ne confond pas leur champ `version` avec la
version affichée par l'application. Les lectures Lua n'alimentent pas encore la
progression ni l'historique des challenges.

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
- `progress.json` : badges, captures, morts (`deaths`), zones et level cap courant ; saisie manuelle.
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

Le trajet d'une lecture est : **RAM DeSmuME → lecteur Lua → instantané JSON local →
BridgeService → signaux du BridgeController → BridgePage**. Les widgets ne contiennent
aucune adresse mémoire et n'effectuent pas de lecture de la passerelle.

Chaque préparation crée un identifiant de session et un dossier dédié. Lua termine
l'écriture d'un fichier temporaire avant de le renommer en instantané JSON. Le protocole
porte notamment l'identifiant de session, la séquence, l'événement, le jeu, la région,
la révision, les capacités et les données d'équipe éventuellement disponibles.
La validation rejette les versions incompatibles, les messages mal formés et les
données qui ne correspondent pas à la session attendue. Les doublons ne maintiennent
pas artificiellement une connexion en vie.

Le controller crée son `QThread` au premier démarrage demandé. Le worker prépare la
session puis utilise son propre `QTimer` pour effectuer le polling. Les signaux
mettent les widgets à jour sur le thread principal. La fermeture de la fenêtre
arrête le timer dans le worker puis attend la fin du thread.

Les états distinguent une session arrêtée, l'attente, la connexion Lua, la réception
de données d'équipe, la déconnexion et une erreur. Une connexion Lua ou un PID de
processus ne prouve pas la disponibilité de l'équipe. Les données absentes restent
nulles dans le protocole et sont affichées **Non disponible**. En cas de déconnexion,
l'interface retire l'équipe précédemment affichée.

## Limites de la lecture mémoire

Les profils de `data/memory_profiles.json` sélectionnent explicitement le jeu, la
région et la révision. Ils portent actuellement le statut `source_documented` :
leurs sources sont identifiées, leur fonctionnement sur une équipe réelle n'est
pas présenté comme validé. Le transport réel, son cycle de connexion et l'identité
`IREF / FR / 0` ont été vérifiés avec les scripts et services de production.
Pour l'équipe, les espèces, les niveaux et les PV :
**En attente de validation sur la machine utilisateur.**

Le lecteur vérifie notamment les bornes, la somme de contrôle des blocs et la
cohérence de l'instantané. Une mémoire d'équipe non initialisée ne produit pas
de fausse équipe vide. Aucun de ces contrôles ne remplace une comparaison avec
les données visibles dans le jeu. Les tests Lua sur mémoire synthétique sont
distincts des essais réels.

[Protocole, utilisation et dépannage](desmume-bridge.md) ·
[Adresses et sources mémoire](memory-map.md) · [Preuves de vérification](verification.md)
