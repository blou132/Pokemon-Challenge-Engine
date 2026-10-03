# Mort permanente — V0.4

Le cimetière est **virtuel et propre à la partie PCE**. Un mort identifié reste
mort dans cette partie après un soin, une évolution compatible ou son départ de
l'équipe. PCE ne supprime aucun Pokémon, ne modifie ni ses PV ni sa sauvegarde,
ne déplace rien vers une boîte et n'empêche aucune action du joueur.

## Conditions de détection automatique

La règle automatique exige les règles `nuzlocke` et `permanent_death` dans le
snapshot figé de la partie. Le suivi doit être actif, le processus et l'identité
du jeu compatibles, et l'équipe valide. Pour un individu suffisamment identifié,
deux observations continues doivent montrer **PV positifs → PV égaux à zéro**.
Le suivi enregistre `pokemon_fainted`, puis `pokemon_marked_dead` si cet individu
n'est pas déjà mort. La mort et ses événements sont sauvegardés immédiatement.

Une partie Classique peut conserver l'événement de K.O. observé sans appliquer
la mort permanente. Aucune défaite globale ni fin de partie n'est déduite d'une
équipe à zéro PV.

Le lecteur équipe connu peut ne refléter les PV de combat qu'à la fin du
combat. Cette limite demeure : une mort peut être constatée après cette
synchronisation, jamais annoncée comme un suivi garanti en temps réel du combat.

## Identité documentée, sans garantie universelle d'unicité

Le Lua 0.4.0 ajoute des champs optionnels au protocole 2 : `personality_id`
(PID) et `original_trainer_id` (ID32 du dresseur d'origine). Les anciens messages
sans ces champs restent recevables ; ils ne permettent pas une mort automatique
fiable. La clé locale Gen V combine génération, PID et ID32. Les valeurs zéro
sont valides ; espèce, niveau et emplacement ne constituent pas l'identité.

Les emplacements et la structure déchiffrée sont documentés dans
[memory-map.md](memory-map.md). Les deux identifiants sont des données techniques
Pokémon, conservées localement et absentes de l'interface principale. Ils ne
servent pas à identifier le joueur.

Des clones ou créations particulières peuvent partager le couple PID/ID32.
Des doublons simultanés rendent l'identité ambiguë. Cette ambiguïté est conservée
dans le registre de la partie, même si un des clones quitte ensuite l'équipe ou
si PCE redémarre. Un retour à une seule occurrence n'efface donc pas le doute.
La V0.4 propose la déclaration manuelle ; elle n'annonce pas une résolution
automatique des collisions.

## Évolutions et familles

La table locale couvre les 649 espèces accessibles en Gen V. Elle est générée
depuis la ressource d'évolution Gen V de PKHeX à un commit fixé, avec empreinte,
liens de format et 320 arêtes documentées dans
[gen5_evolution_families.json](../data/gen5_evolution_families.json). La source
principale est [PKHeX, evos_g5.pkl](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/Resources/byte/evolve/evos_g5.pkl).

La même clé peut suivre Gruikui → Grotichon → Roitiflam ; son historique
individuel et son statut mort restent attachés à cette clé. Un chemin dirigé
d'évolution doit exister entre les espèces. Une branche sœur (Aquali → Voltali),
une évolution arrière ou une espèce sans lien rend l'identité ambiguë et coupe
la détection automatique. L'apparition de Munja depuis Ningale est une création
séparée ; elle est exclue du suivi d'un même individu, même si la famille est
commune. La table ne prouve pas que les conditions de niveau ou d'objet étaient
réunies dans le jeu.

Les familles servent également de base indépendante pour de futures clauses
d'espèces. La V0.4 ne remplace pas le moteur de captures V0.3 et n'invente aucune
capture à partir d'un changement d'équipe.

## Confirmation et actions manuelles

Ces situations ne produisent pas automatiquement une mort : première observation
déjà à zéro PV, identité absente ou partielle, collision, changement d'espèce
incompatible, retour après déconnexion, crash, timeout ou absence de l'individu
dans l'observation précédente. Une observation pertinente à zéro PV apparaît
dans les éléments à vérifier de la fiche.

**Enregistrer une mort** accepte un individu connu ou une déclaration par
Pokémon, zone, date et note/cause. Sa source est `manual`. Confirmer une
observation marque celle-ci comme résolue et conserve sa référence à la mort.
Une déclaration sans clé fiable alimente le cimetière sans coller arbitrairement
le statut mort à un emplacement ou à un autre Pokémon de même espèce.

**Annuler / corriger une mort** exige une confirmation. L'entrée originale reste
présente avec son statut corrigé et un événement `death_corrected`. Elle ne compte
plus parmi les morts actives ; l'historique initial n'est pas effacé. Une nouvelle
transition positive → zéro ultérieure peut constituer un nouvel événement.

Badges et captures restent manuels. Les inconnus restent affichés comme non
renseignés ; l'absence de preuve ne devient pas un compteur inventé.

## Niveau de validation

La structure des identifiants et les familles sont **documentées par des
sources techniques**. Les transitions, collisions, évolutions, soins après mort,
corrections et reprises après crash sont couverts par **tests synthétiques**.
Ces tests ne prouvent pas qu'un combat réel a causé la mort attendue. Les essais
réels effectués et le scénario K.O. puis soin encore à vérifier par l'utilisateur
doivent être consultés dans [verification.md](verification.md), sans confondre
ces trois niveaux de preuve.
