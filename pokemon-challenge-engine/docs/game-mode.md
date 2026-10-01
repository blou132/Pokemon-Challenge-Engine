# Mode Jeu — V0.3.5

Le bouton **Mode Jeu** ouvre une fenêtre dédiée, en conservant les six pages existantes de PCE. DeSmuME reste une application séparée : le centre du Mode Jeu réserve un emplacement visuel à sa fenêtre. Il ne contient ni vidéo du jeu, ni émulateur intégré, ni injection de commandes DS.

## Préparer une session

1. Choisir Pokémon Noir, Blanc, Noir 2 ou Blanc 2 dans le Mode Jeu.
2. Ouvrir **Profil de lancement** et renseigner la ROM, l'exécutable DeSmuME et, au besoin, le fichier INI vérifié. Choisir le profil de contrôles, le preset graphique, la vitesse demandée et le challenge associé.
3. Dans **Sauvegardes**, renseigner les chemins propres à ce jeu. Les backups automatiques sont désactivés par défaut et s'activent explicitement. Les détails de restauration et de rétention sont dans [save-manager.md](save-manager.md).
4. Enregistrer puis lancer DeSmuME. La préférence **Revenir au Mode Jeu après le lancement** affiche les panneaux ; décochée, elle masque la fenêtre sans arrêter le suivi du processus ou les backups activés.
5. Utiliser **Connexion Lua** pour retrouver la page de connexion existante, avec le jeu et les chemins du profil de lancement. La procédure Lua reste manuelle. Une connexion déjà active conserve son jeu et sa configuration.

Les associations de challenge enregistrées sont restaurées lors du choix d'un jeu. Choisir explicitement **Sans profil** reste possible : ce choix est conservé pour le lancement. Le jeu et le challenge sont verrouillés tant qu'une session lancée est suivie ou que la connexion Lua n'est pas arrêtée. Ouvrir le Mode Jeu ne remplace pas un profil déjà sélectionné dans Connexion DeSmuME.

Le profil de lancement mémorise des préférences. L'option d'application des réglages DeSmuME est désactivée par défaut : sans elle, lancer un jeu ne réécrit pas son INI. Les réglages demandés ne sont appliqués que si l'adaptateur les reconnaît et les valide ; voir [emulator-settings.md](emulator-settings.md). Les chemins et préférences se trouvent dans `game-mode.local.json`, exclu de Git. Les anciens chemins de configuration servent de valeurs initiales sans réécriture à la simple ouverture.

## Lire les panneaux

| Panneau | Origine et limite |
| --- | --- |
| Contrôles | Mapping lu dans la configuration reconnue de DeSmuME. Une configuration inconnue reste « Non disponible ». Réinitialiser prépare un brouillon dans Contrôles ; l'export reste une action explicite. La manette reste indisponible faute de détection fiable. |
| Vitesse | x1, x2, x4 et MAX sont des demandes. « État réel : Non disponible » reste affiché tant qu'aucune confirmation n'est reçue. Un changement de bouton ne prouve pas une accélération du jeu. |
| Équipe | Six emplacements, noms issus de la table française, niveaux et PV reçus de Lua. Un autre jeu, une déconnexion ou des données absentes effacent les valeurs présentées comme courantes. Un emplacement vide est distingué d'une lecture indisponible. Le statut ne devient K.O. que si les PV reçus valent zéro ; les altérations de statut ne sont pas inventées. |
| Challenge | Profil, jeu, mode, seed et règles enregistrés. Les badges, morts et captures proviennent de la progression du profil ; le compteur de captures est explicitement manuel. Le level cap reste indisponible si absent. |
| Session PCE | Durée du processus lancé et suivi par ce Mode Jeu. Ce n'est ni le temps sauvegardé dans Pokémon, ni un chronomètre persistant de toute la run. |
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

Fermer le Mode Jeu arrête son suivi du processus et ses backups automatiques ; cela ne ferme pas DeSmuME. Masquer les panneaux ou utiliser la préférence de masquage après lancement conserve le suivi. La passerelle Lua dispose de son propre bouton d'arrêt.

## Vérification

Les tests UI automatisés utilisent des profils et messages de passerelle synthétiques. Ils couvrent l'affichage des six emplacements, les champs indisponibles, les incompatibilités entre jeux, le verrouillage pendant une session, les associations de profils, les raccourcis limités aux fenêtres, la navigation Lua, les 13 blocs et les trois densités. Les pages historiques sont conservées et testées séparément.

Des fenêtres Qt natives Windows ont été rendues et inspectées à 1366 × 768 et 1920 × 1080 avec des données explicitement synthétiques. Les trois colonnes, les touches, les six emplacements et le défilement des informations de run ont été vérifiés visuellement. Les captures et le script de revue restent dans `runtime/`, exclu de Git. Cette vérification de rendu ne valide pas une ROM, une vitesse réelle ni le placement d'une fenêtre DeSmuME.

Pour les lectures de Pokémon Blanc, les événements Nuzlocke et les opérations propres au build de DeSmuME, se reporter à [verification.md](verification.md) et [emulator-settings.md](emulator-settings.md). Toute opération non testée en conditions réelles conserve son statut : **En attente de validation sur la machine utilisateur.**
