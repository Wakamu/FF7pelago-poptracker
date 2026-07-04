Tracker:AddItems("items/items.json")

ScriptHost:LoadScript("scripts/logic_seed.lua")
ScriptHost:LoadScript("scripts/logic.lua")
ScriptHost:LoadScript("scripts/logic_pool.lua")

Tracker:AddLocations("locations/world.json")

Tracker:AddMaps("maps/maps.json")
Tracker:AddLayouts("layouts/tracker.json")

ScriptHost:LoadScript("scripts/autotracking/init.lua")
