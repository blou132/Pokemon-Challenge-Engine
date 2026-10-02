# Pokemon Challenge Engine — V0.3.6

Le code de l'application, les tests et la documentation sont dans
[`pokemon-challenge-engine/`](pokemon-challenge-engine/README.md).

La V0.3.6 ajoute **Installation & diagnostic** : découverte RetroBat/DeSmuME,
préparation des ZIP locaux dans un cache, installation Lua officielle confirmée,
proposition des sauvegardes et contrôle avant **Jouer**. L'étape **Run** du script
dans DeSmuME reste manuelle. Les ambiguïtés demandent un choix explicite.

Les corrections de profils sélectionnent le profil effectivement sauvegardé,
conservent ses règles à la reprise et masquent les paramètres des règles inactives.
Un profil décrit un challenge ; le futur gestionnaire de parties reste distinct.

[Premier démarrage](pokemon-challenge-engine/docs/first-run.md) ·
[Préparation automatique](pokemon-challenge-engine/docs/auto-setup.md) ·
[Installation Lua vérifiée](pokemon-challenge-engine/docs/lua-runtime.md).

**1 167 tests réussis, aucun ignoré**. Compilation, démarrage Windows et rendus
Qt vérifiés. ZIP, installation Lua, lancement de Blanc et réception d'équipe
testés sur copies isolées ; les limites sont détaillées dans le rapport.

Pour lancer avec l'environnement déjà préparé dans cet espace de travail :

```powershell
cd .\pokemon-challenge-engine
..\.venv\Scripts\python.exe -m app.main
```

La V0.2 ajoute une passerelle DeSmuME/Lua locale en lecture seule et une page de
connexion pour **Pokémon Noir, Blanc, Noir 2 et Blanc 2**. Les profils locaux,
la roue Monotype et le launcher de la V0.1 sont conservés. Aucune règle n'est
encore imposée dans le jeu ; les ROM ne sont pas modifiées. La restauration
d'une sauvegarde par le gestionnaire V0.3.5 exige une confirmation explicite.

Le transport réel et l'identification de Noir 2 français (`IREF`, révision `0`)
ont été vérifiés, ainsi que la déconnexion, la reprise et l'arrêt de la passerelle.
Le 30 septembre 2026, un échantillon réel de Blanc français (`IRAF`, révision `0`)
a aussi été comparé au jeu : deux Pokémon, Feuillajou (niveau 15, PV 6/42) et
Gruikui (niveau 14, PV 45/45), reçus par la passerelle et l'interface Qt.
Cette observation ne constitue pas une garantie de compatibilité universelle.
Pour l'équipe de Noir, Noir 2 et Blanc 2 : **En attente de validation sur la
machine utilisateur.** Les tests synthétiques restent distincts de ces essais réels.

Les quatre profils français de révision 0 possèdent des adresses documentées
séparément et des tests synthétiques. Le profil `white_fr_rev0` porte le statut
`real_sample_verified` pour l'échantillon comparé ; les trois autres restent
`source_documented`. Noir et Blanc 2 n'ont pas été validés dans un émulateur.
La V0.2 reste sur `feat/v0.2-desmume-bridge` et la V0.3 sur
`feat/v0.3-nuzlocke-tracking`. La branche de travail est désormais
`feat/v0.3.6-auto-setup`, créée depuis la V0.3.5
`ce8d888629f613b84d3bac3a9831b27cfbea1845`
après vérification des **960 tests existants, tous réussis et aucun ignoré**.
Aucune fusion dans `main`.

La V0.3 ajoute le moteur d'événements Nuzlocke, la Species Clause optionnelle,
la progression persistante et un panneau lié au profil actif. Les cartes de
Noir et Blanc FR rev0 ont des sources et des tests synthétiques. Les lectures
de combat et de résultat restent **indisponibles faute d'adresses suffisamment
documentées** : cette livraison ne détecte pas encore les captures réelles.
La chaîne réelle zone → rencontre → résultat n'est donc pas validée et la V0.3
n'est pas terminée. **En attente de validation sur la machine utilisateur.**

Application : `0.3.6` ; scripts Lua : `0.3.0` ; challenge conservé : `0.1.0` ; progression :
schéma `2` avec migration des anciens suivis ; protocole Lua : `2`, lecteur
Python compatible avec les messages v1 des scripts `0.2.0`.

[Suivi Nuzlocke et limites](pokemon-challenge-engine/docs/nuzlocke-tracking.md).

[Installation et utilisation](pokemon-challenge-engine/README.md) ·
[Connexion DeSmuME](pokemon-challenge-engine/docs/desmume-bridge.md) ·
[Sources mémoire](pokemon-challenge-engine/docs/memory-map.md) ·
[Vérifications réalisées](pokemon-challenge-engine/docs/verification.md)

La V0.3.5 ajoute un **Mode Jeu**, les profils de lancement par jeu, les pages
Contrôles et Graphismes, un gestionnaire de sauvegardes avec backups, les panneaux
de run et la personnalisation. DeSmuME conserve sa fenêtre externe. La vitesse
en direct reste demandée, sans confirmation ; l'export INI vérifié concerne
x1/MAX au prochain lancement. Manettes, shaders et contraintes en jeu ne sont
pas implémentés. Les essais réels et synthétiques sont séparés dans le rapport.

[Guide du Mode Jeu](pokemon-challenge-engine/docs/game-mode.md) ·
[Réglages DeSmuME](pokemon-challenge-engine/docs/emulator-settings.md) ·
[Sauvegardes](pokemon-challenge-engine/docs/save-manager.md).

Le test utilisateur récent confirme équipe, soins et changements de route sur
Blanc FR rev0, dont la Route 3. **Les valeurs d'équipe sont garanties après
synchronisation de la structure principale, notamment en fin de combat.**
Les PV pendant le combat ne sont pas suivis en temps réel. Cette validation
concerne Blanc uniquement ; aucune capture réelle ni règle imposée n'est annoncée.
