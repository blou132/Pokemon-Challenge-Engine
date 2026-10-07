# Mode Jeu — V0.4.1

## Partie persistante

Depuis **Mes parties**, créez ou reprenez une partie. Pour réutiliser une
configuration, choisissez **Depuis un modèle existant** à la création ou ouvrez
**Modèles de challenge → Créer une partie** depuis la bibliothèque.
Le Mode Jeu affiche son nom, ses règles figées, son temps
cumulé, sa dernière équipe, sa zone et son autosave PCE. Les boutons **Capture**,
**Mort**, **Badge +/−** et **Note** ouvrent les saisies manuelles. Une première
saisie de badges demande le total ; une donnée absente reste « Non renseigné ».

La création propose **Partie classique**, **Depuis un modèle existant** ou
**Challenge personnalisé** avec l'éditeur existant. Après l'enregistrement confirmé,
la bibliothèque affiche **Partie créée**, actualise son compteur et sélectionne
la carte ; elle retire les filtres qui masqueraient celle-ci. Une erreur de
création affiche **Partie non créée** et n'ouvre pas le Mode Jeu.

Les références de lancement/sauvegarde appartiennent à cette partie ; les changer
dans ses réglages ne réécrit pas les préférences globales d'un autre lancement.
Reprendre vérifie l'environnement, sans créer une nouvelle partie ni lancer le
jeu automatiquement. Un changement de partie exige de fermer DeSmuME et arrêter
Lua. Les choix de jeu/profil restent verrouillés dans le Mode Jeu lié à une partie.

Le Mode Jeu est associé à la partie demandée avant d'être affiché. Son identifiant,
celui du contrôleur et celui de `runs/active.json` doivent correspondre, y compris
avant **Jouer**. Une incohérence bloque l'action avec une explication. Si A tourne
encore lorsque B est créée, B reste visible dans la bibliothèque ; A ne se présente
pas comme B. Les réponses d'une ancienne préparation sont ignorées. Au redémarrage
de PCE, la sélection enregistrée est restaurée sans lancement automatique.

Le compteur durable avance seulement lorsque DeSmuME lancé ici tourne et que
des messages valides du jeu associé arrivent. Il s'arrête à la déconnexion et
ne compte pas les heures hors ligne après crash. Il n'est pas le compteur interne
Pokémon ; sans drapeau fiable, PCE ne distingue pas les menus et pauses du jeu.
Fermer seulement la fenêtre Mode Jeu conserve ce suivi en arrière-plan tant que
PCE reste ouvert. Fermer PCE termine la session suivie sans fermer DeSmuME.

L'équipe conservée hors ligne est explicitement présentée comme **dernière équipe
observée**. « ☠ Mort dans cette partie » peut accompagner des PV positifs après
soin : le statut virtuel est durable. Les observations à confirmer sont signalées
dans Morts ; les détails de la partie permettent confirmation et correction.
L'autosave PCE ne sauvegarde jamais la partie Pokémon. Le bouton de backup et
l'onglet Sauvegardes réutilisent SaveManagerService et ses confirmations.

Voir [Run Manager](run-manager.md), [autosave](run-autosave.md) et
[mort permanente](permanent-death.md). Le parcours historique sans partie décrit
ci-dessous conserve son compteur de processus non persistant et son suivi de profil.
Son lancement direct reste accessible dans **Mes parties → Modèles de challenge →
Ancien suivi par profil**.

## Parcours simplifié

**Installation & diagnostic** détecte les jeux locaux, prépare les ZIP, propose
la sauvegarde et installe Lua après confirmation. Une fois le jeu préparé, **Jouer**
revérifie l'environnement, prépare une nouvelle session Bridge et son `connect.lua`,
prépare l'autoload, puis lance DeSmuME. Le processus lancé ne prouve pas la connexion :
PCE attend les messages valides du jeu et de la session courante.

Dans **Profil de lancement**, **Connecter automatiquement Lua avec Jouer** permet
d'utiliser l'autoload officiel du build reconnu. À la première activation compatible,
PCE propose **Activer** ou **Conserver le mode manuel** et mémorise la décision pour
cet exécutable. L'activation sauvegarde l'INI puis règle `[Scripting] AutoLoad=1`
et `[PathSettings] Lua` vers un dossier appartenant à PCE. Le loader porte le nom
de la ROM réellement préparée, sans son extension ; il charge le `connect.lua`
de cette session. Aucun script personnel n'est remplacé et aucune commande clavier
ou souris n'est envoyée à DeSmuME.

Le retour au mode manuel restaure les deux anciens réglages Lua au prochain
**Jouer**, DeSmuME fermé, sans remplacer les autres réglages INI. Si ces clés ont
été changées hors de PCE, la restauration signale le conflit et conserve le backup.
Le consentement et le journal de restauration restent dans
`lua-autoload.local.json`, exclu de Git. Voir les
[sources et limites de l'autoload](lua-runtime.md#chargement-automatique-avec-jouer).

Un build inconnu, des fichiers Lua non vérifiés, un refus ou un échec d'autoload
conservent le lancement de la ROM en mode manuel avec une explication. Le chemin
du script et son dossier restent accessibles : chargez le `connect.lua` courant
dans DeSmuME, puis cliquez **Run**. Les erreurs d'environnement empêchant le
lancement du jeu restent bloquantes.

Le badge Lua distingue **préparation**, **attente de DeSmuME**, **attente du script**,
**connecté**, **déconnecté** et **erreur**. L'état général indique **PARTIE PRÊTE**,
**DÉMARRAGE**, **ATTENTE LUA**, **EN JEU** ou **ERREUR LUA**. Après huit secondes sans
heartbeat valide, PCE explique l'absence de connexion et propose **Réessayer la
connexion**, le mode manuel et le diagnostic. Le jeu reste ouvert.

En cas de déconnexion, **Reconnecter Lua** arrête l'ancienne session et crée un
nouveau script ainsi qu'un nouveau loader. Dans un DeSmuME déjà ouvert, l'INI n'est
pas modifié : chargez ce nouveau `connect.lua` manuellement. L'autoload ne s'exécute
qu'au chargement de la ROM ; un prochain **Jouer**, après fermeture de DeSmuME,
peut configurer la nouvelle session. **Arrêter et changer de jeu** demande confirmation et libère le
choix après l'arrêt de Lua ; si DeSmuME est toujours lancé, son verrouillage est
expliqué et sa fermeture reste à l'utilisateur. PCE ne tue pas ce processus.

Les valeurs d'équipe sont garanties après synchronisation de la structure
principale, notamment en fin de combat. Le test utilisateur de Blanc FR rev0
confirme soins et zones hors combat, PV et Pokémon à 0 PV après combat. Le suivi
instantané des PV de combat, les captures réelles et les règles strictes ne sont
pas ajoutés par cette version.

Le bouton **Mode Jeu** ouvre une fenêtre dédiée, en conservant les six pages existantes de PCE. DeSmuME reste une application séparée : le centre du Mode Jeu réserve un emplacement visuel à sa fenêtre. Il ne contient ni vidéo du jeu, ni émulateur intégré, ni injection de commandes DS.

## Préparer une session

1. Reprendre la partie voulue depuis **Mes parties**. Dans le parcours historique sans partie, choisir Pokémon Noir, Blanc, Noir 2 ou Blanc 2 dans le Mode Jeu.
2. Ouvrir **Profil de lancement** et renseigner la ROM, l'exécutable DeSmuME et, au besoin, le fichier INI vérifié. Choisir le profil de contrôles, le preset graphique, la vitesse demandée et le challenge associé.
3. Dans **Sauvegardes**, renseigner les chemins propres à ce jeu. Les backups automatiques sont désactivés par défaut et s'activent explicitement. Les détails de restauration et de rétention sont dans [save-manager.md](save-manager.md).
4. Enregistrer puis cliquer **Jouer**. La préférence **Revenir au Mode Jeu après le lancement** affiche les panneaux ; décochée, elle masque la fenêtre sans arrêter le suivi du processus ou les backups activés.
5. Attendre la confirmation de connexion Lua. Si le mode manuel est choisi ou nécessaire, ouvrir sa page depuis le Mode Jeu puis charger le script courant dans DeSmuME. Une connexion déjà active conserve son jeu et sa configuration.

Les associations de challenge enregistrées sont restaurées lors du choix d'un jeu. Choisir explicitement **Sans profil** reste possible : ce choix est conservé pour le lancement. Le jeu et le challenge sont verrouillés tant qu'une session lancée est suivie ou que la connexion Lua n'est pas arrêtée. Ouvrir le Mode Jeu ne remplace pas un profil déjà sélectionné dans Connexion DeSmuME.

Le profil de lancement mémorise des préférences. L'option d'application des réglages
de contrôles, graphismes et vitesse est désactivée par défaut. L'autoload Lua
possède son propre accord ; les deux options peuvent modifier des clés distinctes
de l'INI avant le lancement, avec backup et contrôles. Sans ces activations ni
restauration d'un ancien autoload PCE, le lancement PCE ne réécrit pas l'INI.
Voir [emulator-settings.md](emulator-settings.md).
Les préférences globales se trouvent dans `game-mode.local.json`, exclu de Git ;
une partie possède sa propre copie des références de lancement. La simple ouverture
ne réécrit pas ces références.

## Lire les panneaux

| Panneau | Origine et limite |
| --- | --- |
| Contrôles | Mapping relu pour l'exécutable de la partie à son association, au changement de ses références et à la réouverture du Mode Jeu. Une configuration inconnue reste « Non disponible » avec l'action **Configurer les contrôles**. Réinitialiser prépare un brouillon dans Contrôles ; l'export reste une action explicite. La manette reste indisponible faute de détection fiable. |
| Vitesse | x1, x2, x4 et MAX sont des demandes. « État réel : Non disponible » reste affiché tant qu'aucune confirmation n'est reçue. Un changement de bouton ne prouve pas une accélération du jeu. |
| Équipe | Six emplacements, noms issus de la table française, niveaux et PV reçus de Lua. Un autre jeu, une déconnexion ou des données absentes effacent les valeurs présentées comme courantes. Un emplacement vide est distingué d'une lecture indisponible. Le statut ne devient K.O. que si les PV reçus valent zéro ; les altérations de statut ne sont pas inventées. |
| Challenge | Règles figées, jeu et seed de la partie sélectionnée ; sa progression fournit badges, morts et captures. Sans partie persistante, le profil historique reste la source. Les captures et badges restent manuels. Le level cap reste indisponible si absent. |
| Session PCE | Avec une partie, temps cumulé durable confirmé par le processus suivi et les messages Lua associés. Sans partie, durée non persistante du processus suivi. Ces compteurs sont distincts du temps sauvegardé dans Pokémon. |
| Monotype | Type et mode configurés. La conformité des membres reste indisponible lorsque la passerelle ne transmet pas leurs types. Aucun blocage n'est appliqué. |
| Randomizer | Configuration enregistrée lorsqu'elle existe, présentée comme « configuré, non appliqué ». Les catégories non renseignées restent indisponibles. Le Mode Jeu ne randomise aucune ROM. |
| Zone / capture | Réutilisation de l'état V0.3 et de son widget Nuzlocke. Les limites de lecture V0.3 restent inchangées : afficher un widget ne rend pas disponibles les événements de combat absents du lecteur réel. |
| Save states | Politique affichée seulement lorsque son application ne peut être assurée. PCE ne prétend pas bloquer un chargement effectué dans DeSmuME. |

Les blocs Logs et Debug exposent seulement l'historique et les diagnostics disponibles. Aucune donnée synthétique utilisée par les tests n'est installée comme état de démonstration dans l'application.

## Personnaliser l'affichage

**Personnaliser → Interface en jeu** permet d'afficher ou masquer indépendamment 13 blocs : Contrôles, Équipe, Challenge, Zone, Capture, Morts, Badges, Level Cap, Seed, Vitesse, Sauvegardes, Logs et Debug. Chaque bloc peut être placé à gauche ou à droite ; les colonnes défilent lorsque leur contenu dépasse la hauteur disponible.

Trois densités sont proposées : compacte pour 1366 × 768, standard et large pour 1920 × 1080. Le mode compact réduit notamment le détail des règles et la note de lecture d'équipe. **Plein écran** agit sur PCE ; DeSmuME conserve sa propre fenêtre.

L'organisation des fenêtres nécessite un écran choisi explicitement dans Interface en jeu et une instance lancée par ce Mode Jeu. L'organisation automatique est désactivée par défaut. La V0.3.5 refuse le placement automatique quand l'écran choisi utilise une mise à l'échelle différente de 100 %, car la conversion entre coordonnées Qt et Win32 n'est pas validée pour ce cas. Le placement manuel reste possible. Le gestionnaire vérifie le processus et l'exécutable avant de déplacer sa fenêtre ; il ne modifie ni son parent Win32 ni les entrées clavier du jeu.

Les neuf raccourcis applicatifs se configurent dans **Contrôles** : vitesses, plein écran, ouverture du Mode Jeu, backup manuel, changement de panneau et affichage des panneaux. Ils sont vides par défaut et actifs uniquement dans la fenêtre PCE concernée. Le raccourci d'ouverture du Mode Jeu fonctionne également depuis la fenêtre principale. Ce ne sont pas des raccourcis globaux : ils n'interceptent pas les touches lorsque DeSmuME a le focus.

Sans partie persistante sélectionnée, fermer le Mode Jeu arrête le suivi historique
du processus et ses backups automatiques ; cela ne ferme pas DeSmuME. Avec une
partie V0.4, le suivi continue en arrière-plan jusqu'à fermeture de PCE, déconnexion
ou fermeture du processus. Masquer les panneaux conserve le suivi. La passerelle
Lua dispose de son propre bouton d'arrêt.

## Vérification

Les tests UI automatisés utilisent des profils et messages de passerelle synthétiques. Ils couvrent l'affichage des six emplacements, les champs indisponibles, les incompatibilités entre jeux, le verrouillage pendant une session, les associations de profils, les raccourcis limités aux fenêtres, la navigation Lua, les 13 blocs et les trois densités. Les pages historiques sont conservées et testées séparément.

Les régressions V0.4.1 couvrent aussi la création et ses filtres, le passage entre
deux parties, les retours asynchrones anciens, l'ordre de préparation Lua avant
le processus, le consentement, le repli manuel, le timeout et la relecture des
contrôles. Les fichiers INI et messages de ces tests sont synthétiques ; ils ne
prouvent pas l'exécution du loader dans DeSmuME. Les résultats du parcours réel
**Jouer → autoload → heartbeat** sur copie isolée figurent séparément dans le
[rapport de vérification](verification.md).

Des fenêtres Qt natives Windows ont été rendues et inspectées à 1366 × 768 et 1920 × 1080 avec des données explicitement synthétiques. Les trois colonnes, les touches, les six emplacements et le défilement des informations de run ont été vérifiés visuellement. Les captures et le script de revue restent dans `runtime/`, exclu de Git. Cette vérification de rendu ne valide pas une ROM, une vitesse réelle ni le placement d'une fenêtre DeSmuME.

Pour les lectures de Pokémon Blanc, les événements Nuzlocke et les opérations propres au build de DeSmuME, se reporter à [verification.md](verification.md) et [emulator-settings.md](emulator-settings.md). Toute opération non testée en conditions réelles conserve son statut : **En attente de validation sur la machine utilisateur.**
