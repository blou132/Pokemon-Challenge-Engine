# Vérification V0.4.1 et historique V0.4 / V0.3.6 / V0.3.5 / V0.3 / V0.2 / V0.1

## V0.4.1 — création, activation exacte et autoload Lua, 7 octobre 2026

Base exacte : `237614fe4269f1420e46c86c3de26758500b09f9`, dépôt propre sur
`feat/v0.4-runs-permadeath`, puis branche `feat/v0.4.1-run-flow-autolua`.
Aucune fusion dans `main`. Application **0.4.1**, lecteur Lua **0.4.0**,
protocole **2**, Run **schéma 1** et challenge **0.1.0**.

### État de référence et non-régression

Avant modification, la suite source a donné **1 510 réussites et un échec** :
`test_incomplete_identity_keeps_tracking_waiting_without_writes` a dépassé son
délai Qt de trois secondes. Les **20 tests du module concerné** ont ensuite
réussi sans modification. La compilation et le démarrage natif Windows ont réussi.
Ce résultat de référence n'est pas présenté comme une première exécution verte.

Résultat de la suite complète : **1 630 tests réussis, aucun échec, aucun ignoré**,
avec **1 511 cas historiques conservés et 119 nouveaux cas**. Rapport local
`runtime/v041-tests-final.xml`. Un complément de **81 tests ciblés**, tous réussis,
vérifie aussi le dernier ajustement du consentement dans les lancements configurés
sans AutoSetup. `compileall app tools` et le démarrage natif `app.main` sur données
isolées sont réussis après cet ajustement (fermeture propre, code 0).

Une première suite intermédiaire avait donné 1 610 réussites et un dépassement
du même délai de préparation Qt, dans un autre cas de `test_tracking_ui.py`.
Le helper de test cède désormais explicitement le GIL aux workers après le
traitement des événements Qt. Le délai maximal de trois secondes et les assertions
restent inchangés ; aucun test n'est désactivé. La suite complète ci-dessus a
ensuite réussi. Les attentes hors test et interruptions de session ne constituent
pas une mesure de performance de l'application.

Deux tests existants ont été adaptés
au lancement désormais asynchrone et à l'ordre Bridge avant processus ; leurs
vérifications de fond sont conservées. Les assertions du diagnostic sont enrichies
pour distinguer un jeu lançable d'un support Lua prêt. Aucun test n'a été supprimé pour faire
passer la suite.

| Nouveaux cas | Nombre |
| --- | ---: |
| Service d'autoload, consentement, INI et erreurs atomiques | 42 |
| Sources de création, éditeur existant et bibliothèque | 26 |
| Activation et navigation entre parties | 13 |
| Orchestration Jouer, heartbeat, timeout, reconnexion et contrôles | 19 |
| Verrouillage temporaire de l'accusé Windows | 10 |
| Disposition verticale du Mode Jeu avec partie et récupération Lua | 9 |

Les nouveaux tests couvrent les trois sources de création, snapshot indépendant,
filtres masquants, carte et compteur immédiats, A/B, restauration de sélection,
échecs atomiques de `active.json`, publications asynchrones périmées, ordre
bridge/autoload/processus, consentement, timeout, arrêt pendant préparation,
reconnexion, refus des anciennes sessions, sauvegarde/restauration INI et
verrouillage Windows temporaire de l'accusé Lua. Ce sont des **tests synthétiques**.

### Causes reproduites et correction du parcours

- La bibliothèque était déjà relue après création, mais ses filtres pouvaient
  masquer la nouvelle partie et l'ouverture du Mode Jeu recouvrait la page sans
  confirmation. La carte est maintenant relue, comptée, surlignée et rendue visible,
  avec « Partie créée » ; seuls les filtres qui la masqueraient sont réinitialisés.
- Une session A occupée pouvait refuser la reprise de B tout en conservant la
  fenêtre A. Le traitement d'activation ouvrait aussi cette ancienne fenêtre
  avant de lui associer B. L'intention de reprise est désormais mémorisée dès le
  clic, les signaux périmés sont ignorés et B est associée avant affichage.
  Une confirmation interne du worker précède l'écriture atomique de la sélection ;
  la publication finale et l'ouverture attendent son succès. Les identifiants
  demandé, contrôleur et `active.json` doivent correspondre, sinon les actions
  « Réessayer » et « Retour à Mes parties » sont proposées.
- Le lancement préparait auparavant Lua après avoir démarré DeSmuME. Il prépare
  maintenant la session, son `connect.lua` et l'autoload avant le processus.
- Les parties persistantes évitaient la lecture des contrôles dans `_game_changed`
  et `set_persistent_run` ne la remplaçait pas. La configuration de l'exécutable
  de la partie est relue à l'association, au changement d'environnement et à la
  réouverture. L'absence réelle de mapping propose « Configurer les contrôles ».

Le challenge direct réutilise `ChallengePage` et `ChallengeEngine`, garde
`profile_id = null` et fige toutes les règles et paramètres. Aucun nouveau moteur,
offset ou mécanisme d'application des règles n'est ajouté.

### Essai réel du bouton Jouer sur copies isolées

Rapport local : `runtime/v041/t04/report.json`, harnais `runtime/v041_verify.py`,
exclus de Git. Un dossier neuf contient les copies de l'EXE, des DLL vérifiées,
de Pokémon Blanc FR rev0 et d'une sauvegarde explicitement partagée entre A et B.
L'INI de départ a **AutoLoad=0** et un script personnel témoin conservé dans son
propre dossier Lua. Le harnais utilise les widgets Qt de PCE : formulaire de
création, bouton Jouer et bouton Activer du dialogue de consentement. Il n'envoie
aucune entrée au système ou au jeu et ne remplace aucun service de production.
Il ne prépare pas l'autoload à la place de l'application et n'ouvre pas Lua Scripting.

Build testé : DeSmuME x64 0.9.14 git#a779eb7, SHA-256
`34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
Les sources du mécanisme officiel restent distinctes de cette preuve réelle,
dans [lua-runtime.md](lua-runtime.md) et [desmume-bridge.md](desmume-bridge.md).

| Contrôle | Résultat réel du dernier essai |
| --- | --- |
| Création A puis B | Cartes présentes immédiatement ; compteurs 1/1 puis 2/2 ; confirmation et surlignage |
| Partie affichée | B avant son lancement ; A après reprise explicite, jamais A à la place de B |
| Jouer | Un seul clic pour B, puis un seul pour A ; aucun chargement manuel de script |
| Consentement | Un clic Activer lors de B ; choix réutilisé pour A, aucune seconde demande |
| Identité | `IRAF / FR / 0`, lecteur `0.4.0`, sessions Lua distinctes |
| Heartbeat | 34 messages pour B et 32 pour A au relevé ; interface « Lua · connecté » / « EN JEU » |
| Équipe | Feuillajou 511 N18, PV 48/48 ; Tritonde 535 N15, PV 42/42 ; Grotichon 499 N23, PV 79/79 |
| Durée et autosave | Plus de six secondes suivies dans chaque partie ; équipe enregistrée sur disque avant fermeture |
| Séparation A/B | A reste vide pendant le jeu de B ; statistiques de B inchangées pendant le jeu de A |
| Redémarrage PCE | Sélection B restaurée, puis reprise explicite de A |
| Contrôles | Mapping INI relu, touches disponibles dans les deux parties ; les entrées de jeu ne sont pas testées |
| Restauration | AutoLoad revient à 0 et Lua à son dossier précédent ; script personnel témoin inchangé |
| Intégrité | EXE/INI/DLL/ROM/save originaux inchangés par empreintes avant/après ; ROM et save copiées inchangées aussi |

Les premiers passages de ce harnais ont nécessité des corrections de vérification :
attente Qt qui ne cédait pas assez le GIL aux lectures de fichiers, attente de
l'enregistrement des références avant le clic Jouer, puis appel au lecteur INI
sans son argument de valeur par défaut. Ils ne sont pas comptés
comme des essais complets réussis. Le dernier passage se termine avec code 0.
Un verrou Windows ponctuel sur `ack.txt` observé dans le passage précédent a
motivé trois essais bornés de remplacement atomique (5 puis 10 ms d'attente),
avec propagation de toute erreur persistante ; les autres erreurs ne sont pas masquées.

### INI, repli manuel et limites

Après accord lié au chemin et à l'empreinte de l'exécutable, seuls
`[Scripting] AutoLoad=1` et `[PathSettings] Lua=<dossier PCE de cette session>`
sont configurés. Le loader porte le vrai nom `Path.stem` de la ROM préparée.
Un backup complet précède le remplacement atomique ; le journal local conserve
les anciennes lignes des deux clés. La restauration préserve les autres réglages
et refuse d'écraser une modification externe de ces clés. Aucun INI n'est édité
pendant l'exécution de DeSmuME. Désactiver l'option restaure les réglages avant le
prochain lancement manuel, émulateur fermé.

Build inconnu, support Lua non vérifié ou impossibilité d'autoload : repli manuel
explicite. Le jeu peut démarrer si ses autres références sont valides ; le support
Lua manquant doit être réparé pour obtenir des messages. Sans heartbeat au bout
de huit secondes, l'interface propose réessai, mode manuel et diagnostic sans
tuer DeSmuME. Reconnecter crée une nouvelle session et un nouveau loader ; dans
un processus déjà ouvert, l'exécution manuelle est nécessaire et l'INI reste intact.

Les neuf rendus Qt **Windows** inspectés couvrent les états attente/erreur/connecté,
1366×768 compact et standard, puis 1920×1080 standard. Le décor central s'adapte
sans chevauchement avec Jouer. Les grandes dimensions sont des widgets enfants
à taille exacte, pas la preuve d'un écran physique 1920. Preuves locales :
`runtime/v041-ui/review-geometry.json` et PNG associés, exclus de Git.

L'essai réel ne provoque ni variation de PV, K.O., soin après mort, capture,
combat ou changement de zone. Aucune zone nommée n'a été reçue ; aucune validation
réelle supplémentaire de ces lectures n'est revendiquée. Les autres jeux/builds,
longs chemins particuliers et configurations personnelles non testés restent
**En attente de validation sur la machine utilisateur.** Aucune écriture RAM,
aucune modification de ROM ou sauvegarde utilisateur, aucune commande de jeu.

## V0.4 — parties et mort permanente, 3 octobre 2026

Base exacte : `58395b4607cc38270dd68b8a31d5a0fd44a880ea`, branche source
`feat/v0.3.6-auto-setup`. Avant modification : dépôt propre, **1 167 tests réussis,
aucun ignoré** (218,50 s), compilation et point d'entrée Qt Windows réussis.
Travail sur `feat/v0.4-runs-permadeath`, sans fusion dans `main`.

Versions : application **0.4.0**, Lua **0.4.0**, Run **schéma 1**. Challenge
**0.1.0**, progression historique **2** et protocole **2** conservés.
Les champs PID/OTID et la capacité `party_identity` sont facultatifs ; les messages
historiques continuent d'être acceptés. Aucun offset absolu mémoire n'est ajouté.

### Tests synthétiques et interface

**Résultat complet : 1 511 tests réussis, aucun ignoré.** Les 1 167 cas historiques
sont conservés, avec 344 nouveaux cas. Deux assertions d'équipe Lua historiques
sont enrichies des deux champs d'identité, sans retirer les valeurs déjà vérifiées.
Le temps total affiché par pytest inclut une longue interruption de session et
ne constitue pas une mesure de performance. La compilation `app`/`tools` et le
point d'entrée natif `app.main` sont aussi vérifiés sur des données temporaires.
Après les derniers ajustements de l'affichage, **124 tests ciblés d'intégration
et d'interface** ont également réussi, ainsi qu'une nouvelle compilation et un
nouveau démarrage natif avec fermeture propre (code 0).

La suite couvre UUID, classique, copie figée du profil, écritures atomiques,
corruption préservée, modifications concurrentes, sessions, changements de jeu,
heartbeat, arrêt de DeSmuME, crash, debounce, erreurs disque et fermeture/reprise.
Les tests de mort couvrent transition PV, première observation zéro, règles
inactives, collisions, changement de slot/niveau/espèce, soin après mort,
confirmation manuelle et correction historisée. La table d'évolution couvre les
649 espèces ; branches sœurs, dévolution et création de Munja ne sont pas prises
pour une évolution du même individu.

Les essais Qt couvrent 0/1/20 parties, filtres, recherche, tris, six sections,
cimetière, confirmations, données inconnues et derniers backups. La revue a aussi
reproduit puis corrigé fermeture/réouverture du Mode Jeu, lancement historique
pendant une partie, réactivation administrative d'une archive, sauvegarde refusée
avant lancement et clics rapides sur les badges. Les références doivent être
durablement enregistrées avant le démarrage du processus.

Rendus inspectés avec le backend **Qt Windows** : bibliothèque à 1146×718 et
1700×1030 (surfaces prévues après sidebar/chrome pour fenêtres 1366/1920), création,
cimetière, équipe soignée toujours marquée morte, puis Mode Jeu à **1366×768** et
**1920×1080** exacts. Les grandes surfaces sont rendues comme widgets enfants à
taille fixe, le moniteur disponible bridant les fenêtres natives de cette taille.
Il s'agit de rendus de widgets, pas de captures prouvant un écran physique 1920.
Fichiers de revue locaux : `runtime/v04-ui/`, exclus de Git.

### Essai réel sur copie isolée de Pokémon Blanc FR rev0

Le harnais local `runtime/v040_verify.py`, non versionné, a créé un dossier neuf
avec copies de l'exécutable, ROM et `.dsv`, DLL Lua vérifiées et INI de test dont
toutes les sorties restent dans ce dossier. L'autoload Lua de cet INI sert au
harnais ; il ne prouve pas une activation automatique de Run dans l'interface produit.
Aucune entrée clavier/joypad, commande de combat, modification RAM ou chargement
de save state n'a été envoyé. Seul le processus créé par cet essai a été arrêté.

Services de production utilisés : AutoSetupService, RunLaunchService,
GameModeService, EmulatorService, BridgeService, RunManager et RunTrackingService.
Partie créée : **Blanc V0.4 Test**, règles Nuzlocke, Mort permanente, Species Clause.
Build DeSmuME x64 0.9.14 git#a779eb7, SHA-256 de l'exécutable
`34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.

Résultat du rapport local `runtime/v040/t01/report.json` :

| Contrôle | Résultat réel |
| --- | --- |
| Identité et heartbeat | Blanc `IRAF / FR / 0`, script `0.4.0`, 84 messages |
| Équipe | 2 Pokémon : Grotichon 499, niveau 19, PV 67/67 ; Feuillajou 511, niveau 17, PV 46/46 |
| Identité individuelle | Deux paires PID/OTID reçues et deux individus persistés ; pas de comparaison indépendante de leurs valeurs brutes |
| Partie et durée | Statut actif, 21,0877 s suivies avec processus vivant et messages valides |
| Autosave en session | Équipe présente sur disque avant fermeture, durée intermédiaire 17,1913 s |
| Réouverture | Même run, 21,0877 s conservées, aucune session active ni temps hors ligne ajouté |
| Zone nommée | Non reçue pendant cet essai sans interaction |
| Variation de PV, K.O., soin après mort | Non provoqués et non observés ; aucune validation réelle revendiquée |
| Intégrité | Empreintes ROM/save/EXE/INI/DLL originaux inchangées ; ROM de copie inchangée |

La relecture du fichier réel après renforcement de la validation du modèle a
également réussi sans le modifier. Le temps suivi est celui de la réception
éligible, pas le compteur interne du jeu ; les menus/pauses ne disposent pas d'un
drapeau fiable pour être déduits automatiquement.

### Validation utilisateur et limites

**En attente de validation sur la machine utilisateur.** Restent à parcourir dans
la V0.4 : zones nommées, variation de PV hors combat, K.O. après synchronisation
de fin de combat, mort virtuelle conservée après soin, évolution, plusieurs parties,
reconnexions, fermeture/reprise et crash en usage prolongé. Le constat utilisateur
V0.3.6 sur zones et PV reste une preuve distincte ; il ne remplace pas ces essais.
Les retours serviront aux corrections V0.4.1/V0.4.x.

Les captures et badges restent manuels. Aucun ajout à l'équipe n'est une preuve
de capture. Une ambiguïté PID/OT ne redevient pas fiable automatiquement. Une mort
manuelle sans individu stable reste au cimetière sans condamner arbitrairement un
membre de l'équipe. La règle est virtuelle : aucune suppression, déplacement PC,
interdiction de soin, écriture RAM ou patch ROM. Les anciens profils restent
intacts, sans migration forcée ni mise à zéro. `runs/`, ROM, sauvegardes, secrets,
configurations et journaux locaux sont exclus de Git.

## V0.3.6 — installation et corrections de profils, 2 octobre 2026

Base exacte : `ce8d888629f613b84d3bac3a9831b27cfbea1845`, V0.3.5.
Les **960 tests de référence ont réussi, aucun ignoré**, avant modification,
ainsi que la compilation et le démarrage Qt. Le temps affiché lors de ce premier
passage inclut une longue interruption de session et ne mesure pas les performances.
Travail sur `feat/v0.3.6-auto-setup`, sans fusion dans `main`.

Application `0.3.6` ; scripts `0.3.0`, protocole `2`, challenge `0.1.0` et
progression `2` conservés. Les lecteurs Lua d'équipe et de carte n'ont pas changé.

**Résultat final : 1 167 tests réussis, aucun ignoré, 200,09 s**, avec Python
3.13.7, pytest 9.1.1, PySide6 6.11.2 et Lua 5.1 local. Les 960 cas historiques
sont conservés, avec deux attentes adaptées à la demande sur les règles inactives,
et 207 nouveaux cas. Un passage précédent interrompu avait atteint 1 166 réussites
et un dépassement du délai Qt de déconnexion ; ce test a repassé isolément, puis
le passage complet ci-dessus a réussi sans modifier son délai ni sa logique.

### Régressions de profils et paramètres

L'inspection locale en lecture seule du cas signalé a trouvé un profil déjà
enregistré en mode normal avec zéro règle. Les traces disponibles situaient la
génération de l'aperçu personnalisé à trois règles après cette création, sans
nouvelle sauvegarde correspondante. Cette observation ne prouve pas une perte
de règles pendant la désérialisation ; aucun profil utilisateur n'a été réécrit.

Un défaut d'interface distinct a été reproduit : après création d'un nouveau
profil, la page pouvait conserver l'ancien identifiant sélectionné, même avec
le même nom et la même seed. La sauvegarde relit désormais son résultat exact
et sélectionne le nouvel ID. L'aperçu non enregistré est signalé explicitement.

Les régressions parcourent génération → modèle → fichier → nouvelle instance →
affichage → reprise. Blanc 2 + Classic Nuzlocke conserve exactement Nuzlocke,
Mort permanente et Species Clause, ainsi que jeu, mode, seed et preset. Les
profils personnalisés, paramètres actifs et profils normaux sont également couverts.
Les états Possible/Interdite n'activent aucun paramètre final. Monotype, Level Cap
et Catch Limit sont masqués ou exclus lorsqu'inactifs ; le type et le mode Monotype
restent visibles et persistés lorsqu'actifs. Deux attentes historiques ont été
adaptées à cette nouvelle spécification, sans supprimer les tests concernés.

### Vérifications synthétiques et interface

Les nouveaux tests couvrent découverte bornée, en-têtes des quatre jeux, ZIP et
collision du cache, installation Lua x86/x64 avec réseau simulé, confirmations,
rollback, erreurs de permissions, provenance locale, diagnostic avant lancement,
nettoyage, reconnexion et exclusion des scripts arrêtés. Une présence de DLL
n'est jamais assimilée à une console Lua testée.

Les rendus Qt Windows ont été inspectés à **1366×768 et 1920×1080**, avec rendu
hors écran aux dimensions exactes. L'assistant a aussi été inspecté à 980×720 :
Lua absent, installation prête, réparation partielle, détails et stockage. Le
contraste des panneaux et onglets a été corrigé après inspection. Les parcours
A–E des profils ont été exécutés sur des données synthétiques isolées, avec
fermeture/réouverture et reprise. Les captures restent sous `runtime/`, ignorées.
Elles ne prouvent aucune lecture de jeu réelle.

`compileall` réussit. Le vrai point d'entrée `app.main` affiche une fenêtre sous
Windows, exécute Qt et se ferme avec code 0. Le test de démarrage utilise un
catalogue copié dans un dossier temporaire et une découverte de disques vide ;
il attend la fin de la préparation avant de fermer.

### Essais réels sur copies isolées

Build : **DeSmuME 0.9.14 git#a779eb7 x64-JIT SSE2**, empreinte
`34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
ROM Blanc locale, émulateur et sauvegarde copiés dans un RetroBat de test.
L'INI créé pour l'essai confine Battery, Lua, StateSlots et les autres sorties
dans ce dossier. Aucun clavier, déplacement ou combat n'a été automatisé.

| Étape | Résultat observé | Limite |
| --- | --- | --- |
| Jeu uniquement en ZIP dans le RetroBat de test | Détection `white / IRAF / FR / 0`, extraction contrôlée et profil enregistré | ZIP créé depuis une ROM locale, aucun téléchargement de jeu |
| DeSmuME sans DLL Lua | Diagnostic manquant, lancement non prêt | Diagnostic sur disque |
| Réparation réelle | Archive officielle téléchargée ; deux DLL x64 installées et empreintes/PE vérifiés | x86 examiné dans l'archive, pas exécuté dans DeSmuME |
| Cache | Réutilisation sans modification de date du `.nds`, archive inchangée | Chemin réel de 241 caractères ; les chemins >259 sont refusés avant extraction |
| Lancement par `GameModeService` | Processus et fenêtre du jeu identifiés par PID/chemin | Fenêtre externe, pas d'intégration ni mesure FPS |
| APIs Lua et protocole | Lua 5.1, `memory.readbyte`, `emu.frameadvance`, heartbeat et identité `IRAF / FR / 0`, profil `white_fr_rev0`, protocole 2 reçus | Chargement par autoload configuré uniquement dans l'INI de test |
| Équipe | Deux entrées réellement reçues ; second essai : espèce 499, niveau 19, PV 67/67 ; espèce 511, niveau 17, PV 46/46 | Lecture de la structure principale ; pas de comparaison visuelle de combat pendant cet essai |
| Zone | Valeurs brutes de carte reçues, zone nommée absente à l'écran de démarrage | Ne constitue pas une revalidation de la Route 3 |

Les deux essais locaux sont conservés dans `runtime/v036/01` et `02`. Le premier
rapport utilisait un champ `zone_received` trop large : il signifiait seulement
qu'un ID brut existait. Le second sépare `map_value_received=true` et
`named_zone_received=false` ; aucune zone nommée n'est revendiquée pour cet essai.
Le scénario de jeu utilisateur ci-dessous constitue une preuve distincte.

L'autoload officiel a été vérifié sur ces copies. Il utilise `[Scripting] AutoLoad`
et le script nommé comme la ROM dans `[PathSettings] Lua` ; voir les
[sources et limites](lua-runtime.md). Le produit ne change pas silencieusement
cette politique globale ni les scripts personnels : **Run reste manuel dans le
parcours livré**. La création de session, le chemin à copier et l'ouverture du
dossier sont assistés. Aucun argument CLI Lua n'est inventé.

À la fin de chaque essai, SHA-256, taille et date des ROM, sauvegarde, INI,
exécutable et DLL originaux ont été comparés : **inchangés**. Les archives de
test sont également inchangées. Seuls les processus créés pour l'essai ont été
arrêtés ; aucune donnée de jeu, DLL, configuration ou trace locale n'est publiée.

Un dernier essai d'installation, sous `runtime/v036-installer-final/`, vérifie le
chemin final du cache : téléchargement officiel de 166 260 octets, installation
x64, second appel sans écriture, inventaire d'une archive dans le stockage, puis
nettoyage confirmé de cette seule archive. DLL et journal restent présents ;
exécutable original et copie gardent leurs empreintes et dates. Cet essai ne lance
pas l'émulateur et ne prétend donc pas valider à nouveau les APIs en exécution.

### Validation rapportée par l'utilisateur et limites acceptées

L'utilisateur confirme sur **Blanc FR rev0 / IRAF**, avec ce build DeSmuME,
identité, équipe, espèces, niveaux, PV et zone, dont Feuillajou, Gruikui et Route 3.
Il rapporte des changements immédiats de route, de soins et d'équipe hors combat.
Les PV ne suivent pas le combat en temps réel, puis se synchronisent à sa fin,
y compris un Pokémon à zéro PV. Ce comportement est accepté pour cette version.

**Les valeurs d'équipe sont garanties après synchronisation de la structure
principale, notamment en fin de combat.** Il s'agit de la limite fonctionnelle
observée sur ce jeu ; elle ne promet pas une compatibilité universelle. Noir,
Noir 2 et Blanc 2 conservent leurs propres statuts de validation. Les captures
réelles, structures de combat, application stricte, vitesse directe x2/x4 et
gestionnaire complet de parties restent hors périmètre.

Un profil reste une configuration réutilisable. Le suivi V0.3 continue de
persister automatiquement les événements applicables ; l'équipe affichée et
la durée de session ne sont pas encore un historique durable de run. Cela est
distinct de la sauvegarde Pokémon `.dsv` et du futur « Mes parties ».

## V0.3.5 Mode Jeu — 1er octobre 2026

Base : `e7fc0c20afb899579ecf5d7e6558525b443c6d0d`, branche
`feat/v0.3-nuzlocke-tracking`. Avant modification : **779 tests réussis, aucun
ignoré, 117,93 s**. Nouvelle branche : `feat/v0.3.5-game-mode`, sans fusion.
Application `0.3.5` ; scripts Lua `0.3.0`, protocole `2`, challenge `0.1.0` et
progression `2` conservés.

### Interface et non-régression

Après les dernières corrections : **960 tests réussis, aucun ignoré, 111,90 s**
avec Python 3.13.7, pytest 9.1.1, PySide6 6.11.2 et la DLL Lua 5.1 locale.
Les **779 tests historiques sont conservés**, avec 181 nouveaux cas couvrant
les réglages/contrôles (49), les sauvegardes (75), les services du Mode Jeu (32)
et son interface (25). Les tests de données de jeu demeurent synthétiques.
`python -m compileall -q app tools` réussit.

Les tests nouveaux couvrent notamment les profils par jeu, la migration en
mémoire, les conflits clavier, la conservation de l'INI et ses backups,
les chemins invalides, fichiers verrouillés et permissions refusées,
la copie vérifiée et la rétention, la confirmation de restauration et le refus
si un émulateur est ouvert, les états de vitesse demandés, le verrouillage des
profils pendant une session et la synchronisation des chemins vers Connexion Lua.
L'audit Git vérifie les exclusions, y compris les fichiers temporaires locaux
après interruption, et ne détecte aucun fichier interdit ni format de secret usuel.

Le point d'entrée natif Windows `tools.verify_ui --entrypoint` a affiché la
fenêtre, exécuté la boucle Qt puis fermé l'application proprement (code 0).
Les rendus du Mode Jeu à **1366×768** et **1920×1080** ont été inspectés : trois
colonnes accessibles, contrôles lisibles, équipe à six emplacements et panneaux
latéraux défilables. Le grand rendu a également été inspecté en bas de panneau.
Ces images utilisent exclusivement un profil et une passerelle **synthétiques** ;
elles restent dans `runtime/game-mode-ui-review/`, ignoré par Git, et ne prouvent
aucune lecture réelle d'équipe, de zone ou de capture.

### Essais réels sur copies isolées

Build observé : **DeSmuME 0.9.14 git#a779eb7 x64-JIT SSE2**.
SHA-256 du binaire : `34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
La ROM Blanc, la sauvegarde et l'émulateur ont été copiés dans un dossier de
validation ignoré. Les chemins INI de Lua, sauvegardes et save states pointaient
exclusivement vers ce dossier. Aucun déplacement, combat, pression de touche
ou modification de mémoire Pokémon n'a été automatisé.

| Essai | Observation réelle | Limite de la preuve |
| --- | --- | --- |
| Lancement avec `LauncherService`, puis `GameModeService` | Lua 5.1 a répondu avec `IRAF`, compteur à 121 frames ; fenêtre retrouvée par PID + chemin, titre Pokémon Version Blanche | Ne revalide pas l'équipe ou les rencontres V0.3 |
| Export INI contrôles/graphismes/MAX puis x1 | Backup égal à l'INI précédent ; valeurs relues ; deux relancements réels réussis | Aucun facteur FPS mesuré, aucune pression de la nouvelle touche, qualité visuelle non comparée |
| Protection INI | Export refusé pendant que le processus de test s'exécutait | Pas une transaction avec un émulateur qu'un autre programme lancerait simultanément |
| Fenêtre externe | Titre lu ; appel de placement sur son rectangle courant, géométrie conservée | Pas de validation multi-écrans/DPI ni d'embedding |
| Save state | `savestate.save(0)` réel a créé `StateSlots/fixture.ds0` ; inventaire du slot 0 non vide et des neuf autres vides | Chargement du save state et miniatures non testés ; PCE n'injecte pas cette commande |
| Backups | Copies DSV de 524 410 octets vérifiées, rétention de deux copies après trois créations, restauration confirmée d'une copie de test vérifiée octet par octet | Aucun fichier original utilisé comme cible |
| Automatismes de session | Backups activés au lancement et à la fermeture produits par `GameModeService` après observation de l'arrêt de son processus | Timer périodique couvert par simulation, pas par attente réelle longue |

Avant/après chaque lancement, empreinte SHA-256, taille et date de modification
de l'INI et de la sauvegarde originaux ont été comparées : **inchangés**. Seuls
les processus créés pour l'essai ont été arrêtés. Les traces, copies, configs et
save states restent dans `runtime/v035-validation/`, exclus de Git ; aucun
chemin utilisateur ou fichier de jeu n'est publié.

### Ce qui reste préparé ou indisponible

- Les boutons de vitesse du Mode Jeu changent l'**état demandé**. Aucune commande
  directe ni mesure du facteur réel ; x1/MAX exportables au prochain lancement,
  x2/x4 à régler manuellement dans DeSmuME. Fast-forward et hotkeys sont documentés.
- Les options graphiques et le format clavier sont documentés pour le binaire
  identifié ; leur effet visuel et chaque touche doivent encore être essayés
  par l'utilisateur. Les builds inconnus restent sans export activé.
- Manettes, shaders, embedding, contrainte de save states et randomisation réelle
  ne sont pas implémentés. La conformité Monotype n'est pas déduite sans données.
- Les rencontres, captures et fuites réelles V0.3 restent indisponibles faute de
  lectures FR documentées. La V0.3.5 ne transforme pas les fixtures en preuve réelle.

Pour ces essais utilisateur non réalisés : **En attente de validation sur la machine utilisateur.**

## V0.3 en cours — 1er octobre 2026

Base : `f0f66e2c00e8ba53f39651fe1eaeb4e1713deedb`, branche
`feat/v0.2-desmume-bridge`. Avant modification : **598 tests réussis, aucun ignoré,
34,36 s**. Le travail V0.3 est sur `feat/v0.3-nuzlocke-tracking` ; aucune fusion.

Après implémentation et corrections : **779 tests réussis, aucun ignoré,
91,28 s** avec Python 3.13.7, pytest 9.1.1, PySide6 6.11.2 et la DLL Lua 5.1
locale. La suite existante est conservée. `compileall -q app tools` réussit.

Contrôles nouveaux, tous **synthétiques** pour les données de jeu :

- Cartes Noir/Blanc FR : adresses distinctes, uint16, regroupements sourcés,
  identité réelle du lecteur simulée, inconnues et transitions ; aucune adresse BW
  transférée aux suites BW2 et aucune fausse classification depuis un tampon ennemi.
- Protocole v1/v2, valeurs nulles, valeurs contradictoires, journal conservé malgré
  la perte des snapshots, acquittement après traitement et refus d'un autre jeu.
- Exécution du producteur Lua jusqu'au service Python et aux fichiers du profil
  pour capture, K.O., fuite joueur, fuite sauvage et résultat inconnu. Ces combats
  sont injectés comme **fixtures de contrat du lecteur**, sans offsets RAM inventés.
- Long flux de heartbeat ne remplissant pas le journal ; saturation à 256
  observations préservant les événements et signalant l'erreur ; reprise Lua et
  refus d'un index corrompu.
- Première rencontre, Species Clause active/inactive, zone déjà utilisée,
  changements de zone en combat, reconnexion et événements idempotents.
- Profil absent, mauvaise identité, règle inactive, migration d'anciens suivis,
  JSON corrompu et récupération après interruption entre les remplacements de fichiers.
- Interface : sélection explicite du profil, verrouillage pendant la session,
  résultat/restauration/historique et conservation du suivi automatique pendant
  une modification manuelle.

L'entrée native Windows `tools.verify_ui --entrypoint` a démarré puis fermé
l'application sans erreur. Des rendus des widgets Qt ont été inspectés à
**1060×640** et **1366×768** avec la police Segoe UI : sélection du profil,
capture factice et lectures de combat indisponibles sont lisibles. Ces rendus
utilisent un profil **« Démonstration synthétique »** et restent dans le dossier
ignoré `runtime/v03-ui/`. Ils ne prouvent aucune lecture d'une partie réelle.

**Aucun nouvel essai réel de rencontre n'a été réalisé pour V0.3.** Aucun
déplacement, combat ou choix de capture n'a été automatisé. Aucune ROM ni
sauvegarde utilisateur n'a été modifiée par ce travail. La validation réelle
V0.2 de l'équipe Blanc ci-dessous reste un résultat historique distinct.

Les cartes ont des sources et des tests synthétiques ; les lectures de combat
et de résultat des ROM françaises restent **non implémentées faute d'adresses
suffisamment documentées**. Le pipeline réel zone → rencontre → résultat → profil
ne fonctionne donc pas encore entièrement. **La V0.3 n'est pas terminée.**

**En attente de validation sur la machine utilisateur.** La
[procédure Nuzlocke](nuzlocke-tracking.md#validation-utilisateur-prioritaire--blanc-fr-rev0)
sépare l'essai de carte disponible maintenant des essais de rencontre bloqués
par les lectures manquantes. Les [sources de suivi](tracking-sources.md)
expliquent ce qui est retenu et ce qui n'est pas déduit.

## Historique de validation V0.2

## Extension aux quatre jeux Gen V — 30 septembre 2026

Le catalogue, les paramètres, le launcher, le protocole v1, la préparation Lua
et la page Connexion DeSmuME acceptent `black`, `white`, `black2` et `white2`.
Les profils français de révision 0 sont séparés :

| Jeu | Code | Profil | Compteur / début de l'équipe |
| --- | --- | --- | --- |
| Noir | `IRBF` | `black_fr_rev0` | `0x02234930` / `0x02234934` |
| Blanc | `IRAF` | `white_fr_rev0` | `0x02234950` / `0x02234954` |
| Noir 2 | `IREF` | `black2_fr_rev0` | `0x0221E408` / `0x0221E40C` |
| Blanc 2 | `IRDF` | `white2_fr_rev0` | `0x0221E428` / `0x0221E42C` |

Les décalages Blanc/Blanc 2 sont explicites dans les branches françaises de
PokeLua, avec sources épinglées dans [memory-map.md](memory-map.md).
Ils ne proviennent pas d'une supposition d'égalité entre versions.

La suite complète a réussi : **598 tests, aucun ignoré**, en 37,67 s,
avec Python 3.13.7, PySide6 6.11.2 et la DLL Lua 5.1 locale. La compilation et
le démarrage natif Qt (`tools.verify_ui --entrypoint`) ont aussi réussi.
Les quatre cartes d'accueil sont lisibles à 1060×640 et 1366×768.

Les tests synthétiques couvrent les quatre codes, les 32 permutations du PID
sur chaque profil, le transport Lua → JSON → Python et les douze associations
avec un profil étranger. Ces associations sont refusées avant toute lecture
d'équipe. Le protocole refuse aussi une identité dont `game_code` et `game_id`
se contredisent. Les anciens messages valides Noir/Noir 2 restent acceptés.
Les configurations V0.1 sont chargées sans réécriture, leurs chemins conservés
et les deux nouveaux chemins initialisés en mémoire. Les profils de challenge
restent au schéma `0.1.0`.

### Essai réel de Pokémon Blanc

Une copie de la ROM personnelle et une copie de la sauvegarde `.dsv` existante
ont été chargées dans un DeSmuME x64 isolé sous `runtime/white-validation/`.
L'exécutable et les DLL sont ceux de l'essai Noir 2 décrit plus bas ; la
configuration Battery/States/Lua de cette copie ne vise que ce dossier.
Le script et les services de production sont utilisés sans injection de
messages simulés. L'instrumentation locale de test utilise seulement
`joypad.set` pour les menus et `gui.gdscreenshot` pour lire les écrans rendus,
API documentées dans le
[moteur Lua DeSmuME](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/lua-engine.cpp).
Cette instrumentation ne fait pas partie des scripts distribués.

Le pont a reçu `hello`, `heartbeat`, puis `party_update` et identifié
`white / IRAF / FR / 0`, avec `white_fr_rev0`. Les données d'équipe effectivement
reçues depuis la RAM sont :

| Place | Espèce, identifiant national | Niveau | PV actuels / maximum |
| --- | --- | --- | --- |
| 1 | Feuillajou, `511` | 15 | 6 / 42 |
| 2 | Gruikui, `498` | 14 | 45 / 45 |

**La comparaison visuelle a réussi** : le menu Pokémon du jeu montre exactement
ces deux espèces, ces niveaux et ces PV. Les noms associés aux identifiants
nationaux sont confirmés par
[la table française PKHeX](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/text/other/fr/text_Species_fr.txt#L499-L512).
La page Qt de production a ensuite reçu trois nouveaux messages du même
producteur DeSmuME réel et affiché cette équipe, le code `IRAF`, la révision 0
et le profil `white_fr_rev0`. Aucune valeur n'a été injectée dans le protocole
pour obtenir ce résultat.

Le statut du profil Blanc est donc **`real_sample_verified`** : un échantillon
réel comparé. Les trois autres profils conservent **`source_documented`**.
Les tests synthétiques restent un contrôle distinct et ne changent pas à eux
seuls ces statuts.

Après la fermeture du test, les **empreintes SHA-256 et dates de modification**
de l'archive ROM Blanc, de sa sauvegarde `.dsv` originale et de la configuration
DeSmuME d'origine sont inchangées. Le processus isolé a été arrêté. Les écrans
du jeu, le nom du joueur, les ROM et sauvegardes restent exclus de Git.
Les traces locales sont dans `runtime/white-validation/` : `result.json`,
`ui_result.json`, `party-real.png` et `ui-real-white-top.png`/`bottom.png`.

Le premier essai avait été interrompu par un verrou Windows/OneDrive sur
l'export de diagnostic `latest_state.json` du banc de test. Ce fichier n'est
pas le transport de production, qui emploie des noms de snapshots inédits.
Après correction de l'export du banc, l'essai complet ci-dessus a réussi.

Ces observations concernent cette ROM et cette équipe. Elles ne valident pas
toutes les situations de jeu, toutes les sauvegardes, les révisions différentes
ou les ROM modifiées. Noir, Noir 2 et Blanc 2 restent, pour leur **équipe réelle**,
**En attente de validation sur la machine utilisateur.** Noir 2 dispose déjà
d'une validation réelle du transport et de l'identité, détaillée ci-dessous.
La branche de travail reste `feat/v0.2-desmume-bridge` ; aucune fusion dans `main`.

## Historique V0.2 initiale — contrôles avant l'extension Blanc

Branche : `feat/v0.2-desmume-bridge`. Base V0.1 : `ac1fa31`, déjà publiée
sur `main`. Aucune fusion automatique dans `main`.

État à la date de ce premier essai, avant la validation Blanc décrite ci-dessus :
**transport réel et identification de Noir 2 validés. Lecture d'une équipe,
des niveaux et des PV : En attente de validation sur la machine utilisateur.**
Le décodeur d'équipe est expérimental ; la V0.2 n'est pas déclarée entièrement
validée pour ces lectures. Aucun mécanisme strict Nuzlocke n'est ajouté.

| Contrôle | Résultat observé |
| --- | --- |
| Suite complète, incluant les 191 tests V0.1 | **453 tests réussis**, aucun ignoré, 31,56 s |
| Compilation `python -m compileall -q app tools` | Réussie |
| Point d'entrée `python -m tools.verify_ui --entrypoint` | Fenêtre Windows, boucle Qt et fermeture propres, code 0 |
| Protocole/service/CLI | Types, versions, JSON incomplet, doublons, taille, sessions, timeout, reconnexion et arrêt couverts |
| Producteur Lua et décodeur | Lua 5.1 exécuté avec RAM synthétique ; comparaison aux attentes Python ; aucune preuve d'équipe réelle déduite de ces tests |
| DeSmuME → script de production → BridgeService | `hello`, puis heartbeat reçus ; identité `black2 / IREF / FR / 0` |
| Fermeture forcée de l'émulateur isolé | `disconnected` après 3,3 s sans message ; équipe absente |
| Redémarrage de ce DeSmuME, même session | Reconnexion ; séquence continue de 5 vers 6 puis 9 |
| Arrêt demandé par Python | Marqueur `stop` consommé ; `emulator_closing`, séquence 10 |
| CLI réel, surveillance de 12 s | Code 0 ; 40 messages, dont 39 heartbeat ; fréquence reçue d'environ 4,10/s sur cet essai |
| Interface Qt avec vrai producteur DeSmuME | « Connectée au script Lua », « Pokémon Noir 2 », `FR / IREF`, révision 0, équipe « Non disponible » après quatre messages |
| Panel diagnostic Qt | Rendu et défilement contrôlés aux résolutions 1366×768 et 1920×1080 |
| Intégrité des originaux | SHA-256 **et dates de modification inchangés** pour cinq fichiers contrôlés avant/après les essais |

### Installation et isolation du test réel

Le test utilise une copie de l'exécutable local
`DeSmuME-VS2022-x64-Release.exe`, renommée pour l'essai. Son empreinte SHA-256
est `34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0`.
Le binaire n'expose pas de version produit exploitable : aucune version
DeSmuME non vérifiée ne lui est attribuée.

Les DLL Lua x64 `lua51.dll` et `lua5.1.dll` viennent de
[l'archive du dépôt officiel DeSmuME épinglée](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/lua/lua.7z).
Elles ont été placées uniquement à côté de la copie de test. L'installation
RetroBat originale, qui ne contenait pas ces DLL, n'a pas été modifiée.

Une copie `.nds` a été extraite de l'archive personnelle existante de Noir 2
français. Aucun jeu n'a été téléchargé. Le code `IREF` et la révision `0`
ont été lus d'abord dans son en-tête, puis réellement dans la RAM DeSmuME.
L'identité concorde ; cela ne certifie pas tous les octets d'une ROM ou d'un hack.

Le dossier ignoré `runtime/probe/` contient l'émulateur isolé, cette copie,
ses propres dossiers Battery/States et sa propre configuration. Le mécanisme
DeSmuME `[Scripting] AutoLoad=1` charge le Lua portant le nom de la ROM dans
le dossier Lua de **cette copie uniquement**. La prise en charge provient de
[main.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/frontend/windows/main.cpp#L3026).
Le launcher de l'application conserve la procédure manuelle documentée ;
aucune option CLI `--lua` n'a été inventée.

Les cinq originaux contrôlés sont l'archive de Noir 2, la configuration
DeSmuME d'origine et les trois fichiers de sauvegarde DS déjà présents.
Leurs chemins et leurs empreintes de sauvegarde restent dans les traces
locales ignorées, sans être publiés. Les processus de test ont été arrêtés.
La passerelle ne contient aucune écriture mémoire ; seules ses propres
configurations, séquences et publications JSON sont écrites par le pont.

### Limites observées et reproduction

Aucune sauvegarde Noir 2 contenant une équipe n'était disponible pour cet
essai. Au démarrage, le lecteur a rencontré un compteur nul et signalé
« Equipe non initialisee ou aucun Pokemon ». Il a publié `party_size: null`
et `party: null`, sans prétendre avoir mesuré une équipe vide. Aucun niveau,
PV ou identifiant d'espèce réel n'a donc été validé. Pokémon Noir et les
autres régions n'ont pas été testés dans un émulateur réel.

Pour terminer cette validation, suivre [la procédure de connexion](desmume-bridge.md),
ouvrir une partie française de révision 0 avec une équipe, puis comparer le
nombre de Pokémon, leurs niveaux et leurs PV affichés dans le jeu et dans
l'application. Relever le code/révision, le build d'émulateur et le profil
mémoire ; consigner les résultats sans publier la ROM ni la sauvegarde.
Une erreur doit rester une lecture indisponible, pas être remplacée par une
valeur supposée. Les sources et limites de révision sont dans
[la cartographie mémoire](memory-map.md).

Les essais CLI et interface ont utilisé le **script et les services de
production**, sans injection de faux messages. Le rendu Qt de cette page
a été capturé hors écran avec les messages du vrai DeSmuME. Le contrôle
séparé du point d'entrée a utilisé le plugin Windows natif.

Les preuves brutes de cette machine restent localement dans le dossier
ignoré `runtime/probe/` : `production_result.json`, `cli_result.jsonl`,
`ui_result.json` et `ui_real_bridge.png`. Elles peuvent être inspectées ici ;
elles ne sont pas requises pour lancer l'application et ne sont pas versionnées.

Les tests Lua nécessitent un moteur Lua 5.1 de l'architecture du Python de
test (`PCE_LUA51_DLL`). Sur cette machine, la DLL officielle a été utilisée :
aucun test n'a été ignoré. Sans cette DLL sur une autre machine, pytest indique
explicitement les cas ignorés ; un résultat avec des skips ne prouve pas
l'exécution du décodeur.

## Historique : vérification de la V0.1

Contrôles exécutés le 29 septembre 2026 sous Windows, avec Python 3.13.7,
PySide6 6.11.2 et pytest 9.1.1.

## Reprise et publication de la V0.1

Le 29 septembre 2026, la V0.1 a été réauditée dans le dossier de travail renommé.
La suite a de nouveau réussi (**191 tests**, 13,46 s), ainsi que la compilation et
l'ouverture/fermeture du véritable point d'entrée Windows. Le code V0.1 a été conservé.
Les exclusions Git racine couvrent aussi les secrets, les ROM en majuscules, les
save states DeSmuME et les configurations placées hors du sous-dossier applicatif.
`python -m tools.audit_repository` vérifie ces exclusions et les fichiers déjà suivis
sans afficher de contenu sensible. Aucun fichier interdit ni format de secret usuel
n'a été détecté dans les fichiers suivis avant publication.

## Résultats

| Contrôle | Résultat |
| --- | --- |
| Suite complète `python -m pytest -q --tb=short` | **191 tests réussis**, 10,98 s |
| Compilation des modules `python -m compileall -q app tools` | Réussie |
| Point d'entrée réel `app.main`, plugin Qt `windows` | Fenêtre visible, boucle d'événements exécutée, fermeture propre, code 0 |
| Parcours Qt natif | Génération de 5 règles, sauvegarde, rechargement et navigation réussis |
| Roue Monotype | Animation terminée ; type sous le pointeur identique au résultat logique |
| Chemins invalides | Message français, aucun processus lancé |
| Fichiers ROM/sauvegarde sentinelles | Octets et date de modification inchangés après le test du launcher |
| Lecture de contenu par le launcher | Aucune ouverture de ROM ou de sauvegarde |
| Corruptions JSON | Erreurs contrôlées, données existantes préservées ; Unicode invalide et imbrications excessives couverts |

Les tests Qt utilisent `QApplication`, `QTest` et `QSignalSpy`, sans dépendance pytest-qt.
Les animations sont attendues par leur signal de fin, avec une échéance maximale.
Les profils des tests et du parcours de démonstration sont créés dans des dossiers temporaires.

## Résolutions et captures

La fenêtre a été vérifiée en **1280×700 de surface cliente**, adaptée à un écran
1366×768 avec les bordures Windows, et en **1880×980**, adaptée à 1920×1080.
Les pages longues utilisent le défilement vertical ; aucun débordement horizontal
de page n'a été détecté. Le dialogue Monotype tient dans 850×650.

Le parcours natif utilise le plugin Qt Windows. Le grand rendu utilise le plugin
Qt offscreen, car le bureau disponible borne la taille des fenêtres natives.
Les polices Segoe UI et Segoe UI Symbol sont chargées pour les captures offscreen.

- [Accueil, petit écran](screenshots/accueil-1366.png)
- [Accueil, grand écran](screenshots/accueil-1920.png)
- [Création du challenge](screenshots/challenge-1366.png)
- [Aperçu et sauvegarde](screenshots/challenge-apercu-1366.png)
- [Catalogue des règles](screenshots/regles-1366.png)
- [Profils](screenshots/profils-1366.png)
- [Paramètres](screenshots/parametres-1366.png)
- [Roue Monotype](screenshots/monotype.png)

## Reproduire les contrôles

Dans `pokemon-challenge-engine`, avec l'environnement livré dans le parent :

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m compileall -q app tools
..\.venv\Scripts\python.exe -m tools.verify_ui --entrypoint
..\.venv\Scripts\python.exe -m tools.verify_ui --offscreen
..\.venv\Scripts\python.exe -m tools.verify_ui
```

Le dernier outil ouvre brièvement l'interface, crée des captures dans `docs/screenshots`
et ferme ses fenêtres. Il ne lance pas DeSmuME et ne configure pas de chemin de jeu.

## Limites de la vérification V0.1 d'origine

Aucune ROM personnelle et aucun émulateur réel n'ont été utilisés. La création du
processus DeSmuME est testée avec un substitut ; le chargement effectif d'un jeu devra
être confirmé après configuration des chemins de l'utilisateur.

Aucune application stricte des règles, communication Lua, écriture mémoire ou
randomisation de ROM n'est implémentée. La sauvegarde d'un profil est atomique par
fichier, sans transaction globale entre ses trois fichiers.
