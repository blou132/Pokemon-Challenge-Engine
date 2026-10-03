# Pokemon Challenge Engine — V0.4.0

Application Windows en français pour préparer des challenges **Pokémon Noir**,
**Pokémon Blanc**, **Pokémon Noir 2** et **Pokémon Blanc 2**, enregistrer des profils,
lancer DeSmuME standalone et consulter
les données transmises par une passerelle Lua locale en lecture seule.

**L'application ne modifie pas la ROM, n'écrit pas dans la mémoire du jeu et n'impose
aucune règle dans Pokémon.** Le suivi manuel est conservé. Le mode STRICT est une intention enregistrée
pour les versions suivantes. La règle Randomizer est uniquement prévue et configurable.

![Accueil de l'application — capture V0.1](docs/screenshots/accueil-1920.png)

[Voir la roue Monotype](docs/screenshots/monotype.png) · [Résultats des contrôles](docs/verification.md)

## Mes parties — V0.4

**Mes parties → Nouvelle partie** crée une partie classique sans règle ou une
partie issue d'un profil. **Profils → Commencer une partie** copie sa configuration.
Chaque partie reçoit un UUID, ses règles figées, ses sessions, son équipe observée,
ses Pokémon connus, sa progression et son historique. Modifier un profil ensuite
ne change aucune partie existante. Plusieurs parties du même jeu sont possibles.

**Reprendre** sélectionne la même partie, vérifie son environnement et ouvre le
Mode Jeu. **Jouer** lance DeSmuME ; le temps commence uniquement avec les messages
valides du jeu correspondant et le processus lancé par PCE. Fermez DeSmuME et
arrêtez Lua avant de changer de partie. Une fenêtre DeSmuME lancée ailleurs n'est
pas associée automatiquement à ce chronomètre.

L'équipe et les zones documentées sont enregistrées automatiquement. Avec
Nuzlocke et Mort permanente actifs, une transition observée **PV > 0 → 0** d'un
individu identifié crée une mort dans le **cimetière virtuel PCE**. Un soin dans
Pokémon ne l'annule pas. Une identité ambiguë ou une première observation à zéro
demande confirmation. Les captures et badges sont **manuels** ; notes, morts
manuelles et corrections confirmées restent dans l'historique.

La progression se trouve dans `runs/<uuid>/run.json`, hors des caches et exclue de
Git. L'autosave PCE est atomique ; elle ne force aucune sauvegarde Pokémon.
Les anciens `profiles/*/progress.json` et historiques sont conservés sans migration
forcée. Deux parties liées au même `.dsv` partagent la sauvegarde Pokémon : créer
une partie PCE ne crée ni n'importe une nouvelle sauvegarde en jeu.

L'identité Gen V utilise PID et identifiant du dresseur d'origine documentés par
PKHeX. La table sourcée couvre les 649 espèces et leurs familles ; les changements
de branche, retours en arrière et identifiants dupliqués suspendent l'identification
automatique. Le protocole **2** est conservé, avec deux champs facultatifs et des
scripts Lua **0.4.0** ; les anciens messages restent acceptés.

[Guide des parties](docs/run-manager.md) · [Stockage](docs/run-storage.md) ·
[Mort permanente](docs/permanent-death.md) · [Autosave](docs/run-autosave.md) ·
[Sources de l'identité et des évolutions](docs/pokemon-identity-sources.md).

Branche : `feat/v0.4-runs-permadeath`, depuis
`58395b4607cc38270dd68b8a31d5a0fd44a880ea`, sans fusion dans `main`.
**1 511 tests réussis, aucun ignoré** : 1 167 historiques conservés et 344 nouveaux.
Le [rapport V0.4](docs/verification.md) distingue tests synthétiques, rendus Qt
et lectures réelles sur copie isolée. La séquence réelle K.O. → mort PCE → soin
et les évolutions restent **En attente de validation sur la machine utilisateur.**

## Premier démarrage — V0.3.6

Ouvrez **Installation & diagnostic** au premier lancement ou depuis Paramètres.
PCE recherche les installations locales et propose les jeux et sauvegardes trouvés.
Choisissez un candidat lorsque plusieurs existent, puis **Préparer et enregistrer**,
ou **Réparer l'installation** si le support Lua manque. Le téléchargement Lua
provient exclusivement de l'archive officielle épinglée ; un remplacement de DLL
différente exige une seconde confirmation et crée un backup.

Les ROM ZIP sont préparées dans un cache vérifié, sans changer l'archive source.
**Jouer** revérifie l'installation, lance DeSmuME et prépare une nouvelle session
Lua. Copiez le chemin du script avec le bouton prévu, puis chargez-le et cliquez
**Run** dans DeSmuME. Cette dernière étape reste manuelle. Le diagnostic distingue
les fichiers vérifiés de la connexion réellement reçue. Le nettoyage confirmé ne
concerne que les caches et sessions arrêtées reconnus comme appartenant à PCE.

[Guide du premier démarrage](docs/first-run.md) · [Détection et cache](docs/auto-setup.md) ·
[Sources et installation Lua](docs/lua-runtime.md).

Validation de référence V0.3.6 : **1 167 tests réussis, aucun ignoré**, compilation et démarrage
Qt Windows vérifiés, rendus 1366×768 et 1920×1080 inspectés. Les tests synthétiques
et les essais réels sur copies isolées sont distingués dans le
[rapport de vérification](docs/verification.md).

Les profils sauvegardés affichent leur mode et leur nombre exact de règles ;
la sauvegarde sélectionne le nouvel identifiant puis relit ses données.
**Possible** et **Interdite** ne sont pas des règles actives. Les options Monotype,
Level Cap et Catch Limit sont exclues du challenge final si leurs règles ne sont
pas actives. « Niveau de support » et « Suivi uniquement » décrivent les capacités
actuelles : aucune règle n'est imposée dans le jeu.

## Mode Jeu — V0.3.5

Le **Mode Jeu** ouvre un frontend autour de la fenêtre externe de DeSmuME.
Les panneaux affichent le challenge, la seed, les compteurs du profil, l'équipe
reçue par Lua et le suivi Nuzlocke V0.3. Les données absentes restent « Non
disponible ». Les dispositions compacte, standard et large, la visibilité des
blocs et leur côté gauche/droit sont configurables ; le plein écran concerne PCE.

Les réglages regroupent cinq onglets :

- **Lancement** : un profil par jeu avec ROM, émulateur, challenge, contrôles,
  graphismes et vitesse demandée ; export INI uniquement sur activation explicite.
- **Contrôles** : clavier, profils locaux, conflits et raccourcis de l'application.
  Le format DeSmuME est vérifié avant tout export, précédé d'un backup.
- **Graphismes** : options documentées et presets composés de réglages existants,
  réservés au binaire DeSmuME identifié ; leur effet visuel n'est pas garanti.
- **Sauvegardes** : fichier `.dsv` choisi explicitement, inventaire des slots,
  backups manuels ou automatiques activés par l'utilisateur, rétention et
  restauration avec confirmation. Aucun original n'est supprimé par la rétention.
- **Interface en jeu** : blocs visibles, disposition, écran mémorisé et
  organisation facultative des fenêtres.

Les préférences sont locales : `game-mode.local.json`, `controls.local.json` et
le dossier des backups restent exclus de Git. Les chemins RetroBat existants
sont conservés. Les boutons x1/x2/x4/MAX affichent un **état demandé**, sans
pilotage direct ni mesure de vitesse réelle. L'export vérifié de x1/MAX prépare
le prochain lancement ; x2/x4 se règlent dans DeSmuME. Les manettes, shaders,
contraintes sur les save states et randomisation réelle ne sont pas implémentés.

Branche historique V0.3.6 : `feat/v0.3.6-auto-setup`, issue de
`ce8d888629f613b84d3bac3a9831b27cfbea1845` après les **960 tests de référence
réussis, aucun ignoré**, sans fusion automatique.

[Guide du Mode Jeu](docs/game-mode.md) · [Réglages DeSmuME](docs/emulator-settings.md) ·
[Sauvegardes et backups](docs/save-manager.md) · [Vérifications](docs/verification.md)

Validation de la base V0.3.5 : **960 tests réussis, aucun ignoré** ; compilation
et démarrage natif Windows vérifiés, rendus Qt inspectés à 1366×768 et 1920×1080.
Les essais DeSmuME réels sur copies isolées sont détaillés séparément dans le rapport.

## État conservé de la V0.3

Le panneau **Suivi Nuzlocke**, dans **Connexion DeSmuME**, associe le suivi au
profil choisi avant la connexion. Sans profil, la connexion reste un diagnostic.
Le moteur indépendant traite première rencontre, capture, K.O., fuites, résultat
inconnu et Species Clause exacte, avec sauvegarde de progression et historique
idempotent. Ces comportements sont vérifiés par des **événements synthétiques**.

Les lectures de carte de Noir et Blanc FR rev0 sont documentées et testées sur
RAM synthétique. Les profils de suivi de Noir 2 et Blanc 2 restent indisponibles.
Les adresses permettant de distinguer combat sauvage/dresseur et capture/fuite
ne sont pas suffisamment documentées pour ces ROM françaises. Elles restent
`null` : **les captures réelles ne sont pas encore détectées automatiquement**.
La V0.3 n'est donc pas terminée. Pour la lecture réelle des cartes et la chaîne
complète : **En attente de validation sur la machine utilisateur.**

[Modèle de suivi, limites et procédure de validation](docs/nuzlocke-tracking.md).

## État conservé de la V0.2

La nouvelle page **Connexion DeSmuME** prépare un script local, affiche l'état de la
connexion, l'identité du jeu, les capacités reçues et les données d'équipe disponibles.
La génération par seed, les 15 règles configurables, la roue Monotype, les profils,
les paramètres et le launcher de la V0.1 sont conservés.

Le transport DeSmuME → Lua → Python et l'identification de **Noir 2 français,
code `IREF`, révision `0`** ont été testés réellement, avec déconnexion, reprise
dans la même session et arrêt demandé par Python. La CLI et l'interface Qt ont reçu
les messages du vrai producteur Lua. Cela ne valide pas la lecture d'une équipe.
Les quatre profils mémoire français de révision 0 sont documentés et testés sur
mémoire synthétique. Blanc et Blanc 2 possèdent leurs propres adresses, issues
des branches correspondantes de PokeLua.

Le **30 septembre 2026**, un échantillon réel de **Pokémon Blanc** (`IRAF`, `FR`,
révision `0`, profil `white_fr_rev0`) a été comparé au jeu : deux Pokémon,
Feuillajou (ID `511`, niveau `15`, PV `6/42`) et Gruikui (ID `498`, niveau `14`,
PV `45/45`). L'identité, les heartbeat et ces valeurs ont été reçus par les
services et l'interface Qt de production. Le statut `real_sample_verified`
décrit cet échantillon ; il ne garantit pas toutes les ROM, situations ou équipes.

Pour l'équipe de Noir, Noir 2 et Blanc 2 : **En attente de validation sur la
machine utilisateur.** Noir 2 ne disposait pas d'une équipe chargée lors de son
essai de transport. Noir et Blanc 2 n'ont pas été validés en émulateur.
Voir le [rapport de vérification](docs/verification.md) pour les preuves et les limites exactes.

Les versions sont distinctes : application **`0.4.0`**, scripts Lua **`0.4.0`**, challenge
**`0.1.0`** conservé, progression historique **schéma `2`**, partie **schéma `1`**,
protocole **`2`**. Python accepte les anciens scripts `0.3.0/v2` et
aussi les messages v1 des scripts `0.2.0`, sans observations Nuzlocke.
Les anciens suivis sont migrés en mémoire à la lecture, puis persistés seulement
lors d'une sauvegarde ou d'un événement applicable au profil actif.

## Installation sous Windows

Prérequis : Python **3.12 ou plus récent**, avec le lanceur Windows `py`.
Configuration vérifiée : Python 3.13, PySide6 6.11.2, pytest 9.1.1.

Depuis PowerShell, dans le dossier `pokemon-challenge-engine` :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.main
```

Remplacer `-3.13` par une version installée compatible (`py -0p` affiche la liste).
Si l'activation PowerShell est désactivée, les commandes suivantes fonctionnent sans
modifier la politique d'exécution :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

Dans l'espace de travail livré, un environnement a déjà été préparé dans **le dossier
parent**. Pour le démarrer immédiatement depuis `pokemon-challenge-engine` :

```powershell
..\.venv\Scripts\python.exe -m app.main
```

`Lancer.ps1` détecte l'environnement dans le projet ou son parent et utilise `pythonw.exe`
pour éviter une console Python supplémentaire :

```powershell
.\Lancer.ps1
```

## Utilisation

1. Ouvrir **Nouveau challenge** et choisir Noir, Blanc, Noir 2 ou Blanc 2.
2. Choisir un preset ou régler les états : obligatoire, possible, interdite.
3. En mode aléatoire, choisir le total exact de règles et une seed facultative.
4. Si Monotype est actif, ouvrir la roue, exclure des types si souhaité, tirer puis confirmer.
5. Générer le challenge, lui donner un nom et sauvegarder le profil.
6. Préparer le jeu dans **Installation & diagnostic**, puis cliquer **Jouer**.

Le mode personnalisé inclut les obligations et leurs dépendances. Le mode aléatoire
complète le total avec les règles possibles ; une combinaison impossible est expliquée.
La partie normale conserve zéro règle. Chaque modification de réglage invalide l'aperçu.

Les presets Classic Nuzlocke, Hardcore Nuzlocke, Monotype, Chaos et Custom sont des
propositions modifiables, pas des définitions officielles universelles.

Monotype propose 17 types, **sans Fée**, avec trois modes : Souple (au moins un type),
Strict (type principal) et Pur (type unique). Le mode, les exclusions et les relances
sont conservés. Sans roue manuelle, la seed choisit le type à la génération.

Dans **Profils**, consulter le challenge et sa seed, reprendre les réglages pour créer
une copie ou mettre à jour la progression manuelle. Une sauvegarde de challenge crée
toujours un nouveau profil ; la modification du suivi existant demande confirmation.

## RetroBat et DeSmuME

Le diagnostic recherche des structures RetroBat réelles aux racines de disques et
dans les chemins déjà configurés, sans scanner tout le disque. Les chemins proposés
sont vérifiés ; plusieurs candidats restent à choisir. Les paramètres historiques
permettent toujours de saisir les chemins manuellement. `.nds` et `.zip` sont pris
en charge par l'assistant ; les ROM `.7z` ne le sont pas.

Le launcher lance **directement DeSmuME standalone** avec la ROM configurée, même si cet
émulateur est aussi utilisé depuis RetroBat. Elle ne modifie pas la configuration de
RetroBat et ne le pilote pas. Le champ RetroBat sert de repère local pour l'intégration
future. Le bouton Tester contrôle les chemins, sans démarrer un jeu.

Le chemin des sauvegardes est informatif : aucune sauvegarde n'est redirigée, supprimée,
copiée ou écrasée par cette application. DeSmuME conserve son comportement normal lorsque
vous jouez. Aucun émulateur, jeu, ROM ou asset Pokémon officiel n'est fourni.

## Connecter Lua

Il faut un build DeSmuME standalone proposant le menu **Tools > Lua Scripting**.
La présence d'un exécutable DeSmuME ne garantit pas son support Lua. L'application
n'ajoute aucun argument de lancement Lua supposé et ne pilote pas les menus de l'émulateur.

1. Dans **Connexion DeSmuME**, choisir le profil actif, ou le diagnostic sans
   profil, puis sélectionner Noir, Blanc, Noir 2 ou Blanc 2 et
   **Préparer la connexion**. Pour reproduire l'essai de Blanc, sélectionner **Pokémon Blanc**.
2. Dans DeSmuME, ouvrir le jeu correspondant et le laisser en cours d'exécution.
3. Ouvrir **Tools > Lua Scripting > New Lua Script**, sélectionner le chemin exact
   `connect.lua` affiché par l'application, puis cliquer sur **Run**.
4. Consulter l'état, le jeu identifié et le diagnostic. Un PID lancé ne prouve pas
   une connexion Lua ; celle-ci dépend des messages effectivement reçus.

Pour Blanc français, vérifier `Pokémon Blanc`, code `IRAF`, région `FR`, révision
`0` et profil `white_fr_rev0`, puis comparer le nombre de Pokémon, chaque espèce
(affichée par son identifiant), le niveau et les PV avec l'équipe visible dans le jeu.
Le [guide de connexion](docs/desmume-bridge.md#validation-prioritaire--pokémon-blanc)
détaille cette validation. La console de diagnostic accepte également
`python -m tools.bridge_diagnostic --game white --duration 60`.

Les données absentes sont affichées **Non disponible**. Une ROM, région ou révision
sans profil mémoire compatible ne donne pas lieu à une lecture d'équipe supposée.
Une mémoire d'équipe non initialisée ne produit pas de fausse équipe vide. Les
données d'équipe sont retirées de l'affichage en cas de déconnexion ou d'erreur.

Sur Blanc FR rev0, le test utilisateur confirme les changements de route, soins,
équipe et PV après combat. **Les valeurs d'équipe sont garanties après synchronisation
de la structure principale, notamment en fin de combat.** Les PV en temps réel
pendant le combat restent hors périmètre. Ce constat ne valide pas les autres jeux.

La préparation peut se faire sans chemin de ROM pour un jeu déjà ouvert manuellement.
Si un chemin est configuré, son en-tête est lu en lecture seule pour vérifier le jeu
attendu. Le transport écrit seulement dans le dossier local ignoré `runtime/bridge/`.
**Arrêter la connexion** arrête le suivi ; l'application ne ferme pas DeSmuME.

[Installation et dépannage de la passerelle](docs/desmume-bridge.md) ·
[Scripts Lua](lua/README.md) · [Profils et sources mémoire](docs/memory-map.md)

## Tests et contrôles

Les résultats des tests automatisés, leur environnement et les preuves des essais
réels sont consignés séparément dans le [rapport de vérification](docs/verification.md).
Les tests synthétiques couvrent les quatre codes de jeu, les quatre profils distincts
et le refus d'utiliser le profil d'un autre jeu avant de lire son équipe.

Avec l'environnement du projet :

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app
```

Avec l'environnement déjà préparé dans le parent :

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m compileall -q app
```

Les tests couvrent les obligations/interdictions, dépendances, conflits, jeux, seed,
comptage exact, Monotype et position finale de la roue, profils corrompus ou manquants,
configuration, arguments du launcher et intégrité de fichiers sentinelles ROM/sauvegarde.
La passerelle ajoute des tests de protocole, de sessions, de messages invalides,
de déconnexion et de reprise. Les tests Qt vérifient les signaux, l'affichage des
valeurs absentes, la réactivité pendant la préparation et l'arrêt du worker.
Les tests du launcher avec processus simulé sont distingués des essais réels dans
le [rapport de vérification](docs/verification.md).

Les tests du lecteur et du producteur Lua exécutent le code Lua sur des données
**synthétiques**. Ils nécessitent facultativement une bibliothèque Lua **5.1** compatible
avec l'architecture de Python. Pour indiquer une DLL installée localement :

```powershell
$env:PCE_LUA51_DLL = "C:\chemin\vers\lua5.1.dll"
..\.venv\Scripts\python.exe -m pytest tests/test_lua_gen5_reader.py tests/test_lua_bridge.py -q
```

Sans moteur Lua 5.1 disponible, ces tests sont marqués **skipped**, pas présentés comme
réussis. Le chemin de repli local est `../runtime/probe/lua5.1.dll`. Aucun binaire Lua
n'est distribué dans le dépôt. Ces tests ne remplacent pas la comparaison avec une
équipe réellement affichée dans le jeu.

## Architecture et limites

```text
app/
  main.py       démarrage, thème et logs
  models/       dataclasses et validation
  core/         catalogue, règles, tirages, profils
  bridge/       protocole versionné et état de connexion
  services/     configuration, launcher, préparation Lua, réception et worker Qt
  ui/           navigation, pages et roue Qt
data/           jeux, règles, types Gen V, presets et profils mémoire JSON
profiles/       un dossier par profil
lua/            points d'entrée et modules de transport, JSON et lecture Gen V
runtime/        sessions locales de la passerelle, ignorées par Git
tests/          tests pytest métier, fichiers et interface
docs/           architecture, roadmap et vérification
```

[Architecture détaillée](docs/architecture.md) · [Feuille de route](docs/roadmap.md) ·
[Passerelle DeSmuME/Lua](docs/desmume-bridge.md) · [Vérification de la livraison](docs/verification.md)

Les journaux rotatifs sont dans `logs/app.log`. `--debug` active les détails dont la
commande de lancement (les chemins sont alors visibles dans ce journal).
Les profils locaux, la configuration, les logs, les sessions de passerelle, les ROM,
les sauvegardes, les environnements Python, les caches et les secrets sont exclus de Git.

Le catalogue contient 15 règles. Les jeux futurs sont décrits dans les données mais
restent indisponibles. Une forte augmentation du catalogue nécessitera d'adapter la
recherche de combinaisons. Les blocages stricts, le vrai Randomizer et
l'empaquetage PyInstaller ne sont pas implémentés.

Les observations valides alimentent uniquement le profil actif compatible dont
la règle Nuzlocke est sélectionnée. Les profils livrés peuvent actuellement
émettre des changements de carte ; aucune rencontre réelle ne peut être consommée
avec leurs champs de combat inconnus.
Les adresses utilisées et leur statut de validation sont décrits dans la
[cartographie mémoire](docs/memory-map.md).

Documentation Qt utilisée : [Qt for Python](https://doc.qt.io/qtforpython-6/),
[QPropertyAnimation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QPropertyAnimation.html).
