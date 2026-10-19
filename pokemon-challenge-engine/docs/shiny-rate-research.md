# Taux shiny Gen V : état de la recherche

Recherche documentaire du 15 octobre 2026. **Les taux personnalisés restent
désactivés pour Noir, Blanc, Noir 2 et Blanc 2 FR révision 0.** Aucun patch de
génération n'a été validé sur ces versions. Shiny Only observe les Pokémon
présents ; il ne change pas leur probabilité d'apparition.

## Génération et apparence

Le statut shiny Gen V dépend du PID et des identifiants du dresseur d'origine :
`TID xor SID xor PID_bas16 xor PID_haut16 < 8`. C'est le critère utilisé par
[PK5.PSV/TSV](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PK5.cs#L295),
[PKM.IsShiny](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PKM.cs#L318)
et le [contrôle PCE](gen5-rule-observation.md).

Le [tutoriel ARM9 de theSLAYER](https://projectpokemon.org/home/forums/topic/59405-gen-4-5-shiny-rate-modification/)
augmente le seuil de cette comparaison. L'auteur précise que la génération
des PID/IV reste inchangée : certains Pokémon paraissent shiny uniquement
dans la ROM modifiée. Cette méthode ne répond pas à la génération de Pokémon
réellement shiny selon le critère Gen V. Elle n'est pas intégrée à PCE ; son
motif de recherche ne constitue pas une signature validée pour Blanc FR0.

## Chemins de génération à distinguer

La [décompilation pokebw2](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/README.md)
cible actuellement les builds B2/W2 USA/Europe identifiés dans son README.
Elle documente des mécanismes utiles, mais ne fournit pas une carte mémoire
Blanc 1 FR. Aucun build de cette décompilation n'a été vérifié par PCE.

| Catégorie | Mécanisme documenté | Vérification encore nécessaire sur Blanc FR0 |
| --- | --- | --- |
| Sauvages | Génération PID puis correction du bit 31 ; boucle de tirages avec bonus dans B2W2 | Localiser les fonctions et appels, puis vérifier le PID final pour herbe, surf et pêche |
| Starters et cadeaux ordinaires | Création par script, avec modes shiny paramétrés pour certains cadeaux | Relier les scripts FR à la création finale ; ne pas supposer une couverture commune |
| Statiques | Drapeaux pouvant imposer ou interdire le shiny | Préserver ces verrous et identifier les rencontres concernées |
| Œufs de pension | Chemins BW et B2W2 distincts ; tirages supplémentaires Masuda et charme selon le jeu | Localiser le chemin BW FR, vérifier héritage, bonus et stockage du PID |
| Œufs cadeaux et événements | Création par script ou politique propre à la carte cadeau | Vérifier identifiants du dresseur d'origine, éclosion et contraintes du cadeau |
| Fuyards et Pokémon précréés | Réutilisation possible d'un PID déjà stocké | Identifier la création initiale ; ne pas modifier un individu existant à sa rencontre |

Sources primaires épinglées pour cette distinction :

- [PML_GenPID et PML_CreatePkm](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/src/system/poke_tool.c) : modes shiny, sexe, talent et autre entrée de création directe.
- [Génération sauvage](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/src/ov036/enc_pokeset.c) et [rencontres statiques](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/src/ov036/field_encount.c).
- [Commandes de création par script](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/src/ov012/scrcmd_pokemon.c).
- PokeFinder : [finalisation PID](https://github.com/Admiral-Fish/PokeFinder/blob/c3d88283ef3ea829c67888ed5354e65cbf9b542c/Core/Util/Utilities.cpp#L200), [œufs BW/B2W2](https://github.com/Admiral-Fish/PokeFinder/blob/c3d88283ef3ea829c67888ed5354e65cbf9b542c/Core/Gen5/Generators/EggGenerator5.cpp), [statiques/cadeaux](https://github.com/Admiral-Fish/PokeFinder/blob/c3d88283ef3ea829c67888ed5354e65cbf9b542c/Core/Gen5/Generators/StaticGenerator5.cpp) et [événements](https://github.com/Admiral-Fish/PokeFinder/blob/c3d88283ef3ea829c67888ed5354e65cbf9b542c/Core/Gen5/Generators/EventGenerator5.cpp).

Ces sources montrent pourquoi un changement du générateur commun ne prouve
pas une couverture universelle : certains chemins le contournent, d'autres
corrigent ensuite le PID. Elles n'établissent aucun offset français utilisable.

## Compatibilité avec le Randomizer

[ZX 4.6.1](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/romhandlers/Gen5RomHandler.java)
contrôle les CRC de l'entrée, étend ARM9 et peut modifier des overlays,
notamment pour les évolutions de Munja. La chaîne PCE exige actuellement
une ROM originale reconnue. Un futur patch shiny devra donc être évalué sur
la copie produite par ZX, avec ses propres préconditions et son hash final ;
la compatibilité n'est pas acquise par le seul code de jeu.

L'option `shinyChance` de
[ZX](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/romhandlers/AbstractRomHandler.java#L1667)
appartient au traitement des dresseurs. Ce n'est pas une API de taux global
pour les sauvages, starters et œufs.

## Conditions avant activation

1. Identifier chaque build par code, révision et empreinte ; établir les
   fonctions, appels, préimages et signatures complètes dans ARM9/overlays.
   Vérifier une reconstruction sans changement avant de modifier une copie.
2. Limiter explicitement le premier périmètre, par exemple aux sauvages
   ordinaires de Blanc FR0. Conserver `< 8`, les verrous et les contraintes
   sexe/talent/nature/IV ; intervenir avant chiffrement, après finalisation PID.
3. Définir le cumul avec les bonus. R tirages indépendants de probabilité p
   donnent `1-(1-p)^R`, pas exactement `R*p` : un nombre de relances ne suffit
   pas à promettre un dénominateur exact.
4. Vérifier l'ordre des transformations, les préconditions après ZX et la
   reproductibilité ; lier le manifeste et les données effectives à la ROM
   finale. Refuser toute signature ambiguë ou combinaison non testée.
5. Tester en jeu chaque catégorie annoncée, contrôler PID/OT en lecture seule
   puis après sauvegarde/rechargement sur copies dédiées. Pour un taux
   probabiliste, documenter échantillon et incertitude statistique.

**État des preuves :** sources documentées ci-dessus ; aucun test synthétique
d'un patch shiny, aucune ROM shiny dérivée et aucune validation réelle de taux
obtenus par cette recherche. Une couleur affichée ou une rencontre shiny isolée
ne valide ni la génération ni la probabilité annoncée.
