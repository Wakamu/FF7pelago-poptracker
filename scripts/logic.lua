-- FF7 Pelago slot_data-driven logic (Free Roam gates + seed pool visibility).

SLOT = {
    free_roam = true,
    weapon_fight_checks = true,
    disable_gold_saucer = false,
    disable_fort_condor_checks = false,
}

POOL = {}
USE_EXACT_POOL = false

function normalize_location_id(id)
    if type(id) == "string" then
        return tonumber(id) or id
    end
    return id
end

function ff7_linear()
    if SLOT.free_roam then
        return 0
    end
    return 1
end

function ff7_static_in_pool(location_id)
    local meta = LOCATION_META[location_id]
    if meta and GOLD_SAUCER_REGIONS[meta.region] and SLOT.disable_gold_saucer then
        return false
    end
    if FORT_CONDOR_CODES[location_id] and SLOT.disable_fort_condor_checks then
        return false
    end
    if WEAPON_BOSS_CODES[location_id] and not SLOT.weapon_fight_checks then
        return false
    end
    if DEAD_CODES[location_id] and SLOT.free_roam then
        return false
    end
    return true
end

function ff7_location_in_pool(location_id)
    if USE_EXACT_POOL then
        return POOL[location_id] == true
    end
    -- No AP seed pool yet: show every check. Pool filtering is AP-only.
    return true
end

function ff7_endgame()
    for _, code in ipairs(ENDGAME_ITEM_CODES) do
        local obj = Tracker:FindObjectForCode(code)
        if obj == nil or not obj.Active then
            return 0
        end
    end
    return 1
end

local function ff7_has_item(item_code)
    local obj = Tracker:FindObjectForCode(item_code)
    return obj ~= nil and obj.Active
end

local OCEAN_ITEMS = {
    "item_300505", -- Blue Chocobo
    "item_300506", -- Black Chocobo
    "item_300507", -- Gold Chocobo
    "item_300501", -- Highwind
}

local SUB_ITEMS = {
    "item_300502", -- Submarine
    "item_300505",
    "item_300506",
    "item_300507",
    "item_300501",
}

local function ff7_has_any_item(codes)
    for _, code in ipairs(codes) do
        local obj = Tracker:FindObjectForCode(code)
        if obj and obj.Active then
            return true
        end
    end
    return false
end

function ff7_ocean()
    return ff7_has_any_item(OCEAN_ITEMS) and 1 or 0
end

function ff7_sub()
    return ff7_has_any_item(SUB_ITEMS) and 1 or 0
end

function ff7_lunar_harp()
    if not ff7_has_any_item(OCEAN_ITEMS) then
        return 0
    end
    return ff7_has_item("item_100527") and 1 or 0
end

function ff7_shinra_basement()
    if not ff7_has_any_item(OCEAN_ITEMS) then
        return 0
    end
    return ff7_has_item("item_100528") and 1 or 0
end

function ff7_great_glacier()
    if not ff7_has_any_item(OCEAN_ITEMS) then
        return 0
    end
    if not ff7_has_item("item_100546") then
        return 0
    end
    return ff7_has_item("item_100540") and 1 or 0
end

function ff7_gold_saucer()
    if not ff7_has_any_item(SUB_ITEMS) then
        return 0
    end
    return ff7_has_item("item_100537") and 1 or 0
end

function ff7_key_sector_5()
    return ff7_has_item("item_300503") and 1 or 0
end

local function set_option_toggle(code, active)
    local obj = Tracker:FindObjectForCode(code)
    if obj then
        obj.Active = active
    end
end

local function pool_matches_pack()
    for location_id, _ in pairs(POOL) do
        if LOCATION_META[location_id] then
            return true
        end
    end
    return false
end

local function rebuild_pool_from_ap()
    if not Archipelago.MissingLocations and not Archipelago.CheckedLocations then
        return false
    end

    local next_pool = {}
    local count = 0
    if Archipelago.MissingLocations then
        for _, location_id in ipairs(Archipelago.MissingLocations) do
            next_pool[normalize_location_id(location_id)] = true
            count = count + 1
        end
    end
    if Archipelago.CheckedLocations then
        for _, location_id in ipairs(Archipelago.CheckedLocations) do
            next_pool[normalize_location_id(location_id)] = true
            count = count + 1
        end
    end
    if count == 0 then
        return false
    end

    POOL = next_pool
    USE_EXACT_POOL = true
    return pool_matches_pack()
end

local function rebuild_pool_from_slot_data(slot_data)
    if not slot_data then
        return false
    end

    local biton_map = slot_data.biton_map
    local shops = slot_data.shops
    if not biton_map and not shops then
        return false
    end

    POOL = {}
    USE_EXACT_POOL = true
    if biton_map then
        for code, _ in pairs(biton_map) do
            POOL[normalize_location_id(code)] = true
        end
    end
    if shops then
        for _, shop in ipairs(shops) do
            if shop.location_id then
                POOL[normalize_location_id(shop.location_id)] = true
            end
        end
    end
    return pool_matches_pack()
end

function apply_slot_data(slot_data)
    SLOT.free_roam = true
    SLOT.weapon_fight_checks = true
    SLOT.disable_gold_saucer = false
    SLOT.disable_fort_condor_checks = false

    if slot_data then
        if slot_data.free_roam ~= nil then
            SLOT.free_roam = slot_data.free_roam and true or false
        end

        local opts = slot_data.options or {}
        if opts.weapon_fight_checks ~= nil then
            SLOT.weapon_fight_checks = opts.weapon_fight_checks and true or false
        end
        if opts.disable_gold_saucer ~= nil then
            SLOT.disable_gold_saucer = opts.disable_gold_saucer and true or false
        end
        if opts.disable_fort_condor_checks ~= nil then
            SLOT.disable_fort_condor_checks = opts.disable_fort_condor_checks and true or false
        end

        if slot_data.seed_name then
            Tracker:UiHint("Seed", slot_data.seed_name)
        end
        if slot_data.player then
            Tracker:UiHint("Player", slot_data.player)
        end
    end

    POOL = {}
    USE_EXACT_POOL = false
    -- slot_data biton_map is the full seed pool; AP missing/checked alone can be incomplete.
    if not rebuild_pool_from_slot_data(slot_data) and not rebuild_pool_from_ap() then
        POOL = {}
        USE_EXACT_POOL = false
    end

    local mode = SLOT.free_roam and "Free Roam" or "Linear"
    Tracker:UiHint("Mode", mode)

    set_option_toggle("opt_free_roam", SLOT.free_roam)
    set_option_toggle("opt_weapon_fight_checks", SLOT.weapon_fight_checks)
    set_option_toggle("opt_gold_saucer_checks", not SLOT.disable_gold_saucer)
    set_option_toggle("opt_fort_condor_checks", not SLOT.disable_fort_condor_checks)
end
