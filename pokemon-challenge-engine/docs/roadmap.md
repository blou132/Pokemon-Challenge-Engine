# Feuille de route

Les étapes ci-dessous sont des objectifs, sans promesse de compatibilité ou de date.
Chaque lecture mémoire devra être vérifiée pour le jeu, la région et la révision concernés.

## Situation actuelle

La V0.4.1 est finalisée sur `feat/v0.4.1-run-flow-autolua` au commit
`7a823ca58b5898d3231408ebece4deb01a5dbbdd`. La branche
`feat/v0.5-challenge-observation` implémente maintenant les
[contrôles de règles](gen5-rule-observation.md), après la
[proposition technique initiale](v0.5-proposal.md). Shiny Only, Monotype, Level Cap,
stades et historique ont un moteur et une interface ; les lectures de combat et
captures restent partielles ou indisponibles. Le Randomizer sur copies constitue
un lot distinct, maintenant raccordé à la création et à l'isolation des nouvelles
parties. Une ROM Blanc dérivée a démarré puis été rouverte avec heartbeat Lua ;
son équipe et sa progression ne sont pas encore validées. Aucun taux shiny
personnalisé n'est activé sans patch validé.
Le contrôle final V0.4.1 du 13 octobre 2026 compte **1 829 tests réussis, aucun échec ni
ignoré**, dont les 1 716 cas précédents et 113 nouveaux pour les fichiers par
aventure, les suppressions et le changement de session. Les résultats historiques
restent consignés séparément dans le rapport de vérification.
Le parcours réel Jouer avec autoload, le passage A/B et la restauration INI ont
réussi sur copies isolées de Blanc. Les résultats et limites sont détaillés dans
le [rapport de vérification](verification.md).
Application de base `0.4.1`, scripts Lua `0.5.0`, protocole `2` avec compatibilité des anciens
messages v1/v2, progression historique schéma `2` et nouveau Run schéma `1`.
La V0.4 ajoute les parties indépendantes, leur bibliothèque, les sessions durables,
l'autosave, l'identité PID/OT, les familles et la mort permanente virtuelle.
La V0.4.1 corrige la visibilité immédiate des parties créées, ajoute la configuration
directe d'un challenge avec le moteur existant, sécurise l'activation et le passage
entre parties, et relit les contrôles du lancement associé. **Jouer** prépare la
session Lua et l'autoload officiel avant DeSmuME, après un accord mémorisé. Le
heartbeat de la bonne session confirme seul la connexion. Le refus, l'absence de
support ou une erreur d'autoload conservent un mode manuel explicite ; les anciens
réglages Lua sont restaurables et aucune écriture INI n'est faite pendant que
l'émulateur tourne. Les sources, tests synthétiques et essais réels sont distingués
dans le rapport. K.O./soin, évolutions et scénarios non observés restent ouverts
pour les essais utilisateur suivants.

L'ajout du **8 octobre 2026** fait de la découverte locale le parcours normal :
recherche automatique au démarrage, états indépendants des quatre jeux,
préparation des ZIP simples et sauvegarde unique à forte confiance sélectionnée.
Une vérification légère à l'ouverture de Mes parties réutilise les signatures
des fichiers et dossiers connus ; les changements ou une demande explicite
relancent la recherche bornée. Avant Jouer, seuls les références, l'environnement
et la sauvegarde de la partie concernée sont contrôlés. Un jeu absent ne bloque
pas les autres. Les choix manuels valides priment sur les nouvelles découvertes.

Paramètres et Installation & diagnostic présentent l'état avant les outils
avancés. Les ambiguïtés restent explicites, l'installation Lua externe reste
confirmée et aucun téléchargement de ROM, jeu, BIOS ou sauvegarde n'est proposé.
Le menu secondaire **Actions manuelles** regroupe captures, badges, notes et
ajout d'une mort en secours. Le moteur existant continue de déduire une mort
virtuelle d'une transition fiable de PV lorsque Mort permanente est active.
Les tests synthétiques de ces parcours ne valident pas les captures réelles,
les badges ni de nouveaux scénarios réels de mort permanente.

La finalisation V0.4.1 ajoute les copies propres à chaque aventure : ROM avec UUID,
environnement DeSmuME, sauvegarde, states et nouveaux backups. Une nouvelle aventure
démarre sans ancienne sauvegarde ; l'import et l'association d'une ancienne partie
exigent confirmation et conservent les originaux. La suppression inventorie les
fichiers de la partie et garde les références externes ; l'archivage reste disponible.
Le passage d'une session à une autre demande une fermeture normale confirmée,
attend DeSmuME puis Lua et conserve les identités du jeu et de la partie demandée.
Les essais réels du 12 octobre confirment les fichiers séparés de deux parties
de Blanc, leur reprise et la suppression de A sans toucher à B. Le lancement de
Noir 2 après Blanc et son autoload sont vérifiés ; son équipe reste non validée.
Les sources RetroBat sont identiques avant/après. Consulter les preuves et limites
du [rapport de vérification](verification.md).

Les captures et badges restent manuels ; aucune règle stricte n'agit dans le jeu.
Le moteur d'événements, les clauses optionnelles, la persistance et le panneau
de profil actif sont implémentés et testés sur événements synthétiques.
Les cartes Noir/Blanc FR ont des lectures sourcées ; les lectures de combat,
capture et fuite restent à documenter, puis à implémenter et à valider.
**La V0.3 n'est pas terminée. En attente de validation sur la machine utilisateur.**
Un test utilisateur ne remplace pas les adresses de combat manquantes.

V0.3.6 ajoute premier démarrage, détection locale, ZIP non destructif, installation
Lua officielle confirmée, diagnostic avant Jouer, reconnexion et stockage géré.
Elle corrige aussi la sélection du profil sauvegardé et les options inactives.
Le test utilisateur de Blanc FR rev0 confirme équipe et zone, soins hors combat
et PV après combat ; le lecteur principal et ses offsets restent inchangés.
Les valeurs d'équipe sont garanties après synchronisation de la structure
principale, notamment en fin de combat. Aucun travail de mémoire de combat n'est
engagé dans cette version.

La **V0.1 est conservée** : préparation, génération par seed, Monotype, profils,
suivi manuel, paramètres et launcher. La **V0.2 ajoute une passerelle locale en
lecture seule**, un protocole versionné, les états de connexion et un lecteur
Gen V pour **Noir, Blanc, Noir 2 et Blanc 2**, avec quatre profils français de
révision 0 documentés séparément et testés sur mémoire synthétique.
Elle ne met pas encore en œuvre de règles
dans le jeu ni de mise à jour automatique de la progression des challenges.

Le transport de production et l'identification de Noir 2 français (`IREF`,
révision `0`) ont été testés réellement, de même que la déconnexion, la reprise
dans la même session et l'arrêt demandé par Python. La CLI et l'interface Qt
ont reçu les messages du vrai DeSmuME.
Pour Noir, Noir 2 et Blanc 2, la validation de l'équipe réelle, de ses espèces,
niveaux et PV reste ouverte :
**En attente de validation sur la machine utilisateur.** Aucun succès de tests
sur données synthétiques ne clôt cette étape. Le périmètre V0.2 ne doit donc pas
être présenté comme entièrement validé en jeu.

La priorité **Pokémon Blanc français** a produit un échantillon réel comparé le
**30 septembre 2026** : transport, heartbeat, identité `IRAF / FR / 0`, profil
`white_fr_rev0`, puis deux Pokémon correspondant à l'écran du jeu et à
l'interface Qt (Feuillajou, niveau 15, PV 6/42 ; Gruikui, niveau 14, PV 45/45).
Le statut `real_sample_verified` ne garantit pas toutes les situations ou ROM.
Les adresses de
Blanc et Blanc 2 proviennent de leurs propres branches PokeLua ; aucune égalité
avec Noir ou Noir 2 n'est supposée. La lecture d'équipe de chacun des quatre
profils nécessite sa propre validation réelle.

Le travail V0.2 est conservé sur `feat/v0.2-desmume-bridge`. La condition de validation
réelle de Blanc dispose maintenant de cet échantillon documenté ; **aucune fusion
dans `main` n'est effectuée**. `main` conserve la V0.1.

[Résultats et limites des essais](verification.md) · [Profils mémoire](memory-map.md)

| Version | Périmètre | Critère de validation |
| --- | --- | --- |
| V0.1 | Interface, catalogue, règles, randomisation, roue Monotype, profils, suivi manuel, launcher | Tests métier et interface, lancement réel de l'application, intégrité des fichiers |
| V0.2 | Communication DeSmuME/Lua en lecture seule, identité, équipe, espèces, niveaux et PV | Transport local versionné, déconnexion/reprise testées, comparaison de l'équipe avec une partie réelle pour chaque profil |
| V0.3, en cours | Zones, rencontres, captures, Species Clause exacte optionnelle | Sources des combats FR, puis chaîne réelle zone → rencontre → résultat → profil vérifiée |
| V0.3.5 | Mode Jeu, contrôles et graphismes documentés, backups, profils de lancement et panneaux | Non-régression V0.3, UI 1366/1920, lancement et copies isolées réels ; vitesse directe/manettes non disponibles |
| V0.3.6 | Premier démarrage, installation Lua, ZIP, diagnostic, reconnexion et fiabilité des profils | Tests de régression, interface et essais réels isolés distingués dans le rapport |
| V0.4 | Parties persistantes, sessions, bibliothèque, identité, familles et mort permanente virtuelle | Tests synthétiques et lectures réelles séparés ; parcours réel K.O./soin et évolution à valider par l'utilisateur |
| V0.4.1 | Mes parties unifié, création directe, installation automatique, autoload Lua, copies par aventure, suppression contrôlée et changement de session | Régressions de création et passage A/B, originaux intacts, sauvegardes/states distincts ; preuves réelles distinguées pour Blanc et Noir 2 |
| V0.4.2, différée | Distribution Windows portable PyInstaller onedir | Exécutable réellement lancé sous Windows, persistance et import historique, ZIP sans ROM/BIOS/save personnelle |
| V0.4.x | Suite des corrections issues des essais utilisateur | K.O./soin, évolutions et autres scénarios réels encore ouverts ; reproductions documentées et non-régression |
| V0.5, en développement | Quinze règles, Monotype, Shiny Only, Nuzlocke/Hardcore, ROM Randomizer et combinaisons | Contrôles fiables et ROM dédiées reproductibles ; essais réels par jeu séparés des tests synthétiques ; actions non observables et taux shiny non validés explicitement indisponibles |
| Étapes ultérieures, numérotation à réexaminer après V0.5 | Extension des contrôles de combat, validations complémentaires et distribution | Les anciens objectifs Monotype et Randomizer V0.6–V0.8 sont désormais inclus dans V0.5 ; aucune validation réelle n'est présumée |

Autres axes : installation par utilisateur, migration des profils,
clavier et mise à l'échelle élevée, jeux Platine, HeartGold/SoulSilver,
Émeraude et catalogues de types propres à chaque génération.

Une option visible ou un statut `future_strict` ne constitue jamais une fonctionnalité
d'application en jeu. L'interface devra continuer à distinguer l'intention, la lecture
réelle et la contrainte effectivement mise en œuvre.

La préparation V0.5 commence après finalisation de V0.4.1, sur une branche dédiée,
par une proposition technique avant les changements majeurs. Elle doit partir de
Blanc FR révision 0 puis traiter chaque autre profil séparément. Aucune écriture
RAM n'est autorisée par cette préparation. Un Randomizer reste une recherche tant
qu'une méthode fiable, une copie dérivée séparée et une autorisation explicite ne
sont pas réunies. Un strict paramétré ne doit pas être affiché comme appliqué.

Le numéro d'application `0.4.1` ne change pas le format du challenge (`0.1.0`).
Le protocole Lua (`2`), la progression historique (`schema_version: 2`) et les
parties (`schema_version: 1`) sont versionnés séparément.

## Suite du Mode Jeu

L'autoload V0.4.1 utilise uniquement le mécanisme documenté du build DeSmuME
reconnu. Il ne s'exécute pas à la création d'un script dans un processus déjà
ouvert : une reconnexion exige alors de charger le nouveau script manuellement.
L'absence de heartbeat ne ferme pas le jeu et ne se transforme pas en connexion
validée. L'extension de ce mécanisme à d'autres builds exige des sources et des
essais distincts. Voir [Support Lua](lua-runtime.md).

Le frontend V0.3.5 ne clôt pas les lectures de combat encore manquantes de la V0.3.
Restent à vérifier avant activation : pilotage et mesure de vitesse en direct,
commandes manette réelles, qualité visuelle de chaque option, autres builds DeSmuME,
scénarios multi-écrans/DPI et éventuel embedding. Les formats et limites retenus
sont décrits dans [Réglages DeSmuME](emulator-settings.md). Aucune fusion automatique
dans `main` n'est prévue.

## Profils et parties V0.4

Un profil est une configuration réutilisable ; une partie copie ses règles et
possède une progression indépendante. **Mes parties** accepte plusieurs parties
du même jeu et filtre par génération, jeu, challenge et statut. Le modèle accepte
d'autres générations ; le lecteur d'identité livré est limité à Gen V.
Les anciens profils/progressions restent intacts. La création depuis un profil
est explicite et ne prétend pas convertir des compteurs historiques en individus
identifiés. Aucun ajout de Pokémon à l'équipe ne prouve une capture.

**Mes parties** devient l'entrée principale et la page d'ouverture. Sa création
réunit partie classique, modèle existant et challenge personnalisé. La gestion
des **Modèles de challenge** est secondaire et accessible depuis cette page ;
le modèle de données profil/partie reste distinct. L'ancien suivi par profil est
conservé dans un volet replié de la gestion des modèles.

La V0.4.1 permet aussi une configuration directe sans profil intermédiaire.
La bibliothèque sélectionne la carte créée après sa persistance ; l'ouverture
du Mode Jeu exige l'accord entre l'identifiant demandé, le contrôleur actif et
`runs/active.json`. Une session A encore ouverte propose une fermeture normale
confirmée avant la reprise de B. Une nouvelle aventure ne reprend aucune ancienne
sauvegarde détectée. Les nouvelles parties préparent leurs fichiers indépendants ;
les anciennes références partagées restent inchangées jusqu'à une copie confirmée.

La V0.4 ne dépend pas de la disponibilité future des lectures de combat V0.3.
Les familles préparent les clauses futures sans modifier le moteur de captures
historique. **En attente de validation sur la machine utilisateur** pour les
séquences réelles de mort après synchronisation de combat, soin et évolution.
