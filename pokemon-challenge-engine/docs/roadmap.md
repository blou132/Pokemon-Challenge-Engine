# Feuille de route

Les étapes ci-dessous sont des objectifs, sans promesse de compatibilité ou de date.
Chaque lecture mémoire devra être vérifiée pour le jeu, la région et la révision concernés.

## Situation actuelle

La branche active est `feat/v0.3-nuzlocke-tracking`, issue de la V0.2 après
confirmation de ses **598 tests réussis, aucun ignoré**. Application `0.3.0`,
protocole `2` avec compatibilité de réception v1, progression schéma `2`.
Le moteur d'événements, les clauses optionnelles, la persistance et le panneau
de profil actif sont implémentés et testés sur événements synthétiques.
Les cartes Noir/Blanc FR ont des lectures sourcées ; les lectures de combat,
capture et fuite restent à documenter, puis à implémenter et à valider.
**La V0.3 n'est pas terminée. En attente de validation sur la machine utilisateur.**
Un test utilisateur ne remplace pas les adresses de combat manquantes.

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
| V0.4 | Morts permanentes et extension des clauses | Identification fiable des Pokémon et traitement des familles évolutives |
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

Le numéro d'application `0.3.0` ne change pas le format du challenge (`0.1.0`).
Le protocole Lua (`2`) et la progression (`schema_version: 2`) sont versionnés séparément.
