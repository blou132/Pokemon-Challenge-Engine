# Premier démarrage — V0.3.6

Au premier lancement de PCE, **Installation & diagnostic** recherche les installations RetroBat et DeSmuME connues, les jeux Nintendo DS locaux et leurs sauvegardes. L'assistant peut être rouvert depuis **Paramètres** ou le **Mode Jeu**. Les six pages historiques restent disponibles.

## Préparer votre jeu

1. Laissez la recherche se terminer. Si l'installation n'est pas trouvée, utilisez **Autre dossier**, **Choisir DeSmuME** ou **Ajouter un jeu**. Aucun scan récursif de tout le disque n'est nécessaire.
2. Vérifiez les propositions. Une installation ou une sauvegarde ambiguë demande un choix explicite. Une archive contenant plusieurs ROM demande aussi de choisir le fichier voulu. Vous pouvez sélectionner **Continuer sans sauvegarde associée** ; cela ne supprime aucun fichier.
3. Cliquez sur **Préparer et enregistrer**. Une ROM `.zip` locale est préparée dans le cache de PCE, sans remplacer ni déplacer l'archive originale. Son identité est vérifiée depuis son en-tête, puis le profil de lancement est renseigné.
4. Si le support Lua demande une réparation, utilisez **Réparer l'installation**. Le dialogue explique l'installation dans le dossier DeSmuME et demande confirmation. Si des fichiers Lua différents existent déjà, une **seconde confirmation** énumère les fichiers à remplacer ; une copie de sauvegarde précède leur remplacement.
5. Lorsque les contrôles autorisent le lancement, cliquez sur **Jouer**. PCE revérifie l'environnement en arrière-plan, lance DeSmuME puis prépare une nouvelle connexion Lua.

Seule la dépendance Lua officielle et épinglée peut être téléchargée. PCE ne télécharge jamais de ROM ni de sauvegarde. Les méthodes de détection, empreintes, formats d'archives et limites sont décrits dans [auto-setup.md](auto-setup.md) et [lua-runtime.md](lua-runtime.md).

**Détails techniques**, replié par défaut, présente les chemins détectés, identités, empreintes, actions et erreurs disponibles. Ces informations restent locales. La recherche, les téléchargements, l'extraction et le diagnostic de lancement s'exécutent hors du thread graphique : l'interface reste réactive. La fermeture attend la fin d'une opération engagée ; PCE ne tue pas un téléchargement ou une copie au milieu d'une écriture.

## Terminer la connexion Lua

La V0.3.6 prépare le script, mais conserve l'étape de chargement dans DeSmuME :

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

Les profils de lancement historiques restent utilisables selon leur ancien parcours. Pour bénéficier de la vérification complète avant lancement et de la préparation automatique de Lua, préparez une fois leur jeu depuis Installation & diagnostic.

## Automatique, assisté ou manuel

| Opération | Comportement |
| --- | --- |
| Détection des installations, jeux, INI et sauvegardes | Automatique, dans les emplacements bornés et configurés |
| Sélection parmi plusieurs candidats | Manuelle et explicite |
| Préparation d'une archive locale et remplissage du profil | Automatique après **Préparer et enregistrer** |
| Installation de Lua | Assistée, avec confirmation préalable ; remplacement confirmé séparément |
| Revérification d'un jeu préparé et création de la session Lua | Automatiques lors de **Jouer** |
| Chargement du nouveau script puis **Run** dans DeSmuME | Manuel |
| Validation de la connexion, équipe et zone | À partir des messages effectivement reçus et des lecteurs disponibles |
| Pilotage réel x2/x4 et détection des captures réelles | Limites V0.3.5/V0.3 inchangées ; aucun succès déduit de l'assistant |

## Vérifications UI

Les tests de l'assistant utilisent des installations, réponses de diagnostic et messages Lua synthétiques. Ils couvrent les ambiguïtés, confirmations, erreurs de permissions, maintien de la réactivité, nettoyage, préflight avant lancement et non-régression des pages existantes. Les tests de récupération utilisent les vrais services de session sur des dossiers temporaires, sans émulateur réel.

Ces essais ne remplacent pas une validation du jeu. La preuve réelle existante de Pokémon Blanc français rev0 concerne ce jeu et cet échantillon uniquement ; elle ne s'étend pas automatiquement à Noir, Noir 2 ou Blanc 2. Les essais réels de la V0.3.6 et leurs limites sont consignés dans [verification.md](verification.md).
