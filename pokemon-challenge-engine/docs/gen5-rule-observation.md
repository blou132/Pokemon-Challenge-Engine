# Contrôles des règles V0.5

Développement sur `feat/v0.5-challenge-observation`, à partir de `40dc841`.
La base V0.4.1 comporte 1 829 tests historiques. Les premiers lots ajoutent des
contrôles exécutables et des observations persistantes ; ils ne constituent pas
une validation complète des quinze modes sur les quatre jeux.

## Parcours utilisateur

Dans **Mes parties → Nouvelle partie → Challenge personnalisé**, choisir les
règles, leurs paramètres et la seed. Les paramètres restent figés dans chaque
partie. **Détails → Règles** présente les capacités, les résultats actuels et les
écarts historiques. Le **Mode Jeu** montre les contrôles des dernières observations
enregistrées, y compris hors ligne, et le plafond de niveau réellement configuré.
Les membres de l'équipe affichent « Shiny », « Normal » ou « Shiny : inconnu ».

Une présence non conforme dans l'équipe n'est jamais présentée comme une preuve
d'utilisation en combat. « Conforme » porte sur l'observation indiquée, jamais sur
toute l'aventure. Une observation absente ou inexploitable reste inconnue.

Les résultats sont recalculés à partir de `current_party`, `known_pokemon`,
`species_history`, des captures déclarées et des événements `party_changed` déjà
persistés dans `run.json`. Les écarts historiques d'équipe sont dédupliqués dans
la fiche. Le moteur ne réécrit ni les règles, ni les observations anciennes, ni les
sauvegardes Pokémon. Le schéma Run reste compatible avec la V0.4.1. Il n'existe
pas encore d'acquittement séparé des alertes ni de journal automatique des captures.

Les nouvelles observations conservent aussi les changements de forme dans
`species_history`, sans compléter rétroactivement une ancienne entrée. Une forme
inconnue puis lue à 0 avant une évolution transformée permet ainsi de vérifier
le changement d'espèce ultérieur. Un changement de forme seul ne constitue jamais
une évolution. Une capture déclarée avec seulement un nom ou surnom reste
explicitement inconnue pour Species Clause ; elle compte toujours pour les
limites de zone si sa zone est renseignée.

Les identifiants de zone `capture_zone_id`, `zone_id` et l'ancien `id` sont
comparés dans le même espace, sans réécrire les captures historiques.
Des identifiants contradictoires ou absents restent inconnus ; un `map_id`
ou un libellé de dictionnaire ne remplace jamais cet identifiant. Une carte
observée sans zone de capture connue ne conserve pas la zone précédente.
Le formulaire de capture conserve l'identifiant prérempli si la zone n'est pas
modifiée ; un champ vidé signifie explicitement « inconnue ». Les noms saisis
manuellement restent comparés exactement entre eux, sans rapprochement supposé
avec les identifiants. Les captures antérieures sans zone ne sont jamais affectées
rétroactivement à la première zone ensuite observée.

## Couverture des quinze règles

| Règle | Contrôle livré | Limite explicite |
| --- | --- | --- |
| Nuzlocke | Journal manuel des rencontres, captures, K.O. sauvages et fuites ; zone consommée par la première rencontre ordinaire déclarée | Première rencontre réelle et résultats non lus automatiquement ; historique non déclaré inconnu |
| Mort permanente | K.O. avec identité fiable et transition PV positifs → zéro ; cimetière et correction manuelle ; présence d'un mort dans l'équipe signalée | Première observation à zéro/identité ambiguë à confirmer ; utilisation en combat inconnue |
| Species Clause | Espèces répétées signalées ; doublon ignoré justifié seulement par une capture antérieure du journal | Aucun droit de relance déduit de l'équipe ; pas de clause de famille implicite |
| Level Cap | Chaque niveau comparé au plafond figé, écarts historiques conservés | Aucun plafond supposé si l'ancien réglage manque ; aucun blocage du jeu |
| Monotype | Espèces/formes, trois conventions, équipe et individus connus | Types dynamiques en combat inconnus ; données originales inutilisables si types randomisés sans extraction vérifiée |
| No Items | Déclarations/corrections des objets du sac en combat, hors Poké Balls ; alertes persistantes | Vérification manuelle ; aucun lecteur fiable de l’action ni blocage dans le jeu |
| No Healing | Déclarations/corrections des objets et capacités de soin volontaires ; alertes persistantes | Vérification manuelle ; une hausse de PV ne prouve pas un soin interdit |
| No Pokémon Center | Déclarations/corrections du service de soin ; alertes persistantes | Vérification manuelle ; la carte ne prouve pas l’utilisation du service |
| No Evolution | Historique d'espèce d'un individu fiable, chemin évolutif documenté ; déclaration manuelle d'évolution possible | Clones/identités ambiguës exclus ; pas de blocage ROM ; évolutions modifiées sans données vérifiées inconnues |
| Solo Run | Désignation manuelle d'un individu fiable ; comparaison de présence ; déclaration de combat avec un autre individu | Usage en combat non observé, aucune violation déduite de la taille de l'équipe |
| Shiny Only | Critère Gen V PID/OT, présence normale signalée, état inconnu possible | Utilisation en combat inconnue ; taux personnalisé désactivé sans patch validé |
| Randomizer | Transformation externe sur copie, selon le lot dédié | Une règle sélectionnée seule ne prouve aucune modification ; validation émulateur distincte |
| Catch Limit | Comptage des captures déclarées par zone et seuil configuré | Zones inconnues jamais fusionnées ; aucune capture déduite d'un ajout dans l'équipe |
| Starter Only | Starter déclaré manuellement, puis comparaison de présence ; déclaration de combat avec un autre individu | Origine starter déclarative, jamais prouvée par l'espèce ou la place ; usage en combat non observé |
| Unevolved | Espèce au stade initial selon graphe sourcé, y compris espèces sans évolution | Ne prouve pas l'histoire du Pokémon ; graphe modifié non supposé identique |

La Mort permanente fonctionne désormais également seule. Cela applique la règle
déjà choisie dans la partie sans lui ajouter Nuzlocke. Aucun K.O. antérieur n'est
converti rétroactivement en mort : la transition doit être observée pendant le suivi.

### Désignation Starter Only / Solo Run

Dans **Mes parties → fiche de la partie → Règles**, le bouton **Désigner / corriger
l'individu autorisé** permet de choisir un individu de la dernière équipe
enregistrée. Le formulaire exige une confirmation explicite. Il ne sélectionne
jamais automatiquement le premier emplacement ni une espèce de starter. Si
Starter Only est actif, cette déclaration est également utilisée pour Solo Run,
dont il dépend. Une partie classique n'affiche pas cette action.

Seules les identités fortes, enregistrées et non ambiguës sont proposées.
La présence et une évolution documentée peuvent être comparées à la déclaration,
mais l'origine starter et l'utilisation en combat ne sont pas prouvées. Les
résultats restent **À vérifier** ou **Non vérifiable**, sans conformité globale
ni violation de combat. Un autre individu de la même espèce ne remplace pas le
choix. Un clone détecté, une identité faible ou un changement d'espèce sans graphe
individuel vérifié suspend la comparaison. Le départ de l'équipe ne prouve ni la
perte du Pokémon ni son utilisation ailleurs.

Si la forme était inconnue lors de la désignation, les observations fiables
postérieures peuvent établir une chaîne jusqu'à l'individu actuel : par exemple,
même espèce ensuite observée en forme 0, puis évolution documentée. Seules les
observations après cette déclaration sont utilisées. Un maillon faible, dupliqué,
inexploitable ou sans graphe vérifié conserve le résultat inconnu. La déclaration
initiale et les anciennes entrées ne sont pas réécrites.

Correction et retrait ajoutent chacun un événement manuel dans l'historique.
Ils ne modifient pas le snapshot des règles et ne s'appliquent pas rétroactivement
aux anciennes observations. La désignation est propre à la partie ; l'action
nécessite de l'avoir reprise dans PCE. Elle peut être préparée hors ligne à partir
de la dernière équipe enregistrée et elle est revérifiée au moment de l'action.
Voir le [format de stockage](run-storage.md) pour la chaîne de correction.

Les tests de cette désignation utilisent des observations synthétiques et une
interface Qt hors écran. **En attente de validation sur la machine utilisateur**
avec un starter réel, son évolution et une reprise réelle.

## Sources et limites

Le critère shiny utilise le PID et l'ID du **dresseur d'origine**. Dans
[PK5.PSV/TSV](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PK5.cs),
les valeurs sont calculées à partir des deux moitiés du PID et des identifiants
TID/SID. [PKM.IsShiny](https://github.com/kwsch/PKHeX/blob/09e7f18fbb33635e35cf9ffcbfd3322403780f8e/PKHeX.Core/PKM/PKM.cs)
compare ces valeurs ; la formule équivalente employée est
`(PID_hi ^ PID_lo ^ TID ^ SID) < 8`. Les identifiants absents, invalides ou d'une
autre génération ne produisent aucune conclusion. Le seuil 8 correspond au taux
de base 1/8192 pour une génération uniforme, pas à une promesse couvrant les bonus,
rencontres shiny imposées/interdites ou tous les mécanismes de génération.

Les [tables d'espèces et de formes](gen5-species-data.md) distinguent BW et B2W2.
Le [champ de forme Lua](memory-map.md) provient du bloc B déchiffré ; il reste
facultatif pour les scripts antérieurs. La forme inconnue interdit une conclusion
Monotype lorsque les formes documentées ont des types différents.

Aucun offset de combat, d'objet, de soin ou de résultat de capture n'a été ajouté
sans source. Le tampon d'un adversaire ne suffit pas à établir qu'un combat est
en cours, ni comment il s'est terminé. Les [limites de lecture](tracking-sources.md)
restent applicables. Les combinaisons appliquent les restrictions simultanément :
un plafond Catch Limit supérieur à un n'annule jamais le droit de première
rencontre Nuzlocke ; Shiny Only n'accorde aucun droit de relance shiny implicite.
Les restrictions d'usage en combat Solo Run/Starter Only n'interdisent pas à elles
seules des captures de compagnons. Aucune ancienne partie n'est réécrite.

## Vérifications

Les tests synthétiques couvrent les bornes shiny 7/8, les identités manquantes,
les trois conventions Monotype, les formes, les changements d'espèce ambigus,
le plafond, la relecture après autosave, les alertes historiques, les déclarations
manuelles, les états hors ligne et les historiques anciens inexploitables.
Ils ne prouvent pas un combat ou une capture dans un vrai jeu.

Essai réel Blanc FR rev0 du 13 octobre 2026 : lancement et reprise avec les
services PCE, DeSmuME réel et autoload du Lua 0.5.0, sur copies indépendantes de la
ROM et d'un DSV explicitement importé. Les trois Pokémon observés sont :

| Espèce | Niveau | PV | Forme | Shiny | Monotype Feu souple | Plafond 20 | Stade initial |
| --- | ---: | --- | ---: | --- | --- | --- | --- |
| 511 | 20 | 53/53 | 0 | Non | Non conforme | Conforme | Oui |
| 535 | 16 | 44/44 | 0 | Non | Non conforme | Conforme | Oui |
| 499 | 23 | 79/79 | 0 | Non | Conforme | Dépassement | Non |

Les résultats sont conservés après fermeture normale et rechargement de la même
partie, avec deux sessions et environ 18,2 secondes suivies. Un slot réel et un
backup ont été créés dans le dossier de test. Les huit sources surveillées
(deux ROM, deux DSV, DeSmuME, son INI et deux DLL Lua) gardent leur SHA-256, taille
et date de modification. Preuve locale exclue de Git :
`runtime/iso12/v05a1/report.json` à la racine du dépôt.

Ce test valide le classement **normal** des individus observés, pas une rencontre
shiny, une forme alternative, une évolution, un K.O., un objet ou une capture.
Il passe par les services et un harnais Lua de boutons, pas par un parcours souris
intégral. Lors de ce lot du 13 octobre, l'équipe de Noir 2 n'était pas encore
validée réellement. Le [test melonDS du 22 octobre](v0.5-melonds-validation.md#lecture-réelle-noir-2-fr-rev0-22-octobre-2026)
a depuis confirmé la lecture de Gruikui, niveau 5, 22/22 PV ; il ne valide pas
tous les contrôles de règles. Noir et Blanc 2 : aucun nouvel essai réel de ce lot.
**En attente de validation sur la machine utilisateur.**


### Réutilisation des données effectives en mémoire

Le fournisseur de transformation expose un `TransformationSnapshot` immuable :
les copies entre le worker et les vues réutilisent ses données et ses tables
validées. Le moteur vérifie encore à chaque évaluation le jeu, la génération,
le SHA de ROM et les catégories configurées. Les cinq fichiers de provenance
restent contrôlés à chaque appel du fournisseur ; toute signature modifiée
impose une nouvelle validation. Les anciens contextes dictionnaires restent
acceptés et sont revalidés à chaque évaluation. Aucun format persistant ne change.

Mesure du 21 octobre 2026, lecture seule d'une partie Blanc FR dérivée, 667 lignes,
un Pokémon et quatre règles (Randomizer, Monotype, Shiny Only, Level Cap),
100 répétitions par opération sans profiler : copie de transformation
15,95 → 0,001 ms, fournisseur déjà chargé 29,78 → 9,48 ms, préparation des tables
6,97 → 0,021 ms, évaluation 9,51 → 0,095 ms. Le run actif a gagné quatre événements
entre les deux mesures (35 → 39) ; ce sont des mesures locales indicatives,
pas une mesure de latence de jeu ou du build distribué. La vérification froide
et les contrôles anti-liens des chemins restent effectués.

## Déclarations d'objets et de soins — 27 octobre 2026

**Règles → Déclarer / corriger une action** et **Mode Jeu → Actions manuelles**
ouvrent le même formulaire. La sélection distingue un objet du sac en combat, un
objet de soin en/hors combat, une capacité de soin volontaire et le Centre Pokémon.
Un objet de soin en combat concerne simultanément No Items et No Healing si ces
règles sont actives. Les Poké Balls, objets tenus et soins scénarisés ne sont pas
reclassés comme violations de ces conventions.

L'action est explicitement confirmée par le joueur et affichée comme
**Vérification manuelle**. L'écart déclaré reste consultable après fermeture et
reprise. Correction et retrait exigent une raison et conservent l'événement
original. Aucune déclaration ne modifie la RAM, la ROM, les sauvegardes Pokémon
ou les paramètres figés de la partie. Une absence de déclaration ne démontre
jamais une partie conforme. Voir le [format de stockage](run-storage.md).

Le tracker de rencontre ne transforme plus un adversaire à zéro PV en résultat
`fainted`. Seul un résultat explicitement fourni peut conclure ; un combat terminé
sans résultat reste inconnu. Cette correction concerne aussi la première lecture
à zéro PV et les journaux de plusieurs observations entre deux rafraîchissements.
Le suivi des transitions individuelles d'équipe pour Mort permanente reste séparé.

Vérifications : tests synthétiques de déclaration, combinaisons, reprise,
correction, rejet de fausse source automatique, et parcours Qt hors écran.
Ces tests ne constituent pas une validation d'événements natifs en jeu.

## Journal des rencontres et combinaisons — 2 novembre 2026

Le formulaire commun permet aussi de déclarer une rencontre avec son espèce,
sa zone, son type et son résultat : capturé, adversaire K.O., fuite du joueur,
fuite de l'adversaire, résultat inconnu ou doublon ignoré. Il permet de déclarer
un combat avec un autre individu que celui autorisé, un combat avec un Pokémon
non shiny et une évolution. Ces informations restent **manuelles**, même
quand elles produisent une alerte non conforme.

La première rencontre sauvage ordinaire du journal consomme la zone, y compris
si son résultat est inconnu. Une capture ordinaire déclarée ensuite dans la
même zone produit un écart Nuzlocke. Species Clause autorise une relance déclarée
uniquement si la même espèce a déjà été capturée à un emplacement antérieur du
journal ; cette relance ne rouvre pas une zone consommée. Une espèce capturée
plus tard ne justifie pas rétroactivement un doublon. Une correction conserve
la place de l'action originale pour cette analyse ; l'historique conserve aussi
la date réelle et la raison de la correction.

Les rencontres spéciales, cadeaux, statiques, œufs et rencontres scénarisées
restent à examiner selon la convention du joueur, séparément de la première
rencontre sauvage ordinaire. Leurs captures comptent pour Catch Limit. Les
anciennes captures sans type de rencontre restent à vérifier : le moteur ne
leur invente pas un contexte sauvage. Zones inconnues, identifiants
contradictoires et historique incomplet ne prouvent jamais un droit disponible.

Une capture déclarée dans ce formulaire figure dans les compteurs de la
bibliothèque, de la fiche et du Mode Jeu. Ne pas la saisir également avec
« Ajouter une capture ». Corriger ou retirer la déclaration recalcule ces
compteurs sans supprimer les événements initiaux ni créer de capture dans la
RAM ou la sauvegarde du jeu.

Les combinaisons demandées sont testées dans le moteur de préparation pour les
quatre identifiants Gen V, avec conservation des paramètres et dépendances.
Les tests de services écrivent et relisent des dossiers de parties temporaires ;
les tests Qt traversent le formulaire, le worker propriétaire et les compteurs.
Ce sont des validations de logiciel sur données synthétiques, **pas** des preuves
de lecture native de captures, fuites, objets ou soins. Les niveaux de suivi
du tableau restent applicables ; aucune de ces restrictions n'est imposée au jeu.
