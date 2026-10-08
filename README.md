# Pokemon Challenge Engine — V0.4.1

Le code de l'application, les tests et la documentation sont dans
[`pokemon-challenge-engine/`](pokemon-challenge-engine/README.md).

La V0.4.1 rend la nouvelle partie immédiatement visible dans **Mes parties**,
avec confirmation, carte sélectionnée et filtres incompatibles réinitialisés.
**Mes parties** est la page d'ouverture et l'entrée principale. **Nouvelle partie**
propose **Partie classique**, **Depuis un modèle existant** ou **Challenge personnalisé**.
Les configurations réutilisables restent accessibles depuis **Mes parties →
Modèles de challenge** ; leur gestion est secondaire et leur stockage en profils
est conservé. Le challenge personnalisé se prépare directement, sans profil
intermédiaire. Le Mode Jeu attend l'activation confirmée
de l'identifiant demandé ; il ne reprend pas silencieusement l'ancienne partie.

La recherche locale démarre automatiquement avec PCE. RetroBat, DeSmuME, Lua,
les jeux `.nds`/`.zip`, l'INI et les sauvegardes sont vérifiés dans des emplacements
bornés. Un candidat unique est préparé dans le cache PCE ; les choix manuels
valides sont conservés. Chaque jeu affiche son état : **Prêt**, **Jeu non trouvé**
ou l'action nécessaire. Les jeux absents ne bloquent pas celui que vous possédez.
**Paramètres → Installation & diagnostic** présente ces résultats ; les chemins
manuels sont regroupés dans **Avancé**. Aucun jeu, BIOS ou fichier de sauvegarde
n'est téléchargé.

**Jouer** prépare maintenant la session Bridge et son loader **avant** de lancer
DeSmuME. Sur le build reconnu, **Connecter automatiquement Lua avec Jouer** propose
un accord mémorisé, sauvegarde l'INI et configure son autoload officiel. Les
scripts personnels sont conservés et les deux anciens réglages Lua sont
restaurables. Le mode manuel reste disponible en cas de refus ou d'impossibilité.
Seul un heartbeat accepté confirme la connexion ; le lancement du processus
ne suffit pas. Un délai de huit secondes sans connexion donne accès au nouvel
essai, au mode manuel et au diagnostic sans fermer le jeu. Les contrôles sont
relus depuis l'exécutable associé à la partie lors de sa reprise et à la
réouverture du Mode Jeu. Les résultats V0.4.1 sont consignés dans le
[rapport de vérification](pokemon-challenge-engine/docs/verification.md).

La V0.4 ajoute **Mes parties** : parties indépendantes des profils, règles figées,
sessions durables, autosave PCE, équipe observée et cimetière virtuel. La mort
permanente utilise les transitions de PV et l'identité PID/OT documentée ; une
ambiguïté demande confirmation. Le menu secondaire **Actions manuelles** regroupe
les captures, badges, notes et l'ajout d'une mort en secours. Les captures et
badges ne sont pas détectés automatiquement.

[Guide des parties](pokemon-challenge-engine/docs/run-manager.md) ·
[Mort permanente](pokemon-challenge-engine/docs/permanent-death.md) ·
[Autosave et récupération](pokemon-challenge-engine/docs/run-autosave.md).

Les services de découverte V0.3.6 deviennent le parcours normal de la V0.4.1 :
préparation des ZIP locaux et sélection d'une sauvegarde unique à forte confiance
sans étape de configuration imposée. **Jouer** vérifie seulement la partie
concernée. Lua déjà conforme ne demande rien ; son installation externe garde
sa confirmation. L'étape **Run** du script reste nécessaire dans le mode manuel.
Les ambiguïtés demandent un choix explicite.

Les corrections de profils sélectionnent le profil effectivement sauvegardé,
conservent ses règles à la reprise et masquent les paramètres des règles inactives.
Un profil décrit un challenge ; chaque partie V0.4 en conserve sa propre copie.

[Premier démarrage](pokemon-challenge-engine/docs/first-run.md) ·
[Préparation automatique](pokemon-challenge-engine/docs/auto-setup.md) ·
[Installation Lua vérifiée](pokemon-challenge-engine/docs/lua-runtime.md).

La V0.4.1 compte **1 716 tests réussis, aucun ignoré**, dont 72 nouveaux cas pour
la préparation automatique et les actions manuelles. Compilation, démarrage Windows
et rendus Qt sont vérifiés ; le rapport distingue ces tests des essais réels.
L'essai réel antérieur sur copies de Blanc confirme le lancement Lua automatique avec Jouer, la séparation A/B,
l'équipe, le temps, l'autosave et la restauration INI. K.O./soin, évolution et zone nommée dans ce nouveau
parcours restent **En attente de validation sur la machine utilisateur.**

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
`feat/v0.4.1-run-flow-autolua`, créée depuis la V0.4
`237614fe4269f1420e46c86c3de26758500b09f9` sur `feat/v0.4-runs-permadeath`.
Aucune fusion dans `main`.

La V0.3 ajoute le moteur d'événements Nuzlocke, la Species Clause optionnelle,
la progression persistante et un panneau lié au profil actif. Les cartes de
Noir et Blanc FR rev0 ont des sources et des tests synthétiques. Les lectures
de combat et de résultat restent **indisponibles faute d'adresses suffisamment
documentées** : cette livraison ne détecte pas encore les captures réelles.
La chaîne réelle zone → rencontre → résultat n'est donc pas validée et la V0.3
n'est pas terminée. **En attente de validation sur la machine utilisateur.**

Application : `0.4.1` ; scripts Lua : `0.4.0` ; challenge conservé : `0.1.0` ;
progression historique : schéma `2` ; partie Run : schéma `1`, sans migration forcée
des profils. Protocole Lua : `2`, compatible avec les anciens messages v1/v2.

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
