# Pokemon Challenge Engine — V0.2

Le code de l'application, les tests et la documentation sont dans
[`pokemon-challenge-engine/`](pokemon-challenge-engine/README.md).

Pour lancer avec l'environnement déjà préparé dans cet espace de travail :

```powershell
cd .\pokemon-challenge-engine
..\.venv\Scripts\python.exe -m app.main
```

La V0.2 ajoute une passerelle DeSmuME/Lua locale en lecture seule et une page de
connexion. La préparation des challenges Noir / Noir 2, les profils locaux,
la roue Monotype et le launcher de la V0.1 sont conservés. Aucune règle n'est
encore imposée dans le jeu ; les ROM et sauvegardes ne sont pas modifiées.

Le transport réel et l'identification de Noir 2 français (`IREF`, révision `0`)
ont été vérifiés, ainsi que la déconnexion, la reprise et l'arrêt de la passerelle.
Pour la lecture d'équipe, des niveaux et des PV :
**En attente de validation sur la machine utilisateur.** Les tests sur mémoire synthétique ne constituent pas
une validation sur une partie réelle.

Application et scripts : `0.2.0` ; format des profils conservé : `0.1.0` ;
protocole Lua : `1`.

[Installation et utilisation](pokemon-challenge-engine/README.md) ·
[Connexion DeSmuME](pokemon-challenge-engine/docs/desmume-bridge.md) ·
[Sources mémoire](pokemon-challenge-engine/docs/memory-map.md) ·
[Vérifications réalisées](pokemon-challenge-engine/docs/verification.md)
