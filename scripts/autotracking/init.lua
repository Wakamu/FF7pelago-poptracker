require("scripts/autotracking/item_mapping")
require("scripts/autotracking/location_mapping")

CUR_INDEX = -1
RECEIVED_ITEMS = {}
LAST_SEED_NAME = nil

local function sanitize_section_ref(code)
    if not code or code:sub(1, 1) ~= "@" then
        return code
    end
    local trimmed = code:sub(2)
    if trimmed:sub(-1) == "/" then
        trimmed = trimmed:sub(1, -2)
    end
    local slash_pos = trimmed:find("/")
    if not slash_pos then
        return code
    end
    local area = trimmed:sub(1, slash_pos - 1)
    local section = trimmed:sub(slash_pos + 1)
    if not section:find("/", 1, true) then
        return code
    end
    -- PopTracker treats "/" as a path separator inside @area/section/ refs.
    section = section:gsub("/", "⁄")
    return "@" .. area .. "/" .. section .. "/"
end

local function find_tracker_object(code)
    local obj = Tracker:FindObjectForCode(code)
    if obj then
        return obj
    end
    local sanitized = sanitize_section_ref(code)
    if sanitized ~= code then
        obj = Tracker:FindObjectForCode(sanitized)
        if obj then
            return obj
        end
    end
    if not code or code:sub(1, 1) ~= "@" then
        return nil
    end
    if code:sub(-1) == "/" then
        return Tracker:FindObjectForCode(code:sub(1, -2))
    end
    return Tracker:FindObjectForCode(code .. "/")
end

local function location_code_for_id(location_id)
    local id = normalize_location_id(location_id)
    return LOCATION_MAPPING[id]
end

local function clear_location(code)
    local obj = find_tracker_object(code)
    if not obj then
        return
    end
    if code:sub(1, 1) == "@" then
        obj.AvailableChestCount = obj.ChestCount
    else
        obj.Active = false
    end
end

local function mark_location(code)
    local obj = find_tracker_object(code)
    if not obj then
        return
    end
    if code:sub(1, 1) == "@" then
        obj.AvailableChestCount = 0
    else
        obj.Active = true
    end
end

local function apply_received_item(item_id)
    local mapping = ITEM_MAPPING[item_id]
    if not mapping then
        return
    end
    local tracker_code = mapping[1]
    local item_type = mapping[2]
    local obj = Tracker:FindObjectForCode(tracker_code)
    if not obj then
        return
    end
    if item_type == "toggle" then
        obj.Active = true
    elseif item_type == "consumable" then
        obj.AcquiredCount = obj.AcquiredCount + obj.Increment
    end
end

local function sync_checked_locations()
    if not Archipelago.CheckedLocations then
        return
    end
    for _, location_id in ipairs(Archipelago.CheckedLocations) do
        local code = location_code_for_id(location_id)
        if code then
            mark_location(code)
        end
    end
end

local function sync_received_items()
    for item_id, _ in pairs(RECEIVED_ITEMS) do
        apply_received_item(item_id)
    end
end

function onClear(slot_data)
    local seed_name = slot_data and slot_data.seed_name
    if seed_name and seed_name ~= LAST_SEED_NAME then
        RECEIVED_ITEMS = {}
        LAST_SEED_NAME = seed_name
    end
    CUR_INDEX = -1
    Tracker.BulkUpdate = true

    apply_slot_data(slot_data)

    for _, code in pairs(LOCATION_MAPPING) do
        clear_location(code)
    end
    for _, mapping in pairs(ITEM_MAPPING) do
        local tracker_code = mapping[1]
        local item_type = mapping[2]
        if tracker_code:sub(1, 4) ~= "opt_" then
            local obj = Tracker:FindObjectForCode(tracker_code)
            if obj then
                if item_type == "toggle" then
                    obj.Active = false
                elseif item_type == "consumable" then
                    obj.AcquiredCount = 0
                end
            end
        end
    end

    sync_received_items()
    sync_checked_locations()

    Tracker.BulkUpdate = false
end

function onItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then
        return
    end
    CUR_INDEX = index
    RECEIVED_ITEMS[item_id] = true
    apply_received_item(item_id)
end

function onLocation(location_id, location_name)
    local code = location_code_for_id(location_id)
    if not code then
        return
    end
    mark_location(code)
end

Archipelago:AddClearHandler("ff7 clear", onClear)
Archipelago:AddItemHandler("ff7 item", onItem)
Archipelago:AddLocationHandler("ff7 location", onLocation)
