# Passerelle DeSmuME / Lua — prévue

Les fichiers `black.lua` et `black2.lua` sont des placeholders documentaires.
La V0.1 ne les charge pas, n'injecte rien dans DeSmuME et ne connaît aucune adresse mémoire.

La première étape sera une communication **en lecture seule** entre une version de
DeSmuME disposant du support Lua et un service Python indépendant de l'interface.
Le jeu, la région, la révision et l'empreinte devront être identifiés explicitement.
Un jeu inconnu ou une donnée incohérente devra arrêter la synchronisation.

Objectifs successifs :

- Lire l'équipe, les PV et les niveaux.
- Détecter le début et la fin d'un combat et les rencontres sauvages.
- Détecter les captures, zones visitées et Pokémon K.O.
- Échanger des événements versionnés avec l'application locale.
- Relier ces événements au profil actif et à son historique.

TODO V0.2 : définir le transport local, le format de message, les délais d'expiration,
la gestion des doublons et des états de connexion, puis tester la déconnexion/reconnexion.
Les commandes Lua et capacités devront être vérifiées pour la version précise de DeSmuME.

TODO avant toute application stricte : vérifier et documenter les adresses sur chaque
version prise en charge, reproduire les lectures et prévoir une sauvegarde de secours
avec accord de l'utilisateur. Aucune adresse supposée ne doit être ajoutée.

Une lecture fiable des états n'est pas encore un mécanisme d'application des règles.
Les versions suivantes devront l'afficher séparément.
