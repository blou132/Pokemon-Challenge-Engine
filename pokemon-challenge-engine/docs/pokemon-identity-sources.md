# Identité individuelle et familles Gen V — V0.4

## Champs documentés

Le lecteur d'équipe reste en lecture seule. Les quatre adresses de base,
le pas de 220 octets et le contrôle du profil restent ceux de
[la cartographie mémoire](memory-map.md). Aucun nouvel offset absolu RAM
n'est introduit. Après déchiffrement et contrôle de somme, deux champs sont
maintenant transmis :

| Champ JSON | Format | Source dans la structure PK5 |
| --- | --- | --- |
| `personality_id` | entier non signé 32 bits | PID non chiffré, offset `0x00` |
| `original_trainer_id` | entier non signé 32 bits | ID32, offset canonique `0x0C`, soit bloc A + 4 après permutation/déchiffrement |

Ces positions sont explicitement définies par
[PKHeX PK5.cs](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PK5.cs#L67-L79).
Le bloc A est déjà identifié par le lecteur. Les deux identifiants ne sont pas
calculés depuis l'espèce, le niveau, les PV ou le slot.

Le format local est `gen5:<PID hexadécimal sur 8 caractères>:<ID32 sur 8 caractères>`.
La valeur zéro est admise ; une donnée manquante, booléenne ou hors bornes ne
produit aucune identité fiable. Le PID seul reste insuffisant pour le suivi
automatique de mort. Ces nombres servent au suivi technique local et ne doivent
pas apparaître dans l'interface principale.

Une paire PID/ID32 n'est pas une preuve d'unicité absolue : clones et collisions
restent possibles. Un doublon simultané reste ambigu dans le suivi de run,
même après sa disparition de l'équipe et après redémarrage de PCE. Un changement
d'espèce sans évolution individuelle documentée conserve également cette
ambiguïté. La V0.4 permet alors une mort manuelle, pas une résolution automatique
de l'identité.
Une famille évolutive commune ne suffit jamais à identifier un individu.

## Décision de protocole

Le protocole reste **2**. Le script livré passe à **0.4.0**, puisqu'il expose
les identifiants. Il déclare sa version réelle même si une ancienne configuration
locale contenait la version 0.3.0. Le récepteur conserve :

- protocole 1 / Lua 0.2.0, sans identité individuelle ni observation ;
- protocole 2 / Lua 0.3.0, sans identité individuelle ;
- protocole 2 / Lua 0.4.0, avec ou sans les deux champs facultatifs d'identité.

Toute valeur d'identité non nulle exige la capacité `party_identity`.
Le script courant transmet la paire complète lorsque l'équipe est valide.
Les anciens messages conservent exactement leurs champs : aucune valeur fictive
n'est ajoutée aux Pokémon reçus. Une paire partielle reste transmissible mais
ne suffit pas pour identifier l'individu. Un ancien PCE ne sait pas accepter
cette nouvelle capacité ; la compatibilité garantie est la réception des anciens
producteurs par PCE V0.4, pas la réception du nouveau script par une ancienne app.

## Familles évolutives

La table [gen5_evolution_families.json](../data/gen5_evolution_families.json)
couvre exactement les espèces **1 à 649** avec **329 familles**. Elle provient
des 321 entrées d'évolution (320 liens distincts) de la ressource Gen V
[evos_g5.pkl de PKHeX](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/byte/evolve/evos_g5.pkl).
La ressource est explicitement sélectionnée pour Gen V dans
[EvolutionTree](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Evolutions/EvolutionTree.cs#L18).

- Commit source : `09e7f18fbb33635e35cf9ffcbfd3322403780f8e`.
- Taille source : `3874` octets.
- SHA-256 : `40a415c1febd807cd6e82b1bece71d7dcd724c7a17f03d9117af67304023479f`.
- Index des bornes : entiers 16 bits petit-boutistes,
  [BinLinkerAccessor16](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Assets/BinLinkerAccessor16.cs#L32-L40).
- Entrées de 8 octets, espèce cible à +4 :
  [EvolutionSet](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Evolutions/EvolutionSet.cs#L34-L42).

Le générateur conserve les liens documentés puis calcule leurs composantes
connexes, branches incluses. L'ID d'une famille est son plus petit numéro de
Pokédex, pas nécessairement son premier stade : Pichu/Pikachu/Raichu valent 25.
Les espèces sans évolution forment une famille d'un seul membre.
Nymphali (700) et toute autre évolution ultérieure ne sont pas introduits.
Il ne s'agit pas d'un moteur de conditions d'évolution ou de capture.

Le suivi d'un individu utilise en plus les **liens orientés** : Gruikui peut
devenir Grotichon puis Roitiflam ; Aquali ne devient pas Voltali, même si leur
famille est commune. Une évolution arrière ne prouve pas non plus la continuité
de l'individu. La création de Munja (290 → 292) reste dans la famille mais est
exclue des transitions individuelles automatiques. La ressource la distingue
avec la méthode 15, `LevelUpShedinja`, alors que Ningale → Ninjask utilise 14,
selon [EvolutionType](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Evolutions/Methods/EvolutionType.cs#L24-L25).
Le helper `documented_evolution` vérifie un chemin avant possible ; il ne
prétend pas vérifier ses conditions de niveau, d'objet ou d'échange dans le jeu.

La régénération est explicite et hors ligne, depuis une copie de la seule
ressource publique PKHeX. Le SHA doit correspondre avant toute interprétation :

```powershell
..\.venv\Scripts\python.exe -m tools.build_gen5_evolution_families C:\source\evos_g5.pkl
```

Aucune ROM, sauvegarde, DLL ou ressource binaire n'est distribuée avec la table.
Les familles ne modifient pas la logique de capture V0.3. Elles permettent à la
run de conserver l'historique du même individu lorsque son espèce évolue et
préparent les clauses de famille futures.

## Nature des preuves

La position des champs et la table sont **documentées par les sources**.
Les tests exécutent le lecteur Lua réel sur une **RAM synthétique chiffrée** :
32 permutations, uint32 extrêmes et nul, somme de contrôle, changement d'espèce,
ancien protocole, paire incomplète, doublons et refus des valeurs invalides.
Les familles sont testées séparément sur leurs liens et leur couverture complète.

L'essai isolé V0.4 a ensuite reçu réellement 84 messages du script 0.4.0 dans
Pokémon Blanc `IRAF / FR / 0`, avec deux paires PID/ID32 distinctes et une équipe
de Grotichon (19, 67/67 PV) et Feuillajou (17, 46/46 PV). Cela confirme le transport
réel des identifiants et leur association à deux individus suivis. Les valeurs
brutes du PID ne disposent pas d'une comparaison indépendante dans l'interface
du jeu ; les offsets et le décodage restent justifiés par les sources et tests
chiffrés. L'essai a vérifié la persistance de la run et du temps, avec les
originaux inchangés.

Cet essai ne valide aucune zone nommée, transition de PV, mort, soin après mort
ou évolution. Ces parcours ne sont donc pas validés
réellement par le succès des tests synthétiques. Les résultats détaillés restent
séparés dans [verification.md](verification.md) : **En attente de validation sur
la machine utilisateur** pour toute situation qui n'y est pas explicitement
vérifiée.
