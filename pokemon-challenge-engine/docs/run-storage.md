# Stockage des parties — schéma 1

Les parties sont stockées dans `pokemon-challenge-engine/runs/`, hors de
`runtime/`. Le nettoyage des caches et sessions Lua n'y accède pas. Ce stockage
est local et exclu de Git, comme les profils et les chemins de sauvegarde.

```text
runs/
  active.json
  .runs.lock
  <UUID canonique>/
    run.json
```

`run.json` contient la partie, ses sessions et son historique dans **un seul
document atomique**. Une mort et son événement ne peuvent donc pas être publiés
dans deux états distincts. `active.json` ne contient que `schema_version: 1` et
`run_id` ; il mémorise une sélection, pas la preuve d'un émulateur en cours.

## Données conservées

| Groupe | Champs principaux |
| --- | --- |
| Identité | `run_id`, `schema_version`, `name`, `game_id`, `generation` |
| Jeu connu | `game_code`, `region`, `revision`, `rom_fingerprint` |
| Origine | `profile_id`, `preset`, `seed`, `rules_snapshot` |
| Cycle | `created_at`, `started_at`, `last_played_at`, `finished_at`, `status` |
| Lancement | `save_path`, `launch_profile` |
| Observation | `current_zone`, `current_party`, `known_pokemon` |
| Progression | `badges`, `captures`, `deaths`, `pending_deaths`, `notes` |
| Temps et audit | `total_play_seconds`, `sessions`, `history` |

Les statuts autorisés sont `preparing`, `active`, `finished`, `abandoned` et
`archived`. Aucun statut de défaite n'est calculé. Les valeurs inconnues restent
`null` : par exemple badges, captures et morts d'une nouvelle partie. Une liste
de morts contenant uniquement des corrections produit un compte connu de zéro.

`rules_snapshot` est une copie complète du challenge au format `0.1.0`, avec ses
règles actives, paramètres, Monotype éventuel et seed. Une partie Classique
utilise ce même format avec zéro règle. Le gestionnaire interdit la modification
du snapshot, du jeu, de la génération, de la seed, de la provenance et de la date
de création après création. Le nom et les références de lancement peuvent être
actualisés sans suivre les modifications ultérieures du profil source.

`launch_profile` conserve les options de lancement et leur provenance locale ;
il ne contient ni ROM ni sauvegarde Pokémon. `save_path` est une référence. La
gestion des copies, backups et restaurations reste celle de `SaveManagerService`.
Créer ou sauvegarder une partie PCE n'écrit jamais dans le fichier `.dsv` lié.

## Pokémon observé et individu connu

L'équipe courante est le dernier instantané accepté. Chaque entrée contient
notamment `slot`, `species_id`, `level`, `hp`, `current_hp` (même valeur),
`max_hp`, les identifiants optionnels, `pokemon_key`, `identity_confidence` et
`life_status` (`alive`, `dead`, `unknown`). L'absence de l'équipe ne prouve pas
une capture ou une mort.

`known_pokemon` est un registre distinct. Une identité Gen V documentée utilise
la clé technique `gen5:<PID hexadécimal>:<ID32 dresseur d'origine hexadécimal>`.
Le registre conserve `first_seen_at`, `last_seen_at` et `species_history`, même
après départ de l'équipe. Une collision déjà observée reste signalée par
`identity_ambiguous` et sa raison après réouverture. Les clés techniques ne sont
pas affichées dans l'interface principale.

Une mort contient `death_id`, `pokemon_key` éventuellement nul, `pokemon`,
`zone`, `date`, `note`, `source` et `corrected`. Une correction ajoute
`corrected_at` et `correction_note` sans effacer l'événement initial. Les
observations à confirmer restent dans `pending_deaths` ; après confirmation,
`resolved` et `death_id` conservent le lien avec la déclaration manuelle.

## Écriture et conflits

`RunManager` valide les UUID, le schéma, les types, les dates avec fuseau,
les sessions, les individus connus et les références des corrections. Les
traversées de dossiers, liens symboliques et jonctions sont refusés. Une version
de schéma inconnue, un JSON corrompu ou des clés JSON dupliquées sont conservés
sur disque et signalés ; aucun suivi vide ne les remplace automatiquement.

La publication écrit un fichier temporaire dans le même dossier, vide son
tampon, appelle `fsync`, puis le remplace atomiquement. Une erreur avant le
remplacement conserve l'ancien fichier. La taille maximale d'un document est
32 Mio ; au-delà, la sauvegarde échoue explicitement sans supprimer l'historique.

Un verrou du système d'exploitation protège les écritures entre instances et
se libère en cas de crash. Chaque objet chargé possède une empreinte transitoire
de sa version sur disque, exclue du JSON. Une modification externe rend cet
objet obsolète : même un rafraîchissement de bibliothèque ne l'autorise pas à
écraser la nouvelle version. Il faut recharger et examiner le conflit. Les
modifications directes simultanées par un éditeur externe ne bénéficient pas du
verrou PCE ; les empreintes sont contrôlées avant publication.

## Profils V0.3

Il n'y a **aucune migration destructive** des progressions de profils.
`profiles/<id>/progress.json` et `history.json` restent en place, au schéma de
progression 2. La création d'une partie depuis un profil copie sa configuration,
pas un historique qui pourrait concerner plusieurs anciennes aventures.
L'utilisateur conserve ainsi l'ancien suivi et commence une partie identifiée
explicitement. Le schéma Run 1 est indépendant du challenge 0.1.0, de la
progression 2 et du protocole de passerelle 2.

Voir [run-autosave.md](run-autosave.md) pour le temps et la récupération, et
[permanent-death.md](permanent-death.md) pour les conditions de détection.
