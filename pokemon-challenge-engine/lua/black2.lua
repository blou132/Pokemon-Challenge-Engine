-- Pokémon Noir 2 : préparer d'abord la connexion dans l'application.
-- connect.lua affiché par l'interface convient aussi aux dossiers personnalisés.
local source = debug.getinfo(1, 'S').source:sub(2)
local directory = source:match('^(.*)[/\\]') or '.'
dofile(directory .. '/common/bridge.lua').run(directory .. '/../runtime/bridge/current-black2.lua')
