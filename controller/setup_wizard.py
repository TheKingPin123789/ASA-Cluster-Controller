"""
setup_wizard.py — First-run (or re-run) configuration wizard.
Writes config.ini in the same directory.
"""

import ctypes
import io
import os
import re
import time
import hashlib
import getpass
import subprocess
import urllib.request
import zipfile
import configparser
from pathlib import Path
from config_crypt import encrypt_cfg_value, decrypt_cfg_value

CONFIG_PATH      = Path(__file__).resolve().parent / "config.ini"


def _wizard_ram_max_maps() -> int:
    """Return the RAM-based suggested max concurrent maps: floor((total_gb - 15) / 12), min 1."""
    try:
        class _MEMSTATEX(ctypes.Structure):
            _fields_ = [
                ("dwLength",                ctypes.c_ulong),
                ("dwMemoryLoad",            ctypes.c_ulong),
                ("ullTotalPhys",            ctypes.c_ulonglong),
                ("ullAvailPhys",            ctypes.c_ulonglong),
                ("ullTotalPageFile",        ctypes.c_ulonglong),
                ("ullAvailPageFile",        ctypes.c_ulonglong),
                ("ullTotalVirtual",         ctypes.c_ulonglong),
                ("ullAvailVirtual",         ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = _MEMSTATEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_gb = stat.ullTotalPhys / (1024 ** 3)
        if total_gb > 15:
            return max(1, int((total_gb - 15) / 12))
    except Exception:
        pass
    return 3


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


def _ask_optional(prompt: str, hint: str = "skip") -> str:
    """Ask a question where pressing Enter returns an empty string (field is optional)."""
    return input(f"{prompt} [{hint}]: ").strip()


def _ask_password_optional() -> str:
    """Ask for a password without echoing it to the screen. Enter skips."""
    try:
        pw = getpass.getpass("  Password [skip]: ").strip()
    except Exception:
        # Fallback if getpass isn't available (e.g. redirected stdin)
        pw = input("  Password [skip]: ").strip()
    return pw


def _hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 with a random salt.
    Format: pbkdf2:<salt_hex>:<hash_hex>"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2:{salt.hex()}:{key.hex()}"


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
        prev_get("cluster", "default_map", "theisland"),
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
    _ram_suggested = _wizard_ram_max_maps()
    print(f"  Each active map requires roughly 12 GB of RAM, plus 15 GB overhead.")
    print(f"  Based on your system RAM, the suggested maximum is {_ram_suggested} map(s).")
    print(f"  You can set a lower value; setting a higher value is not recommended.")
    print()

    _prev_max = int(prev_get("limits", "max_active_servers", str(_ram_suggested)))
    max_active = _ask_int(
        "Maximum simultaneously active maps",
        default=min(_prev_max, _ram_suggested),
        min_val=1,
        max_val=len(MAPS),
    )
    ram_needed = max_active * 12 + 15
    print(f"  → You will need at least {ram_needed} GB of RAM for {max_active} active map(s) + overhead.")
    print()

    max_players = _ask_int(
        "Max players per map",
        default=int(prev_get("limits", "max_players", "70")),
        min_val=1,
        max_val=500,
    )
    print()

    # ── Timers ────────────────────────────────────────────
    print("[ Timers  (press Enter to keep defaults) ]")
    print()

    poll_seconds = _ask_int(
        "Controller poll interval (seconds)",
        default=int(prev_get("schedule", "poll_seconds", "5")),
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
        min_val=1, max_val=25,
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
    _rec_imprint  = 100.0  # guarantees 100% imprint in 1 cuddle for any creature

    baby_cuddle_interval = _ask_float("Baby cuddle interval multiplier",    _rec_interval)
    baby_cuddle_grace    = _ask_float("Baby cuddle grace period multiplier", _rec_grace)
    baby_imprint_amount  = _ask_float("Baby imprint amount multiplier",      _rec_imprint)
    print()

    # ── Dashboard login ───────────────────────────────────
    print("[ Dashboard login ]")
    print()
    print("  Set a username and password to protect the web dashboard.")
    print("  Press Enter for both to skip — the dashboard will open without a login page.")
    print("  To change credentials later, re-run setup_wizard.py.")
    print()

    _prev_user = prev_get("auth", "username", "")
    _has_existing_auth = bool(prev_get("auth", "password_hash", ""))

    if _has_existing_auth:
        print(f"  Existing credentials found (username: {_prev_user}).")
        _keep_auth = _ask_yes_no("  Keep existing credentials?", default=True)
        if _keep_auth:
            dash_username = _prev_user
            dash_password_hash = prev_get("auth", "password_hash", "")
        else:
            dash_username = _ask_optional("  Username", hint=_prev_user or "skip")
            if dash_username:
                dash_password_hash = None  # will prompt below
            else:
                dash_password_hash = ""    # clearing auth
    else:
        dash_username = _ask_optional("  Username", hint="skip")
        dash_password_hash = None  # will prompt below if username set

    if dash_username and dash_password_hash is None:
        # Need to collect a password
        while True:
            pw1 = _ask_password_optional()
            if not pw1:
                print("  No password entered — login will be disabled.")
                dash_username = ""
                dash_password_hash = ""
                break
            pw2 = _ask_password_optional()
            if pw1 == pw2:
                dash_password_hash = _hash_password(pw1)
                break
            print("  Passwords do not match — please try again.")
    elif not dash_username:
        dash_password_hash = ""

    if dash_username and dash_password_hash:
        print(f"  → Dashboard login enabled (username: {dash_username})")
    else:
        print("  → Dashboard login disabled — no login page will be shown.")
    print()

    # ── Dashboard port & VPS ──────────────────────────────
    print("[ Dashboard access ]")
    print()
    print("  Live server = dashboard accessible from outside your PC (anyone with the IP).")
    print("  Localhost   = dashboard only accessible from this PC.")
    print()
    _prev_public = prev_get("network", "dashboard_public", "false").lower() == "true"
    dashboard_public = _ask_yes_no("Run as live server (accessible from outside)?", default=_prev_public)
    if dashboard_public:
        print("  → Dashboard will be accessible from outside this PC.")
    else:
        print("  → Dashboard will only be accessible from this PC (localhost).")
    print()
    print("  Port the web dashboard listens on.")
    print("  Leave blank to use the default (5000).")
    _raw_port = _ask(
        "Dashboard port (leave blank for 5000)",
        prev_get("network", "web_status_port", ""),
    ).strip()
    if _raw_port:
        try:
            web_status_port = str(int(_raw_port))
        except ValueError:
            print("  Invalid port — using 5000.")
            web_status_port = "5000"
    else:
        web_status_port = "5000"

    if dashboard_public:
        print()
        print("  If you use a VPS relay (WireGuard tunnel) so outside players")
        print("  can reach the server, enter the VPS public IP here.")
        print("  Leave blank if players connect directly to your home IP.")
        public_ip = _ask(
            "VPS public IP (leave blank if none)",
            prev_get("network", "public_ip", ""),
        ).strip()
        if public_ip:
            print(f"  → ARK will advertise {public_ip} to Steam.")
        else:
            print("  → No VPS relay — using direct connection.")
    else:
        # Always carry forward the existing IP even when live mode is off —
        # so re-enabling live mode later doesn't lose the setting.
        public_ip = prev_get("network", "public_ip", "")
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
    if dash_username and dash_password_hash:
        print(f"  Dashboard login   : enabled (username: {dash_username})")
    else:
        print( "  Dashboard login   : disabled (no login page)")
    print(f"  Live server       : {'yes (accessible from outside)' if dashboard_public else 'no (localhost only)'}")
    print(f"  Dashboard port    : {web_status_port}")
    print(f"  VPS public IP     : {public_ip if public_ip else 'none (direct connection)'}")
    print()

    if not _ask_yes_no("Save this configuration?", default=True):
        print("Setup cancelled. No changes were saved.")
        raise SystemExit(0)

    cfg = configparser.ConfigParser()

    cfg["cluster"] = {
        "cluster_name": cluster_name,
        "cluster_id": cluster_id,
        "rcon_password": encrypt_cfg_value(rcon_password),
        "default_map": default_map,
    }
    cfg["network"] = {
        "rcon_host":        prev_get("network", "rcon_host", "127.0.0.1"),
        "web_status_port":  web_status_port,
        "dashboard_public": "true" if dashboard_public else "false",
        "public_ip":        public_ip,  # always written; empty string = disabled
    }
    cfg["paths"] = {
        "server_root": server_root,
        "cluster_dir": cluster_dir,
        "steamcmd_path": steamcmd_path,
    }
    cfg["limits"] = {
        "max_active_servers":       str(max_active),
        "max_players":              str(max_players),
        "max_tamed_dinos":          prev_get("limits", "max_tamed_dinos",          "5000"),
        "max_personal_tamed_dinos": prev_get("limits", "max_personal_tamed_dinos", "40"),
        "low_memory_mode":          prev_get("limits", "low_memory_mode",          "true"),
        "no_sound":                 prev_get("limits", "no_sound",                 "true"),
        "gc_purge_interval":        prev_get("limits", "gc_purge_interval",        "30"),
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
        "max_logs":    prev_get("backup", "max_logs", "10"),
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
    cfg["crash"] = {
        "auto_restart_on_crash":  prev_get("crash","auto_restart_on_crash",  "true"),
        "crash_grace_seconds":    prev_get("crash","crash_grace_seconds",    "120"),
        "crash_cooldown_minutes": prev_get("crash","crash_cooldown_minutes", "5"),
        "max_crash_restarts":     prev_get("crash","max_crash_restarts",     "3"),
        "crash_window_minutes":   prev_get("crash","crash_window_minutes",   "60"),
    }
    cfg["discord"] = {
        "discord_enabled":        prev_get("discord","discord_enabled",        "false"),
        "use_bot":                prev_get("discord","use_bot",                "false"),
        "webhook_url":            encrypt_cfg_value(decrypt_cfg_value(prev_get("discord","webhook_url",""))),
        "notify_server_events":   prev_get("discord","notify_server_events",   "true"),
        "notify_crash_events":    prev_get("discord","notify_crash_events",    "true"),
        "notify_cluster_events":  prev_get("discord","notify_cluster_events",  "true"),
        "bot_token":              encrypt_cfg_value(decrypt_cfg_value(prev_get("discord","bot_token",""))),
        "notification_channel_id":prev_get("discord","notification_channel_id",""),
        "command_channel_id":     prev_get("discord","command_channel_id",     ""),
        "admin_role_name":        prev_get("discord","admin_role_name",        "Admin"),
    }

    # Only write [auth] if credentials were provided — no section means auth disabled
    if dash_username and dash_password_hash:
        cfg["auth"] = {
            "username":      dash_username,
            "password_hash": dash_password_hash,
            # Preserve the existing secret_key so active browser sessions survive a
            # wizard re-run. The dashboard generates it on first start if missing.
            # Keep it encrypted — decrypt first so we don't double-encrypt.
            "secret_key":    encrypt_cfg_value(decrypt_cfg_value(prev_get("auth", "secret_key", ""))),
        }
    # If auth was cleared (user chose to disable), omit the section entirely so
    # the dashboard opens without a login page.

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"  Config saved to: {CONFIG_PATH}")
    print()

    _check_and_setup_dependencies(steamcmd_path, server_root)

    return cfg


# ── Hardcoded defaults for every key the controller/dashboard expects ─────────
_DEFAULTS: dict = {
    "cluster":  {"cluster_name": "MyCluster", "cluster_id": "MyClusterCluster",
                 "default_map": "theisland"},
    "network":  {"rcon_host": "127.0.0.1", "web_status_port": "5000",
                 "public_ip": "", "dashboard_public": "false"},
    "limits":   {"max_active_servers": "3", "max_players": "70",
                 "max_tamed_dinos": "5000", "max_personal_tamed_dinos": "40",
                 "low_memory_mode": "true", "no_sound": "true", "gc_purge_interval": "30"},
    "schedule": {"poll_seconds": "5", "check_updates_on_startup": "true", "restart_time": ""},
    "timers":   {"map_shutdown_minutes": "60", "startup_grace_minutes": "15",
                 "autosave_minutes": "30", "cluster_shutdown_minutes": "30",
                 "server_start_timeout_seconds": "300", "save_before_exit_seconds": "10",
                 "post_shutdown_wait_seconds": "30", "crash_detection_threshold": "5"},
    "backup":   {"max_backups": "10", "max_logs": "10"},
    "world":    {"day_time_speed_scale": "1.0", "night_time_speed_scale": "1.0",
                 "dino_count_multiplier": "1.0", "resources_respawn_period_multiplier": "1.0",
                 "active_event": "", "disable_weather_fog": "false"},
    "rates":    {"xp_multiplier": "1.0", "taming_speed_multiplier": "1.0",
                 "harvest_amount_multiplier": "1.0", "difficulty_offset": "1.0",
                 "item_stack_size_multiplier": "1.0", "loot_quality_multiplier": "1.0",
                 "fishing_loot_quality_multiplier": "1.0",
                 "supply_crate_loot_quality_multiplier": "1.0",
                 "global_spoiling_time_multiplier": "1.0",
                 "global_item_decomposition_time_multiplier": "1.0",
                 "global_corpse_decomposition_time_multiplier": "1.0",
                 "crop_growth_speed_multiplier": "1.0",
                 "fuel_consumption_interval_multiplier": "1.0"},
    "survival": {"player_food_drain_multiplier": "1.0", "player_water_drain_multiplier": "1.0",
                 "player_stamina_drain_multiplier": "1.0",
                 "player_health_recovery_multiplier": "1.0",
                 "dino_food_drain_multiplier": "1.0", "dino_health_recovery_multiplier": "1.0"},
    "combat":   {"player_damage_multiplier": "1.0", "player_resistance_multiplier": "1.0",
                 "dino_damage_multiplier": "1.0", "dino_resistance_multiplier": "1.0",
                 "tamed_dino_damage_multiplier": "1.0", "tamed_dino_resistance_multiplier": "1.0",
                 "structure_damage_multiplier": "1.0", "show_floating_damage_text": "false",
                 "allow_hit_markers": "true"},
    "breeding": {"mating_interval_multiplier": "1.0", "mating_speed_multiplier": "1.0",
                 "egg_hatch_speed_multiplier": "1.0", "lay_egg_interval_multiplier": "1.0",
                 "baby_mature_speed_multiplier": "1.0", "baby_cuddle_interval_multiplier": "1.8",
                 "baby_cuddle_grace_period_multiplier": "1.0",
                 "baby_imprint_amount_multiplier": "100.0"},
    "structures": {"structure_pickup_time_after_placement": "30",
                   "per_platform_max_structures_multiplier": "1.0"},
    "flags":    {"allow_third_person": "false", "show_map_player_location": "true",
                 "always_allow_structure_pickup": "true", "disable_structure_decay_pve": "false",
                 "disable_dino_decay_pve": "false", "allow_cave_building_pve": "false",
                 "allow_anyone_baby_imprint_cuddle": "false", "allow_flyer_carry_pve": "true",
                 "allow_flyer_speed_leveling": "false", "prevent_download_survivors": "false",
                 "prevent_download_items": "false", "require_powered_cryofridge": "true",
                 "disable_cryo_sickness_pvp": "false", "force_allow_cave_flyers": "false",
                 "exclusive_join": "false"},
    "mods":     {"crossplay": "false", "mod_ids": ""},
    "crash":    {"auto_restart_on_crash": "true", "crash_grace_seconds": "120",
                 "crash_cooldown_minutes": "5", "max_crash_restarts": "3",
                 "crash_window_minutes": "60"},
    "discord":  {"discord_enabled": "false", "use_bot": "false", "webhook_url": "",
                 "notify_server_events": "true", "notify_crash_events": "true",
                 "notify_cluster_events": "true", "bot_token": "",
                 "notification_channel_id": "", "command_channel_id": "",
                 "admin_role_name": "Admin"},
}

# Keys that are machine-specific paths — skip auto-filling if missing so the user
# is not surprised by wrong paths appearing silently.
_SKIP_AUTOFILL: set = {"server_root", "cluster_dir", "steamcmd_path", "backup_dir"}


def _backfill_config(cfg: configparser.ConfigParser) -> bool:
    """
    Add any missing sections/keys from _DEFAULTS to cfg in-place.
    Writes the updated config back to disk only if something was added.
    Returns True if the file was updated.
    """
    added: list[str] = []
    for section, keys in _DEFAULTS.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for key, default in keys.items():
            if key in _SKIP_AUTOFILL:
                continue
            if not cfg.has_option(section, key):
                cfg.set(section, key, default)
                added.append(f"[{section}] {key} = {default!r}")
    if added:
        try:
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                cfg.write(f)
            print(f"  Config backfilled {len(added)} missing key(s) with defaults.")
        except Exception as exc:
            print(f"  WARNING: could not write backfilled config: {exc}")
        return True
    return False


def prompt_setup_on_startup() -> configparser.ConfigParser:
    """
    Called at controller startup.
    If config.ini is missing, runs the interactive setup wizard right here
    in the CMD window.  If config.ini already exists, loads it and backfills
    any keys that are missing (e.g. after an update added new settings).
    Returns the active ConfigParser.
    """
    if not config_exists():
        return run_wizard()
    cfg = load_config()
    _backfill_config(cfg)
    return cfg


if __name__ == "__main__":
    run_wizard()
