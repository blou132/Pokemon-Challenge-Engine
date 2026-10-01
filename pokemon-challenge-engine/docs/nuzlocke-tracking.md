# Suivi Nuzlocke V0.3 — état et limites

La branche `feat/v0.3-nuzlocke-tracking` prépare un suivi automatique en lecture
seule. **La V0.3 n'est pas terminée** : les lecteurs livrés savent produire une
carte documentée pour Noir/Blanc FR rev0, mais ne disposent pas encore d'adresses
fiables pour le cycle de combat et son résultat. La production ne détecte donc
pas encore une capture réelle. Il reste à documenter et implémenter ces lectures,
puis à comparer toute la chaîne sur une partie réelle.

**En attente de validation sur la machine utilisateur.**

## Ce qui est vérifié séparément

| Couche | Source / contrôle | Validation réelle |
| --- | --- | --- |
| Équipe et identité Blanc FR rev0 | Lecteur V0.2 conservé, tests de non-régression | Échantillon de deux Pokémon comparé le 30 septembre 2026 |
| Carte Noir/Blanc FR rev0 | PokeLua, table de lieux, tests Lua sur RAM synthétique | En attente |
| Carte Noir 2/Blanc 2 | Aucune adresse retenue | Indisponible |
| Combat sauvage/dresseur, capture, fuite | Champs de protocole et machine à états testés avec événements factices | Lectures mémoire non implémentées faute de sources suffisantes |
| Profil, clauses, historique, interface | Tests synthétiques et démarrage Qt natif | Aucun cycle réel zone → rencontre → résultat comparé |

Les [sources du suivi](tracking-sources.md) documentent chaque adresse retenue,
les sources rejetées et les limites. Les noms des espèces sont les identifiants
1–649 de la table française PKHeX épinglée dans `data/species_fr.json`.

## Zone et première rencontre

`map_id` désigne la carte RAM. `capture_zone_id` désigne une zone Nuzlocke du
projet. La table BW regroupe les cartes portant exactement le même nom de lieu
dans PokeLua ; cette politique est explicite, sans extrapolation aux suites BW2.
Elle ne sépare pas les parties intérieure/extérieure de la Forêt d'Empoigne.
Une carte non documentée conserve son identifiant brut et n'autorise pas de
consommation de tentative. Une valeur de carte au titre peut être ancienne :
aucun drapeau de partie chargée n'est encore disponible.

Les classifications prévues sont `wild_standard`, `wild_special`, `static`,
`gift`, `egg`, `fossil`, `scripted`, `unknown`. Seul `wild_standard` dans un
combat positivement classé `wild` peut commencer une tentative. Dresseurs,
doubles et combats scriptés sont ignorés. Les phénomènes spéciaux, cadeaux,
œufs, fossiles et rencontres statiques ne sont pas assimilés aux herbes normales.
Surf et pêche nécessiteront également une classification sourcée.

Une zone commence `unused`. Une première rencontre admissible la passe à
`encounter_started`. La rencontre garde sa zone d'origine même si la carte
change. À sa résolution, la zone passe à `captured` ou `failed`, avec `used: true`.
Les rencontres suivantes ne remplacent jamais cette première tentative.

| Résultat | Consomme la tentative | Preuve attendue |
| --- | --- | --- |
| `captured` | Oui | Indicateur positif de capture réussie, pas disparition du combat |
| `fainted` | Oui | PV du sauvage actif à zéro, ou résultat documenté |
| `escaped` | Oui | Fuite du sauvage positivement identifiée |
| `player_fled` | Oui | Fuite du joueur positivement identifiée |
| `battle_ended_unknown` | Oui | Fin connue, résultat indisponible ou contradictoire |
| `duplicate_ignored` | Non | Species Clause active et espèce exacte déjà capturée |
| `invalid_encounter` | Non | Combat identifié comme incompatible |
| `special_encounter_ignored` | Non | Classification spéciale non prise en charge |

Une lecture `null`, une pause ou une déconnexion ne signifie pas fin de combat.
L'apparition d'un Pokémon dans l'équipe n'est pas utilisée comme preuve de
capture : cela ne couvrirait notamment pas les captures envoyées aux boîtes.
Les booléens et résultats du protocole restent inconnus tant qu'une lecture
suffisamment documentée n'existe pas.

## Règles et profil actif

Choisir le profil dans **Connexion DeSmuME** avant **Préparer la connexion**.
Le sélecteur est verrouillé pendant la
session ; arrêter la connexion avant de changer de profil. Le panneau compact
affiche zone, disponibilité, espèce, niveau, état et résultat, ainsi que les
événements récents. Les limites des lectures sont affichées en permanence.

Sans profil, le diagnostic affiche les observations et n'écrit aucun suivi.
Sans `nuzlocke` dans les règles actives, aucune zone n'est consommée. Sans
`species_clause`, un doublon est une tentative normale. Quand cette clause est
active, une espèce déjà capturée est enregistrée `duplicate_ignored` ; la zone
reste disponible (`ignored_by_clause`) pour la prochaine espèce admissible.
Le moteur consulte les espèces capturées automatiquement et les captures
manuelles portant un `species_id` valide. Une simple saisie de nom libre n'est
pas convertie en espèce supposée. Les familles évolutives restent prévues.

Le service contrôle le jeu, le code, la région et la révision attendus dans le
catalogue avant toute écriture. Un profil Blanc n'est jamais appliqué à Noir 2.
Une identité incomplète suspend le suivi ; une incompatibilité affiche une
erreur et préserve les fichiers du profil.

## Événements et persistance

Les observations traversent `GameObservation`, puis `NuzlockeTracker`, sans Qt.
L'historique contient des objets structurés : `id`, `event`, `timestamp`,
`zone_id`, `map_id`, `battle_id`, `species_id`, `level`, `result`.
Les événements incluent `zone_entered`, `wild_encounter_started`,
`capture_success`, `wild_fainted`, `wild_escaped`, `player_fled`,
`battle_ended_unknown` et les motifs d'exclusion.

L'application et Lua sont en `0.3.0`, le protocole en `2`, le challenge reste en
`0.1.0`. La progression a son propre `schema_version: 2`. Les champs manuels
`badges`, `captures`, `deaths`, `zones` (liste) et `current_level_cap` sont conservés.
Le suivi automatique se trouve dans `nuzlocke` :

```json
{
  "schema_version": 2,
  "nuzlocke": {
    "zones": {
      "route_1": {
        "name": "Route 1",
        "used": true,
        "status": "captured",
        "first_encounter": {
          "id": "identifiant-stable-exemple",
          "battle_id": "combat-synthetique-exemple",
          "zone_id": "route_1",
          "species_id": 504,
          "level": 3,
          "result": "captured",
          "timestamp": 1790000000
        },
        "last_ignored": null
      }
    },
    "current_zone_id": "route_1",
    "current_map_id": 317,
    "active_encounter": null,
    "seen_battles": {"identifiant-stable-exemple": "captured"},
    "captured_species": [504],
    "source_cursors": {"session-exemple": 4}
  }
}
```

Cet extrait est **synthétique** ; les champs manuels sont omis pour la lisibilité.
Les anciens suivis sans version sont migrés en mémoire. La simple consultation
ne réécrit pas un ancien fichier. Un suivi corrompu, une version future ou un
historique illisible suspend l'écriture automatique, sans remise à zéro.

`ProfileManager.update` recharge le profil sous un verrou partagé dans le
processus, applique les changements, puis sauvegarde seulement si nécessaire.
La saisie manuelle utilise aussi cette opération pour préserver les événements
arrivés depuis l'ouverture de la page. Utiliser une seule instance de l'application.

Un journal `.transaction.json`, écrit avec `fsync` et remplacement atomique,
constitue le point de validation de la transaction. Les trois fichiers du profil
sont ensuite remplacés. Après interruption, le chargement valide le journal et
termine la transaction avant d'exposer le profil. Si un fichier a été modifié
depuis par un autre outil, la récupération refuse de l'écraser. Ce mécanisme ne
prétend pas rendre trois renommages simultanés pour un lecteur externe.

Les observations différentes ont leur propre journal de transport, conservé
jusqu'à acquittement après persistance. Lua compte les observations en attente,
pas les heartbeat ; son index est repris au rechargement. Les curseurs de session
et identifiants de combat évitent les doublons après réessai ou redémarrage de
l'application. L'identité d'un combat doit rester stable lors d'une reconnexion
et distinguer deux combats différents ; sa lecture RAM reste à documenter.
Une nouvelle session n'importe pas un ancien journal non acquitté : conserver
celui-ci pour diagnostic après une erreur, sans changer de profil pour le rejouer.
La réinitialisation d'une sauvegarde ou un retour par savestate ne remet jamais
automatiquement à zéro la progression du challenge.

## Validation utilisateur prioritaire : Blanc FR rev0

Pour la **carte**, la procédure est disponible maintenant :

1. Ouvrir l'application et choisir un profil Nuzlocke de test pour Pokémon Blanc.
2. Préparer la connexion puis charger le `connect.lua` indiqué dans DeSmuME.
3. Vérifier `white`, `IRAF`, `FR`, révision `0`, profil d'équipe `white_fr_rev0`.
4. Jouer normalement jusqu'à une zone connue, par exemple Route 1, puis comparer
   le nom affiché et l'ID brut (`317` pour Route 1).
5. Changer de zone puis revenir ; consulter le panneau et `history.json`.
6. Vérifier `progress.json` : la zone reste disponible, aucun combat n'étant connu.

Pour la **chaîne complète**, les étapes suivantes sont bloquées tant que les
lectures de combat ne sont pas documentées et implémentées :

1. Entrer dans une zone neuve et confirmer son nom.
2. Déclencher soi-même une rencontre sauvage ; comparer espèce, niveau et PV.
3. Capturer ou mettre K.O. en jouant normalement.
4. Comparer le résultat dans l'application, `progress.json` et `history.json`.
5. Reconnecter et redémarrer l'application ; vérifier qu'aucun événement ne se duplique.
6. Répéter avec fuite, dresseur, zone déjà consommée et clause active/inactive.

Aucune action de déplacement, de combat ou de capture n'est automatisée pour
cette validation. Aucun test V0.3 n'a modifié une ROM ou une sauvegarde utilisateur.
Les preuves locales restent dans les dossiers ignorés ; ne publier ni ROM,
sauvegarde, état, configuration, log ou capture révélant des données privées.

**En attente de validation sur la machine utilisateur.**
