# Mes parties — V0.4.1

Une **partie (run)** représente une aventure persistante. Un **profil** reste une
configuration de challenge réutilisable. Plusieurs parties du même jeu peuvent
coexister ; une seule reçoit le suivi actif à la fois.

## Créer une partie

Dans **Mes parties → Nouvelle partie**, choisissez le jeu et une source :

- **Partie classique** : zéro règle, aucun paramètre de challenge à remplir.
- **Utiliser un profil existant** : son nom et ses règles sont affichés avant
  d'être copiés dans la partie.
- **Configurer un challenge** : **Configurer les règles** ouvre le même éditeur
  et le même moteur que la page Nouveau challenge. Preset, règles obligatoires,
  possibles ou interdites, nombre de règles en mode aléatoire, seed et paramètres
  existants sont disponibles. Monotype, Level Cap et Catch Limit ne montrent
  leurs paramètres que lorsqu'ils sont actifs. Leur présence dans l'éditeur
  n'ajoute aucune application stricte dans le jeu.

**Utiliser cette configuration** valide les contraintes avec le moteur existant.
Un aperçu déjà à jour est conservé exactement ; un aperçu périmé est régénéré
avec les réglages courants. Le résultat revient dans la fenêtre de création,
où vous confirmez le nom et les références. Annuler l'éditeur conserve la
configuration précédente. Changer de jeu invalide un challenge personnalisé
préparé pour l'autre jeu.

Une configuration directe crée un `rules_snapshot` complet, avec
`profile_id = null` : aucun profil intermédiaire n'est écrit. La seed et le
preset d'origine restent conservés dans le snapshot et la partie.

Choisissez ensuite le nom et, facultativement, la sauvegarde Pokémon liée.
Le champ de sauvegarde commence vide. **Utiliser la sauvegarde configurée**
permet de reprendre explicitement la référence existante ; **Choisir** permet
de désigner un autre fichier. Aucun fichier n'est copié ni créé par ce choix.
L'environnement de lancement enregistré pour ce jeu est proposé. Sans
environnement prêt, la partie peut être créée mais son lancement nécessite
**Installation & Diagnostic**.

Après l'écriture atomique et la relecture réussies, **Mes parties** affiche
immédiatement la nouvelle carte, son compteur mis à jour et **Partie créée**.
La carte est mise en évidence. Si les filtres précédents la masquaient, ils
sont réinitialisés avec une indication ; les filtres compatibles sont gardés.
Il n'est pas nécessaire de cliquer sur Actualiser.

Depuis **Profils → Commencer une partie**, le profil sélectionné est proposé.
Les règles, leurs paramètres et la seed sont copiés dans `rules_snapshot`.
Modifier ensuite le profil ne modifie pas la partie créée. La progression
historique V0.3 du profil est conservée dans son stockage et n'est pas fusionnée
automatiquement avec une nouvelle partie.

Une partie **Classique** possède zéro règle active. Elle conserve néanmoins
ses sessions, son temps suivi, son équipe observée, sa zone, ses notes et ses
événements manuels. Créer une partie PCE ne crée pas une nouvelle sauvegarde
Pokémon et ne redémarre pas le jeu : choisissez explicitement le fichier `.dsv`
à utiliser. Deux parties liées au même fichier partagent cette sauvegarde du
jeu, mais leurs progressions PCE restent distinctes.

## Retrouver et reprendre

La bibliothèque affiche des cartes et permet de combiner recherche par nom,
génération, jeu, challenge et statut. Les tris disponibles portent sur la
dernière session, la création, le nom et le temps suivi.

**Reprendre** sélectionne l'identifiant existant, restaure sa configuration et
prépare le Mode Jeu avec le contrôle de l'environnement V0.3.6. Cette action ne
crée pas une nouvelle partie. Un changement de partie suivie est explicite ;
une connexion d'un autre jeu ne doit pas alimenter la progression actuelle.

L'ouverture du Mode Jeu attend la confirmation de l'activation demandée. Le
UUID demandé, celui du contrôleur et celui de `runs/active.json` doivent
correspondre. Une incohérence affiche **La partie active ne correspond pas à
celle demandée** ; elle ne permet pas de continuer silencieusement avec
l'ancienne partie. Nom, temps, équipe, zone, événements et compteurs de la
nouvelle partie ne sont pas repris de la précédente.

Si l'émulateur ou Lua suit encore une autre partie, la nouvelle partie reste
enregistrée et visible dans la bibliothèque. Fermez la session précédente puis
reprenez la nouvelle carte ; l'ancien Mode Jeu ne s'ouvre pas au nom de la
nouvelle partie. Les réponses asynchrones d'une demande devenue ancienne ne
peuvent pas remplacer la sélection demandée. Après fermeture et réouverture
de PCE, la sélection persistante est retrouvée sans ouvrir automatiquement le
Mode Jeu ni lancer l'émulateur.

Statuts : **Préparation**, **En cours**, **Terminée**, **Abandonnée**, **Archivée**.
Le statut peut être modifié depuis la fiche après confirmation. Pour reprendre
une partie terminée, abandonnée ou archivée, remettez-la explicitement en
préparation ou en cours. Aucun statut « partie perdue » n'est déduit.

## Fiche détaillée

| Section | Contenu |
| --- | --- |
| Aperçu | Jeu, génération, règles, statut, dates, temps suivi et notes |
| Progression | Badges manuels, captures manuelles, morts, zone et cimetière virtuel |
| Équipe | Dernière équipe observée, espèce, niveau, PV et statut vivant/mort PCE |
| Règles | Règles copiées et snapshot exact accessible dans les détails techniques |
| Historique | Chronologie lisible, avec source automatique, manuelle ou système |
| Sauvegardes | Fichier Pokémon lié et accès au gestionnaire de sauvegardes existant |

À l'ouverture de **Sauvegardes**, le dernier backup enregistré est recherché
dans le manifeste existant, pour le chemin exact du fichier lié. Deux
sauvegardes du même jeu, même si elles portent le même nom dans deux dossiers,
ne sont pas confondues. Cette consultation n'écrit aucun fichier.

Une valeur inconnue affiche **Non renseigné**. Le nombre de captures n'est pas
déduit d'un agrandissement de l'équipe ni de l'apparition d'une espèce. Les
badges restent une saisie **MANUELLE**. Le temps affiché est celui des sessions
suivies par PCE, et non la durée enregistrée à l'intérieur du jeu.

## Actions et cimetière

Les captures, morts et notes disposent d'un formulaire. Pour une mort, la
sélection d'un individu connu conserve son identité technique ; saisir un nom
libre crée une déclaration manuelle sans attribuer arbitrairement un individu
de même espèce. Le PID brut n'est pas affiché dans les cartes, l'équipe ou la
chronologie principale.

Les observations de K.O. nécessitant vérification apparaissent dans la fiche.
**Vérifier / confirmer la mort sélectionnée** ouvre une saisie manuelle
préremplie. La confirmation d'un nom sans identité fiable inscrit la mort dans
le cimetière virtuel ; elle ne rend pas fiable l'identification automatique du
Pokémon dans les observations suivantes.

**Annuler / corriger une mort** exige une confirmation. La mort corrigée ne
compte plus dans le cimetière actif, mais son événement d'origine et la
correction restent dans l'historique. Un mort confirmé avec identité stable
reste mort dans PCE après un soin ou son départ de l'équipe. Aucun déplacement
vers une boîte PC ni aucune écriture dans le jeu n'est effectué.

## Sauvegardes distinctes

La progression PCE est sauvegardée automatiquement dans le stockage persistant
des parties. Le fichier `.dsv` est une référence séparée. Le gestionnaire
existant conserve ses confirmations de restauration et ses contrôles de
fermeture de DeSmuME. PCE ne force aucune sauvegarde en jeu.

Les boutons rapides du Mode Jeu utilisent les mêmes formulaires. La V0.4.1
prépare l'autoload Lua avec **Jouer** lorsqu'il a été accepté pour un
environnement compatible. Le mode manuel reste disponible si cette préparation
est impossible ou n'a pas été activée. Le statut connecté exige toujours un
message réellement reçu. Le fonctionnement et les limites de l'autoload sont
décrits dans [desmume-bridge.md](desmume-bridge.md).

Les détails techniques de persistance et de récupération sont décrits
dans [run-storage.md](run-storage.md) et [run-autosave.md](run-autosave.md) ; les
limites de détection dans [permanent-death.md](permanent-death.md).

## Vérification de l'interface

Les tests Qt utilisent des parties synthétiques sur un stockage temporaire :
bibliothèques de 0, 1 et 20 parties, recherche, filtres, tris, reprise d'un UUID
existant, six sections, saisie manuelle, confirmation de correction et de
statut, observations à vérifier, identité conservée ou explicitement inconnue.
Les tailles 1366×768 et 1920×1080 sont couvertes ; les listes restent
défilantes. Ces vérifications d'interface ne constituent pas une validation
réelle d'une mort survenue dans un combat Pokémon.

Les régressions V0.4.1 couvrent aussi les trois sources de création, les règles
personnalisées indépendantes des profils, les paramètres actifs, la seed et les
presets conservés, l'annulation, les changements de jeu, la référence de
sauvegarde explicitement choisie, l'apparition immédiate de la carte et les
filtres qui pouvaient cacher la nouvelle partie. Les tests du contrôleur
vérifient séparément l'ordre d'activation et le passage exact de la partie A
à la partie B.
