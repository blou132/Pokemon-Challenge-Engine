# Feuille de route

Les étapes ci-dessous sont des objectifs, sans promesse de compatibilité ou de date.
Chaque lecture mémoire devra être vérifiée pour le jeu, la région et la révision concernés.

## Situation actuelle

La **V0.1 est conservée** : préparation, génération par seed, Monotype, profils,
suivi manuel, paramètres et launcher. La **V0.2 ajoute une passerelle locale en
lecture seule**, un protocole versionné, les états de connexion et un lecteur
Gen V avec profils mémoire documentés. Elle ne met pas encore en œuvre de règles
dans le jeu ni de mise à jour automatique de la progression des challenges.

Le transport de production et l'identification de Noir 2 français (`IREF`,
révision `0`) ont été testés réellement, de même que la déconnexion, la reprise
dans la même session et l'arrêt demandé par Python. La CLI et l'interface Qt
ont reçu les messages du vrai DeSmuME.
La validation de l'équipe réelle, de ses espèces, niveaux et PV reste ouverte :
**En attente de validation sur la machine utilisateur.** Aucun succès de tests
sur données synthétiques ne clôt cette étape. Le périmètre V0.2 ne doit donc pas
être présenté comme entièrement validé en jeu.

[Résultats et limites des essais](verification.md) · [Profils mémoire](memory-map.md)

| Version | Périmètre | Critère de validation |
| --- | --- | --- |
| V0.1 | Interface, catalogue, règles, randomisation, roue Monotype, profils, suivi manuel, launcher | Tests métier et interface, lancement réel de l'application, intégrité des fichiers |
| V0.2 | Communication DeSmuME/Lua en lecture seule, identité, équipe, espèces, niveaux et PV | Transport local versionné, déconnexion/reprise testées, comparaison de l'équipe avec une partie réelle pour chaque profil |
| V0.3 | Zones, rencontres, captures, premier suivi Nuzlocke réel | Événements reproductibles, clauses de capture cohérentes |
| V0.4 | Morts permanentes et Species Clause | Identification fiable des Pokémon et traitement des évolutions |
| V0.5 | Level Cap | Plafonds par progression, comportement strict testé |
| V0.6 | Monotype appliqué | Modes Souple, Strict et Pur validés sur données réelles |
| V0.7 | Restrictions en combat | Objets et soins détectés puis contraintes effectivement appliquées |
| V0.8 | Randomizer et règles avancées | Compatibilité, reproductibilité, sauvegardes et distribution documentées |

Autres axes : empaquetage PyInstaller, installation par utilisateur, migration des profils,
clavier et mise à l'échelle élevée, jeux Blanc/Blanc 2 puis Platine, HeartGold/SoulSilver,
Émeraude et catalogues de types propres à chaque génération.

Une option visible ou un statut `future_strict` ne constitue jamais une fonctionnalité
d'application en jeu. L'interface devra continuer à distinguer l'intention, la lecture
réelle et la contrainte effectivement mise en œuvre.

Le numéro d'application `0.2.0` ne change pas le format des profils existants
(`0.1.0`). Le protocole Lua possède son propre numéro de version (`1`).
