# Feuille de route

Les étapes ci-dessous sont des objectifs, sans promesse de compatibilité ou de date.
Chaque lecture mémoire devra être vérifiée pour le jeu, la région et la révision concernés.

## Situation actuelle

La branche active est `feat/v0.4.1-run-flow-autolua`, issue de
`feat/v0.4-runs-permadeath` au commit `237614fe4269f1420e46c86c3de26758500b09f9`.
La V0.4.1 compte **1 630 tests réussis, aucun ignoré**, dont les 1 511 cas V0.4.
Le parcours réel Jouer avec autoload, le passage A/B et la restauration INI ont
réussi sur copies isolées de Blanc. Les résultats et limites sont détaillés dans
le [rapport de vérification](verification.md).
Application `0.4.1`, scripts Lua `0.4.0`, protocole `2` avec compatibilité des anciens
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
| V0.4.1 | Création visible, challenge direct, activation de la bonne partie, Jouer avec autoload Lua, contrôles relus | Régressions de création et passage A/B, INI réversible, refus/repli/timeout, parcours réel Jouer → heartbeat sur copies isolées |
| V0.4.x | Suite des corrections issues des essais utilisateur | K.O./soin, évolutions et autres scénarios réels encore ouverts ; reproductions documentées et non-régression |
| V0.5 | Level Cap | Plafonds par progression, comportement strict testé |
| V0.6 | Monotype appliqué | Modes Souple, Strict et Pur validés sur données réelles |
| V0.7 | Restrictions en combat | Objets et soins détectés puis contraintes effectivement appliquées |
| V0.8 | Randomizer et règles avancées | Compatibilité, reproductibilité, sauvegardes et distribution documentées |

Autres axes : empaquetage PyInstaller, installation par utilisateur, migration des profils,
clavier et mise à l'échelle élevée, jeux Platine, HeartGold/SoulSilver,
Émeraude et catalogues de types propres à chaque génération.

Une option visible ou un statut `future_strict` ne constitue jamais une fonctionnalité
d'application en jeu. L'interface devra continuer à distinguer l'intention, la lecture
réelle et la contrainte effectivement mise en œuvre.

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

La V0.4.1 permet aussi une configuration directe sans profil intermédiaire.
La bibliothèque sélectionne la carte créée après sa persistance ; l'ouverture
du Mode Jeu exige l'accord entre l'identifiant demandé, le contrôleur actif et
`runs/active.json`. Une session A encore ouverte bloque la reprise de B avec une
explication. Deux parties ne partagent une référence `.dsv` que par un choix
explicite ; leurs règles, compteurs et historiques PCE restent indépendants.

La V0.4 ne dépend pas de la disponibilité future des lectures de combat V0.3.
Les familles préparent les clauses futures sans modifier le moteur de captures
historique. **En attente de validation sur la machine utilisateur** pour les
séquences réelles de mort après synchronisation de combat, soin et évolution.
