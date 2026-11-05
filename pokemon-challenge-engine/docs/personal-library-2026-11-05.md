# Bibliothèque personnelle — 5 novembre 2026

La bibliothèque conserve les ROM maîtresses dans un stockage privé permanent,
indépendant du dépôt, du ZIP portable et des dossiers des aventures. La version
reste **0.5.0 en validation**. Ce rapport décrit les développements et les preuves
disponibles ; la suite complète et la nouvelle construction Windows restent à
consigner après leur exécution.

## Inventaire réel et import privé

Le dossier local `roms sources` contient **neuf archives ZIP**, chacune contenant
une ROM Nintendo DS. Les neuf jeux sont français, identifiés par leur en-tête et
leur SHA-256. Aucun des neuf jeux envisagés n'est absent ; aucun doublon n'a été
trouvé dans cet inventaire. Le nombre initial de sept a été rectifié après
lecture des fichiers et confirmation de l'utilisateur.

| Jeu | Génération | Code | Région | Révision | Taille de la ROM |
| --- | --- | --- | --- | --- | --- |
| Diamant | IV | ADAF | FR | 5 | 64 Mio |
| Perle | IV | APAF | FR | 5 | 64 Mio |
| Platine | IV | CPUF | FR | 0 | 128 Mio |
| HeartGold | IV | IPKF | FR | 0 | 128 Mio |
| SoulSilver | IV | IPGF | FR | 0 | 128 Mio |
| Noir | V | IRBF | FR | 0 | 256 Mio |
| Blanc | V | IRAF | FR | 0 | 256 Mio |
| Noir 2 | V | IREF | FR | 0 | 512 Mio |
| Blanc 2 | V | IRDF | FR | 0 | 512 Mio |

Les neuf maîtresses ont été importées et vérifiées le 4 novembre. Un second
import a ajouté **zéro copie** : le manifeste et les dates de modification des
maîtresses sont inchangés. Les SHA-256 des neuf archives sources sont identiques
avant et après ces opérations. Les relevés locaux sont
`runtime/personal-library-inventory-20261104.json` et
`runtime/personal-library-import-20261104.json` ; ils ne contiennent pas les ROM.

La bibliothèque Windows par défaut est :

```text
%LOCALAPPDATA%\Pokemon-Challenge-Engine\library\
  library.json
  masters\<jeu>\<sha256>.nds
```

Ce chemin reste le même après remplacement du dossier de l'application, même
en mode portable ou avec un autre `--data-dir`. Une copie du ZIP sur un autre
ordinateur n'emporte pas cette bibliothèque personnelle. L'option avancée
`--library-dir` permet de choisir explicitement un autre dossier absolu, notamment
pour les tests isolés.

## Utilisation dans l'application

**Paramètres → Bibliothèque de jeux** présente les neuf jeux, leur génération,
la présence de la maîtresse, le dernier contrôle d'intégrité, la disponibilité
de melonDS, les modes compatibles et le nombre de parties enregistrées.
**Vérifier ma bibliothèque** recalcule les empreintes. Le résultat affiché est
lié au SHA-256 de la maîtresse concernée : un ancien contrôle ne valide pas une
autre entrée.

**Importer un dossier local…** accepte les fichiers `.nds` et les archives ZIP
contenant une seule ROM `.nds`. Un fichier identique déjà importé est conservé.
Une autre empreinte pour le même jeu provoque un refus explicite, sans remplacer
la maîtresse. Les copies et les calculs d'empreintes s'exécutent hors du thread
de l'interface ; fermer pendant une opération demande d'attendre sa terminaison.
Une erreur reste visible dans le panneau.

Au premier démarrage avec une bibliothèque vide, le programme peut importer le
dossier `roms sources` voisin de l'installation ou à la racine du dépôt. Les
lancements suivants utilisent la bibliothèque persistante : les chemins des
archives d'origine n'ont pas à être saisis à nouveau. L'import explicite reste
disponible pour ajouter un jeu dans une bibliothèque déjà constituée.

Depuis **Mes parties → Nouvelle partie**, choisir le jeu et une configuration
compatible. La préparation vérifie l'identité et l'empreinte de la maîtresse,
copie la ROM dans l'espace de l'aventure, puis applique les transformations
demandées sur cette copie. Les fichiers de sauvegarde et de states appartiennent
à cette aventure. Une intégrité non conforme interrompt la préparation.
La suppression d'une aventure ne possède aucun droit de suppression sur la
bibliothèque ; la maîtresse peut servir à une autre partie.

## Compatibilité réelle

| Jeux | Fonctions proposées | Limites |
| --- | --- | --- |
| Diamant, Perle, Platine, HeartGold, SoulSilver | Nouvelle partie classique avec melonDS, ROM et sauvegardes indépendantes, reprise | Aucun suivi d'équipe ou de zone, challenge, Randomizer, Monotype ou patch shiny Gen IV ; import d'une ancienne batterie Gen IV refusé |
| Noir, Blanc, Noir 2, Blanc 2 FR0 | Partie classique, challenges Gen V, Randomizer et Monotype sur copies | Suivi limité aux événements réellement observables ; plusieurs déclarations restent manuelles |
| Blanc FR0 reconnu | Patch shiny expérimental du générateur terrain, après les transformations compatibles | Herbe normale vérifiée ; autres catégories non validées, verrous antishiny conservés |
| Noir, Noir 2, Blanc 2 | Surveillance Shiny Only selon les observations disponibles | Taux shiny original uniquement |

Les contraintes Gen IV sont contrôlées dans l'interface et les services métier.
Une présence dans la bibliothèque ne déclenche pas l'interprétation de la mémoire
Gen IV avec les structures Gen V. Les messages natifs d'identité et de session
peuvent alimenter le temps de jeu et les commandes melonDS ; ils ne sont pas
présentés comme une lecture d'équipe.

Les [preuves de la livraison précédente](v0.5-delivery-20261102.md) conservent leur
portée propre. L'identification des neuf ROM et leur import fidèle ne constituent
pas une validation de toutes les aventures ou de tous les challenges sur chacun
des neuf jeux. Les nouveaux essais en émulation et de l'EXE seront consignés
séparément après exécution.

## Préparation locale en ligne de commande

La préparation privée est distincte de la distribution générale. Depuis le
dossier du nouvel EXE, PowerShell permet d'attendre la fin de l'import :

```powershell
$preparation = Start-Process -FilePath '.\Pokemon-Challenge-Engine.exe' -ArgumentList '--prepare-library "C:\Mes jeux\roms sources" --library-report "C:\Mes jeux\import-bibliotheque.json"' -Wait -PassThru -WindowStyle Hidden
$preparation.ExitCode
```

Pour vérifier ensuite les maîtresses sans ouvrir l'interface :

```powershell
$verification = Start-Process -FilePath '.\Pokemon-Challenge-Engine.exe' -ArgumentList '--verify-library --library-report "C:\Mes jeux\controle-bibliotheque.json"' -Wait -PassThru -WindowStyle Hidden
$verification.ExitCode
```

Adapter les chemins à ses dossiers. Le dossier du rapport doit exister et le
fichier JSON demandé doit être nouveau : un rapport existant n'est pas écrasé.
Le code de sortie est zéro lorsque les contrôles réussissent, un en cas d'échec.
Le rapport donne les jeux, empreintes et résultats d'intégrité. Cette sortie
fichier permet de consulter le résultat même lorsque l'EXE n'ouvre pas de console.

Pour le développement, depuis `pokemon-challenge-engine/`, les mêmes options
sont disponibles avec Python :

```powershell
python -m app.main --prepare-library '..\roms sources' --library-report 'C:\Mes tests\import.json'
python -m app.main --verify-library --library-report 'C:\Mes tests\controle.json'
```

Aucune de ces commandes ne télécharge de ROM. La bibliothèque privée, son
manifeste, le dossier `roms sources` et les sauvegardes sont exclus des archives
publiques et des commits. Les fichiers redistribuables restent l'application,
ses composants et leurs notices/sources, avec la bibliothèque locale séparée.

## État des validations de ce lot

- Import réel : neuf maîtresses vérifiées, neuf sources originales intactes,
  nouvel import sans doublon ni réécriture.
- Interface : opérations asynchrones, erreur d'intégrité, import déjà présent,
  erreur d'import partiel, fermeture pendant un travail, provenance des contrôles
  et affichage des neuf jeux testés avec des services injectés dans des dossiers
  temporaires. Le raccordement du rapport de découverte et des comptes de parties
  à la fenêtre principale est également testé. Le module dédié compte **14 tests
  réussis**, incluant le retour du diagnostic vers Paramètres et la création
  d'une partie Blanc ou Diamant avec la référence de bibliothèque correcte.
- Les tests ciblés du stockage privé et du périmètre Gen IV ont réussi. Les
  **35 nouveaux cas Gen IV** couvrent notamment les copies indépendantes, la
  reprise, les limites de modes et l'absence de lecture Gen V supposée. Les
  différentes séries ciblées se chevauchent ; leurs nombres ne s'additionnent
  pas au résultat de la future suite complète.
- **Suite pytest complète après intégration : en attente.**
- **Nouveau ZIP Windows, contrôle d'exclusion des ROM et essais de son EXE :
  en attente.** Le ZIP de la livraison précédente ne contient pas cette nouvelle
  bibliothèque dans son code.

Les tests automatiques de ce lot utilisent des données synthétiques et des
racines explicitement isolées. Les rapports des neuf imports réels sont distincts
de ces tests. Aucun résultat synthétique ne remplace une preuve d'émulation.
