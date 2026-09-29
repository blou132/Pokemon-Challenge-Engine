# Feuille de route

Les étapes ci-dessous sont des objectifs, sans promesse de compatibilité ou de date.
Chaque lecture mémoire devra être vérifiée pour le jeu, la région et la révision concernés.

| Version | Périmètre | Critère de validation |
| --- | --- | --- |
| V0.1 | Interface, catalogue, règles, randomisation, roue Monotype, profils, suivi manuel, launcher | Tests métier et interface, lancement réel de l'application, intégrité des fichiers |
| V0.2 | Communication DeSmuME/Lua, lecture équipe et niveaux | Transport local versionné, lectures vérifiées, reprise après déconnexion |
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
