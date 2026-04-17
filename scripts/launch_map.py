"""
launch_map.py — Standalone map launcher.
Reads config.ini, patches GameUserSettings.ini with the correct rates,
and starts the server directly — no controller required.

Usage:
    python launch_map.py <map_key>
    e.g.  python launch_map.py ragnarok
"""

import os
import sys
import subprocess
import configparser

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR    = os.path.dirname(_SCRIPTS_DIR)
CONFIG_PATH  = os.path.join(_BASE_DIR, "controller", "config.ini")

MAP_DEFS = {
    "ragnarok":      ("Ragnarok",       "Ragnarok_WP",      7777, 27015, 27020),
    "thecenter":     ("The Center",     "TheCenter_WP",     7787, 27025, 27021),
    "valguero":      ("Valguero",       "Valguero_WP",      7797, 27035, 27022),
    "theisland":     ("The Island",     "TheIsland_WP",     7807, 27045, 27023),
    "scorchedearth": ("Scorched Earth", "ScorchedEarth_WP", 7817, 27055, 27024),
    "aberration":    ("Aberration",     "Aberration_WP",    7827, 27065, 27029),
    "extinction":    ("Extinction",     "Extinction_WP",    7837, 27075, 27026),
    "lostcolony":    ("Lost Colony",    "LostColony_WP",    7847, 27085, 27027),
    "astraeos":      ("Astraeos",       "Astraeos_WP",      7857, 27095, 27028),
}


def _g(cfg, s, k, fb=""):
    try:    return cfg.get(s, k).strip()
    except: return fb

def _g2(cfg, s, k, fb, alt):
    v = _g(cfg, s, k, None)
    return v if v is not None else _g(cfg, alt, k, fb)

def _b(cfg, s, k, fb):
    return "True" if _g(cfg, s, k, fb).lower() == "true" else "False"


def _patch_ini(path: str, section: str, desired: dict) -> None:
    """Patch an ini file — line-by-line, case-insensitive, key=value format."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    desired_lower  = {k.lower(): (k, v) for k, v in desired.items()}
    section_header = f"[{section}]"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            orig_lines = f.readlines()
    else:
        orig_lines = [f"{section_header}\n"]

    in_sec = False
    seen   = set()
    result = []

    for line in orig_lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if in_sec:
                for lk, (ck, val) in desired_lower.items():
                    if lk not in seen:
                        result.append(f"{ck}={val}\n"); seen.add(lk)
            in_sec = stripped.lower() == section_header.lower()
            result.append(line); continue
        if in_sec and "=" in stripped and not stripped.startswith(";"):
            key_part = stripped.split("=", 1)[0].strip().lower()
            if key_part in desired_lower:
                ck, val = desired_lower[key_part]
                if key_part not in seen:
                    result.append(f"{ck}={val}\n"); seen.add(key_part)
                continue
            result.append(line)
        else:
            result.append(line)

    if in_sec:
        for lk, (ck, val) in desired_lower.items():
            if lk not in seen:
                result.append(f"{ck}={val}\n")
    if not seen:
        result.append(f"\n{section_header}\n")
        for ck, val in desired.items():
            result.append(f"{ck}={val}\n")

    new_text = "".join(result)
    if new_text != "".join(orig_lines):
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"  {os.path.basename(path)} patched.")


def _patch_game_user_settings(cfg, server_root: str) -> None:
    """Patch GameUserSettings.ini [ServerSettings] with rates, combat, flags, etc."""
    path = os.path.join(
        server_root, "ShooterGame", "Saved", "Config", "WindowsServer", "GameUserSettings.ini"
    )
    _patch_ini(path, "ServerSettings", {
        # Limits
        "MaxPlayers":                              _g2(cfg,"limits","max_players","70","performance"),
        "MaxTamedDinos":                           _g(cfg, "limits","max_tamed_dinos","5000"),
        "MaxPersonalTamedDinos":                   _g(cfg, "limits","max_personal_tamed_dinos","40"),
        # World
        "DayTimeSpeedScale":                       _g(cfg, "world","day_time_speed_scale","1.0"),
        "NightTimeSpeedScale":                     _g(cfg, "world","night_time_speed_scale","1.0"),
        "DinoCountMultiplier":                     _g(cfg, "world","dino_count_multiplier","1.0"),
        "ResourcesRespawnPeriodMultiplier":        _g(cfg, "world","resources_respawn_period_multiplier","1.0"),
        # Rates
        "XPMultiplier":                            _g(cfg, "rates","xp_multiplier","1.0"),
        "TamingSpeedMultiplier":                   _g(cfg, "rates","taming_speed_multiplier","1.0"),
        "HarvestAmountMultiplier":                 _g(cfg, "rates","harvest_amount_multiplier","1.0"),
        "DifficultyOffset":                        _g(cfg, "rates","difficulty_offset","1.0"),
        "ItemStackSizeMultiplier":                 _g(cfg, "rates","item_stack_size_multiplier","1.0"),
        "LootQualityMultiplier":                   _g(cfg, "rates","loot_quality_multiplier","1.0"),
        "FishingLootQualityMultiplier":            _g(cfg, "rates","fishing_loot_quality_multiplier","1.0"),
        "SupplyCrateLootQualityMultiplier":        _g(cfg, "rates","supply_crate_loot_quality_multiplier","1.0"),
        # Survival
        "PlayerCharacterFoodDrainMultiplier":      _g(cfg, "survival","player_food_drain_multiplier","1.0"),
        "PlayerCharacterWaterDrainMultiplier":     _g(cfg, "survival","player_water_drain_multiplier","1.0"),
        "PlayerCharacterStaminaDrainMultiplier":   _g(cfg, "survival","player_stamina_drain_multiplier","1.0"),
        "PlayerCharacterHealthRecoveryMultiplier": _g(cfg, "survival","player_health_recovery_multiplier","1.0"),
        "DinoCharacterFoodDrainMultiplier":        _g(cfg, "survival","dino_food_drain_multiplier","1.0"),
        "DinoCharacterHealthRecoveryMultiplier":   _g(cfg, "survival","dino_health_recovery_multiplier","1.0"),
        # Combat
        "PlayerDamageMultiplier":                  _g(cfg, "combat","player_damage_multiplier","1.0"),
        "PlayerResistanceMultiplier":              _g(cfg, "combat","player_resistance_multiplier","1.0"),
        "DinoDamageMultiplier":                    _g(cfg, "combat","dino_damage_multiplier","1.0"),
        "DinoResistanceMultiplier":                _g(cfg, "combat","dino_resistance_multiplier","1.0"),
        "TamedDinoDamageMultiplier":               _g(cfg, "combat","tamed_dino_damage_multiplier","1.0"),
        "TamedDinoResistanceMultiplier":           _g(cfg, "combat","tamed_dino_resistance_multiplier","1.0"),
        "StructureDamageMultiplier":               _g(cfg, "combat","structure_damage_multiplier","1.0"),
        "ShowFloatingDamageText":                  _b(cfg, "combat","show_floating_damage_text","false"),
        "AllowHitMarkers":                         _b(cfg, "combat","allow_hit_markers","true"),
        # Structures
        "StructurePickupTimeAfterPlacement":       _g(cfg, "structures","structure_pickup_time_after_placement","30"),
        "PerPlatformMaxStructuresMultiplier":      _g(cfg, "structures","per_platform_max_structures_multiplier","1.0"),
        # Flags
        "AlwaysAllowStructurePickup":              _b(cfg, "flags","always_allow_structure_pickup","true"),
        "DisableStructureDecayPvE":                _b(cfg, "flags","disable_structure_decay_pve","false"),
        "DisableDinoDecayPvE":                     _b(cfg, "flags","disable_dino_decay_pve","false"),
        "AllowCaveBuildingPvE":                    _b(cfg, "flags","allow_cave_building_pve","false"),
        "AllowAnyoneBabyImprintCuddle":            _b(cfg, "flags","allow_anyone_baby_imprint_cuddle","false"),
        "AllowFlyerCarryPvE":                      _b(cfg, "flags","allow_flyer_carry_pve","true"),
        "AllowFlyerSpeedLeveling":                 _b(cfg, "flags","allow_flyer_speed_leveling","false"),
        "DisableCryoSicknessPVP":                  _b(cfg, "flags","disable_cryo_sickness_pvp","false"),
        "bDisableCryopodEnemyCheck":               "False" if _g(cfg,"flags","require_powered_cryofridge","true").lower() == "true" else "True",
    })


def _patch_game_ini(cfg, server_root: str) -> None:
    """Patch Game.ini [/Script/ShooterGame.ShooterGameMode] with breeding multipliers.

    Breeding settings belong here, NOT in GameUserSettings.ini — the server
    ignores them if placed there.
    """
    path = os.path.join(
        server_root, "ShooterGame", "Saved", "Config", "WindowsServer", "Game.ini"
    )
    _patch_ini(path, "/Script/ShooterGame.ShooterGameMode", {
        "MatingIntervalMultiplier":        _g2(cfg,"breeding","mating_interval_multiplier","1.0","rates"),
        "MatingSpeedMultiplier":           _g2(cfg,"breeding","mating_speed_multiplier","1.0","rates"),
        "EggHatchSpeedMultiplier":         _g2(cfg,"breeding","egg_hatch_speed_multiplier","1.0","rates"),
        "LayEggIntervalMultiplier":        _g(cfg, "breeding","lay_egg_interval_multiplier","1.0"),
        "BabyMatureSpeedMultiplier":       _g(cfg, "breeding","baby_mature_speed_multiplier","1.0"),
        "BabyCuddleIntervalMultiplier":    _g(cfg, "breeding","baby_cuddle_interval_multiplier","1.0"),
        "BabyCuddleGracePeriodMultiplier": _g(cfg, "breeding","baby_cuddle_grace_period_multiplier","1.0"),
        "BabyImprintAmountMultiplier":     _g(cfg, "breeding","baby_imprint_amount_multiplier","1.0"),
        # Rates (Game.ini only)
        "GlobalSpoilingTimeMultiplier":            _g(cfg, "rates","global_spoiling_time_multiplier","1.0"),
        "GlobalItemDecompositionTimeMultiplier":   _g(cfg, "rates","global_item_decomposition_time_multiplier","1.0"),
        "GlobalCorpseDecompositionTimeMultiplier": _g(cfg, "rates","global_corpse_decomposition_time_multiplier","1.0"),
        "CropGrowthSpeedMultiplier":               _g(cfg, "rates","crop_growth_speed_multiplier","1.0"),
        "FuelConsumptionIntervalMultiplier":       _g(cfg, "rates","fuel_consumption_interval_multiplier","1.0"),
    })


def _patch_engine_ini(cfg, server_root: str) -> None:
    """Tune GC frequency in Engine.ini before server launch."""
    path = os.path.join(
        server_root, "ShooterGame", "Saved", "Config", "WindowsServer", "Engine.ini"
    )
    _patch_ini(path, "/Script/Engine.GarbageCollectionSettings", {
        "gc.TimeBetweenPurgingPendingKillObjects": _g(cfg, "limits", "gc_purge_interval", "30"),
    })


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python launch_map.py <map_key>")
        print("Available maps:", ", ".join(MAP_DEFS))
        input("\nPress Enter to close..."); sys.exit(1)

    key = sys.argv[1].lower().strip()
    if key not in MAP_DEFS:
        print(f"Unknown map: '{key}'")
        print("Available maps:", ", ".join(MAP_DEFS))
        input("\nPress Enter to close..."); sys.exit(1)

    if not os.path.exists(CONFIG_PATH):
        print(f"config.ini not found at:\n  {CONFIG_PATH}")
        print("\nRun the setup wizard (start_controller.bat) to create one first.")
        input("\nPress Enter to close..."); sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    server_root   = _g2(cfg,"paths","server_root",       r"C:\ASA_Cluster\asa_server","paths")
    cluster_dir   = _g(cfg, "paths","cluster_dir",       os.path.join(server_root,"cluster"))
    cluster_name  = _g(cfg, "cluster","cluster_name",    "MyCluster")
    cluster_id    = cluster_name.replace(" ","") + "Cluster"
    rcon_password = _g(cfg, "cluster","rcon_password",   "ChangeMe123")
    max_players   = _g2(cfg,"limits","max_players",      "70","performance")
    low_memory    = _g(cfg, "limits","low_memory_mode",            "true").lower()  == "true"
    no_sound      = _g(cfg, "limits","no_sound",                  "true").lower()  == "true"
    allow_tp      = _g(cfg, "flags","allow_third_person",        "false").lower() == "true"
    show_map_loc  = _g(cfg, "flags","show_map_player_location",  "true").lower()  == "true"
    no_dl_surv    = _g(cfg, "flags","prevent_download_survivors","false").lower() == "true"
    no_dl_items   = _g(cfg, "flags","prevent_download_items",    "false").lower() == "true"
    cave_flyers   = _g(cfg, "flags","force_allow_cave_flyers",   "false").lower() == "true"
    excl_join     = _g(cfg, "flags","exclusive_join",            "false").lower() == "true"
    crossplay     = _g(cfg, "mods", "crossplay",                 "false").lower() == "true"
    mod_ids       = _g(cfg, "mods", "mod_ids",                   "").strip()
    active_event  = _g(cfg, "world","active_event",              "").strip()

    exe = os.path.join(server_root, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    if not os.path.exists(exe):
        print(f"ArkAscendedServer.exe not found at:\n  {exe}")
        print("\nCheck server_root in config.ini, or run the controller to download the server.")
        input("\nPress Enter to close..."); sys.exit(1)

    print("Applying rates from config.ini...")
    _patch_game_user_settings(cfg, server_root)
    _patch_game_ini(cfg, server_root)
    _patch_engine_ini(cfg, server_root)

    display, map_name, game_port, query_port, rcon_port = MAP_DEFS[key]
    session_name = f"{cluster_name}_{display.replace(' ', '')}"

    map_arg = (
        f"{map_name}"
        f"?SessionName={session_name}"
        f"?MaxPlayers={max_players}"
        f"?Port={game_port}"
        f"?QueryPort={query_port}"
        f"?RCONEnabled=True"
        f"?RCONPort={rcon_port}"
        f"?ServerAdminPassword={rcon_password}"
    )
    flags = [
        "-server", "-log", "-servergamelog", "-NoBattlEye",
        f"-ClusterDirOverride={cluster_dir}",
        f"-ClusterId={cluster_id}",
    ]
    if low_memory:   flags.extend(["-lowmemory", "-nomemorybias"])
    if no_sound:     flags.append("-nosound")
    if allow_tp:     flags.append("-AllowThirdPersonPlayer")
    if show_map_loc: flags.append("-ShowMapPlayerLocation")
    if no_dl_surv:   flags.append("-PreventDownloadSurvivors")
    if no_dl_items:  flags.append("-PreventDownloadItems")
    if cave_flyers:  flags.append("-ForceAllowCaveFlyers")
    if excl_join:    flags.append("-exclusivejoin")
    if crossplay:    flags.append("-crossplay")
    if mod_ids:      flags.append(f"-GameModIds={mod_ids}")
    if active_event: flags.append(f"-ActiveEvent={active_event}")

    print(f"Launching {display}...")
    print(f"  Session : {session_name}")
    print(f"  Ports   : game={game_port}  query={query_port}  rcon={rcon_port}")
    print(f"  Cluster : {cluster_id}")
    print()

    subprocess.Popen(
        [exe, map_arg] + flags,
        cwd=os.path.dirname(exe),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    print(f"{display} launched successfully.")


if __name__ == "__main__":
    main()
