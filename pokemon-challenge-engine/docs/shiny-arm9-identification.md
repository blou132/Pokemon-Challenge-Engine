# Shiny : identification ARM9 en lecture seule

Complément expérimental du 20 octobre 2026 à [la recherche existante](shiny-rate-research.md).
**Aucun nouveau taux, patch ROM ou changement RAM n'est activé.**

## Résultat supplémentaire

Un même prédicat Thumb complet est présent une seule fois dans les copies
locales de Blanc FR0 et Noir 2 FR0, ainsi que dans leurs deux dérivées ZX et
Monotype déjà produites. Il extrait les quatre demi-mots de deux paramètres,
effectue leur XOR, compare le résultat à 8 et retourne un booléen. Cette
sémantique correspond à
[PML_UtilPIDIsRare](https://github.com/fuddlesworth/pokebw2/blob/9a3236bc8169d61fa6493046eceea9089961a71b/src/system/poke_tool.c).
L'outil vérifie toutes les instructions de cette variante et la constante
chargée via le PC, au-delà du motif court du tutoriel.

| Copie analysée | Taille ARM9 décompressée | Début du prédicat | Comparaison |
| --- | ---: | --- | --- |
| Blanc FR0, source | 681824 | `0x13EF4` | `0x13F0C` |
| Blanc FR0, ZX + Monotype | 681824 | `0x13EF4` | `0x13F0C` |
| Noir 2 FR0, source | 633888 | `0x18DD8` | `0x18DF0` |
| Noir 2 FR0, ZX + Monotype | 633888 | `0x18DD8` | `0x18DF0` |

Ce sont des offsets dans **ARM9 décompressé**, pas des positions modifiables
directement dans la ROM. L'adresse de chargement lue dans les quatre en-têtes
est `0x02004000`. Les CRC32 ARM9 décompressés des deux sources sont
`961E0C7B` et `98ACB21A`, conformes aux entrées françaises de
[ZX 4.6.1](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/config/gen5_offsets.ini).
Cette comparaison concerne ARM9, sans certifier l'ensemble du contenu des ROMs.

SHA-256 complets des fichiers analysés, identiques avant et après chaque essai :

- Blanc source : `0a7d6e87d9878c2fb903bcca01ecc8f9a186d0eed14ddbc87912ae126faa0bdb`.
- Noir 2 source : `693c009dc031e74d01e00385f7156386c457640ebf800e1a04629e1e07aa7d37`.
- Blanc ZX + Monotype : `023c357e51826829b51fd5485e3bf27c49aae6a650ee3207876920fcd4ba12e1`.
- Noir 2 ZX + Monotype : `dc6c28280c9b8e19526e6da3b6ea7845e78830998f925aae719f155533cd67d6`.

## Reproduire le diagnostic

Depuis le dossier de l'application, avec Python, un JDK (21 vérifié) et le
JAR officiel ZX 4.6.1 déjà utilisé par le Randomizer :

```powershell
python -m tools.shiny_arm9_inspect --rom COPIE.nds --java CHEMIN/java.exe --jar CHEMIN/PokeRandoZX.jar
```

Le programme ouvre la ROM en lecture seule, valide les bornes de l'en-tête,
retire les éventuels pieds Nitro selon
[NDSRom.getARM9](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/com/dabomstew/pkrandom/newnds/NDSRom.java),
puis appelle uniquement l'API en mémoire
[BLZ_DecodePub](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/blob/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/src/cuecompressors/BLZCoder.java).
Le SHA-256 du JAR est contrôlé avant cet appel. La CLI BLZ amont, qui peut
écraser ses entrées, n'est jamais appelée. Les octets passent par des tubes
mémoire ; aucun ARM9 extrait ni fichier ROM dérivé n'est écrit.

Le JSON sur la sortie standard contient les empreintes, tailles, offsets et
le statut `unique`, `absent` ou `ambiguous`. Il ne contient aucun octet de ROM.
Un avertissement du codec, une sortie incomplète ou un changement de l'entrée
pendant l'analyse fait échouer la commande. `patch_eligible` et
`custom_shiny_rate_validated` restent toujours faux, même avec un résultat unique.

## Vérifications et frontière restante

- Tests synthétiques : **17 réussis** pour l'analyse, incluant bornes, révision,
  JAR non reconnu, motifs incomplets/modifiés/multiples, constante PC, erreurs
  BLZ et changement concurrent de l'entrée. Un interpréteur Thumb indépendant
  dans les tests vérifie les 65536 XOR réduits, chaque bit des deux paramètres
  et 2048 combinaisons aux limites du seuil.
- Régression de l'interface Shiny : **7 réussies** ; les taux personnalisés
  restent indisponibles. Total ciblé : **24 réussis**.
- Exécutions réelles : **4 analyses CLI réussies**, avec compilation à la volée
  du pont Java et décompression réelle par ZX ; aucune mutation des entrées.
- Aucun émulateur lancé, aucun taux mesuré, aucun patch synthétique ou réel testé.
  Noir FR et Blanc 2 FR n'ont pas été analysés sur un fichier réel.

Une occurrence statique ne prouve ni les appels exécutés ni les paramètres
effectivement passés. Aucun appelant, overlay de génération, finalisation PID
ou chemin de stockage français n'est établi par cet outil. Il reconnaît une
seule variante exacte ; une absence ne démontre pas l'absence de contrôle shiny.
La présence inchangée du prédicat après les deux transformations testées ne
valide pas d'autres options ZX. La prochaine preuve nécessaire reste le lien
entre un chemin de génération limité et le PID final stocké, sans toucher au
seuil `< 8`. Les conditions d'activation de la recherche initiale restent ouvertes.
