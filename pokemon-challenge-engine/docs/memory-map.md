# Cartographie mémoire de la V0.2

Le lecteur lit uniquement la RAM exposée par `memory.readbyte` dans DeSmuME.
Il ne modifie ni cette RAM, ni une ROM, ni une sauvegarde. Les adresses d'équipe
proviennent exclusivement de [memory_profiles.json](../data/memory_profiles.json).

## État de validation

Les deux profils portent le statut `source_documented` : leurs adresses sont
documentées dans les sources ci-dessous. **La lecture d'une équipe réelle avec
ces profils n'a pas été vérifiée.** Les tests du décodeur exécutent le module Lua
5.1 sur une RAM synthétique chiffrée et ne changent pas ce statut.

PokeLua ne distingue pas les révisions de ROM pour ces adresses. La restriction
à la révision `0` est donc un choix conservateur du projet, pas une validation
de cette révision par PokeLua. Une autre révision, une autre région ou une ROM
modifiée nécessitent une vérification propre ; le code du jeu et la révision
ne constituent pas une preuve d'identité de l'ensemble de la ROM.

## Profils d'équipe

| Profil | Jeu | Code | Révision admise | Compteur, 1 octet | Premier Pokémon | Taille par Pokémon |
| --- | --- | --- | --- | --- | --- | --- |
| `black_fr_rev0` | Noir français | `IRBF` | `0` | `0x02234930` | `0x02234934` | `220` (`0xDC`) octets |
| `black2_fr_rev0` | Noir 2 français | `IREF` | `0` | `0x0221E408` | `0x0221E40C` | `220` (`0xDC`) octets |

Pour l'emplacement `n`, numéroté de 1 à 6, l'adresse est
`party_address + (n - 1) * pokemon_size`. Les adresses françaises viennent de
[PokeLua, Noir](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/BW_RNG_DeSmuMe.lua#L451)
et de
[PokeLua, Noir 2](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/B2W2_RNG_DeSmuMe.lua#L405).
La lecture du compteur et le pas de `0xDC` sont employés dans
[la lecture de l'équipe de Noir 2](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/B2W2_RNG_DeSmuMe.lua#L937).

Un compteur égal à zéro donne **`not_ready`**, sans équipe ni taille publiées :
il ne permet pas de distinguer une équipe vide d'une mémoire non initialisée.
Un compteur supérieur à six, un Pokémon invalide ou un compteur qui change
pendant la lecture donnent `invalid_data`. Aucun résultat partiel n'est publié.

## Identification du jeu chargé

DeSmuME copie les `0x170` premiers octets de l'en-tête ROM à `0x027FFE00`.
Le lecteur lit le code de quatre caractères à `0x027FFE0C` et la révision à
`0x027FFE1E`. Ces positions sont documentées dans
[NDSSystem.cpp](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/NDSSystem.cpp#L2589)
et dans la
[structure NDS_header](https://github.com/TASEmulators/desmume/blob/1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a/desmume/src/NDSSystem.h#L135).

Le préfixe `IRB` identifie Noir et `IRE` identifie Noir 2. Le dernier caractère
est traduit vers la région du protocole : `F` → `FR`, `O` → `EN`, `D` → `DE`,
`I` → `IT`, `J` → `JP`, `K` → `KO`, `S` → `ES`. La détection d'une région
n'implique pas qu'un profil d'équipe existe pour celle-ci. Avant de lire
l'équipe, le jeu, le code complet, la région et la révision doivent tous
correspondre au profil transmis.

## Structure et déchiffrement

Les offsets ci-dessous sont relatifs au premier octet d'un Pokémon. `u16` et
`u32` désignent des entiers non signés en ordre petit-boutiste.

| Offset | Donnée | Traitement |
| --- | --- | --- |
| `0x00` | PID, `u32` | Non chiffré |
| `0x04` | Champ `Sanity`, `u16` | Doit être nul pour publier ce Pokémon |
| `0x06` | Somme de contrôle, `u16` | Initialise le flux des blocs |
| `0x08` à `0x87` | Quatre blocs de 32 octets | Déchiffrement et permutation |
| Premier `u16` du bloc A | Identifiant d'espèce | De 1 à 649 |
| `0x88` à `0xDB` | Extension d'équipe | Flux séparé, initialisé par le PID |
| `0x8C` | Niveau, 1 octet | De 1 à 100 après déchiffrement |
| `0x8E` | PV actuels, `u16` | De zéro aux PV maximaux |
| `0x90` | PV maximaux, `u16` | De 1 à 9999 |

Le flux avance avant chaque mot de 16 bits :
`seed = (seed * 0x41C64E6D + 0x6073) modulo 2^32`.
Le mot est combiné par XOR avec les 16 bits hauts de la nouvelle seed.
Le calcul Lua décompose le produit pour préserver les entiers exacts.
Le chiffrement des blocs commence avec la somme de contrôle ; celui de
l'extension recommence avec le PID. Voir
[PKHeX, Decrypt45](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/Util/PokeCrypto.cs#L166)
et
[PKHeX, CryptArray](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/Util/PokeCrypto.cs#L327).

L'indice de permutation est `((PID >> 13) & 31) modulo 24`. La position
du bloc A provient de
[PokeLua, getOffset](https://github.com/Real96/PokeLua/blob/b76caf669872897295db5304eebbdf5e53125efb/Gen%205/DeSmuMe/B2W2_RNG_DeSmuMe.lua#L736).
Le lecteur ne réordonne pas les quatre blocs : il lit directement le bloc A
à sa position et additionne tous les mots déchiffrés pour vérifier la somme.

Cette somme est une addition des 64 mots déchiffrés de `0x08` à `0x87`,
modulo `65536` ; ce n'est pas un CRC. Elle ne couvre pas l'extension d'équipe.
Les positions et les contrôles sont issus de
[PKHeX, PK5](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PK5.cs#L43)
et des
[statistiques d'équipe PK5](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PK5.cs#L276).
Les bornes de niveau et de PV ajoutent un contrôle de cohérence ; elles ne
remplacent pas une validation visuelle dans le jeu.

## Tests reproductibles

`tests/test_lua_gen5_reader.py` utilise la DLL Lua 5.1 fournie localement par
`PCE_LUA51_DLL` ou `runtime/probe/lua5.1.dll`. Ce binaire reste ignoré par Git.
Les données synthétiques sont produites par une implémentation Python
indépendante du flux et des permutations.

Les tests couvrent les 32 valeurs de permutation pour chaque profil, les six
emplacements, un Pokémon à zéro PV, les niveaux limites, les erreurs de somme
de contrôle, les identités incompatibles et les erreurs de lecture. En l'absence
de moteur Lua, les cas correspondants sont explicitement ignorés par pytest ;
ils ne doivent pas être présentés comme exécutés.
