# ROM dérivées Gen V — V0.5

14 octobre 2026. Le moteur produit une ROM Randomizer dédiée avant publication
des fichiers de la nouvelle aventure. La modification réelle des données ROM,
la vérification structurelle et la validation du jeu dans DeSmuME sont des
preuves distinctes. Les derniers essais de jeu figurent dans
[verification.md](verification.md).

## Outil, provenance et seed

L'intégration utilise **Universal Pokémon Randomizer ZX 4.6.1**, commit
`7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c`. Un JDK local 11 ou supérieur et le
JAR officiel sont nécessaires. L'application ne télécharge ni ROM, ni Java,
ni Randomizer et n'installe rien globalement.

Le JAR sélectionné doit correspondre au SHA-256
`380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8`, relevé sur
la [release officielle](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/releases/tag/v4.6.1).
L'empreinte ne constitue pas une signature fournie par l'auteur. La provenance,
la licence complète et les liens de code épinglés sont dans le
[README de l'adaptateur](../tools/randomizer/README.md).

La CLI ZX n'accepte pas de seed. L'adaptateur Java PCE appelle la surcharge réelle
[`Randomizer.randomize(filename, log, long seed)`](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/Randomizer.java).
La seed de la partie est aussi celle de cette transformation, dans l'intervalle
0 à 9223372036854775807. L'adaptateur est fourni en source sous GPL-3.0-or-later
avec [COPYING](../tools/randomizer/COPYING), sans JAR redistribué. Le code source
correspondant de ZX est accessible au commit indiqué ; ZX est également sous
GPL-3.0-or-later.

## Catégories réellement intégrées

| Option | Portée |
| --- | --- |
| Rencontres sauvages | Tables de rencontres ; toutes les variantes temporelles exposées par ZX |
| Starters | Choix d'espèces des starters |
| Dresseurs | Équipes des dresseurs, champions compris ; pas d'option séparée « champions seulement » |
| Capacités apprises | Movesets ; pas une randomisation générale des CT et tuteurs |
| Talents | Talents des espèces |
| Objets de terrain | Objets ordinaires au sol ; pas tous les objets du jeu |
| Évolutions | Destinations des évolutions |
| Types | Types des espèces et formes effectivement exposées par ZX |
| Puissance similaire | Option de ZX appliquée aux rencontres, dresseurs et évolutions sélectionnés ; aucune garantie de difficulté équilibrée |

La modification demandée est vérifiée par comparaison des structures relues
avant et après transformation. Une catégorie sélectionnée inchangée est refusée ;
une des huit catégories modifiée sans sélection est également refusée. ZX modifie
aussi son Pokémon d'introduction et ses marqueurs internes de randomisation : le
contrôle de catégories ne prétend pas limiter toute différence binaire à ces tables.

Les identités acceptées sont **IRBF / IRAF / IREF / IRDF**, français, révision 0,
avec paramètres distincts dans
[`gen5_offsets.ini`](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/config/gen5_offsets.ini).
ZX doit reconnaître les CRC de la ROM originale avant de modifier sa copie.
Un code de jeu valide seul ne suffit pas. Une ROM déjà modifiée n'est pas une
entrée acceptée pour cette chaîne.

## Création, isolation et reprise

Dans le challenge, les réglages reproductibles sont figés sous
`settings.rom_transformation` :

```json
{"kind":"zx","categories":["wild","starters","trainers"],"balanced":true}
```

Ils utilisent `challenge.seed`. Les chemins du JDK et du JAR restent dans
`randomizer.local.json`, jamais dans le modèle réutilisable. L'API locale est
`RandomizerToolStore(base_dir).load()` / `.save(java_path, jar_path)` ; `save`
vérifie l'outil et doit être exécuté hors du thread graphique.

La préparation exige une aventure neuve, encore en préparation, sans session,
équipe, capture, décès, badges, zone ni temps de jeu. L'import d'un ancien `.dsv`
ou de save states est refusé pour une ROM Randomizer. Une partie historique qui
déclarait seulement la règle Randomizer est conservée : aucun réglage de patch
n'est inventé et aucune transformation n'est déclenchée implicitement.

Le déroulement est le suivant :

1. Vérifier identité, outil et empreinte source, puis copier la ROM dans un dossier
   de travail neuf. Java reçoit uniquement cette copie.
2. Produire une autre ROM, la recharger avec ZX, comparer les catégories et
   exporter les données effectives. Vérifier que la source et l'outil n'ont pas changé.
3. Copier la dérivée dans `play/game/<jeu>-<uuid>.nds`. Garder le manifeste, le
   rapport, l'adaptateur et le journal dans `play/transformation/` ; retirer seulement
   le doublon de ROM produit par cette opération.
4. Publier ensemble l'espace de jeu et les références de la partie sous le verrou
   existant. Un changement concurrent de la partie annule cette publication.

La ROM publiée devient immuable comme dans la V0.4.1. Son empreinte, le manifeste
et le rapport sont vérifiés à la reprise. Java et le JAR ne sont plus nécessaires
pour reprendre cette aventure. Les chemins de sauvegarde, états et backups
restent propres à l'UUID. La suppression existante inventorie aussi la provenance.

Un échec de l'outil autonome conserve un dossier `.pce-transform-…` explicitement
marqué non publié. Dans la préparation d'une aventure, les fichiers provisoires
appartenant à cette seule tentative sont nettoyés et les références précédentes
sont conservées. La source demeure intacte dans les deux cas. Aucun dossier de
destination existant n'est remplacé. Le processus Java dispose d'un délai maximal
de dix minutes.

## Types et évolutions effectifs

`RunTransformationProvider(runs_directory).for_run(run)` renvoie les données
effectives seulement après validation de leur liaison à la ROM et à l'aventure.
Le résultat contient `game_id`, `rom_sha256`, `categories`, `pokemon`, `starters`
et la provenance. Les signatures des fichiers invalident un cache borné : la ROM
n'est pas rehachée à chaque rafraîchissement si tous les artefacts sont inchangés.
Une erreur de validation interdit le repli silencieux sur les données originales.

Chaque ligne contient `species_id`, `form`, `types`, `evolutions` et, depuis
l'adaptateur final, `identity_evolutions`. Le dernier champ exclut la méthode ZX
`LEVEL_IS_EXTRA` : celle-ci crée l'individu supplémentaire de type Munja ; elle
ne prouve pas que l'individu précédent a évolué en ce nouvel individu.
`LEVEL_CREATE_EXTRA` est au contraire la méthode de l'évolution principale.
Ce sens a été vérifié dans
[`EvolutionType`](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/pokemon/EvolutionType.java),
[`Gen5RomHandler`](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/romhandlers/Gen5RomHandler.java)
et par lecture d'une copie originale Blanc : 290→291 `LEVEL_CREATE_EXTRA`,
290→292 `LEVEL_IS_EXTRA`.

L'absence de `identity_evolutions` dans un ancien rapport reste une inconnue,
sans reconstitution aveugle depuis `evolutions`. Une forme absente du rapport
reste également inconnue. En particulier, les formes cosmétiques d'Arceus,
Ceriflor et Genesect ne doivent pas être remplacées arbitrairement par la forme 0.
Les cycles d'évolution ou les observations sans identité suffisante restent à
traiter comme ambigus par le suivi.
Pour une évolution randomisée, le suivi exige aussi une forme 0 connue aux deux
observations : les liens extraits donnent l'espèce cible, pas sa forme. Les
changements impliquant une forme alternative restent donc non vérifiables,
même lorsque cette forme figure dans la table des types.

## Preuves déjà obtenues et limites

Les essais suivants ont réellement exécuté Java/ZX sur des copies de **Blanc FR
révision 0**, les 13 et 14 octobre, sous Windows, avec Java 25.0.4.1 déjà installé :

- Les huit catégories activées, puissance similaire, seed 5122026 : deux
  transformations indépendantes produisent exactement la même ROM et le même
  rapport. Les sources sont inchangées selon empreinte et signature de fichier.
- La ROM dérivée mesure 201424956 octets ; SHA-256
  `e2327f0c154919b0aee1c7467684e9fa551730afe30809a0af18043a2e7317a0`.
  Le rapport initial contient 667 couples espèce/forme. Starters relus : 246,
  632, 418. Cela prouve les données ROM, pas la sélection effective en jeu.
- Une transformation « rencontres sauvages seules » réussit également : cette
  catégorie change, les sept autres empreintes de catégories restent inchangées.
- L'ajout ultérieur de `identity_evolutions` enrichit le rapport de provenance ;
  les deux rapports initiaux identiques précédaient cet ajout.

Les tests Python utilisent des ROM et un outil synthétiques pour exercer les
refus, la persistance, la reprise, les sources inchangées, les imports interdits,
les fichiers altérés et l'isolation entre deux aventures. Ils ne prouvent aucune
jouabilité. Le manifeste de transformation inscrit `emulator: not_tested` et
`lua: not_tested` : tout essai réel ultérieur est documenté séparément.

**Noir, Noir 2 et Blanc 2 :** leurs profils ZX sont documentés ; ces seuls essais
Blanc ne valident ni leur génération de ROM dérivée, ni leur lecture Lua. La lecture
d'équipe Noir 2 reste soumise à sa validation propre.

## Taux shiny personnalisé

Les valeurs personnalisées restent désactivées : aucun patch ROM fiable n'a été
validé pour ces builds FR. Il n'existe aucune modification RAM dans cette chaîne.
La source concrète examinée
[BW Action Replay](https://github.com/TylerD007/The_Shiny_Pokemon_Code_Repository/blob/main/BW.txt)
concerne les versions US et des écritures mémoire. Ses routines diffèrent selon
les rencontres et comportent des limites documentées ; elles ne sont pas reprises
comme offsets FR ni converties arbitrairement en patch ROM.

L'observation Shiny Only peut donc être combinée avec une ROM randomisée au taux
original, sous réserve des données du lecteur. **Randomizer + taux 1/512**, ou
toute autre probabilité personnalisée, n'est pas une transformation disponible.
Une rencontre shiny isolée ne constituerait pas une validation statistique du taux.
