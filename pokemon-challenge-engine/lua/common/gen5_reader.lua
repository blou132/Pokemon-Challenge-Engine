-- Décodeur d'équipe de cinquième génération, en lecture seule.
-- Les adresses propres au jeu proviennent du profil data/memory_profiles.json.
-- Les sources et les limites des révisions sont consignées dans ces profils.
-- Compatible Lua 5.1, sans bibliothèque externe d'opérations binaires.
local M = {}

local HEADER_ADDRESS = 0x027FFE00 -- Copie RAM de l'en-tête dans NDSSystem.cpp de DeSmuME.
local PARTY_BYTES = 220
local STORED_BYTES = 136
local GROWTH_POSITIONS = {
    0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3,
    1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3,
}
local REGIONS = {F = "FR", O = "EN", D = "DE", I = "IT", J = "JP", K = "KO", S = "ES"}

local function integer(value, minimum, maximum)
    return type(value) == "number" and value == math.floor(value)
        and value >= minimum and value <= maximum
end

local function byte(readbyte, address)
    local value = readbyte(address)
    if not integer(value, 0, 255) then error("Lecture memoire invalide") end
    return value
end

local function word(bytes, offset)
    return bytes[offset] + bytes[offset + 1] * 256
end

local function dword(bytes, offset)
    return word(bytes, offset) + word(bytes, offset + 2) * 65536
end

local function xor16(first, second)
    local result, place = 0, 1
    for _ = 1, 16 do
        if first % 2 ~= second % 2 then result = result + place end
        first, second, place = math.floor(first / 2), math.floor(second / 2), place * 2
    end
    return result
end

local function advance(seed)
    -- Décomposer le produit préserve les entiers exacts avec les nombres de Lua 5.1.
    local low, high = seed % 65536, math.floor(seed / 65536)
    local cross = (high * 0x4E6D + low * 0x41C6) % 65536
    return (low * 0x4E6D + cross * 65536 + 0x6073) % 4294967296
end

local function decrypt(bytes, first, last, seed)
    for offset = first, last, 2 do
        seed = advance(seed)
        local value = xor16(word(bytes, offset), math.floor(seed / 65536))
        bytes[offset], bytes[offset + 1] = value % 256, math.floor(value / 256)
    end
end

function M.detect(readbyte)
    local ok, result = pcall(function()
        local code = ""
        for offset = 0x0C, 0x0F do
            code = code .. string.char(byte(readbyte, HEADER_ADDRESS + offset))
        end
        local game_id
        if code:sub(1, 3) == "IRB" then game_id = "black"
        elseif code:sub(1, 3) == "IRA" then game_id = "white"
        elseif code:sub(1, 3) == "IRE" then game_id = "black2"
        elseif code:sub(1, 3) == "IRD" then game_id = "white2" end
        return {
            game_id = game_id,
            game_code = code,
            rom_revision = byte(readbyte, HEADER_ADDRESS + 0x1E),
            game_region = REGIONS[code:sub(4, 4)] or "unknown",
        }
    end)
    if ok then return result end
    return {game_code = "", game_region = "unknown", message = "En-tete RAM illisible"}
end

local function failure(status, message)
    return {status = status, message = message}
end

local function decode_slot(readbyte, address, slot)
    local bytes = {}
    for offset = 0, PARTY_BYTES - 1 do bytes[offset] = byte(readbyte, address + offset) end
    if word(bytes, 4) ~= 0 then return nil, "Structure Pokemon transitoire ou invalide" end
    local pid, expected = dword(bytes, 0), word(bytes, 6)
    decrypt(bytes, 8, STORED_BYTES - 2, expected)
    local checksum = 0
    for offset = 8, STORED_BYTES - 2, 2 do checksum = (checksum + word(bytes, offset)) % 65536 end
    if checksum ~= expected then return nil, "Checksum Pokemon invalide" end

    -- La permutation des blocs ne change pas la somme de contrôle. L'espèce
    -- provient du bloc A ; les statistiques utilisent un flux initialisé par le PID.
    local permutation = math.floor(pid / 8192) % 32 % 24 + 1
    local growth = 8 + GROWTH_POSITIONS[permutation] * 32
    local species = word(bytes, growth)
    -- PKHeX PK5: PID at 0x00; ID32 at canonical 0x0C (block A + 4).
    -- Both stay independent of species, slot, level and current HP.
    local trainer_id = dword(bytes, growth + 4)
    decrypt(bytes, STORED_BYTES, PARTY_BYTES - 2, pid)
    local level, hp, maximum = bytes[0x8C], word(bytes, 0x8E), word(bytes, 0x90)
    if not integer(species, 1, 649) or not integer(level, 1, 100)
        or not integer(maximum, 1, 9999) or hp > maximum then
        return nil, "Valeurs Pokemon incoherentes"
    end
    return {slot = slot, species_id = species, level = level, hp = hp, max_hp = maximum,
        personality_id = pid, original_trainer_id = trainer_id}
end

function M.read_party(memory, profile)
    if type(memory) ~= "table" or type(memory.readbyte) ~= "function" then
        return failure("invalid_data", "API memory.readbyte absente")
    end
    if type(profile) ~= "table" or profile.pokemon_size ~= PARTY_BYTES
        or not integer(profile.party_count_address, 0x02000000, 0x023FFFFF)
        or not integer(profile.party_address, 0x02000000, 0x02400000 - 6 * PARTY_BYTES) then
        return failure("unsupported", "Profil memoire absent ou invalide")
    end
    local identity = M.detect(memory.readbyte)
    if not identity.game_id or identity.game_id ~= profile.game_id
        or identity.game_code ~= profile.game_code or identity.rom_revision ~= profile.revision
        or identity.game_region ~= profile.region then
        return failure("unsupported", "Jeu, region ou revision incompatibles avec le profil")
    end
    local ok, result = pcall(function()
        local count = byte(memory.readbyte, profile.party_count_address)
        if count == 0 then return failure("not_ready", "Equipe non initialisee ou aucun Pokemon") end
        if count > 6 then return failure("invalid_data", "Taille de l'equipe incoherente") end
        local party = {}
        for slot = 1, count do
            local entry, problem = decode_slot(memory.readbyte,
                profile.party_address + (slot - 1) * PARTY_BYTES, slot)
            if not entry then return failure("invalid_data", problem) end
            party[slot] = entry
        end
        if byte(memory.readbyte, profile.party_count_address) ~= count then
            return failure("invalid_data", "Equipe modifiee pendant la lecture")
        end
        return {status = "ok", party_size = count, party = party}
    end)
    if ok then return result end
    return failure("invalid_data", "Lecture de l'equipe impossible")
end

return M
