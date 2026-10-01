-- Lectures Gen V documentées, sans écriture RAM ni commande de jeu.
-- Le jeu, la langue et la révision doivent correspondre avant toute lecture.
-- Les profils livrés ne documentent pas encore le cycle d'un combat : un
-- tampon de Pokémon ennemi ne prouve ni combat actif ni rencontre sauvage.
local M = {}

local function integer(value, minimum, maximum)
    return type(value) == "number" and value == math.floor(value)
        and value >= minimum and value <= maximum
end

local function byte(memory, address)
    local result = memory.readbyte(address)
    if not integer(result, 0, 255) then error("Octet RAM illisible") end
    return result
end

local function failure(status, message)
    return {status = status, message = message}
end

function M.read_observation(memory, identity, profile)
    if type(memory) ~= "table" or type(memory.readbyte) ~= "function" then
        return failure("invalid_data", "API memory.readbyte absente")
    end
    if type(identity) ~= "table" or type(profile) ~= "table"
        or identity.game_id ~= profile.game_id
        or identity.game_code ~= profile.game_code
        or identity.game_region ~= profile.region
        or identity.rom_revision ~= profile.revision then
        return failure("unsupported", "Identite incompatible avec le profil de suivi")
    end
    if profile.map_id_size ~= 2
        or not integer(profile.map_id_address, 0x02000000, 0x023FFFFE)
        or type(profile.game_code) ~= "string" or #profile.game_code ~= 4
        or not integer(profile.revision, 0, 255) then
        return failure("unsupported", "Adresse de carte non documentee pour ce jeu")
    end
    local ok, result = pcall(function()
        -- Vérifier de nouveau l'en-tête réel : un appelant utilisant l'identité
        -- d'une ancienne session ne peut pas choisir les adresses d'un autre jeu.
        for index = 1, 4 do
            if byte(memory, 0x027FFE0B + index) ~= profile.game_code:byte(index) then
                return failure("unsupported", "Jeu reel incompatible avec le profil de suivi")
            end
        end
        if byte(memory, 0x027FFE1E) ~= profile.revision then
            return failure("unsupported", "Revision reelle incompatible avec le profil de suivi")
        end
        local address = profile.map_id_address
        local low, high = byte(memory, address), byte(memory, address + 1)
        local map_id = low + high * 256
        -- Écarter une transition intervenue au milieu de l'échantillon.
        if low ~= byte(memory, address) or high ~= byte(memory, address + 1) then
            return failure("invalid_data", "Carte modifiee pendant la lecture")
        end
        local observation = {status = "ok", map_id = map_id}
        local zones = profile.capture_zones
        local zone = type(zones) == "table" and zones[tostring(map_id)] or nil
        if type(zone) == "table" and type(zone.capture_zone_id) == "string"
            and #zone.capture_zone_id > 0 and type(zone.zone_name) == "string"
            and #zone.zone_name > 0 then
            observation.capture_zone_id = zone.capture_zone_id
            observation.zone_name = zone.zone_name
        end
        -- battle_active, battle_type, encounter_kind, battle_id, species_id,
        -- level, hp, max_hp, encounter_slot et outcome restent nil. Le bridge
        -- les sérialise en null, jamais en false ou en valeurs supposées.
        return observation
    end)
    if ok then return result end
    return failure("invalid_data", "Lecture de la carte impossible")
end

return M
