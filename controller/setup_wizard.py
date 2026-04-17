"""
setup_wizard.py — First-run (or re-run) configuration wizard.
Writes config.ini in the same directory.
"""

import io
import os
import re
import time
import subprocess
import urllib.request
import zipfile
import configparser
from pathlib import Path

CONFIG_PATH      = Path(__file__).resolve().parent / "config.ini"
_STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
_ASA_APP_ID   = "2430930"

MAPS = [
    "ragnarok",
    "thecenter",
    "valguero",
    "theisland",
    "scorchedearth",
    "aberration",
    "extinction",
    "lostcolony",
    "astraeos",
]


def _ask(prompt: str, default: str = "") -> str:
    """Ask a question, show default, return stripped answer (or default)."""
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    while True:
        answer = input(display).strip()
        if answer:
            return answer
        if default:
            return default
        print("  This field is required.")


def _ask_int(prompt: str, default: int, min_val: int = 1, max_val: int = 100) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw)
            if min_val <= value <= max_val:
                return value
            print(f"  Please enter a number between {min_val} and {max_val}.")
        except ValueError:
            print("  Please enter a whole number.")


def _ask_choice(prompt: str, choices: list, default: str) -> str:
    opts = ", ".join(choices)
    while True:
        raw = _ask(f"{prompt} ({opts})", default)
        if raw in choices:
            return raw
        print(f"  Please choose one of: {opts}")


def _ask_time_optional(prompt: str, default: str = "") -> str:
    """Ask for an optional HH:MM time. Empty string means disabled."""
    hint = default if default else "disabled"
    print(f"  {prompt} — use HH:MM format (e.g. 4:00 or 04:00), or press Enter to disable.")
    while True:
        raw = input(f"  [{hint}]: ").strip()
        if not raw:
            return default
        if re.fullmatch(r"\d{1,2}:\d{2}", raw):
            h, m = int(raw.split(":")[0]), int(raw.split(":")[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        print("  Invalid time. Please use HH:MM format (e.g. 4:00).")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


def _download_steamcmd(steamcmd_exe: str) -> bool:
    install_dir = os.path.dirname(steamcmd_exe)
    os.makedirs(install_dir, exist_ok=True)
    print("  Downloading SteamCMD...")
    try:
        with urllib.request.urlopen(_STEAMCMD_URL, timeout=60) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(install_dir)
        print("  Initializing SteamCMD (downloads its own runtime — may take a minute)...")
        subprocess.run([steamcmd_exe, "+quit"], check=False)
        print("  SteamCMD ready.")
        return True
    except Exception as exc:
        print(f"  Download failed: {exc}")
        return False


def _download_asa_server(steamcmd_exe: str, server_root: str) -> bool:
    print(f"  Downloading ASA dedicated server to: {server_root}")
    print("  This will take a while (~15 GB). Progress is shown below.")
    print()
    try:
        result = subprocess.run(
            [steamcmd_exe,
             "+@sSteamCmdForcePlatformType", "windows",
             "+force_install_dir", server_root,
             "+login", "anonymous",
             "+app_update", _ASA_APP_ID, "validate",
             "+quit"],
            check=False,
        )
        print()
        if result.returncode == 0:
            print("  ASA server downloaded successfully.")
            return True
        print(f"  SteamCMD exited with code {result.returncode}. Check output above for errors.")
        return False
    except Exception as exc:
        print(f"  Download failed: {exc}")
        return False


def _check_and_setup_dependencies(steamcmd_exe: str, server_root: str) -> None:
    """Auto-download SteamCMD and/or the ASA server if they are missing."""
    ark_exe = os.path.join(
        server_root, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe"
    )

    # ── SteamCMD ──────────────────────────────────────────────────────────
    if not os.path.exists(steamcmd_exe):
        print(f"\nSteamCMD not found at: {steamcmd_exe}")
        print("Downloading SteamCMD automatically...")
        if not _download_steamcmd(steamcmd_exe):
            print("  SteamCMD download failed. Install it manually and re-run.")
            return

    # ── ASA server ────────────────────────────────────────────────────────
    if not os.path.exists(ark_exe):
        print(f"\nASA server not found — downloading automatically (~15 GB)...")
        _download_asa_server(steamcmd_exe, server_root)


def config_exists() -> bool:
    return CONFIG_PATH.exists()


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def run_wizard(existing: configparser.ConfigParser | None = None) -> configparser.ConfigParser:
    """
    Run the interactive setup wizard.
    If `existing` is provided, its values are used as defaults.
    Returns a populated ConfigParser (already written to disk).
    """
    prev = existing or configparser.ConfigParser()

    def prev_get(section: str, key: str, fallback: str = "") -> str:
        try:
            return prev.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    print()
    print("=" * 52)
    print("  ASA Cluster Controller — Setup Wizard")
    print("=" * 52)
    print()

    # ── Cluster identity ──────────────────────────────────
    print("[ Cluster identity ]")
    print()

    cluster_name = _ask(
        "Cluster name (used as <ClusterName>_<MapName>)",
        prev_get("cluster", "cluster_name", "MyCluster"),
    )
    cluster_id = cluster_name.replace(" ", "") + "Cluster"
    rcon_password = _ask(
        "RCON / admin password",
        prev_get("cluster", "rcon_password", "ChangeMe123"),
    )
    default_map = _ask_choice(
        "Default map (always kept running)",
        MAPS,
        prev_get("cluster", "default_map", "ragnarok"),
    )
    print()

    # ── Paths ─────────────────────────────────────────────
    print("[ Server paths ]")
    print()
    print("  All files will be installed under a single base directory.")
    print()

    # Derive default base from existing server_root if it ends with \asa_server,
    # otherwise default to the folder the controller itself lives in (one level up
    # from the controller/ directory) so everything stays self-contained.
    _prev_root = prev_get("paths", "server_root", "")
    if _prev_root and os.path.basename(_prev_root).lower() == "asa_server":
        _default_base = os.path.dirname(_prev_root)
    else:
        _default_base = str(Path(__file__).resolve().parent.parent)

    base_dir = _ask("Base installation directory", _default_base)
    server_root   = os.path.join(base_dir, "asa_server")
    cluster_dir   = os.path.join(base_dir, "asa_server", "cluster")
    _drive = os.path.splitdrive(str(Path(__file__).resolve()))[0] + os.sep
    steamcmd_path = os.path.join(_drive, "SteamCMD", "steamcmd.exe")

    print(f"  → Server root : {server_root}")
    print(f"  → Cluster dir : {cluster_dir}")
    print(f"  → SteamCMD    : {steamcmd_path}")
    print()

    # ── Performance ───────────────────────────────────────
    print("[ Performance ]")
    print()
    print("  Each active map requires roughly 10 GB of free RAM.")
    print("  Make sure your machine has enough before increasing this limit.")
    print()

    max_active = _ask_int(
        "Maximum simultaneously active maps",
        default=int(prev_get("performance", "max_active_servers", "3")),
        min_val=1,
        max_val=len(MAPS),
    )
    ram_needed = max_active * 10
    print(f"  → You will need at least {ram_needed} GB of RAM for {max_active} active map(s).")
    print()

    max_players = _ask_int(
        "Max players per map",
        default=int(prev_get("performance", "max_players", "70")),
        min_val=1,
        max_val=200,
    )
    print()

    # ── Timers ────────────────────────────────────────────
    print("[ Timers  (press Enter to keep defaults) ]")
    print()

    poll_seconds = _ask_int(
        "Controller poll interval (seconds)",
        default=int(prev_get("timers", "poll_seconds", "5")),
        min_val=1, max_val=60,
    )
    map_shutdown_minutes = _ask_int(
        "Shut down an empty map after N minutes",
        default=int(prev_get("timers", "map_shutdown_minutes", "15")),
        min_val=1, max_val=1440,
    )
    startup_grace_minutes = _ask_int(
        "Startup grace period before empty-check (minutes)",
        default=int(prev_get("timers", "startup_grace_minutes", "15")),
        min_val=1, max_val=60,
    )
    autosave_minutes = _ask_int(
        "Auto-save interval (minutes)",
        default=int(prev_get("timers", "autosave_minutes", "15")),
        min_val=1, max_val=120,
    )
    cluster_shutdown_minutes = _ask_int(
        "Default cluster-shutdown countdown (minutes)",
        default=int(prev_get("timers", "cluster_shutdown_minutes", "30")),
        min_val=1, max_val=1440,
    )
    print()

    # ── Backup ────────────────────────────────────────────
    print("[ Backups ]")
    print()

    _default_backup_dir = os.path.join(base_dir, "backups")
    backup_dir = _ask(
        "Backup directory",
        prev_get("backup", "backup_dir", _default_backup_dir),
    )
    max_backups = _ask_int(
        "Maximum number of backups to keep",
        default=int(prev_get("backup", "max_backups", "10")),
        min_val=1, max_val=100,
    )
    print()

    # ── Schedule ──────────────────────────────────────────
    print("[ Schedule ]")
    print()

    check_updates_on_startup = _ask_yes_no(
        "Check for server updates on every startup?",
        default=prev_get("schedule", "check_updates_on_startup", "true").lower() != "false",
    )
    restart_time = _ask_time_optional(
        "Daily restart time (leave blank to disable)",
        prev_get("schedule", "restart_time", "06:00"),
    )
    if restart_time:
        print(f"  → Cluster will restart and update daily at {restart_time}.")
    else:
        print("  → Scheduled restart disabled.")
    print()

    # ── Rates ─────────────────────────────────────────────
    print("[ Game rates  (press Enter to keep defaults) ]")
    print()

    def _ask_float(prompt: str, default: float) -> str:
        while True:
            raw = _ask(prompt, str(default))
            try:
                float(raw)
                return raw
            except ValueError:
                print("  Please enter a number (e.g. 1.0 or 2.5).")

    xp_multiplier             = _ask_float("XP multiplier",             float(prev_get("rates", "xp_multiplier",             "1.0")))
    taming_speed_multiplier   = _ask_float("Taming speed multiplier",   float(prev_get("rates", "taming_speed_multiplier",   "1.0")))
    harvest_amount_multiplier = _ask_float("Harvest amount multiplier", float(prev_get("rates", "harvest_amount_multiplier", "1.0")))
    difficulty_offset         = _ask_float("Difficulty offset (1.0=max level 150)", float(prev_get("rates", "difficulty_offset", "1.0")))
    print()

    # ── Breeding ──────────────────────────────────────────
    print("[ Breeding  (press Enter to keep defaults) ]")
    print()

    mating_interval_mult = _ask_float("Mating interval multiplier", float(prev_get("rates", "mating_interval_multiplier", "1.0")))
    egg_hatch_speed_mult = _ask_float("Egg hatch speed multiplier",  float(prev_get("rates", "egg_hatch_speed_multiplier",  "1.0")))

    baby_mature_speed = _ask_float(
        "Baby mature speed multiplier",
        float(prev_get("breeding", "baby_mature_speed_multiplier", "1.0")),
    )

    _ms = float(baby_mature_speed)
    _rec_interval = round(1.8 / _ms, 4) if _ms > 0 else 1.0
    _rec_grace    = round(max(5.0, _ms / 10), 1)
    _rec_imprint  = 20.0

    baby_cuddle_interval = _ask_float("Baby cuddle interval multiplier",    _rec_interval)
    baby_cuddle_grace    = _ask_float("Baby cuddle grace period multiplier", _rec_grace)
    baby_imprint_amount  = _ask_float("Baby imprint amount multiplier",      _rec_imprint)
    print()

    # ── Confirm & write ───────────────────────────────────
    print("[ Summary ]")
    print()
    print(f"  Cluster name      : {cluster_name}")
    print(f"  Cluster ID        : {cluster_id}  (auto-derived)")
    print(f"  RCON password     : {rcon_password}")
    print(f"  Default map       : {default_map}")
    print(f"  Base directory    : {base_dir}")
    print(f"  Max active maps   : {max_active}  (~{ram_needed} GB RAM)")
    print(f"  Max players/map   : {max_players}")
    print(f"  Poll interval     : {poll_seconds}s")
    print(f"  Empty-map timeout : {map_shutdown_minutes} min")
    print(f"  Startup grace     : {startup_grace_minutes} min")
    print(f"  Auto-save         : {autosave_minutes} min")
    print(f"  Cluster shutdown  : {cluster_shutdown_minutes} min")
    print(f"  Backup directory  : {backup_dir}")
    print(f"  Max backups       : {max_backups}")
    print(f"  Update on startup : {'yes' if check_updates_on_startup else 'no'}")
    print(f"  Daily restart     : {restart_time if restart_time else 'disabled'}")
    print(f"  XP multiplier     : {xp_multiplier}")
    print(f"  Taming speed      : {taming_speed_multiplier}")
    print(f"  Harvest amount    : {harvest_amount_multiplier}")
    print(f"  Difficulty offset : {difficulty_offset}")
    print(f"  Mating interval   : {mating_interval_mult}")
    print(f"  Egg hatch speed   : {egg_hatch_speed_mult}")
    print(f"  Mature speed      : {baby_mature_speed}")
    print(f"  Cuddle interval   : {baby_cuddle_interval}")
    print(f"  Cuddle grace      : {baby_cuddle_grace}")
    print(f"  Imprint amount    : {baby_imprint_amount}")
    print()

    if not _ask_yes_no("Save this configuration?", default=True):
        print("Setup cancelled. No changes were saved.")
        raise SystemExit(0)

    cfg = configparser.ConfigParser()

    cfg["cluster"] = {
        "cluster_name": cluster_name,
        "cluster_id": cluster_id,
        "rcon_password": rcon_password,
        "default_map": default_map,
    }
    cfg["network"] = {
        "rcon_host":      prev_get("network", "rcon_host",      "127.0.0.1"),
        "web_status_port": prev_get("network", "web_status_port", "8880"),
    }
    cfg["paths"] = {
        "server_root": server_root,
        "cluster_dir": cluster_dir,
        "steamcmd_path": steamcmd_path,
    }
    cfg["limits"] = {
        "max_active_servers":      str(max_active),
        "max_players":             str(max_players),
        "max_tamed_dinos":         prev_get("limits", "max_tamed_dinos",         "5000"),
        "max_personal_tamed_dinos":prev_get("limits", "max_personal_tamed_dinos","40"),
    }
    cfg["schedule"] = {
        "poll_seconds":             str(poll_seconds),
        "check_updates_on_startup": "true" if check_updates_on_startup else "false",
        "restart_time":             restart_time,
    }
    cfg["timers"] = {
        "map_shutdown_minutes":         str(map_shutdown_minutes),
        "startup_grace_minutes":        str(startup_grace_minutes),
        "autosave_minutes":             str(autosave_minutes),
        "cluster_shutdown_minutes":     str(cluster_shutdown_minutes),
        "server_start_timeout_seconds": prev_get("timers", "server_start_timeout_seconds", "300"),
        "save_before_exit_seconds":     prev_get("timers", "save_before_exit_seconds",      "10"),
        "post_shutdown_wait_seconds":   prev_get("timers", "post_shutdown_wait_seconds",     "30"),
        "crash_detection_threshold":    prev_get("timers", "crash_detection_threshold",      "5"),
    }
    cfg["backup"] = {
        "backup_dir":  backup_dir,
        "max_backups": str(max_backups),
    }
    cfg["world"] = {
        "day_time_speed_scale":                prev_get("world","day_time_speed_scale",               "1.0"),
        "night_time_speed_scale":              prev_get("world","night_time_speed_scale",             "1.0"),
        "dino_count_multiplier":               prev_get("world","dino_count_multiplier",              "1.0"),
        "resources_respawn_period_multiplier": prev_get("world","resources_respawn_period_multiplier","1.0"),
        "active_event":                        prev_get("world","active_event",                       ""),
        "disable_weather_fog":                 prev_get("world","disable_weather_fog",                "false"),
    }
    cfg["rates"] = {
        "xp_multiplier":                              xp_multiplier,
        "taming_speed_multiplier":                    taming_speed_multiplier,
        "harvest_amount_multiplier":                  harvest_amount_multiplier,
        "difficulty_offset":                          difficulty_offset,
        "item_stack_size_multiplier":                 prev_get("rates","item_stack_size_multiplier",                "1.0"),
        "loot_quality_multiplier":                    prev_get("rates","loot_quality_multiplier",                   "1.0"),
        "fishing_loot_quality_multiplier":            prev_get("rates","fishing_loot_quality_multiplier",           "1.0"),
        "supply_crate_loot_quality_multiplier":       prev_get("rates","supply_crate_loot_quality_multiplier",      "1.0"),
        "global_spoiling_time_multiplier":            prev_get("rates","global_spoiling_time_multiplier",           "1.0"),
        "global_item_decomposition_time_multiplier":  prev_get("rates","global_item_decomposition_time_multiplier", "1.0"),
        "global_corpse_decomposition_time_multiplier":prev_get("rates","global_corpse_decomposition_time_multiplier","1.0"),
        "crop_growth_speed_multiplier":               prev_get("rates","crop_growth_speed_multiplier",              "1.0"),
        "fuel_consumption_interval_multiplier":       prev_get("rates","fuel_consumption_interval_multiplier",      "1.0"),
    }
    cfg["survival"] = {
        "player_food_drain_multiplier":       prev_get("survival","player_food_drain_multiplier",      "1.0"),
        "player_water_drain_multiplier":      prev_get("survival","player_water_drain_multiplier",     "1.0"),
        "player_stamina_drain_multiplier":    prev_get("survival","player_stamina_drain_multiplier",   "1.0"),
        "player_health_recovery_multiplier":  prev_get("survival","player_health_recovery_multiplier", "1.0"),
        "dino_food_drain_multiplier":         prev_get("survival","dino_food_drain_multiplier",        "1.0"),
        "dino_health_recovery_multiplier":    prev_get("survival","dino_health_recovery_multiplier",   "1.0"),
    }
    cfg["combat"] = {
        "player_damage_multiplier":         prev_get("combat","player_damage_multiplier",        "1.0"),
        "player_resistance_multiplier":     prev_get("combat","player_resistance_multiplier",    "1.0"),
        "dino_damage_multiplier":           prev_get("combat","dino_damage_multiplier",          "1.0"),
        "dino_resistance_multiplier":       prev_get("combat","dino_resistance_multiplier",      "1.0"),
        "tamed_dino_damage_multiplier":     prev_get("combat","tamed_dino_damage_multiplier",    "1.0"),
        "tamed_dino_resistance_multiplier": prev_get("combat","tamed_dino_resistance_multiplier","1.0"),
        "structure_damage_multiplier":      prev_get("combat","structure_damage_multiplier",     "1.0"),
        "show_floating_damage_text":        prev_get("combat","show_floating_damage_text",       "false"),
        "allow_hit_markers":                prev_get("combat","allow_hit_markers",               "true"),
    }
    cfg["breeding"] = {
        "mating_interval_multiplier":          mating_interval_mult,
        "mating_speed_multiplier":             prev_get("breeding","mating_speed_multiplier",    "1.0"),
        "egg_hatch_speed_multiplier":          egg_hatch_speed_mult,
        "lay_egg_interval_multiplier":         prev_get("breeding","lay_egg_interval_multiplier","1.0"),
        "baby_mature_speed_multiplier":        baby_mature_speed,
        "baby_cuddle_interval_multiplier":     baby_cuddle_interval,
        "baby_cuddle_grace_period_multiplier": baby_cuddle_grace,
        "baby_imprint_amount_multiplier":      baby_imprint_amount,
    }
    cfg["structures"] = {
        "structure_pickup_time_after_placement":    prev_get("structures","structure_pickup_time_after_placement",   "30"),
        "per_platform_max_structures_multiplier":   prev_get("structures","per_platform_max_structures_multiplier",  "1.0"),
    }
    cfg["flags"] = {
        "allow_third_person":              prev_get("flags","allow_third_person",              "false"),
        "show_map_player_location":        prev_get("flags","show_map_player_location",        "true"),
        "always_allow_structure_pickup":   prev_get("flags","always_allow_structure_pickup",   "true"),
        "disable_structure_decay_pve":     prev_get("flags","disable_structure_decay_pve",     "false"),
        "disable_dino_decay_pve":          prev_get("flags","disable_dino_decay_pve",          "false"),
        "allow_cave_building_pve":         prev_get("flags","allow_cave_building_pve",         "false"),
        "allow_anyone_baby_imprint_cuddle":prev_get("flags","allow_anyone_baby_imprint_cuddle","false"),
        "allow_flyer_carry_pve":           prev_get("flags","allow_flyer_carry_pve",           "true"),
        "allow_flyer_speed_leveling":      prev_get("flags","allow_flyer_speed_leveling",      "false"),
        "prevent_download_survivors":      prev_get("flags","prevent_download_survivors",      "false"),
        "prevent_download_items":          prev_get("flags","prevent_download_items",          "false"),
        "require_powered_cryofridge":      prev_get("flags","require_powered_cryofridge",      "true"),
        "disable_cryo_sickness_pvp":       prev_get("flags","disable_cryo_sickness_pvp",       "false"),
        "force_allow_cave_flyers":         prev_get("flags","force_allow_cave_flyers",          "false"),
        "exclusive_join":                  prev_get("flags","exclusive_join",                   "false"),
    }
    cfg["mods"] = {
        "crossplay": prev_get("mods","crossplay","false"),
        "mod_ids":   prev_get("mods","mod_ids",  ""),
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"  Config saved to: {CONFIG_PATH}")
    print()

    _check_and_setup_dependencies(steamcmd_path, server_root)

    return cfg


def prompt_setup_on_startup() -> configparser.ConfigParser:
    """
    Called at controller startup.
    If config.ini is missing, runs the interactive setup wizard right here
    in the CMD window.  If config.ini already exists, loads and returns it.
    Returns the active ConfigParser.
    """
    if not config_exists():
        return run_wizard()
    return load_config()


if __name__ == "__main__":
    run_wizard()
