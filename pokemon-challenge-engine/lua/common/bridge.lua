-- Passerelle locale, exclusivement en lecture de la mémoire du jeu.
-- Les seuls fichiers écrits appartiennent à la session créée par Python.
local M = {}

local function load_config(path)
    local ok, config = pcall(dofile, path)
    if not ok or type(config) ~= 'table' or type(config.session_id) ~= 'string'
        or #config.session_id ~= 32 or not config.session_id:match('^[0-9a-f]+$') then
        error('Configuration locale absente ou invalide : preparer la connexion dans Python')
    end
    return config
end

function M.run(config_path)
    local config = load_config(config_path)
    local json = dofile(config.common_dir .. '/protocol.lua')
    local reader = dofile(config.common_dir .. '/gen5_reader.lua')
    if type(memory) ~= 'table' or type(memory.readbyte) ~= 'function'
        or type(emu) ~= 'table' or type(emu.frameadvance) ~= 'function' then
        error('API DeSmuME Lua requise : memory.readbyte et emu.frameadvance')
    end
    local sequence, frames, bucket, sent, first = 0, 0, -1, 0, true
    local last_party, running = nil, true

    local function resume_sequence()
        local handle = io.open(config.session_dir .. '/sequence.txt', 'rb')
        sequence = 0
        if handle then sequence = tonumber(handle:read(32)); handle:close() end
        if not sequence or sequence < 0 or sequence ~= math.floor(sequence) or sequence > 1000000000 then
            error('Compteur local invalide : preparer une nouvelle session')
        end
    end
    resume_sequence()

    local function message(event)
        local identity = reader.detect(memory.readbyte)
        local code = identity.game_code
        if type(code) ~= 'string' or not code:match('^[A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]$') then code = nil end
        local region = identity.game_region ~= 'unknown' and identity.game_region or nil
        local result = {
            protocol_version = 1, session_id = config.session_id, sequence = sequence + 1,
            event = event, timestamp = os.time(), emulator = 'desmume', script_version = config.script_version,
            game_id = identity.game_id or json.null, game_code = code or json.null,
            game_region = region or json.null, rom_revision = identity.rom_revision or json.null,
            capabilities = json.array({'heartbeat', 'game_identity'}), memory_profile = json.null,
            party_size = json.null, party = json.null, error = json.null,
        }
        if not identity.game_id or identity.game_id ~= config.expected_game
            or (config.expected_code and config.expected_code ~= code)
            or (config.expected_revision and config.expected_revision ~= identity.rom_revision) then
            result.error = 'Jeu inconnu ou ROM differente de la selection ; lecture equipe refusee'
            return result
        end
        local profile
        for _, candidate in ipairs(config.profiles) do
            if candidate.game_id == identity.game_id and candidate.game_code == code
                and candidate.revision == identity.rom_revision and candidate.region == region then
                profile = candidate; break
            end
        end
        if not profile then
            result.error = 'Region ou revision sans profil memoire documente ; identite seulement'
            return result
        end
        result.memory_profile = profile.id
        local data = reader.read_party(memory, profile)
        if data.status ~= 'ok' then result.error = data.message; return result end
        result.party_size, result.party = data.party_size, json.array(data.party)
        result.capabilities = json.array({'heartbeat', 'game_identity', 'party_size', 'party_species', 'party_level', 'party_hp'})
        return result
    end

    local function publish(value)
        sequence = sequence + 1
        value.sequence = sequence
        local content = json.encode(value)
        if #content > 65536 then error('Message Lua trop volumineux') end
        local counter = assert(io.open(config.session_dir .. '/sequence.txt', 'wb'))
        assert(counter:write(tostring(sequence))); assert(counter:close())
        local name = config.session_dir .. string.format('/snapshot-%010d.json', sequence)
        local handle = assert(io.open(name .. '.tmp', 'wb'))
        assert(handle:write(content)); assert(handle:close())
        assert(os.rename(name .. '.tmp', name))
        if sequence > 2 then
            os.remove(config.session_dir .. string.format('/snapshot-%010d.json', sequence - 2))
        end
    end

    local function close()
        if running then
            running = false
            local ok, problem = pcall(function() publish(message('emulator_closing')) end)
            if not ok then print('PCE : fermeture sans message : ' .. tostring(problem)) end
        end
    end
    if type(emu.registerexit) == 'function' then emu.registerexit(close) end

    while running do
        if frames % 12 == 0 then
            local ok, problem = pcall(function()
                local updated = load_config(config_path)
                if updated.session_id ~= config.session_id then
                    config = updated; resume_sequence(); first = true; last_party = nil
                end
                local stop = io.open(config.session_dir .. '/stop', 'rb')
                if stop then stop:close(); close(); return end
                local now = os.time()
                if now ~= bucket then bucket, sent = now, 0 end
                if sent >= 5 then return end
                local value = message(first and 'hello' or 'heartbeat')
                local signature = json.encode(value.party)
                if not first and signature ~= last_party and value.party ~= json.null then
                    value.event = 'party_update'
                end
                publish(value)
                first, last_party, sent = false, signature, sent + 1
            end)
            if not ok then
                print('PCE : passerelle arretee : ' .. tostring(problem))
                close()
                return
            end
        end
        frames = frames + 1
        if running then emu.frameadvance() end
    end
end
return M
