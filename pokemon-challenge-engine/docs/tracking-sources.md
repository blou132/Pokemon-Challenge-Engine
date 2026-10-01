# Sources des lectures de suivi Gen V

Cette page distingue une adresse documentée, son test sur une RAM synthétique et
sa validation sur une partie réelle. Les profils d'équipe V0.2 conservent leur
statut séparé : la lecture réelle de l'équipe de Blanc ne valide pas ces nouvelles
lectures de carte ou de combat.

## Cartes Noir / Blanc FR

Source primaire retenue : [PokeLua, `BW_RNG_DeSmuMe.lua`, commit
`b76caf669872897295db5304eebbdf5e53125efb`](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua).
Le branchement français donne `playerMapIndexAddr` à
[la ligne 461](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L451-L466).
L'ajout de `0x20` est explicitement conditionné à **White** par
[les lignes 426–427](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L426-L427).
La largeur de lecture est confirmée par l'appel `read16Bit`
[ligne 1157](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L1157).

| Profil | Code | Lecture | Adresse | Validation |
| --- | --- | --- | --- | --- |
| `black_fr_rev0_tracking` | IRBF | `map_id`, u16 little-endian | `0x0224F88C` | Source documentée ; test synthétique |
| `white_fr_rev0_tracking` | IRAF | `map_id`, u16 little-endian | `0x0224F8AC` | Source documentée ; test synthétique |
| `black2_fr_rev0_tracking` | IREF | Indisponible | `null` | Aucune adresse retenue |
| `white2_fr_rev0_tracking` | IRDF | Indisponible | `null` | Aucune adresse retenue |

La source distingue les langues et versions, mais ne décrit pas les révisions
ROM. Le projet limite donc ces essais à FR, révision 0 ; ce choix de portée ne
constitue pas une preuve de validation de la révision. Le lecteur vérifie
l'identité reçue **et l'en-tête réellement présent en RAM** avant toute lecture de
carte. Il relit les deux octets et rejette un changement pendant l'échantillon.
Il ne connaît pas encore de drapeau fiable « partie chargée » : une valeur RAM
au titre ou lors d'un chargement peut être une donnée antérieure. Une carte lue
ne prouve jamais qu'un combat est en cours.

**En attente de validation sur la machine utilisateur.**

## Cartes et zones de capture : deux espaces d'identifiants

`data/capture_zones.json` contient une table `bw_fr_rev0` de 364 cartes réparties
en 64 zones. L'index RAM est celui de la liste `locationNamesList` de PokeLua,
[lignes 363–403](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L363-L403).
L'accès par `mapIndex + 1`
[lignes 1194–1195](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L1194-L1195)
confirme que les identifiants RAM commencent à zéro.

Les libellés français sont les noms correspondants dans les tables parallèles
[anglaise](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/text/locations/gen5/text_bw2_00000_en.txt)
et [française](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/text/locations/gen5/text_bw2_00000_fr.txt)
de PKHeX, commit `09e7f18fbb33635e35cf9ffcbfd3322403780f8e`.
Seuls les noms strictement présents dans les deux listes sont retenus ; aucun
rapprochement approximatif n'est effectué.

Les identifiants PKHeX sont ceux du lieu de rencontre enregistré dans un Pokémon,
**pas** ceux de la carte RAM. Par exemple, Route 1 est la carte RAM **317** et le
lieu de rencontre PKHeX **14**. Le champ `name_location_id` n'est qu'une référence
au libellé : le lecteur ne l'utilise jamais comme `map_id`.

La politique `same_documented_area` regroupe les cartes auxquelles la source donne
exactement le même nom de lieu. Exemples : les cartes 321, 322 et 323 correspondent
à Route 3 ; 154 et 155 à Forêt d'Empoigne ; 324 et 325 à Veine Souterraine. Leur
appartenance à un même lieu est documentée ; le choix de compter ce lieu comme
une seule zone Nuzlocke est une **politique du projet**, pas une mécanique RAM.
Cela inclut les intérieurs portant le même nom et ne propose pas de clause
séparant les deux parties de la Forêt d'Empoigne.

Les portes aux noms génériques, certains lieux spéciaux (métro, Heylink, etc.)
et les lieux exclusifs Ville Noire / Forêt Blanche sont exclus pour cette première
table. Une carte absente conserve son `map_id` brut, avec `capture_zone_id` et
`zone_name` indisponibles. La table Noir/Blanc n'est pas appliquée à Noir 2/Blanc 2.

La table est dérivée de données techniques publiques, sans extraction ni
publication d'une ROM utilisateur. Pour la reproduire : extraire les chaînes de
`locationNamesList` dans l'ordre, numéroter à partir de zéro, exclure les lieux
décrits ci-dessus, puis chercher chaque nom anglais exact dans la table PKHeX.
L'index trouvé donne le libellé français de la table parallèle. Chaque entrée
conserve `source_area_name` et `name_location_id` pour contrôler cette opération.

## Combat : recherches et limites bloquantes

PokeLua documente aussi un tampon de Pokémon ennemi : FR Noir `0x0226AC74`,
FR Blanc `0x0226AC94`, dans le même
[bloc de version](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L451-L466).
**Ces adresses ne sont pas activées dans le lecteur de suivi.** La présence d'un
Pokémon déchiffrable n'établit ni la validité temporelle du tampon, ni la différence
entre sauvage, dresseur et combat scénarisé. Un Pokémon mis K.O. ou capturé peut
laisser des données en RAM. Le mode nommé « Capture » dans l'outil RNG de PokeLua
est un mode d'affichage sélectionné par l'utilisateur, pas un drapeau interne de
capture réussie.

Les recherches ont également consulté :

- [Les scripts BW de Kaphotics sur Project Pokémon](https://projectpokemon.org/home/forums/topic/15140-pokemon-bw-lua-scripts/), qui confirment une lecture de carte **anglaise** ; leur adresse n'est pas transférée au français.
- [L'extraction de Pokémon Gen V depuis la RAM](https://projectpokemon.org/home/forums/topic/56963-extracting-pokemon-from-generation-5-ram/), utile pour les structures Pokémon mais sans contrat complet de cycle de combat FR.
- [La décompilation `pokemodding/pokeblack`, commit `84e6b56639ec5dbc9861da6c5f02b02bd2bac9f0`](https://github.com/pokemodding/pokeblack/tree/84e6b56639ec5dbc9861da6c5f02b02bd2bac9f0), qui cible Noir anglais ; ses symboles ne sont pas une carte mémoire de Blanc FR.
- [Le tracker de JoshuaMootoo, commit `ed8e873b816af1e760279fa7171b6f64b0a55c7b`](https://github.com/JoshuaMootoo/Pkmn-Nuzlocke-Tracker-Emulator-Tool/blob/ed8e873b816af1e760279fa7171b6f64b0a55c7b/nuzlocke.lua), dont les adresses annoncées pour B2W2 US ne fournissent pas de justification transférable à Blanc FR. Aucune n'a été reprise.

Il manque donc encore une source vérifiable spécifique au profil FR pour l'état
actif, le type sauvage/dresseur, la classification de rencontre, les statistiques
du sauvage actif, son identité de combat et les codes de résultat. Les profils
livrés indiquent `battle: null` et la liste explicite des champs indisponibles.
Le lecteur ne conclut jamais « pas de combat » à partir de cette absence : tous
ces champs restent `null` dans le protocole.

Ce manque demande **une recherche mémoire supplémentaire**, puis une validation
réelle. Ce n'est pas une fonctionnalité déjà implémentée qu'un simple essai
utilisateur suffirait à valider. La production ne peut actuellement déclencher
une première rencontre, une capture, un K.O. ou une fuite automatiques. Les tests
de ces transitions portent sur les événements synthétiques du protocole, pas sur
des adresses RAM inventées. Aucun gain d'équipe ni disparition de combat n'est
converti en capture supposée ; une capture envoyée en boîte nécessitera également
une preuve fiable.

## Tests et validation réelle

`tests/test_lua_tracking_reader.py` exécute réellement Lua 5.1 sur une mémoire
factice : adresses distinctes Noir/Blanc, octets little-endian, carte inconnue,
regroupement documenté, en-tête incompatible, révision/langue incompatibles,
lecture corrompue, transition pendant l'échantillon et absence de fausse détection
de combat malgré un tampon ennemi rempli. Il vérifie aussi que Noir 2/Blanc 2
n'empruntent aucune adresse BW.

Ce sont des **tests synthétiques**. Aucun test de rencontre réelle, de capture,
de K.O. ou de fuite n'a été réalisé pour cette couche. Aucun script de cette
couche n'envoie de commandes de déplacement ou de combat. La lecture réelle de
carte Blanc FR doit être comparée visuellement par l'utilisateur, qui joue
normalement. La procédure complète de suivi restera bloquée au stade de la
rencontre tant que les lectures de combat décrites ci-dessus seront absentes.

**En attente de validation sur la machine utilisateur.**
