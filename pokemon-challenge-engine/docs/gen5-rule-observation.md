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

## Couverture des quinze règles

| Règle | Contrôle livré | Limite explicite |
| --- | --- | --- |
| Nuzlocke | Déclarations de captures groupées par zone, dépassement à vérifier | Première rencontre, fuite et capture vers le PC non lues automatiquement |
| Mort permanente | K.O. avec identité fiable et transition PV positifs → zéro ; cimetière et correction manuelle ; présence d'un mort dans l'équipe signalée | Première observation à zéro/identité ambiguë à confirmer ; utilisation en combat inconnue |
| Species Clause | Espèces répétées parmi les captures déclarées signalées | Ni rencontre ni droit de relance déduit de l'équipe ; pas de clause de famille implicite |
| Level Cap | Chaque niveau comparé au plafond figé, écarts historiques conservés | Aucun plafond supposé si l'ancien réglage manque ; aucun blocage du jeu |
| Monotype | Espèces/formes, trois conventions, équipe et individus connus | Types dynamiques en combat inconnus ; données originales inutilisables si types randomisés sans extraction vérifiée |
| No Items | Capacité explicitement indisponible | Aucun lecteur fiable de l'action « utiliser un objet du sac en combat » |
| No Healing | Capacité explicitement indisponible | Une hausse de PV ne suffit pas à identifier un soin interdit |
| No Pokémon Center | Capacité explicitement indisponible | Une carte de Centre Pokémon ne prouve pas l'utilisation du service |
| No Evolution | Historique d'espèce d'un individu fiable, chemin évolutif documenté | Clones/identités ambiguës exclus ; pas de blocage ROM ; évolutions modifiées sans données vérifiées inconnues |
| Solo Run | Désignation manuelle d'un individu fiable ; comparaison de présence ; plusieurs membres signalés | Usage en combat inconnu, aucune violation déduite de la taille de l'équipe |
| Shiny Only | Critère Gen V PID/OT, présence normale signalée, état inconnu possible | Utilisation en combat inconnue ; taux personnalisé désactivé sans patch validé |
| Randomizer | Transformation externe sur copie, selon le lot dédié | Une règle sélectionnée seule ne prouve aucune modification ; validation émulateur distincte |
| Catch Limit | Comptage des captures déclarées par zone et seuil configuré | Zones inconnues jamais fusionnées ; aucune capture déduite d'un ajout dans l'équipe |
| Starter Only | Starter déclaré manuellement, puis comparaison de présence avec son identité fiable | Origine starter déclarative, jamais prouvée par l'espèce ou la place ; usage en combat inconnu |
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
restent applicables. Les clauses de combinaison non encore définies conservent
les conflits historiques du catalogue ; aucune ancienne partie n'est réécrite.

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
intégral. Noir 2 : équipe toujours non validée réellement. Noir et Blanc 2 : aucun
nouvel essai réel de ce lot. **En attente de validation sur la machine utilisateur.**
