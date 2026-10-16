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
    play/                       # après préparation des copies indépendantes
      isolation.json
      save-observed.json       # présence d'une sauvegarde déjà constatée
      game/<jeu>-<UUID>.nds
      emulator/DeSmuME.exe
      emulator/desmume.ini
      saves/<jeu>-<UUID>.dsv    # absent avant la première sauvegarde ou un import
      state-slots/<jeu>-<UUID>.ds0 ... .ds9
      states/
      backups/
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

La désignation Starter Only/Solo Run utilise seulement un événement supplémentaire
`allowed_pokemon_changed`, de source `manual`, dans `history`. Aucun champ Run ni
snapshot de challenge n'est ajouté ou modifié. Son payload conserve `purpose`
(`starter` ou `solo`), `pokemon_key`, une copie de l'observation forte `pokemon`,
`previous_event_id` et une note. Un retrait conserve la chaîne avec `pokemon_key`
et `pokemon` à `null`. La validation exige que chaque correction référence la
désignation précédente de cette même partie. La dernière entrée détermine le
choix courant ; les précédentes restent intactes.

Les anciennes parties sans cet événement restent lisibles sans migration. Une
ancienne version de PCE qui ne connaît pas le nouvel événement le refusera :
elle ne doit pas réécrire ces données. L'historique des parties n'est jamais
tronqué automatiquement. Si `run.json` dépasse la limite de 32 Mio, l'écriture
échoue explicitement et le fichier précédent est conservé ; la désignation
active n'est pas purgée pour faire de la place.

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
le JSON ne contient aucun binaire ROM ou Pokémon. `save_path` désigne le fichier
prévu pour cette partie, même s'il n'existe pas encore pour une nouvelle aventure.
La publication de la progression PCE n'écrit pas dans ce fichier `.dsv`.
Les imports confirmés copient une sauvegarde existante ; les backups et restaurations
conservent les contrôles de `SaveManagerService`.

## Fichiers indépendants et anciennes parties

Une nouvelle partie porte d'abord `_isolation_pending: true` dans son profil de
lancement. `RunLaunchService` prépare ensuite ses fichiers dans un worker avant
de l'activer. Le marqueur disparaît après publication des nouveaux chemins.
Les parties historiques sans ce marqueur restent lisibles, avec leurs références
existantes ; l'interface propose une copie après confirmation.

`RunIsolationService` copie une ROM `.nds`, un exécutable DeSmuME reconnu et les DLL
Lua locales vérifiées. Il produit un INI propre à l'aventure, avec des dossiers
distincts pour Battery, StateSlots, States et les autres sorties prises en charge.
Les réglages de contrôle et d'affichage autorisés sont conservés ; les anciens
scripts, chemins de sortie et listes de ROM ne sont pas recopiés aveuglément.
La ROM porte le jeu et l'UUID dans son nom, auquel correspondent les sauvegardes
et slots DeSmuME. Les fichiers source sont seulement lus et les copies sont
comparées par SHA-256 avant publication.

`play/isolation.json` conserve le propriétaire PCE, l'UUID, l'identité du jeu,
les empreintes ROM/émulateur/DLL et la provenance des imports. Ce manifeste ne
remplace pas les règles et la progression dans `run.json`. Un dossier manquant,
un chemin sortant de cet espace ou une empreinte modifiée bloque la reprise ;
aucun retour automatique à la sauvegarde RetroBat n'est effectué.
Le marqueur `save-observed.json` est écrit lorsque la sauvegarde est constatée
avant reprise, lors du premier backup différé ou à la fermeture de DeSmuME,
même sans backups activés. Une sauvegarde importée ou déjà constatée qui disparaît
bloque la reprise au lieu de redevenir silencieusement une nouvelle aventure.

Une nouvelle aventure ne crée aucun `.dsv` vide. L'import explicite copie seulement
le `.dsv` choisi. L'assistant des anciennes parties peut aussi copier les slots
`.ds0` à `.ds9` et le `.dst` portant le nom de la ROM source dans les dossiers
configurés. Les states portant d'autres noms restent à associer explicitement ;
aucune provenance n'est inventée. Un environnement déjà isolé n'est pas écrasé
par un second import. Les anciens backups restent intacts ; les nouveaux utilisent
`play/backups/`.

La préparation refuse un emplacement temporaire Windows et les chemins trop
longs pour le build DeSmuME pris en charge. Les fichiers sont d'abord copiés dans
un dossier provisoire propre à l'opération ; sa publication et celle de `run.json`
sont protégées par le verrou des parties. Une erreur conserve les anciennes
références. Les sources techniques, tests synthétiques et essais réels du couple
DeSmuME/INI sont distingués dans [verification.md](verification.md).

## Suppression contrôlée

`RunDeletionService` inventorie uniquement `runs/<uuid>/` après détachement du
suivi. Il refuse une session ouverte, une partie encore sélectionnée, les liens,
fichiers spéciaux ou références d'une autre partie vers ce dossier. Une partie
illisible empêche de certifier l'absence de référence partagée.
La confirmation porte sur cet inventaire exact, vérifié de nouveau avant
suppression. Aucun chemin externe contenu dans les métadonnées n'est supprimé.
`run.json` est conservé jusqu'à la suppression des autres fichiers ; une erreur
système laisse les fichiers restants visibles pour récupération. Le statut
`archived` ne supprime aucun fichier.

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
