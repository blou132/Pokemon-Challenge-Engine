# Essai de génération shiny — Blanc FR révision 0

État du 3 novembre 2026 : **option expérimentale disponible pour Blanc FR
révision 0**, avec périmètre explicite « générateur terrain, herbe normale
vérifiée ; autres catégories non validées ». Les réglages 1/4096, 1/1024,
1/512, 1/128 et 100 % modifient réellement une nouvelle copie de ROM.
Le taux original reste le choix par défaut. Noir, Noir 2, Blanc 2 et toute
signature inconnue sont refusés pour ce patch. Le suivi Shiny Only existant
conserve le critère Gen V `< 8`.

Une rencontre Ratentif sur Route 1 dans melonDS a donné un PK5 au checksum
valide, PID `3591503913`, identifiant d'origine `3944037679`, XOR shiny `1`.
Après Randomizer et Monotype, une rencontre Chuchmur sur la même route a donné
PID `3598909624`, même identifiant d'origine, XOR `1`, checksum valide.
Ces deux observations portent sur les essais au sélecteur 1. Le RNG natif
utilise bien les constantes `0x5d588b656c078965` et `0x269ec3`, également
vérifiées dans les états melonDS. La validité des autres bornes repose sur
la preuve arithmétique et les instructions testées ci-dessous, pas sur une
estimation de fréquence à partir de ces deux rencontres.

Le patch agit sur un générateur partagé : il n'est pas présenté comme exclusif
aux sauvages. Starters, cadeaux, statiques, œufs, fuyards et autres chemins ne
sont pas garantis. Certains peuvent être affectés si leur création traverse
ce générateur ; les verrous antishiny restent respectés. La sélection du taux
ne garantit donc pas un starter shiny au début d'une nouvelle partie.

## Périmètre et mécanisme

`tools.shiny_field_trial` cible uniquement `IRAF`, révision 0, et deux empreintes
ARM9 explicitement reconnues : original et variante produite par ZX. Le code
complet de la fonction du générateur de terrain, dans l'overlay 21, doit avoir
l'empreinte attendue. Aucune recherche approximative de motif n'autorise une
modification d'une autre version.

Le patch remplace une partie de cette fonction dans son empreinte existante.
Il utilise le générateur du jeu avec la borne 4096, 1024, 512, 128 ou 1, puis
demande au véritable générateur PID un résultat shiny uniquement pour le
tirage zéro. Le verrou antishiny existant de valeur 2 est conservé. Le prédicat
shiny, les identifiants du dresseur, les sauvegardes et la mémoire d'un émulateur
en cours d'exécution ne sont pas modifiés. L'essai ne concerne que les créations
qui empruntent effectivement cette fonction et ne corrigent pas ensuite le PID.

L'overlay est décompressé puis recompressé avec le codec du JAR ZX épinglé.
Le retour exact compression/décompression est vérifié. Le résultat doit tenir
dans son allocation originale ; seules les données compressées et leurs deux
champs de longueur FAT/overlay sont modifiés. Les indicateurs de l'overlay sont
préservés. Une comparaison de chaque octet contrôle qu'aucun autre endroit de
la copie n'a changé. La ROM source et le JAR sont contrôlés par SHA-256.

La destination doit être un fichier neuf. Une source, sauvegarde ou destination
existante n'est jamais remplacée. Une sortie interrompue reste disponible pour
diagnostic et doit être considérée comme invalide.

## Utilisation dans PCE et provenance

Activer Shiny Only, choisir Blanc FR puis le taux du générateur terrain. La
confirmation de création rappelle le périmètre expérimental. Cette option peut
fonctionner seule, avec Monotype ou avec Randomizer ; elle exige une nouvelle
aventure. Java et ZX intégrés préparent et relisent la copie, puis la sélection
Monotype éventuelle précède le patch terrain. Le pipeline sans catégories
Randomizer conserve les dix catégories de données Pokémon.

Le profil enregistre `settings.rom_transformation.shiny_denominator` uniquement
pour un taux personnalisé. Le manifeste ajoute `pce-shiny-field-v1` à l'ordre
des étapes, conserve le SHA-256 final et l'empreinte de `shiny-patch.json`.
La reprise contrôle ces empreintes, le taux demandé et les garanties de
préservation du verrou et du prédicat. L'affichage distingue une option demandée
d'un patch appliqué dont la provenance de la ROM est vérifiée. Les anciens
profils ne reçoivent aucun patch implicite ; revenir au taux original retire
ce paramètre de la prochaine configuration.

## Reproduction développeur

Depuis la racine du projet Python, avec une ROM personnelle et les outils locaux :

```powershell
python -m tools.shiny_field_trial --rom "C:\jeux\blanc-fr.nds" --output "C:\essais\blanc-trial.nds" --java "C:\jdk\bin\java.exe" --jar "C:\outils\PokeRandoZX.jar" --denominator 1
```

La commande affiche le manifeste technique en JSON. Cette commande développeur
ne crée pas les métadonnées d'aventure PCE ; passer par l'application pour une
partie gérée avec provenance et sauvegarde indépendante. Aucun original Nintendo, code
décompressé, sauvegarde personnelle ni ROM dérivée n'est livré avec les sources.

`tools.check_shiny_field_cpu` permet de reproduire le contrôle des instructions
avec le paquet de développement optionnel `unicorn` :

```powershell
python -m tools.check_shiny_field_cpu --rom "C:\jeux\blanc-fr.nds" --java "C:\jdk\bin\java.exe" --jar "C:\outils\PokeRandoZX.jar"
```

Le test a réussi pour les cinq dénominateurs, soit **46 088 exécutions CPU** :
32 768, 8 192, 4 096, 1 024 et 8 cas. Il couvre chaque valeur du sélecteur,
avec/sans verrou et quatre entrées PID. Il vérifie le critère shiny calculé avec
PID/OT, l'octet bas du PID, les registres restaurés, la pile et les arguments
des appels au générateur aléatoire. **Les sorties RNG sont imposées par le test** :
ce résultat ne mesure aucune distribution aléatoire réelle, ni la fréquence de
rencontres shiny en jeu. Le Pokémon de test et les paramètres de sexe sont
fixes ; les mécanismes de nature, talents, IV et toutes leurs variantes ne
sont pas déclarés validés par cet échantillon.

Un contrôle complémentaire exécute le **RNG natif sans remplacement** pour
11 522 bornes de classes : chaque borne inférieure et supérieure de chacun
des cinq dénominateurs. Des états initiaux choisis sont injectés dans le CPU
de test, sans modifier une ROM ou un émulateur de jeu. Le résultat est exactement
`high32(état_suivant) × dénominateur >> 32`. Les dénominateurs étant des puissances
de deux, chaque classe possède exactement `2^32 / dénominateur` entrées. Il n'y a
donc pas de biais d'arrondi à compenser par un échantillon massif. Ce contrôle
prouve l'arithmétique de la sélection ; il ne prouve pas à lui seul quel chemin
est emprunté par une rencontre en jeu, ni l'absence de correction ultérieure du PID.

Le [rapport CPU du 3 novembre](shiny-cpu-validation-2026-11-03.json) réunit les
46 088 cas du sélecteur et les 11 522 bornes du RNG natif, tous réussis dans
la même exécution de l'outil livré. Il distingue explicitement les appels
RNG remplacés pour tester les branches et le contrôle arithmétique sans remplacement.

La copie originale d'essai au sélecteur 1 a passé la vérification de tous ses
octets et la relecture/décompression, SHA-256 :
`240399d13aefca91b8eb3e1ccdaf9fdd13d7d7ae29696ed6c65c0902fca2eaf2`.
La source Blanc est restée inchangée :
`0a7d6e87d9878c2fb903bcca01ecc8f9a186d0eed14ddbc87912ae126faa0bdb`.

Le même contrôle structurel a réussi après la chaîne Randomizer dix catégories
+ Monotype Feu Pur, seed 5122026. La source intermédiaire
`40f817c8861a7df10408747a4e9f026ec932d00ff49b8c746bc1a059f988992f`
est restée intacte ; la copie d'essai a l'empreinte
`ec8fae0b1eb6c523f961fbf5d4e3111ca58b03192cd18d53d1e383096d0bc4c5`.
Seuls l'overlay et les longueurs déclarées ont changé. Cette vérification
est complétée dans le pipeline produit par le manifeste et les vérifications
de reprise décrits ci-dessus.

## Limites et validations nécessaires pour élargir le support

- Relier chaque chemin effectif au résultat final en jeu : herbe, herbe spéciale,
  grottes, Surf et pêche ; ne pas extrapoler aux starters, cadeaux, statiques,
  œufs ou fuyards. Vérifier aussi les créations explicitement forcées shiny.
- Lire PID et identifiants d'origine après création, capture, sauvegarde et
  reprise ; tester chaque sexe, talent, nature et mécanique spéciale pertinente.
- Compléter les observations par catégorie et mécanique spéciale ; ne pas
  transformer les deux rencontres observées en estimation statistique du taux.
- Valider chaque combinaison Randomizer/Monotype sur sa ROM finale.
- Identifier et tester séparément Noir, Noir 2 et Blanc 2 FR avant tout support.

Pour un essai melonDS, démarrer depuis une copie de sauvegarde disque, pas depuis
un ancien save state : celui-ci peut réinjecter l'overlay d'avant modification.
Les résultats d'émulation sont consignés séparément dans le rapport de livraison.
