# Passerelle DeSmuME / Lua — V0.3 en cours

Les scripts réalisent une communication locale **en lecture seule** avec DeSmuME.
Ils lisent la mémoire exposée par l'émulateur et écrivent des instantanés JSON
uniquement dans la session locale créée par l'application. Ils ne modifient ni
la RAM du jeu, ni une ROM, ni une sauvegarde, et n'appliquent aucune règle.

## Démarrage

1. Utiliser un build DeSmuME standalone avec **Tools > Lua Scripting**.
2. Dans l'application, ouvrir **Connexion DeSmuME**, sélectionner Noir, Blanc,
   Noir 2 ou Blanc 2 (pour reproduire l'essai réel : **Pokémon Blanc**),
   puis cliquer sur **Préparer la connexion**.
3. Ouvrir le jeu correspondant dans DeSmuME et le laisser en cours d'exécution.
4. Dans **Tools > Lua Scripting > New Lua Script**, ouvrir le chemin exact
   `connect.lua` affiché dans l'application, puis cliquer sur **Run**.

Ce script généré est préférable aux chemins supposés : il référence la session
et les ressources réellement préparées. `black.lua`, `white.lua`, `black2.lua`
et `white2.lua` sont aussi
des points d'entrée pour l'organisation standard du projet ; ils nécessitent
une connexion préalablement préparée. Ils ne sont plus des placeholders.

L'application ne lance pas automatiquement le script via une option CLI Lua.
Les étapes détaillées, les états et le dépannage sont décrits dans
[Connexion DeSmuME](../docs/desmume-bridge.md).

## Modules

| Fichier | Responsabilité |
| --- | --- |
| `common/bridge.lua` | Chargement de la session, sélection du profil, heartbeat, événements et publication atomique des instantanés |
| `common/protocol.lua` | Encodage JSON, tableaux et valeurs nulles |
| `common/gen5_reader.lua` | Identification du jeu, validation du profil, déchiffrement et contrôles des données d'équipe |
| `common/gen5_tracking_reader.lua` | Carte Noir/Blanc FR rev0 ; contrôles d'identité ; combat et résultat inconnus |
| `black.lua`, `white.lua`, `black2.lua`, `white2.lua` | Points d'entrée pour les quatre jeux dans l'arborescence standard |

Le script utilise les API DeSmuME `memory.readbyte` et `emu.frameadvance`.
`emu.registerexit`, lorsqu'elle est disponible, permet de signaler la fermeture.
Les capacités effectivement reçues sont affichées par l'application ; les
données indisponibles ne sont pas remplacées par des valeurs fictives.

Les versions sont indépendantes : scripts/application `0.3.0`, protocole JSON
`2` (Python reçoit aussi v1), challenge conservé `0.1.0`, progression schéma `2`.
Lua écrit uniquement les fichiers de transport ; le service Python décide du
suivi du profil actif. Le journal des observations est acquitté après traitement.

Les cartes ont des sources et des tests synthétiques. Les lectures de combat,
capture et fuite restent indisponibles ; aucun offset n'est supposé. Le cycle
Nuzlocke réel n'est donc pas opérationnel. **En attente de validation sur la machine utilisateur.**
Voir [les sources et limites du suivi](../docs/tracking-sources.md).

## Profils mémoire et validation

`data/memory_profiles.json` contient quatre profils français distincts, révision `0` :

| Jeu | Code réel attendu | Profil |
| --- | --- | --- |
| Noir | `IRBF` | `black_fr_rev0` |
| Blanc | `IRAF` | `white_fr_rev0` |
| Noir 2 | `IREF` | `black2_fr_rev0` |
| Blanc 2 | `IRDF` | `white2_fr_rev0` |

Les adresses de Blanc et Blanc 2 sont justifiées séparément dans les sources
PokeLua ; les profils de Noir et Noir 2 ne leur sont pas substitués. Le lecteur
vérifie jeu, code, région et révision avant toute lecture d'équipe.
Le statut `source_documented`
signifie que les adresses ont une source ; il ne constitue pas un test réussi
sur une équipe réelle. La correspondance du code et de la révision ne prouve
pas non plus l'intégrité de l'ensemble d'une ROM.

Le script de production a transmis réellement l'identité de Noir 2 français,
`IREF`, révision `0`, ainsi que les messages de connexion et de heartbeat.
La déconnexion, la reprise et l'arrêt demandé par Python ont aussi été testés.
Pour l'équipe, les espèces, les niveaux et les PV de Noir, Noir 2 et Blanc 2 :
**En attente de validation sur la machine utilisateur.** La situation de test ne disposait pas d'une partie
Noir 2 avec une équipe chargée. Une mémoire non initialisée conserve des données
nulles ; une région ou une révision non prise en charge reste limitée à l'identité.

Un échantillon réel de **Pokémon Blanc** a été comparé le **30 septembre 2026**
avec le profil `white_fr_rev0` : Feuillajou (ID 511, niveau 15, PV 6/42) et
Gruikui (ID 498, niveau 14, PV 45/45). Le service Python et l'interface Qt ont
reçu l'identité `IRAF / FR / 0`, les heartbeat et cette équipe du script Lua
réel. Ce profil porte `real_sample_verified` ; les trois autres conservent
`source_documented`. Un échantillon comparé n'est pas une garantie générale de
compatibilité. Pour reproduire la réception, le diagnostic se lance par
`python -m tools.bridge_diagnostic --game white --duration 60`, puis le script
indiqué doit être chargé dans DeSmuME. Les tests synthétiques couvrent déjà les
quatre jeux, leurs permutations de blocs et le refus de tout profil étranger ;
ils ne constituent pas une validation sur une partie réelle.

[Cartographie et sources mémoire](../docs/memory-map.md) ·
[Rapport des essais réels et synthétiques](../docs/verification.md)

## Tests Lua facultatifs

Depuis `pokemon-challenge-engine`, avec l'environnement Python dans le parent :

```powershell
$env:PCE_LUA51_DLL = "C:\chemin\vers\lua5.1.dll"
..\.venv\Scripts\python.exe -m pytest tests/test_lua_gen5_reader.py tests/test_lua_bridge.py -q
```

La bibliothèque doit être Lua **5.1**, avec une architecture compatible avec
Python. Le test recherche aussi une installation locale dans
`../runtime/probe/lua5.1.dll`. Aucun binaire n'est distribué dans le dépôt.
Sans moteur Lua disponible, les tests concernés sont explicitement **skipped**.
Ils exécutent le vrai code Lua sur une API mémoire synthétique et ne valident
pas une partie Pokémon réelle.
