# FF7 Pelago PopTracker

PopTracker pack for [FF7pelago](https://github.com/blazerwazey/FF7pelago) with Archipelago autotracking.

## Setup

1. Install [PopTracker](https://github.com/black-sliver/PopTracker/releases).
2. Download the latest Release of the pack and copy its folder into your PopTracker `packs/` directory, or load it as an external pack.
3. Open the pack in PopTracker and enable **AP** autotracking from the menu.
4. Connect to your Archipelago room while playing Final Fantasy VII.

## Regenerating from APWorld data

```bash
python tools/generate_pack.py
```

By default this reads APWorld data from `worlds/ff7`.

## Pack contents

- 447 tracked items
- 498 tracked locations on the world map
- Tabs for specific locations.
- Archipelago item/location ID mappings in `scripts/autotracking/`

Map checks are grouped into one pin per area on `images/worldmap.png` (hover/click the pin to see every check in that area).

## Logic (Free Roam)

Region access mirrors the APWorld Free Roam gates in `worlds/ff7/__init__.py`:

- **Foot regions** (Kalm, Mythril Mines, Chocobo Farm, Fort Condor): always reachable
- **Mountain** (Junon): Green / Black / Gold Chocobo or Highwind
- **Sub** (Corel): Submarine or any ocean-capable transport
- **Gold Saucer**: above + Gold Ticket
- **Ocean** (most western continent areas): Blue / Black / Gold Chocobo or Highwind
- **Plateau** (Chocobo Sage, Ancient Forest): Black / Gold Chocobo or Highwind
- **Special keys**: Lunar Harp, Basement Key, Snowboard + Glacier Map, Key to Sector 5
- **Endgame** (Northern Cave): Highwind + full party + 4 Huge Materia
- **Per-check gates**: Kalm Traveler trades, Leviathan Scales (Wutai statue), etc.

PopTracker colors: **green** = logically reachable, **red** = not yet. Toggle items on the Items tab to preview logic.

### Slot data (Archipelago)

When connected with AP autotracking, `onClear` reads the server's `slot_data` payload:

- `free_roam` and `options.*` drive seed settings (weapon bosses, Gold Saucer, Fort Condor)
- `biton_map` + `shops` define the **exact location pool** for this seed (checks not in the pool are hidden)
- `CheckedLocations` re-applies checks already sent to the server on reconnect
- UI hints show seed name, player, and mode

Without a connection, visibility falls back to the static option rules above.

Edit `tools/logic_rules.py` / `scripts/logic.lua` and rerun the generator to adjust rules.

### Missing Location tabs

- Midgar
- Underwater Reactor
- Gelnika
- Gold Saucer
- North Crater
- Temple of The Ancient
