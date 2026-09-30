-- Encodeur JSON autonome Lua 5.1. Aucun module réseau n'est nécessaire.
local M = {null = {}}
local array_marker = {}
function M.array(value) return setmetatable(value or {}, array_marker) end
local function quote(value)
    return '"' .. value:gsub('[%z\1-\31\\"]', function(character)
        if character == '"' then return '\\"' end
        if character == '\\' then return '\\\\' end
        return string.format('\\u%04x', string.byte(character))
    end) .. '"'
end
function M.encode(value)
    if value == M.null then return 'null' end
    local kind = type(value)
    if kind == 'string' then return quote(value) end
    if kind == 'boolean' then return tostring(value) end
    if kind == 'number' and value == math.floor(value) and math.abs(value) < 2^53 then
        return string.format('%.0f', value)
    end
    if kind ~= 'table' then error('Valeur JSON non prise en charge') end
    local result = {}
    if getmetatable(value) == array_marker then
        for _, item in ipairs(value) do result[#result + 1] = M.encode(item) end
        return '[' .. table.concat(result, ',') .. ']'
    end
    for key, item in pairs(value) do
        if type(key) ~= 'string' then error('Cle JSON invalide') end
        result[#result + 1] = quote(key) .. ':' .. M.encode(item)
    end
    table.sort(result)
    return '{' .. table.concat(result, ',') .. '}'
end
return M
