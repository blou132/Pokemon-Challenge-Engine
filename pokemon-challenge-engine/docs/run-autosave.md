# Sessions et sauvegarde automatique PCE

La sauvegarde automatique concerne exclusivement la **progression PCE**. Elle
ne demande pas au jeu de sauvegarder, n'écrit pas de PV et ne remplace pas une
sauvegarde Pokémon. Un backup `.dsv` reste une action distincte du gestionnaire
existant.

## Quand le temps compte

Une session commence après une observation fraîche et valide, pour la partie
sélectionnée, lorsque le processus DeSmuME suivi correspond au jeu lancé. Le
jeu, son code, sa région et sa révision doivent correspondre aux informations
connues de la partie. Ouvrir PCE, sélectionner une partie ou préparer un script
Lua ne démarre pas le compteur.

Le contrôleur Qt transmet uniquement les nouveaux instantanés de passerelle au
service de suivi. Son worker vérifie le contexte du processus et appelle le
heartbeat toutes les secondes. Le service n'accepte ce heartbeat que si la
dernière observation compatible remonte à cinq secondes au maximum. La
déconnexion, l'arrêt de l'émulateur, une erreur d'identité, une observation
invalide ou une longue interruption ferme la session et coupe la continuité des
PV utilisée pour la détection des morts.

Chaque session stocke `session_id`, `started_at`, `last_heartbeat`, `ended_at`
et `duration`. La durée provient d'une horloge monotone ; le total est la somme
des durées de sessions. Il s'agit du temps suivi par PCE, pas du compteur interne
du jeu. Les écrans de démarrage et menus peuvent être comptés tant que les
observations restent valides ; aucune détection de l'attention du joueur n'est
annoncée. Une pause de DeSmuME qui interrompt Lua finit par suspendre le suivi.

Une partie terminée, abandonnée ou archivée ne reçoit pas de temps nouveau.
Sa réactivation demande un changement de statut explicite. Changer de partie
termine et sauvegarde la session précédente ; les observations précédentes ne
deviennent jamais la première observation de la nouvelle partie.

Fermer uniquement la fenêtre **Mode Jeu** conserve la surveillance du processus
et de la partie en arrière-plan tant que PCE reste ouvert. Fermer PCE termine
le suivi et publie sa progression. Le changement de statut d'une partie inactive
reste possible depuis sa fiche sans la reprendre ni changer la partie suivie ;
une ancienne session interrompue est alors fermée à son dernier heartbeat connu.

## Déclencheurs et fréquence

- Début et fin de session, action manuelle, changement de statut, référence de
  lancement, backup enregistré et fermeture : sauvegarde immédiate.
- Mort détectée automatiquement : sauvegarde immédiate de la mort, de l'équipe
  et des événements associés.
- Changement d'équipe, de zone ou observation à confirmer : indicateur `dirty`
  puis regroupement après deux secondes, sans repousser indéfiniment l'écriture
  sous un flux continu.
- Temps seul : heartbeat durable au plus tard toutes les quinze secondes
  pendant le suivi actif. Un instantané identique ne crée pas de nouvel événement
  d'équipe ou de zone.

Le worker effectue les écritures hors du thread graphique. Après succès,
`last_saved_at` indique la dernière publication et `dirty` est remis à faux.
Après échec, les changements restent en mémoire avec `dirty` et un message
d'erreur ; une nouvelle tentative est possible. Le contrôleur ne considère pas
la fermeture propre comme réussie si l'écriture finale échoue. Une extinction
forcée du processus peut néanmoins perdre les changements non encore publiés.

## Récupération après crash

La sélection active est restaurable depuis `runs/active.json`. Une session dont
`ended_at` est nul est récupérée en la fermant à son `last_heartbeat` **déjà
persisté**. Sa durée connue est conservée. Un événement `session_ended` avec la
raison `crash_recovery` rend cette opération visible dans l'historique.

Le redémarrage ne soustrait jamais la date du dernier heartbeat à l'heure
actuelle pour remplir la durée. Huit heures ordinateur éteint ne deviennent donc
pas huit heures de jeu. La sélection récupérée reste en attente d'une nouvelle
observation valide et d'un processus correspondant avant de compter à nouveau.
Un passage de PV positifs avant le crash à zéro après redémarrage nécessite une
confirmation ; il n'est pas interprété comme une transition continue.

Si le fichier existant est corrompu, d'une version inconnue ou modifié par une
autre instance, le service préserve le fichier et affiche l'erreur. Il ne remet
pas silencieusement la partie à zéro. Le stockage atomique, les verrous et les
contrôles de concurrence sont décrits dans [run-storage.md](run-storage.md).

## Vérification

Les tests utilisent une horloge contrôlée et des observations synthétiques :
début, arrêt, reprise, processus fermé, mauvais jeu, timeout, changement de
partie, crash de huit heures, limite du heartbeat durable, debounce, échec de
publication et nouvelle tentative. Ils vérifient également les événements sans
doublons et l'absence de captures déduites de la taille de l'équipe. Les essais
avec un émulateur réel et les limites restantes sont consignés séparément dans
[verification.md](verification.md).
