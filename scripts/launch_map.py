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

# ── Map definitions (key → display, map_name, game_port, query_port, rcon_port)
MAP_DEFS = {
    "ragnarok":      ("Ragnarok",       "Ragnarok_WP",      7777, 27015, 27020),
    "thecenter":     ("The Center",     "TheCenter_WP",     7787, 27025, 27021),
    "valguero":      ("Valguero",       "Valguero_WP",      7797, 27035, 27022),
    "theisland":     ("The Island",     "TheIsland_WP",     7807, 27045, 27023),
    "scorchedearth": ("Scorched Earth", "ScorchedEarth_WP", 7817, 27055, 27024),
    "aberration":    ("Aberration",     "Aberration_WP",    7827, 27065, 27025),
    "extinction":    ("Extinction",     "Extinction_WP",    7837, 27075, 27026),
    "lostcolony":    ("Lost Colony",    "LostColony_WP",    7847, 27085, 27027),
    "astraeos":      ("Astraeos",       "Astraeos_WP",      7857, 27095, 27028),
}


def _cfg_get(cfg: configparser.ConfigParser, section: str, key: str, fallback: str = "") -> str:
    try:
        return cfg.get(section, key).strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def _patch_game_user_settings(cfg: configparser.ConfigParser, server_root: str) -> None:
    """Patch GameUserSettings.ini with rates/flags from config.ini.

    Uses line-by-line rewriting so that:
    - Keys are matched case-insensitively (ARK writes lowercase; we use CamelCase)
    - Values are written as key=value with no spaces (ARK's native format)
    - Duplicate lowercase keys left by ARK are replaced, not appended
    """
    settings_path = os.path.join(
        server_root, "ShooterGame", "Saved", "Config", "WindowsServer", "GameUserSettings.ini"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    def r(s, k, fb):   return _cfg_get(cfg, s, k, fb)
    def _b(s, k, fb):  return "True" if r(s, k, fb).lower() == "true" else "False"

    desired = {
        "MaxPlayers":                              r("performance", "max_players",                               "70"),
        "XPMultiplier":                            r("rates",       "xp_multiplier",                            "1.0"),
        "TamingSpeedMultiplier":                   r("rates",       "taming_speed_multiplier",                  "1.0"),
        "HarvestAmountMultiplier":                 r("rates",       "harvest_amount_multiplier",                "1.0"),
        "DifficultyOffset":                        r("rates",       "difficulty_offset",                        "1.0"),
        "MatingIntervalMultiplier":                r("rates",       "mating_interval_multiplier",               "1.0"),
        "EggHatchSpeedMultiplier":                 r("rates",       "egg_hatch_speed_multiplier",               "1.0"),
        "GlobalSpoilingTimeMultiplier":            r("rates",       "global_spoiling_time_multiplier",          "1.0"),
        "GlobalItemDecompositionTimeMultiplier":   r("rates",       "global_item_decomposition_time_multiplier","1.0"),
        "GlobalCorpseDecompositionTimeMultiplier": r("rates",       "global_corpse_decomposition_time_multiplier","1.0"),
        "CropGrowthSpeedMultiplier":               r("rates",       "crop_growth_speed_multiplier",             "1.0"),
        "MatingSpeedMultiplier":                   r("rates",       "mating_speed_multiplier",                  "1.0"),
        "FuelConsumptionIntervalMultiplier":       r("rates",       "fuel_consumption_interval_multiplier",     "1.0"),
        "AlwaysAllowStructurePickup":              _b("flags",      "always_allow_structure_pickup",            "true"),
        "DisableStructureDecayPvE":                _b("flags",      "disable_structure_decay_pve",              "false"),
        "AllowCaveBuildingPvE":                    _b("flags",      "allow_cave_building_pve",                  "false"),
        "AllowAnyoneBabyImprintCuddle":            _b("flags",      "allow_anyone_baby_imprint_cuddle",         "false"),
        "AllowFlyerCarryPvE":                      _b("flags",      "allow_flyer_carry_pve",                    "true"),
        # bDisableCryopodEnemyCheck=True removes the powered-fridge-nearby requirement.
        # Inverted: require_powered_cryofridge=true  → bDisableCryopodEnemyCheck=False
        #           require_powered_cryofridge=false → bDisableCryopodEnemyCheck=True
        "bDisableCryopodEnemyCheck":               "False" if r("flags", "require_powered_cryofridge", "true").lower() == "true" else "True",
        "BabyMatureSpeedMultiplier":               r("breeding",    "baby_mature_speed_multiplier",             "1.0"),
        "BabyCuddleIntervalMultiplier":            r("breeding",    "baby_cuddle_interval_multiplier",          "1.0"),
        "BabyCuddleGracePeriodMultiplier":         r("breeding",    "baby_cuddle_grace_period_multiplier",      "1.0"),
        "BabyImprintAmountMultiplier":             r("breeding",    "baby_imprint_amount_multiplier",           "1.0"),
    }

    # Lowercase lookup so we can match ARK's own lowercase key names
    desired_lower = {k.lower(): (k, v) for k, v in desired.items()}

    # Read existing file (or start fresh)
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            orig_lines = f.readlines()
    else:
        orig_lines = ["[ServerSettings]\n"]

    # Rewrite line-by-line
    in_ss  = False
    seen   = set()
    result = []

    for line in orig_lines:
        stripped = line.strip()

        if stripped.startswith("["):
            if in_ss:
                # Leaving [ServerSettings] — flush any keys not yet written
                for lk, (ck, val) in desired_lower.items():
                    if lk not in seen:
                        result.append(f"{ck}={val}\n")
                        seen.add(lk)
            in_ss = stripped.lower() == "[serversettings]"
            result.append(line)
            continue

        if in_ss and "=" in stripped and not stripped.startswith(";"):
            key_part = stripped.split("=", 1)[0].strip().lower()
            if key_part in desired_lower:
                ck, val = desired_lower[key_part]
                if key_part not in seen:
                    result.append(f"{ck}={val}\n")
                    seen.add(key_part)
                continue  # drop original (possibly duplicate/lowercase) line
            result.append(line)
        else:
            result.append(line)

    # EOF while still inside [ServerSettings]
    if in_ss:
        for lk, (ck, val) in desired_lower.items():
            if lk not in seen:
                result.append(f"{ck}={val}\n")

    # [ServerSettings] not found at all — append it
    if not seen:
        result.append("\n[ServerSettings]\n")
        for ck, val in desired.items():
            result.append(f"{ck}={val}\n")

    new_text = "".join(result)
    if new_text != "".join(orig_lines):
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"  GameUserSettings.ini patched.")


def main() -> None:
    # ── Resolve map key ───────────────────────────────────────────────────────
    if len(sys.argv) < 2:
        print("Usage: python launch_map.py <map_key>")
        print("Available maps:", ", ".join(MAP_DEFS))
        input("\nPress Enter to close...")
        sys.exit(1)

    key = sys.argv[1].lower().strip()
    if key not in MAP_DEFS:
        print(f"Unknown map: '{key}'")
        print("Available maps:", ", ".join(MAP_DEFS))
        input("\nPress Enter to close...")
        sys.exit(1)

    # ── Load config.ini ───────────────────────────────────────────────────────
    if not os.path.exists(CONFIG_PATH):
        print(f"config.ini not found at:\n  {CONFIG_PATH}")
        print("\nRun the setup wizard (start_controller.bat) to create one first.")
        input("\nPress Enter to close...")
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    server_root   = _cfg_get(cfg, "paths",       "server_root",                r"C:\ASA_Cluster\asa_server")
    cluster_dir   = _cfg_get(cfg, "paths",       "cluster_dir",                os.path.join(server_root, "cluster"))
    cluster_name  = _cfg_get(cfg, "cluster",     "cluster_name",               "MyCluster")
    cluster_id    = cluster_name.replace(" ", "") + "Cluster"
    rcon_password = _cfg_get(cfg, "cluster",     "rcon_password",              "ChangeMe123")
    max_players   = _cfg_get(cfg, "performance", "max_players",                "70")
    allow_tp      = _cfg_get(cfg, "flags",       "allow_third_person",         "false").lower() == "true"
    show_map_loc  = _cfg_get(cfg, "flags",       "show_map_player_location",   "true").lower()  == "true"
    no_dl_surv    = _cfg_get(cfg, "flags",       "prevent_download_survivors", "false").lower() == "true"
    no_dl_items   = _cfg_get(cfg, "flags",       "prevent_download_items",     "false").lower() == "true"

    # ── Resolve EXE ───────────────────────────────────────────────────────────
    exe = os.path.join(server_root, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    if not os.path.exists(exe):
        print(f"ArkAscendedServer.exe not found at:\n  {exe}")
        print("\nCheck server_root in config.ini, or run the controller to download the server.")
        input("\nPress Enter to close...")
        sys.exit(1)

    # ── Patch GameUserSettings.ini with rates from config.ini ─────────────────
    print("Applying rates from config.ini...")
    _patch_game_user_settings(cfg, server_root)

    # ── Build launch command ──────────────────────────────────────────────────
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
    if allow_tp:     flags.append("-AllowThirdPersonPlayer")
    if show_map_loc: flags.append("-ShowMapPlayerLocation")
    if no_dl_surv:   flags.append("-PreventDownloadSurvivors")
    if no_dl_items:  flags.append("-PreventDownloadItems")

    # ── Launch ────────────────────────────────────────────────────────────────
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
