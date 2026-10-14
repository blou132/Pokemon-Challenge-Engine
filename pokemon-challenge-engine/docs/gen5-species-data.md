# Données d'espèces Gen V

`data/gen5_species_types.json` contient 649 espèces dans deux tables distinctes,
Noir/Blanc et Noir 2/Blanc 2, avec leurs formes documentées. Il s'agit de faits
extraits d'une source technique, pas d'une validation de lecture sur émulateur.
Aucune ROM, sauvegarde ni ressource binaire PKHeX n'est distribuée par ce fichier.

## Sources reproductibles

Révision PKHeX : `09e7f18fbb33635e35cf9ffcbfd3322403780f8e`.

| Entrée | Taille | SHA-256 |
|---|---:|---|
| [personal_bw](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/byte/personal/personal_bw) | 40 080 octets | `3b2989703f07416162e61328186d2858cbe3082875c98c21eb40c2f7ce85ab7e` |
| [personal_b2w2](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/byte/personal/personal_b2w2) | 53 884 octets | `6df24e7f00dab32322d9d8f8b3209d30de1c89b0de88277081fe53434211830f` |

Les champs et tailles viennent de
[PersonalInfo5BW](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PersonalInfo/Info/PersonalInfo5BW.cs)
et [PersonalInfo5B2W2](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PersonalInfo/Info/PersonalInfo5B2W2.cs) :
entrées de `0x3C` et `0x4C` octets, types aux positions `0x06` et `0x07`, index
des formes à `0x1C`, nombre de formes à `0x20`. Ce sont des positions dans les
ressources PKHeX, **pas des adresses mémoire du jeu**.

Les formes admissibles et le partage des statistiques sont décrits dans
[PersonalTable5BW](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PersonalInfo/Table/PersonalTable5BW.cs),
[PersonalTable5B2W2](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PersonalInfo/Table/PersonalTable5B2W2.cs)
et [PersonalInfo.FormIndex](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PersonalInfo/PersonalInfo.cs).
Les indices de formes restent propres à l'espèce ; l'entrée personnelle 666
de BW n'est jamais traitée comme l'espèce nationale 666.

Les identifiants de types suivent
[MoveType](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Game/Enums/MoveType.cs),
limité aux 17 types Gen V. Les deux types identiques deviennent un type unique.
Arceus partage une ligne personnelle Normal, mais ses types sont déterminés par
la correspondance explicite de
[GetFormsArceus(Gen5)](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/Util/Conversion/FormConverter.cs).
Genesect conserve Insecte/Acier pour tous ses modules.

Pour régénérer, fournir les deux ressources locales de cette révision au script
depuis le dossier de l'application ; il vérifie leurs SHA-256 avant lecture :

```powershell
python -m tools.build_gen5_species_types <personal_bw> <personal_b2w2>
```

Le script n'effectue aucun téléchargement et n'accède à aucune ROM.

## Contrat des contrôles

`app/core/gen5_species.py` propose :

- `species_types` : types ordonnés de l'espèce et de la forme, ou `None`.
  Une forme omise reste inconnue si les formes documentées ont des types
  différents. Une forme propre aux suites est refusée dans Noir/Blanc.
- `monotype_compliance` : `True`, `False` ou `None`. Souple accepte l'un des
  types ; Strict exige le premier ; Pur exige le type unique choisi.
- `evolution_stage` et `is_unevolved` : le stade initial vaut zéro, y compris
  pour les espèces sans évolution. La convention « non évolué » accepte ce
  stade initial, même si l'espèce n'évolue jamais. Les stades utilisent les
  arêtes orientées de `gen5_evolution_families.json`, déjà sourcées dans le
  projet. La création de Munja constitue ici un stade après Ningale, sans
  changer la règle d'identité individuelle du suivi Nuzlocke.
- `starter_species` : candidats initiaux 495, 498, 501, d'après
  [Encounters5BW](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Encounters/Data/Gen5/Encounters5BW.cs)
  et [Encounters5B2W2](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Legality/Encounters/Data/Gen5/Encounters5B2W2.cs).
  L'appartenance à cette liste **ne prouve jamais** qu'un individu est le
  starter reçu par ce joueur.

Le champ brut `EvoStage` de la table personnelle n'est pas utilisé comme stade
évolutif : des espèces sans évolution y portent notamment une valeur 2 ou 3.
Le graphe orienté tient compte des bébés et des branches, contrairement au
minimum numérique d'une famille.

Chaque contrôle concerné renvoie `None` lorsque les types, évolutions ou
starters sont déclarés modifiés par une ROM dérivée. Un appelant doit transmettre
ces indicateurs ; il ne peut présenter les types originaux comme ceux d'une ROM
aux types randomisés. Aucune extraction des types d'une ROM dérivée n'est faite
par ce module. Les changements temporaires de type en combat (capacités,
transformations, etc.) ne sont pas couverts par cette table d'espèces/formes.

## Vérification

`tests/test_gen5_species.py` contrôle la couverture 1–649, les types Gen V
antérieurs au type Fée, les trois conventions Monotype, les formes Motisma,
Morphéo, Cheniselle, Shaymin, Arceus, Darumacho et Meloetta, les formes propres
aux suites, l'incertitude sans forme, les stades avec bébés et Munja, ainsi que
le refus d'utiliser des données originales modifiées. Ces contrôles sont
synthétiques et documentaires ; ils ne valident aucune lecture réelle du jeu.
