# Premier démarrage — V0.4.1

PCE s'ouvre sur **Mes parties** et lance automatiquement une recherche locale en
arrière-plan. RetroBat, DeSmuME, Lua, les jeux Nintendo DS, l'INI et les sauvegardes
sont recherchés dans des emplacements bornés. **Installation & diagnostic** est
une vue d'état accessible depuis **Paramètres** ou le **Mode Jeu** ; son ouverture
n'est pas nécessaire pour préparer une installation simple.

## Préparer votre jeu

1. Laissez la recherche se terminer. Chaque jeu indique **Prêt**, **Jeu non trouvé**
   ou l'action nécessaire. Une installation DeSmuME valide unique est sélectionnée,
   et un ZIP simple est préparé dans le cache sans toucher à son original.
2. Si Blanc est prêt et les autres jeux absents, vous pouvez jouer à Blanc. Aucun
   chemin n'est demandé pour les jeux que vous ne possédez pas. Un jeu absent invite
   à ajouter une copie locale à la bibliothèque RetroBat.
3. Dans **Mes parties → Nouvelle partie**, choisissez classique, modèle ou challenge
   personnalisé. Le premier jeu prêt est proposé lorsqu'aucun jeu n'a été demandé.
   Sa sauvegarde détectée à forte confiance est préremplie ; vous pouvez la changer
   ou ne lier aucun fichier. La création conserve les données choisies, sans créer
   de sauvegarde Pokémon ni déplacer l'original.
4. Si **Support Lua requis** apparaît, ouvrez **Installation & diagnostic →
   Installer automatiquement le support Lua**. Le dialogue demande confirmation
   avant cette installation externe. Une DLL différente demande une seconde
   confirmation et un backup. Un support Lua déjà conforme ne demande rien.
5. Cliquez **Jouer**. PCE vérifie seulement cette partie, prépare sa session Lua et
   son loader, puis lance DeSmuME. L'activation initiale de l'autoload officiel sur
   le build reconnu garde son accord mémorisé ; la connexion n'est confirmée que
   par les messages reçus du jeu.

Lorsque plusieurs installations, ROM ou sauvegardes sont crédibles, le diagnostic
présente le choix nécessaire. Une archive contenant plusieurs ROM exige aussi un
choix. Une fois les choix résolus, la préparation est automatique. L'absence de
sauvegarde existante n'est pas une erreur pour une nouvelle partie ; un ancien fichier associé
mais introuvable nécessite en revanche une vérification.

**Paramètres → Afficher les chemins manuels · Avancé** conserve la saisie des
chemins et **Relancer la détection**. Dans le diagnostic, **Choix manuels · Avancé**
contient **Autre dossier**, **Choisir DeSmuME** et **Ajouter un jeu**. Les choix
explicites valides ne sont pas remplacés au prochain démarrage. Le bouton historique
**Tester les chemins** n'apparaît pas dans le parcours normal.

Seule la dépendance Lua officielle et épinglée peut être téléchargée après accord.
PCE ne télécharge jamais de ROM, jeu, BIOS ou sauvegarde. Les méthodes de détection,
empreintes, formats d'archives et limites sont décrits dans [auto-setup.md](auto-setup.md)
et [lua-runtime.md](lua-runtime.md).

**Détails techniques**, replié par défaut, présente les chemins détectés, identités, empreintes, actions et erreurs disponibles. Ces informations restent locales. La recherche, les téléchargements, l'extraction et le diagnostic de lancement s'exécutent hors du thread graphique : l'interface reste réactive. La fermeture attend la fin d'une opération engagée ; PCE ne tue pas un téléchargement ou une copie au milieu d'une écriture.

## Connexion Lua automatique ou de secours

Après activation de l'autoload, les lancements compatibles suivants chargent le
loader avec le jeu. Si le mode manuel a été choisi ou si l'autoload est indisponible,
le script courant reste accessible :

1. Dans la page **Connexion DeSmuME**, cliquez sur **Copier le chemin du script**.
2. Dans DeSmuME : **Tools → Lua Scripting → New Lua Script**.
3. Utilisez **Browse**, collez le chemin puis cliquez sur **Run**.

**Ouvrir le dossier du script** permet également de retrouver le fichier sans naviguer dans les dossiers techniques. La copie dans le presse-papiers et l'ouverture du dossier ne se font que sur ces clics explicites. Aucune suite de clics ou de touches n'est injectée dans DeSmuME.

La connexion n'est confirmée qu'à réception des messages du jeu. Des fichiers Lua vérifiés sur disque ne prouvent pas que la console les a chargés. « Prêt à lancer » ne signifie pas non plus que la partie a déjà démarré ou que l'équipe a été reçue.

## Reprendre une connexion interrompue

Quand Lua est déconnecté, **Reconnecter** arrête l'ancienne session PCE et prépare un nouveau script. L'ancien dossier reçoit un marqueur d'arrêt ; le chemin du nouveau script remplace l'ancien. Il faut charger ce nouveau script dans DeSmuME, puis cliquer sur **Run**. PCE ne réutilise pas silencieusement une session arrêtée.

Pour changer de jeu, utilisez **Arrêter et changer de jeu**. Une confirmation précède l'arrêt de la session Lua ; le sélecteur redevient disponible après l'arrêt. Si le Mode Jeu suit encore un processus DeSmuME en cours, fermez sa fenêtre avant de lancer un autre jeu. Arrêter Lua ne ferme pas l'émulateur et ne modifie pas la sauvegarde.

## Stockage et réparations

L'onglet **Stockage local PCE** indique la taille des ROM extraites, du cache de téléchargement et des anciennes sessions Lua arrêtées. Chaque nettoyage demande confirmation. Il porte uniquement sur les fichiers reconnus comme gérés par PCE ; les profils, originaux et backups ne sont pas inclus. Une session Lua active est transmise au service pour exclusion du nettoyage.

En cas d'accès refusé, de fichier déplacé ou de configuration modifiée, le message d'erreur reste visible. Corrigez le problème ou choisissez un autre chemin, puis relancez la recherche. Aucun succès n'est affiché après un échec. Les contrôles de lancement échoués renvoient vers l'installation au lieu de lancer le jeu concerné.

Les profils de lancement historiques restent utilisables. La découverte reprend
leurs chemins valides ; les références des parties existantes restent distinctes.
Une vérification légère réutilise le rapport tant que les fichiers, dossiers et
préférences connus ne changent pas. Elle est relancée à l'ouverture de **Mes parties**
et après les modifications de configuration ou l'installation Lua. Il n'y a pas
de scan récursif permanent du PC.

## Automatique, assisté ou manuel

| Opération | Comportement |
| --- | --- |
| Détection des installations, jeux, INI et sauvegardes | Automatique, dans les emplacements bornés et configurés |
| Sélection parmi plusieurs candidats | Manuelle et explicite |
| Préparation d'une archive locale et remplissage du profil | Automatique si les choix sont uniques ; sinon après résolution de l'ambiguïté |
| Sauvegarde existante | Sélection automatique d'un candidat unique à forte confiance ; choix explicite en cas d'ambiguïté |
| Installation de Lua | Assistée, avec confirmation préalable ; remplacement confirmé séparément |
| Revérification d'un jeu préparé et création de la session Lua | Automatiques lors de **Jouer** |
| Chargement Lua avec **Jouer** | Autoload sur le build reconnu après accord mémorisé ; chargement manuel en secours |
| Validation de la connexion, équipe et zone | À partir des messages effectivement reçus et des lecteurs disponibles |
| Pilotage réel x2/x4 et détection des captures réelles | Limites V0.3.5/V0.3 inchangées ; aucun succès déduit de l'assistant |

## Vérifications UI

Les tests de l'assistant utilisent des installations, réponses de diagnostic et messages Lua synthétiques. Ils couvrent les ambiguïtés, confirmations, erreurs de permissions, maintien de la réactivité, nettoyage, préflight avant lancement et non-régression des pages existantes. Les tests de récupération utilisent les vrais services de session sur des dossiers temporaires, sans émulateur réel.

Ces essais ne remplacent pas une validation du jeu. Les preuves réelles antérieures
de Blanc FR rev0 concernent leurs échantillons et parcours observés ; elles ne
s'étendent ni aux autres jeux ni automatiquement au nouvel enchaînement de découverte.
Les résultats et limites de chaque essai sont consignés dans
[verification.md](verification.md).
