# Architecture V0.1

## Séparation des responsabilités

- `app/models/` : dataclasses de jeu, règle, challenge et profil ; validation des données persistées.
- `app/core/catalog.py` : lecture et validation des catalogues JSON et de leurs références.
- `app/core/rule_engine.py` : dépendances, conflits et prise en charge des jeux.
- `app/core/random_selector.py` : énumération bornée des combinaisons compatibles, cache et tirage déterministe.
- `app/core/challenge_engine.py` : orchestration des règles, paramètres et Monotype, sans dépendance Qt.
- `app/core/monotype.py` : ensemble des 17 types Gen V et sélection reproductible.
- `app/core/profile_manager.py` : persistance des profils et récupération contrôlée des données partielles.
- `app/core/game_detector.py` : détection optionnelle depuis 16 octets de l'en-tête d'une ROM, en lecture seule ; non utilisée par le launcher V0.1.
- `app/services/` : configuration des chemins et création du processus DeSmuME.
- `app/ui/` : pages Qt, signaux, roue, présentation des erreurs et navigation.
- `app/main.py` : chargement, journalisation, thème et démarrage.

Les règles et jeux sont définis dans `data/`. Les identifiants sont stables, les noms
affichés sont français. Les deux jeux pris en charge sont `black` et `black2`.
Les autres jeux ont le statut `planned` et ne peuvent pas être générés ou lancés.

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

`config.json`, `logs/` et `profiles/` se trouvent dans le dossier du projet. Le répertoire
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

V0.2 ajoutera un service de transport et des événements de lecture, sans logique mémoire
dans les widgets Qt. La validation des règles restera utilisable sans interface.
