import io
import os
import re
import sys
import json
import time
import shutil
import datetime
import subprocess
import configparser
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from setup_wizard import prompt_setup_on_startup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MCRCON_EXE = os.path.join(BASE_DIR, "mcrcon.exe")
ADMIN_COMMAND_FILE = os.path.join(BASE_DIR, "admin_commands.txt")
STATUS_FILE = os.path.join(BASE_DIR, "cluster_status.txt")
STATUS_JSON_FILE = os.path.join(BASE_DIR, "cluster_status.json")
LOG_FILE       = os.path.join(BASE_DIR, "controller.log")
ADMIN_LOG_FILE = os.path.join(BASE_DIR, "admin_log.txt")
STOP_FILE = os.path.join(BASE_DIR, "controller.stop")
RESTART_MAPS_FILE = os.path.join(BASE_DIR, "restart_maps.txt")
WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.txt")
WHITELIST_DISABLED_FLAG = os.path.join(BASE_DIR, "whitelist_disabled.flag")

# ── Load config (wizard runs here if needed) ──────────────
_cfg = prompt_setup_on_startup()

def _ci(section: str, key: str, fallback: str = "") -> str:
    try:
        return _cfg.get(section, key)
    except Exception:
        return fallback

CLUSTER_NAME                  = _ci("cluster",     "cluster_name",           "MyCluster")
CLUSTER_ID                    = CLUSTER_NAME.replace(" ", "") + "Cluster"
RCON_PASSWORD                 = _ci("cluster",     "rcon_password",          "ChangeMe123")
SERVER_ROOT                   = _ci("paths",       "server_root",            r"C:\asa_server")
CLUSTER_DIR                   = _ci("paths",       "cluster_dir",            rf"{SERVER_ROOT}\cluster")
STEAMCMD_EXE                  = _ci("paths",       "steamcmd_path",          r"C:\ASA_Cluster\SteamCMD\steamcmd.exe")
MAX_ACTIVE_SERVERS            = int(_ci("performance", "max_active_servers", "3"))
MAX_PLAYERS                   = int(_ci("performance", "max_players",         "70"))
POLL_SECONDS                  = int(_ci("timers",  "poll_seconds",           "5"))
MAP_SHUTDOWN_DELAY_SECONDS    = int(_ci("timers",  "map_shutdown_minutes",   "15")) * 60
STARTUP_GRACE_SECONDS         = int(_ci("timers",  "startup_grace_minutes",  "15")) * 60
AUTOSAVE_SECONDS              = int(_ci("timers",  "autosave_minutes",       "15")) * 60
CLUSTER_SHUTDOWN_DELAY_SECONDS = int(_ci("timers", "cluster_shutdown_minutes","30")) * 60

SAVE_BEFORE_EXIT_WAIT_SECONDS  = int(_ci("timers",  "save_before_exit_seconds",       "10"))
SERVER_START_TIMEOUT_SECONDS   = int(_ci("timers",  "server_start_timeout_seconds",   "300"))
POST_SHUTDOWN_WAIT_SECONDS     = int(_ci("timers",  "post_shutdown_wait_seconds",      "60"))
CRASH_DETECTION_THRESHOLD      = int(_ci("timers",  "crash_detection_threshold",       "5"))
DEFAULT_SERVER_KEY            = _ci("cluster",      "default_map",                   "ragnarok")
HOST                          = _ci("network",      "rcon_host",                     "127.0.0.1")
SHUTDOWN_WARNING_MINUTES      = {60, 30, 15, 10, 5, 4, 3, 2, 1}

RESTART_TIME              = _ci("schedule", "restart_time",             "06:00") # HH:MM or empty
CHECK_UPDATES_ON_STARTUP  = _ci("schedule", "check_updates_on_startup", "true").lower() == "true"

BACKUP_DIR   = _ci("backup", "backup_dir",   os.path.join(os.path.dirname(SERVER_ROOT), "backups"))
MAX_BACKUPS  = int(_ci("backup", "max_backups", "10"))

BABY_MATURE_SPEED_MULT        = _ci("breeding", "baby_mature_speed_multiplier",        "1.0")
BABY_CUDDLE_INTERVAL_MULT     = _ci("breeding", "baby_cuddle_interval_multiplier",     "1.0")
BABY_CUDDLE_GRACE_PERIOD_MULT = _ci("breeding", "baby_cuddle_grace_period_multiplier", "1.0")
BABY_IMPRINT_AMOUNT_MULT      = _ci("breeding", "baby_imprint_amount_multiplier",      "1.0")

XP_MULTIPLIER             = _ci("rates", "xp_multiplier",              "1.0")
TAMING_SPEED_MULTIPLIER   = _ci("rates", "taming_speed_multiplier",    "1.0")
HARVEST_AMOUNT_MULTIPLIER = _ci("rates", "harvest_amount_multiplier",  "1.0")
DIFFICULTY_OFFSET         = _ci("rates", "difficulty_offset",          "1.0")
MATING_INTERVAL_MULT      = _ci("rates", "mating_interval_multiplier", "1.0")
EGG_HATCH_SPEED_MULT      = _ci("rates", "egg_hatch_speed_multiplier", "1.0")

SHOULD_EXIT    = False
LAST_SUMMARY_LINE = None
_last_scheduled_restart_day: Optional[int] = None
_is_admin_context: bool = False   # True while processing an admin command


@dataclass
class ServerConfig:
    key: str
    display_name: str
    map_name: str
    host: str
    game_port: int
    query_port: int
    rcon_port: int
    password: Optional[str] = None


def _make_servers() -> Dict[str, ServerConfig]:
    """Build SERVERS from config-loaded values so session names and passwords are dynamic."""
    _map_defs = [
        # key              display_name      map_name             game_port  query_port  rcon_port
        ("ragnarok",       "Ragnarok",       "Ragnarok_WP",       7777,      27015,      27020),
        ("thecenter",      "The Center",     "TheCenter_WP",      7787,      27025,      27021),
        ("valguero",       "Valguero",       "Valguero_WP",       7797,      27035,      27022),
        ("theisland",      "The Island",     "TheIsland_WP",      7807,      27045,      27023),
        ("scorchedearth",  "Scorched Earth", "ScorchedEarth_WP",  7817,      27055,      27024),
        ("aberration",     "Aberration",     "Aberration_WP",     7827,      27065,      27025),
        ("extinction",     "Extinction",     "Extinction_WP",     7837,      27075,      27026),
        ("lostcolony",     "Lost Colony",    "LostColony_WP",     7847,      27085,      27027),
        ("astraeos",       "Astraeos",       "Astraeos_WP",       7857,      27095,      27028),
    ]
    result = {}
    for key, display, map_name, game_port, query_port, rcon_port in _map_defs:
        result[key] = ServerConfig(
            key=key,
            display_name=display,
            map_name=map_name,
            host=HOST,
            game_port=game_port,
            query_port=query_port,
            rcon_port=rcon_port,
            password=RCON_PASSWORD,
        )
    return result

SERVERS: Dict[str, ServerConfig] = _make_servers()

ALIASES = {
    "tc": "thecenter",
    "center": "thecenter",
    "thecenter": "thecenter",
    "rag": "ragnarok",
    "ragnarok": "ragnarok",
    "val": "valguero",
    "valguero": "valguero",
    "ti": "theisland",
    "island": "theisland",
    "theisland": "theisland",
    "se": "scorchedearth",
    "scorched": "scorchedearth",
    "scorchedearth": "scorchedearth",
    "ab": "aberration",
    "abberation": "aberration",
    "aberration": "aberration",
    "ext": "extinction",
    "extinction": "extinction",
    "lost": "lostcolony",
    "lostcolony": "lostcolony",
    "astraeos": "astraeos",
}


@dataclass
class ServerState:
    cfg: ServerConfig
    is_running: bool = False
    is_starting: bool = False
    start_requested_at: Optional[float] = None
    last_seen_online_at: Optional[float] = None
    last_player_seen_at: Optional[float] = None
    empty_since: Optional[float] = None
    last_autosave_at: float = 0.0
    seen_log_lines: set = field(default_factory=set)
    players: set = field(default_factory=set)
    player_count: int = 0
    online_since: Optional[float] = None
    last_rcon_error: Optional[str] = None
    manual_stop_since: Optional[float] = None
    manual_stop_last_announcement_remaining: Optional[int] = None
    manual_stop_duration_seconds: int = 0
    pending_online_announcement: bool = False
    rcon_fail_count: int = 0
    pending_restart: bool = False
    player_list: List[Dict] = field(default_factory=list)


@dataclass
class ClusterState:
    shutdown_scheduled: bool = False
    shutdown_at: Optional[float] = None
    last_announcement_remaining: Optional[int] = None
    cluster_stopped: bool = False
    restart_pending: bool = False


SERVER_STATES: Dict[str, ServerState] = {k: ServerState(cfg=v) for k, v in SERVERS.items()}
CLUSTER = ClusterState()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    target = ADMIN_LOG_FILE if _is_admin_context else LOG_FILE
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_whitelist() -> set:
    """Return set of whitelisted Steam IDs. Empty set = whitelist disabled (all allowed)."""
    if not os.path.exists(WHITELIST_FILE):
        return set()
    try:
        with open(WHITELIST_FILE, encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip() and not line.startswith("#")}
    except Exception:
        return set()


def is_whitelisted(steam_id: Optional[str]) -> bool:
    if os.path.exists(WHITELIST_DISABLED_FLAG):
        return True  # whitelist disabled — everyone can use !start
    whitelist = load_whitelist()
    if not whitelist:
        return True  # no whitelist file = open to all
    return steam_id in whitelist if steam_id else False


def rcon_command(cfg: ServerConfig, cmd: str, timeout: float = 8.0) -> str:
    result = subprocess.run(
        [
            MCRCON_EXE,
            "-H", cfg.host,
            "-P", str(cfg.rcon_port),
            "-p", cfg.password or RCON_PASSWORD,
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(stderr or stdout or f"mcrcon failed with code {result.returncode}")

    return (result.stdout or "").strip()


def normalize_map_name(raw: str) -> Optional[str]:
    cleaned = re.sub(r"[^a-z]", "", raw.lower())
    if cleaned in SERVERS:
        return cleaned
    return ALIASES.get(cleaned)


def online_servers() -> List[ServerState]:
    return [s for s in SERVER_STATES.values() if s.is_running]


def active_servers() -> List[ServerState]:
    return [s for s in SERVER_STATES.values() if s.is_running or s.is_starting]


def servers_to_probe() -> List[ServerState]:
    result = [s for s in SERVER_STATES.values() if s.is_running or s.is_starting]
    default_state = SERVER_STATES[DEFAULT_SERVER_KEY]
    if default_state not in result:
        # Only probe the default server if the exe exists — avoids RCON
        # failure spam while the server is still being downloaded/installed.
        exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
        if os.path.exists(exe):
            result.append(default_state)
    return result


def other_server_running(key: str) -> bool:
    return any(s.is_running for s in SERVER_STATES.values() if s.cfg.key != key)


def cluster_has_players() -> bool:
    return any(s.player_count > 0 for s in SERVER_STATES.values())


def _patch_game_user_settings() -> None:
    """Write controlled settings from config.ini into GameUserSettings.ini before server launch."""
    settings_path = os.path.join(
        SERVER_ROOT, "ShooterGame", "Saved", "Config", "WindowsServer", "GameUserSettings.ini"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    gus = configparser.RawConfigParser(strict=False)
    gus.optionxform = str  # preserve key casing
    if os.path.exists(settings_path):
        gus.read(settings_path, encoding="utf-8")

    if not gus.has_section("ServerSettings"):
        gus.add_section("ServerSettings")

    desired = {
        "MaxPlayers":                    str(MAX_PLAYERS),
        "XPMultiplier":                  XP_MULTIPLIER,
        "TamingSpeedMultiplier":         TAMING_SPEED_MULTIPLIER,
        "HarvestAmountMultiplier":       HARVEST_AMOUNT_MULTIPLIER,
        "DifficultyOffset":              DIFFICULTY_OFFSET,
        "MatingIntervalMultiplier":      MATING_INTERVAL_MULT,
        "EggHatchSpeedMultiplier":       EGG_HATCH_SPEED_MULT,
        "BabyMatureSpeedMultiplier":     BABY_MATURE_SPEED_MULT,
        "BabyCuddleIntervalMultiplier":  BABY_CUDDLE_INTERVAL_MULT,
        "BabyCuddleGracePeriodMultiplier": BABY_CUDDLE_GRACE_PERIOD_MULT,
        "BabyImprintAmountMultiplier":   BABY_IMPRINT_AMOUNT_MULT,
    }

    changed = []
    for key, value in desired.items():
        if gus.get("ServerSettings", key, fallback=None) != value:
            gus.set("ServerSettings", key, value)
            changed.append(f"{key}={value}")

    if not changed:
        return

    with open(settings_path, "w", encoding="utf-8") as f:
        gus.write(f)
    log(f"GameUserSettings.ini updated: {', '.join(changed)}")


def start_server(key: str) -> bool:
    state = SERVER_STATES[key]
    if state.is_running or state.is_starting:
        return False

    exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    if not os.path.exists(exe):
        log(f"ArkAscendedServer.exe not found at: {exe}")
        return False

    _patch_game_user_settings()

    session_name = f"{CLUSTER_NAME}_{state.cfg.display_name.replace(' ', '')}"
    map_arg = (
        f"{state.cfg.map_name}"
        f"?SessionName={session_name}"
        f"?MaxPlayers={MAX_PLAYERS}"
        f"?Port={state.cfg.game_port}"
        f"?QueryPort={state.cfg.query_port}"
        f"?RCONEnabled=True"
        f"?RCONPort={state.cfg.rcon_port}"
        f"?ServerAdminPassword={state.cfg.password or RCON_PASSWORD}"
    )
    flags = [
        "-server", "-log", "-servergamelog", "-NoBattlEye",
        f"-ClusterDirOverride={CLUSTER_DIR}",
        f"-ClusterId={CLUSTER_ID}",
    ]

    log(f"Starting {key}")
    subprocess.Popen(
        [exe, map_arg] + flags,
        cwd=os.path.dirname(exe),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    state.is_starting = True
    state.start_requested_at = time.time()
    state.pending_online_announcement = True
    return True


def announce(state: ServerState, message: str) -> None:
    try:
        rcon_command(state.cfg, f"ServerChat {message}")
        log(f"CHAT {state.cfg.key}: {message}")
    except Exception as exc:
        log(f"Failed chat on {state.cfg.key}: {exc}")


def announce_all_online(message: str) -> None:
    for state in online_servers():
        announce(state, message)


def save_world(state: ServerState) -> None:
    try:
        log(f"SaveWorld -> {state.cfg.key}")
        rcon_command(state.cfg, "SaveWorld", timeout=20.0)
        state.last_autosave_at = time.time()
    except Exception as exc:
        log(f"SaveWorld failed on {state.cfg.key}: {exc}")


def stop_server_safe(state: ServerState, reason: str) -> None:
    if not state.is_running:
        return

    log(f"Stopping {state.cfg.key} ({reason})")
    save_world(state)
    time.sleep(SAVE_BEFORE_EXIT_WAIT_SECONDS)

    try:
        rcon_command(state.cfg, "DoExit", timeout=10.0)
    except Exception as exc:
        log(f"DoExit failed on {state.cfg.key}: {exc}")

    state.is_running = False
    state.is_starting = False
    state.last_seen_online_at = None
    state.empty_since = None
    state.players.clear()
    state.player_list = []
    state.player_count = 0
    state.last_player_seen_at = None
    state.online_since = None
    state.manual_stop_since = None
    state.manual_stop_last_announcement_remaining = None
    state.manual_stop_duration_seconds = 0
    state.pending_online_announcement = False
    state.seen_log_lines.clear()


def split_chat_sender_and_message(line: str):
    line = line.strip()
    cmd_match = re.search(r"!(start|status|stop|help)\b.*$", line, re.IGNORECASE)
    if not cmd_match:
        return None, line

    message = cmd_match.group(0).strip()
    prefix = line[:cmd_match.start()].strip().rstrip(": ")
    prefix = re.sub(r"^\[[^\]]+\]\s*", "", prefix).strip()
    sender = prefix.split(":")[-1].strip() if ":" in prefix else prefix.strip()
    sender = re.sub(r"\s*\([^)]*\)\s*$", "", sender).strip()
    return sender or None, message


def handle_command(origin: ServerState, sender_name: Optional[str], steam_id: Optional[str], message: str) -> None:
    lowered = message.strip().lower()

    if lowered == "!help":
        announce(origin, "Commands: !help | !start <map> | !status")
        announce(origin, f"Maps: {', '.join(SERVERS.keys())}")
        return

    if lowered == "!status":
        active = [s for s in SERVER_STATES.values() if s.is_running]
        if active:
            parts = [f"{s.cfg.key}:{s.player_count}" for s in active]
            announce(origin, f"Active maps: {', '.join(parts)}")
        else:
            announce(origin, "No active maps")
        return

    start_match = re.match(r"!start\s+(.+)", lowered)
    if start_match:
        if not is_whitelisted(steam_id):
            announce(origin, "You are not whitelisted to use this command")
            return
        requested = normalize_map_name(start_match.group(1))
        if not requested:
            return

        state = SERVER_STATES[requested]
        if state.is_running or state.is_starting:
            return

        active = len(active_servers())
        if active >= MAX_ACTIVE_SERVERS:
            announce(origin, f"Max servers active ({active}/{MAX_ACTIVE_SERVERS})")
            return

        start_server(requested)
        return



def restart_single_server(key: str) -> None:
    state = SERVER_STATES[key]
    if not state.is_running:
        log(f"{key} is not running")
        return
    log(f"RESTART {key}: saving and restarting...")
    announce(state, f"{state.cfg.display_name} is restarting now. Be back in a moment!")
    stop_server_safe(state, "map restart")
    start_server(key)


def _add_to_whitelist(steam_id: str) -> None:
    try:
        existing: set = set()
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, encoding="utf-8") as f:
                existing = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        existing.add(steam_id)
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(existing)) + "\n")
        log(f"Whitelist: added {steam_id}")
    except Exception as exc:
        log(f"Whitelist add failed: {exc}")


def _remove_from_whitelist(steam_id: str) -> None:
    try:
        existing: set = set()
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, encoding="utf-8") as f:
                existing = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        existing.discard(steam_id)
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(existing)) + "\n")
        log(f"Whitelist: removed {steam_id}")
    except Exception as exc:
        log(f"Whitelist remove failed: {exc}")


def send_admin_help() -> None:
    log("Admin commands:")
    log("  start <map>")
    log("  stop <map>")
    log("  cancel <map>")
    log("  restart <map>")
    log("  shutdown cluster")
    log("  shutdown cluster now")
    log("  shutdown cluster <time>   (e.g. 30m, 1h, 1h30m)")
    log("  restart")
    log("  restart now")
    log("  restart <time>")
    log("  cancel shutdown")
    log("  save all")
    log("  backup now")
    log("  whitelist on / whitelist off")
    log("  whitelist add <id>")
    log("  whitelist remove <id>")
    log("  help")
    log("Maps: " + ", ".join(SERVERS.keys()))


def parse_shutdown_delay(arg: str) -> Optional[int]:
    text = arg.strip().lower()

    if re.fullmatch(r"\d+", text):
        return int(text) * 60

    m = re.fullmatch(r"(\d+)m", text)
    if m:
        return int(m.group(1)) * 60

    h = re.fullmatch(r"(\d+)h", text)
    if h:
        return int(h.group(1)) * 3600

    hm = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", text)
    if hm and (hm.group(1) or hm.group(2)):
        hours = int(hm.group(1) or 0)
        minutes = int(hm.group(2) or 0)
        return hours * 3600 + minutes * 60

    return None


def schedule_manual_stop(
    target: ServerState,
    duration_seconds: int,
    source: str = "admin",
    origin: Optional[ServerState] = None,
) -> None:
    if target.cfg.key == DEFAULT_SERVER_KEY and not other_server_running(DEFAULT_SERVER_KEY):
        log("Cannot stop Ragnarok when it is the only active server.")
        return

    if target.manual_stop_since is not None:
        log(f"{target.cfg.key} already has a shutdown scheduled.")
        return

    if target.player_count == 0:
        log(f"{target.cfg.key} is empty, shutting down now ({source})")
        stop_server_safe(target, f"manual stop ({source})")
        return

    target.empty_since = None
    target.manual_stop_since = time.time()
    target.manual_stop_last_announcement_remaining = None
    target.manual_stop_duration_seconds = duration_seconds

    minutes = max(1, duration_seconds // 60)
    message = f"{target.cfg.display_name} shutting down in {minutes} minutes"

    announce(target, message)
    target.manual_stop_last_announcement_remaining = minutes

    if origin is not None and origin.cfg.key != target.cfg.key and origin.is_running:
        announce(origin, message)

    log(f"{target.cfg.key} shutdown scheduled in {minutes} minutes ({source})")


def cancel_manual_stop(target: ServerState) -> None:
    if target.manual_stop_since is None:
        log(f"{target.cfg.key} has no shutdown scheduled.")
        return

    target.manual_stop_since = None
    target.manual_stop_last_announcement_remaining = None
    target.manual_stop_duration_seconds = 0
    announce(target, f"{target.cfg.display_name} shutdown cancelled")
    log(f"{target.cfg.key} shutdown cancelled")


def perform_cluster_shutdown() -> None:
    backup_world()
    log("Executing cluster shutdown")
    announce_all_online("Saving world...")

    for state in list(online_servers()):
        save_world(state)

    time.sleep(10)

    announce_all_online("Cluster shutting down now")

    for state in list(online_servers()):
        stop_server_safe(state, "cluster shutdown")

    log(f"Waiting {POST_SHUTDOWN_WAIT_SECONDS}s for server processes to fully stop...")
    time.sleep(POST_SHUTDOWN_WAIT_SECONDS)

    CLUSTER.shutdown_scheduled = False
    CLUSTER.shutdown_at = None
    CLUSTER.last_announcement_remaining = None
    CLUSTER.cluster_stopped = True
    log("Cluster shutdown complete. Controller is idle — use Start Cluster to bring it back up.")


def schedule_cluster_shutdown(delay_seconds: int = 0) -> None:
    # NOTE: cluster_stopped is intentionally NOT set here for delayed shutdowns.
    # It is only set inside perform_cluster_shutdown() so that ensure_default_server()
    # continues to keep the default map alive during the countdown window, and
    # cancel_cluster_shutdown() can cleanly restore normal operation.
    CLUSTER.last_announcement_remaining = None

    if delay_seconds <= 0:
        announce_all_online("Cluster shutting down now")
        perform_cluster_shutdown()
        return

    CLUSTER.shutdown_scheduled = True
    CLUSTER.shutdown_at = time.time() + delay_seconds

    total_minutes = max(1, int(delay_seconds // 60))
    announce_all_online(f"Cluster shutdown scheduled in {total_minutes} minutes")
    log(f"Cluster shutdown scheduled in {total_minutes} minutes")


def cancel_cluster_shutdown() -> None:
    if CLUSTER.shutdown_scheduled:
        CLUSTER.shutdown_scheduled = False
        CLUSTER.shutdown_at = None
        CLUSTER.last_announcement_remaining = None
        CLUSTER.cluster_stopped = False
        CLUSTER.restart_pending = False
        announce_all_online("Cluster shutdown cancelled")
        log("Cluster shutdown cancelled")



def perform_cluster_restart() -> None:
    backup_world()
    log("Executing cluster restart")
    announce_all_online("Server restarting. Saving world...")

    for state in list(online_servers()):
        save_world(state)

    time.sleep(10)

    announce_all_online("Server restarting now. Be back in a moment!")

    maps_to_restore = [k for k, s in SERVER_STATES.items() if s.is_running]

    for state in list(online_servers()):
        stop_server_safe(state, "cluster restart")

    log(f"Waiting {POST_SHUTDOWN_WAIT_SECONDS}s for server processes to fully stop...")
    time.sleep(POST_SHUTDOWN_WAIT_SECONDS)

    CLUSTER.shutdown_scheduled = False
    CLUSTER.shutdown_at = None
    CLUSTER.last_announcement_remaining = None
    CLUSTER.cluster_stopped = False
    CLUSTER.restart_pending = False

    log("Restarting servers...")
    for key in maps_to_restore:
        start_server(key)


def schedule_cluster_restart(delay_seconds: int = 0) -> None:
    CLUSTER.last_announcement_remaining = None
    CLUSTER.restart_pending = True

    if delay_seconds <= 0:
        announce_all_online("Server restarting now")
        perform_cluster_restart()
        return

    CLUSTER.shutdown_scheduled = True
    CLUSTER.shutdown_at = time.time() + delay_seconds

    total_minutes = max(1, int(delay_seconds // 60))
    announce_all_online(f"Server restart scheduled in {total_minutes} minutes")
    log(f"Server restart scheduled in {total_minutes} minutes")


def handle_admin_command(command: str) -> None:
    lowered = command.strip().lower()
    if not lowered:
        return

    if lowered == "help":
        send_admin_help()
        return

    if lowered == "start cluster":
        if any(s.is_running or s.is_starting for s in SERVER_STATES.values()):
            log("Cluster already has running servers.")
            return
        CLUSTER.cluster_stopped = False
        start_server(DEFAULT_SERVER_KEY)
        return

    if lowered == "shutdown cluster":
        schedule_cluster_shutdown(CLUSTER_SHUTDOWN_DELAY_SECONDS)
        return

    if lowered == "shutdown cluster now":
        schedule_cluster_shutdown(0)
        return

    shutdown_match = re.fullmatch(r"shutdown cluster\s+(.+)", lowered)
    if shutdown_match:
        delay_seconds = parse_shutdown_delay(shutdown_match.group(1))
        if delay_seconds is None or delay_seconds <= 0:
            log("Invalid shutdown time. Examples: shutdown cluster 90 | shutdown cluster 45m | shutdown cluster 2h | shutdown cluster 1h30m")
            return
        schedule_cluster_shutdown(delay_seconds)
        return

    if lowered == "cancel shutdown":
        cancel_cluster_shutdown()
        return

    cancel_map_match = re.fullmatch(r"cancel\s+(.+)", lowered)
    if cancel_map_match:
        requested = normalize_map_name(cancel_map_match.group(1))
        if not requested:
            log("Unknown map.")
            return
        cancel_manual_stop(SERVER_STATES[requested])
        return

    if lowered == "restart":
        schedule_cluster_restart(CLUSTER_SHUTDOWN_DELAY_SECONDS)
        return

    if lowered == "restart now":
        schedule_cluster_restart(0)
        return

    restart_match = re.fullmatch(r"restart\s+(.+)", lowered)
    if restart_match:
        arg = restart_match.group(1).strip()
        # Check if it's a map name first (per-map restart)
        requested = normalize_map_name(arg)
        if requested:
            restart_single_server(requested)
            return
        # Otherwise treat as a cluster restart with a delay
        delay_seconds = parse_shutdown_delay(arg)
        if delay_seconds is None or delay_seconds <= 0:
            log("Invalid map name or restart time. Examples: restart ragnarok | restart 30m | restart 1h")
            return
        schedule_cluster_restart(delay_seconds)
        return

    if lowered == "save all":
        running = list(online_servers())
        if not running:
            log("No servers running.")
            return
        for state in running:
            save_world(state)
        return

    if lowered == "backup now":
        backup_world()
        return

    if lowered == "whitelist on":
        try:
            os.remove(WHITELIST_DISABLED_FLAG)
        except FileNotFoundError:
            pass
        log("Whitelist enabled")
        return

    if lowered == "whitelist off":
        try:
            open(WHITELIST_DISABLED_FLAG, "w").close()
        except Exception as exc:
            log(f"Whitelist disable failed: {exc}")
            return
        log("Whitelist disabled")
        return

    wl_add_match = re.fullmatch(r"whitelist add\s+(\S+)", lowered)
    if wl_add_match:
        _add_to_whitelist(wl_add_match.group(1))
        return

    wl_rem_match = re.fullmatch(r"whitelist remove\s+(\S+)", lowered)
    if wl_rem_match:
        _remove_from_whitelist(wl_rem_match.group(1))
        return

    if lowered == "exit":
        log("Use the dashboard or close the controller window to exit.")
        return

    start_match = re.match(r"start\s+(.+)", lowered)
    if start_match:
        requested = normalize_map_name(start_match.group(1))
        if not requested:
            log("Unknown map.")
            return

        active = len(active_servers())
        if active >= MAX_ACTIVE_SERVERS:
            log(f"Max servers active ({active}/{MAX_ACTIVE_SERVERS})")
            return

        if not start_server(requested):
            log(f"{requested} is already running or starting.")
        return

    stop_match = re.match(r"stop\s+(.+)", lowered)
    if stop_match:
        requested = normalize_map_name(stop_match.group(1))
        if not requested:
            log("Unknown map.")
            return

        target = SERVER_STATES[requested]
        if not target.is_running:
            log(f"{requested} is not running.")
            return

        schedule_manual_stop(target, MAP_SHUTDOWN_DELAY_SECONDS, "admin")
        return

    log(f"Unknown admin command: {command}")


def poll_admin_commands() -> None:
    if not os.path.exists(ADMIN_COMMAND_FILE):
        return

    try:
        with open(ADMIN_COMMAND_FILE, "r", encoding="utf-8") as f:
            commands = [line.strip() for line in f if line.strip()]

        if not commands:
            return

        with open(ADMIN_COMMAND_FILE, "w", encoding="utf-8") as f:
            f.write("")

        for command in commands:
            global _is_admin_context
            _is_admin_context = True
            try:
                log(f"ADMIN CMD: {command}")
                handle_admin_command(command)
            finally:
                _is_admin_context = False

    except Exception as exc:
        log(f"ADMIN COMMAND FILE ERROR: {exc}")


def parse_list_players(raw: str) -> int:
    """Return the number of connected players from ListPlayers RCON output."""
    if not raw or "no players" in raw.lower():
        return 0
    return sum(1 for line in raw.splitlines() if re.match(r"\s*\d+\.\s+\S", line))


def parse_list_players_detailed(raw: str) -> List[Dict]:
    """Parse ListPlayers RCON output into [{name, id}] dicts."""
    if not raw or "no players" in raw.lower():
        return []
    players = []
    for line in raw.splitlines():
        m = re.match(r"\s*\d+\.\s+(.+),\s*(\S+)\s*$", line.strip())
        if m:
            players.append({"name": m.group(1).strip(), "id": m.group(2).strip()})
    return players


def get_pid_on_port(port: int) -> Optional[int]:
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                return int(parts[-1])
    except Exception:
        pass
    return None


def find_server_log_path(state: ServerState) -> Optional[Path]:
    logs_dir = Path(SERVER_ROOT) / "ShooterGame" / "Saved" / "Logs"
    pid = get_pid_on_port(state.cfg.rcon_port)
    if pid is None:
        return None
    matches = list(logs_dir.glob(f"ServerGame.{pid}.*.log"))
    return matches[0] if matches else None


def sync_players_from_game_log(state: ServerState) -> None:
    """On first contact, recover who is currently online.
    Tries the on-disk ServerGame log first (full history), then falls
    back to GetGameLog RCON (limited buffer, may miss old join events)."""

    # ── Disk log (authoritative) ──────────────────────────────────────
    log_path = find_server_log_path(state)
    if log_path:
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            joined: set = set()
            left: set = set()
            for line in lines:
                join_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*joined this ARK", line)
                if join_match:
                    pid = join_match.group(1)
                    joined.add(pid)
                    left.discard(pid)
                    continue
                leave_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*left this ARK", line)
                if leave_match:
                    pid = leave_match.group(1)
                    left.add(pid)
                    joined.discard(pid)
            online = joined - left
            state.players = online
            state.player_count = len(online)
            if online:
                state.last_player_seen_at = time.time()
                log(f"PLAYER SYNC {state.cfg.key}: recovered {state.player_count} player(s) from disk log")
            else:
                log(f"PLAYER SYNC {state.cfg.key}: no players in disk log")
            return
        except Exception as exc:
            log(f"PLAYER SYNC {state.cfg.key}: disk log read failed ({exc}), falling back to GetGameLog")

    # ── GetGameLog fallback (limited buffer) ──────────────────────────
    try:
        raw = rcon_command(state.cfg, "GetGameLog", timeout=8.0)
    except Exception:
        return
    if not raw:
        return
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    joined = set()
    left = set()
    for line in lines:
        state.seen_log_lines.add(line)
        join_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*joined this ARK", line)
        if join_match:
            pid = join_match.group(1)
            joined.add(pid)
            left.discard(pid)
            continue
        leave_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*left this ARK", line)
        if leave_match:
            pid = leave_match.group(1)
            left.add(pid)
            joined.discard(pid)
    online = joined - left
    state.players = online
    state.player_count = len(online)
    if online:
        state.last_player_seen_at = time.time()
        log(f"PLAYER SYNC {state.cfg.key}: recovered {state.player_count} player(s) from game log")
    else:
        log(f"PLAYER SYNC {state.cfg.key}: no players in game log")


def update_running_status(state: ServerState) -> None:
    raw_players: Optional[str] = None
    try:
        raw_players = rcon_command(state.cfg, "ListPlayers", timeout=10.0)

        reachable = True
        state.last_rcon_error = None
    except Exception as exc:
        reachable = False
        error_text = str(exc)
        if state.last_rcon_error != error_text:
            log(f"RCON FAIL {state.cfg.key}: {error_text}")
            state.last_rcon_error = error_text

    now = time.time()

    if reachable:
        state.rcon_fail_count = 0
        just_came_online = not state.is_running

        if just_came_online:
            log(f"ONLINE: {state.cfg.key}")
            state.online_since = now

        state.is_running = True
        state.is_starting = False
        state.last_seen_online_at = now
        state.player_list = parse_list_players_detailed(raw_players or "")
        state.player_count = len(state.player_list)

        # On first contact only: replay the game log to recover who is
        # currently online. This handles controller restarts while players
        # are already in-game. ListPlayers is too unreliable in ASA for this.
        if just_came_online:
            sync_players_from_game_log(state)

        if just_came_online and state.pending_online_announcement:
            announce_all_online(f"{state.cfg.display_name} is up and running")
            state.pending_online_announcement = False

        if state.last_autosave_at == 0:
            state.last_autosave_at = now
    else:
        if state.is_running:
            # Inside startup grace window — tolerate transient failures
            if not state.online_since or (now - state.online_since) <= STARTUP_GRACE_SECONDS:
                return

            # Past grace: accumulate consecutive failures before acting
            state.rcon_fail_count += 1
            if state.rcon_fail_count < CRASH_DETECTION_THRESHOLD:
                return  # not enough failures yet — keep waiting

            # Threshold reached — crash detected
            log(f"CRASH DETECTED: {state.cfg.key} ({state.rcon_fail_count} consecutive RCON failures) — restarting")
            announce_all_online(f"{state.cfg.display_name} has crashed and is being restarted")
            state.is_running = False
            state.is_starting = False
            state.players.clear()
            state.player_count = 0
            state.last_player_seen_at = None
            state.online_since = None
            state.empty_since = None
            state.manual_stop_since = None
            state.manual_stop_last_announcement_remaining = None
            state.manual_stop_duration_seconds = 0
            state.rcon_fail_count = 0
            state.seen_log_lines.clear()
            start_server(state.cfg.key)
            return

        # Server was already offline / still starting — no state transition to log
        state.is_running = False
        state.players.clear()
        state.player_count = 0
        state.last_player_seen_at = None
        state.online_since = None

        if state.is_starting and state.start_requested_at:
            if now - state.start_requested_at > SERVER_START_TIMEOUT_SECONDS:
                log(f"START TIMEOUT: {state.cfg.key}")
                state.is_starting = False
                state.start_requested_at = None
                state.pending_online_announcement = False
        elif not state.is_starting:
            state.rcon_fail_count = 0
            state.empty_since = None
            state.manual_stop_since = None
            state.manual_stop_last_announcement_remaining = None
            state.manual_stop_duration_seconds = 0


def poll_chat(state: ServerState) -> None:
    try:
        raw = rcon_command(state.cfg, "GetGameLog", timeout=8.0)
    except Exception as exc:
        error_text = f"GetGameLog failed: {exc}"
        if state.last_rcon_error != error_text:
            log(f"GETGAMELOG FAIL {state.cfg.key}: {exc}")
            state.last_rcon_error = error_text
        return

    if not raw:
        return

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    new_lines = []

    for ln in lines:
        if ln in state.seen_log_lines:
            continue
        state.seen_log_lines.add(ln)
        new_lines.append(ln)

    if len(state.seen_log_lines) > 1000:
        state.seen_log_lines = set(list(state.seen_log_lines)[-500:])

    for line in new_lines:
        join_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*joined this ARK", line)
        if join_match:
            player_id = join_match.group(1)
            state.players.add(player_id)
            state.player_count = len(state.players)
            state.last_player_seen_at = time.time()
            log(f"PLAYER JOIN {state.cfg.key}: {player_id} (p={state.player_count})")
            continue

        leave_match = re.search(r"UniqueNetId:([0-9a-fA-F]+).*left this ARK", line)
        if leave_match:
            player_id = leave_match.group(1)
            state.players.discard(player_id)
            state.player_count = len(state.players)
            log(f"PLAYER LEAVE {state.cfg.key}: {player_id} (p={state.player_count})")
            continue

        lower = line.lower()
        if not any(cmd in lower for cmd in ["!start", "!status", "!help"]):
            continue

        # Extract Steam ID from the log line (UniqueNetId:<hex>)
        sid_match = re.search(r"UniqueNetId:([0-9a-fA-F]+)", line)
        steam_id = sid_match.group(1) if sid_match else None

        sender_name, message = split_chat_sender_and_message(line)
        log(f"CMD {state.cfg.key}: {line}")
        handle_command(state, sender_name, steam_id, message)


def handle_empty_shutdowns() -> None:
    now = time.time()

    for state in SERVER_STATES.values():
        if not state.is_running:
            continue

        if state.cfg.key == DEFAULT_SERVER_KEY and not other_server_running(DEFAULT_SERVER_KEY):
            continue

        if state.manual_stop_since is not None:
            continue

        if state.online_since is not None:
            uptime = now - state.online_since
            if uptime < STARTUP_GRACE_SECONDS:
                continue

        if state.player_count == 0:
            if state.empty_since is None:
                state.empty_since = now
                delay_minutes = MAP_SHUTDOWN_DELAY_SECONDS // 60
                log(f"{state.cfg.key} shutting down in {delay_minutes} minutes")
        else:
            if state.empty_since is not None:
                log(f"{state.cfg.key} shutdown cancelled")
            state.empty_since = None
            continue

        empty_for = now - state.empty_since
        if empty_for >= MAP_SHUTDOWN_DELAY_SECONDS:
            delay_minutes = MAP_SHUTDOWN_DELAY_SECONDS // 60
            log(f"{state.cfg.key} shutting down (empty for {delay_minutes} minutes)")
            stop_server_safe(state, f"empty for {delay_minutes} minutes")


def handle_manual_stop_timers() -> None:
    now = time.time()
    for state in SERVER_STATES.values():
        if not state.is_running or state.manual_stop_since is None:
            continue

        if state.cfg.key == DEFAULT_SERVER_KEY and not other_server_running(DEFAULT_SERVER_KEY):
            continue

        duration = state.manual_stop_duration_seconds or MAP_SHUTDOWN_DELAY_SECONDS
        elapsed = now - state.manual_stop_since
        remaining_seconds = duration - elapsed

        if remaining_seconds > 0:
            remaining_minutes = max(1, int((remaining_seconds + 59) // 60))
            if (
                remaining_minutes in SHUTDOWN_WARNING_MINUTES
                and remaining_minutes != state.manual_stop_last_announcement_remaining
            ):
                announce(state, f"{state.cfg.display_name} shutting down in {remaining_minutes} minutes")
                state.manual_stop_last_announcement_remaining = remaining_minutes
        else:
            announce(state, f"{state.cfg.display_name} shutting down now")
            stop_server_safe(state, "manual stop")


def handle_autosaves() -> None:
    now = time.time()
    for state in SERVER_STATES.values():
        if state.is_running and now - state.last_autosave_at >= AUTOSAVE_SECONDS:
            save_world(state)


def handle_cluster_shutdown_timer() -> None:
    if not CLUSTER.shutdown_scheduled or not CLUSTER.shutdown_at:
        return

    remaining_seconds = CLUSTER.shutdown_at - time.time()

    if remaining_seconds > 0:
        remaining_minutes = int((remaining_seconds + 59) // 60)

        if (
            remaining_minutes in SHUTDOWN_WARNING_MINUTES
            and CLUSTER.last_announcement_remaining != remaining_minutes
        ):
            if CLUSTER.restart_pending:
                announce_all_online(f"Server restart in {remaining_minutes} minutes")
            else:
                announce_all_online(f"Cluster shutdown in {remaining_minutes} minutes")
            CLUSTER.last_announcement_remaining = remaining_minutes

        return

    if CLUSTER.restart_pending:
        perform_cluster_restart()
    else:
        perform_cluster_shutdown()


def ensure_default_server() -> None:
    if CLUSTER.shutdown_scheduled or CLUSTER.cluster_stopped:
        return

    if any(s.is_running or s.is_starting for s in SERVER_STATES.values()):
        return

    exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    if not os.path.exists(exe):
        return  # Server not installed yet — silently skip

    start_server(DEFAULT_SERVER_KEY)


def write_cluster_status() -> None:
    total_players = sum(state.player_count for state in SERVER_STATES.values())
    running = [state.cfg.key for state in SERVER_STATES.values() if state.is_running]

    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(f"PLAYERS_ONLINE={total_players}\n")
            f.write(f"RUNNING={','.join(running)}\n")
            f.write(f"CLUSTER_SHUTDOWN={CLUSTER.shutdown_scheduled}\n")
    except Exception as exc:
        log(f"STATUS FILE ERROR: {exc}")

    # JSON status for dashboard
    now = time.time()
    servers_data = {}
    for key, state in SERVER_STATES.items():
        shutdown_in = None
        if state.manual_stop_since is not None:
            elapsed = now - state.manual_stop_since
            duration = state.manual_stop_duration_seconds or MAP_SHUTDOWN_DELAY_SECONDS
            shutdown_in = max(0, int(duration - elapsed))
        servers_data[key] = {
            "key": key,
            "display_name": state.cfg.display_name,
            "is_running": state.is_running,
            "is_starting": state.is_starting,
            "player_count": state.player_count,
            "game_port": state.cfg.game_port,
            "rcon_port": state.cfg.rcon_port,
            "manual_stop_in": shutdown_in,
            "pending_restart": state.pending_restart,
            "player_list": state.player_list,
        }

    cluster_shutdown_in = None
    if CLUSTER.shutdown_scheduled and CLUSTER.shutdown_at:
        cluster_shutdown_in = max(0, int(CLUSTER.shutdown_at - now))

    whitelist_active = (
        os.path.exists(WHITELIST_FILE)
        and not os.path.exists(WHITELIST_DISABLED_FLAG)
    )

    # Next daily scheduled restart (unix timestamp), if configured
    next_scheduled_restart = None
    if RESTART_TIME and not CLUSTER.shutdown_scheduled:
        try:
            h, m = map(int, RESTART_TIME.split(":"))
            candidate = datetime.datetime.now().replace(
                hour=h, minute=m, second=0, microsecond=0
            )
            if candidate.timestamp() <= now:
                candidate += datetime.timedelta(days=1)
            next_scheduled_restart = candidate.timestamp()
        except Exception:
            pass

    steamcmd_found = os.path.exists(STEAMCMD_EXE)
    server_exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    server_found = os.path.exists(server_exe)

    payload = {
        "servers": servers_data,
        "total_players": total_players,
        "cluster_shutdown_scheduled": CLUSTER.shutdown_scheduled,
        "cluster_shutdown_in": cluster_shutdown_in,
        "cluster_restart_pending": CLUSTER.restart_pending,
        "next_scheduled_restart": next_scheduled_restart,
        "whitelist_active": whitelist_active,
        "steamcmd_found": steamcmd_found,
        "server_found": server_found,
        "timestamp": now,
    }

    tmp = STATUS_JSON_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, STATUS_JSON_FILE)
    except Exception as exc:
        log(f"STATUS JSON ERROR: {exc}")


def print_summary() -> None:
    global LAST_SUMMARY_LINE

    parts = []

    running_parts = []
    for state in SERVER_STATES.values():
        if state.is_running:
            running_parts.append(f"{state.cfg.key}:{state.player_count}")

    if running_parts:
        parts.append(f"RUNNING={running_parts}")

    starting = [s.cfg.key for s in SERVER_STATES.values() if s.is_starting]
    if starting:
        parts.append(f"STARTING={starting}")

    if CLUSTER.shutdown_scheduled:
        parts.append("CLUSTER_SHUTDOWN=True")

    summary_line = " ".join(parts) if parts else "IDLE"

    if summary_line != LAST_SUMMARY_LINE:
        log(summary_line)
        LAST_SUMMARY_LINE = summary_line




def _ensure_steamcmd() -> bool:
    """Download SteamCMD if not present, then let it self-update before use.
    Returns True if SteamCMD is ready to install/update apps."""
    if os.path.exists(STEAMCMD_EXE):
        return True

    steamcmd_dir = os.path.dirname(STEAMCMD_EXE)
    log(f"SteamCMD not found — downloading to {steamcmd_dir} ...")
    try:
        os.makedirs(steamcmd_dir, exist_ok=True)
        zip_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
        with urllib.request.urlopen(zip_url, timeout=60) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(steamcmd_dir)
    except Exception as exc:
        log(f"SteamCMD download failed: {exc}")
        return False

    # SteamCMD always self-updates on first launch — run +quit now so it
    # finishes updating before we ask it to install the game server.
    log("SteamCMD downloaded — running initial self-update (this takes a moment)...")
    try:
        proc = subprocess.Popen(
            [STEAMCMD_EXE, "+quit"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(line, flush=True)
        proc.wait(timeout=180)
        log("SteamCMD ready.")
        return True
    except Exception as exc:
        log(f"SteamCMD self-update failed: {exc}")
        return False


def _run_steamcmd_app_update() -> None:
    """Run SteamCMD +app_update 2430930. Retries once if Steam reports
    'Missing configuration' — a known first-run quirk where the app
    manifest hasn't been cached locally yet."""
    cmd = [
        STEAMCMD_EXE,
        "+@sSteamCmdForcePlatformType", "windows",
        "+force_install_dir", SERVER_ROOT,
        "+login", "anonymous",
        "+app_update", "2430930",
        "+quit",
    ]
    os.makedirs(SERVER_ROOT, exist_ok=True)

    for attempt in range(1, 3):  # up to 2 attempts
        if attempt > 1:
            log("Retrying server install (attempt 2/2)...")

        output_lines: List[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    print(line, flush=True)
                    output_lines.append(line.lower())
            proc.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            proc.kill()
            log("SteamCMD timed out after 30 minutes.")
            return
        except Exception as exc:
            log(f"SteamCMD error: {exc}")
            return

        combined = " ".join(output_lines)

        if "already up to date" in combined:
            log("Server is already up to date.")
            return
        if "fully installed" in combined or "success" in combined:
            log("Server installed/updated successfully.")
            return
        if "missing configuration" in combined and attempt == 1:
            # Steam hasn't cached the app manifest yet — retry immediately
            log("SteamCMD: app manifest not cached, retrying...")
            continue

        # If the exe is on disk, treat it as success regardless of output text
        exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
        if os.path.exists(exe):
            log("Server installed/updated successfully.")
            return

        log("SteamCMD finished (status unknown).")
        return


def check_and_update_on_startup() -> None:
    """Ensure SteamCMD and the server are present, then check for updates.

    The server is always installed/downloaded if the exe is missing —
    regardless of the check_updates_on_startup setting.  That flag only
    controls whether an already-installed server is updated on each start.
    """
    exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    server_installed = os.path.exists(exe)

    if not server_installed:
        # Fresh install — must download regardless of update setting
        if not _ensure_steamcmd():
            return
        log("Server not installed — downloading now...")
        _run_steamcmd_app_update()
        return

    # Server is already installed — only update if configured to do so
    if not CHECK_UPDATES_ON_STARTUP:
        return

    if not _ensure_steamcmd():
        return

    log("Checking for server updates...")
    _run_steamcmd_app_update()


def handle_scheduled_restart() -> None:
    global _last_scheduled_restart_day

    if not RESTART_TIME:
        return
    if CLUSTER.shutdown_scheduled or CLUSTER.cluster_stopped:
        return

    now = datetime.datetime.now()
    if now.strftime("%H:%M") != RESTART_TIME:
        return

    today = now.toordinal()
    if _last_scheduled_restart_day == today:
        return

    _last_scheduled_restart_day = today
    log(f"Scheduled restart triggered at {RESTART_TIME}")
    schedule_cluster_restart(CLUSTER_SHUTDOWN_DELAY_SECONDS)


def backup_world() -> None:
    """Copy SavedArks to a timestamped backup folder and prune old backups."""
    src = os.path.join(SERVER_ROOT, "ShooterGame", "Saved", "SavedArks")
    if not os.path.exists(src):
        log("Backup skipped: SavedArks folder not found")
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(BACKUP_DIR, timestamp)

    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        log(f"Backing up world saves to: {dest}")
        shutil.copytree(src, dest)
        log("Backup complete")
    except Exception as exc:
        log(f"Backup failed: {exc}")
        return

    # Prune oldest backups if over limit
    try:
        existing = sorted(Path(BACKUP_DIR).iterdir(), key=lambda p: p.stat().st_mtime)
        while len(existing) > MAX_BACKUPS:
            oldest = existing.pop(0)
            shutil.rmtree(oldest)
            log(f"Pruned old backup: {oldest.name}")
    except Exception as exc:
        log(f"Backup pruning failed: {exc}")


_last_saved_running_maps: list = []

def _save_running_maps() -> None:
    """Write the keys of all currently running maps to disk so they can be
    restored after a restart or update cycle."""
    global _last_saved_running_maps
    running = [k for k, s in SERVER_STATES.items() if s.is_running]
    if running == _last_saved_running_maps:
        return
    try:
        with open(RESTART_MAPS_FILE, "w", encoding="utf-8") as f:
            f.write(",".join(running))
        _last_saved_running_maps = running
        log(f"Saved running maps for restore: {running}")
    except Exception as exc:
        log(f"Failed to save running maps: {exc}")


def adopt_running_servers() -> None:
    """On controller startup, probe every configured server via RCON.
    Any that already respond are adopted as running so we never spawn a
    duplicate process on the same port."""
    now = time.time()
    for state in SERVER_STATES.values():
        try:
            rcon_command(state.cfg, "ListPlayers", timeout=4.0)
            # RCON replied — server is already up
            state.is_running  = True
            state.is_starting = False
            state.last_seen_online_at = now
            state.online_since        = now
            log(f"ADOPTED: {state.cfg.key} already running — skipping start")
        except Exception:
            pass   # not running or not reachable yet — that's fine


def restore_maps_after_restart() -> None:
    """Read the saved map list and start those servers again.
    Called once at startup; no-op if the file does not exist."""
    if not os.path.exists(RESTART_MAPS_FILE):
        return

    try:
        with open(RESTART_MAPS_FILE, encoding="utf-8") as f:
            text = f.read().strip()
        os.remove(RESTART_MAPS_FILE)
    except Exception as exc:
        log(f"Failed to read restart maps file: {exc}")
        return

    if not text:
        return

    keys = [k.strip() for k in text.split(",") if k.strip() in SERVERS]
    if not keys:
        return

    log(f"Restoring maps from previous session: {keys}")
    for key in keys:
        start_server(key)


def _write_stop_file() -> None:
    try:
        with open(STOP_FILE, "w") as f:
            f.write("stopped")
    except Exception:
        pass


def main() -> int:
    global SHOULD_EXIT

    # Clean up any leftover stop file from a previous run
    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    check_and_update_on_startup()

    log("Controller started")
    adopt_running_servers()
    restore_maps_after_restart()

    while True:
        try:
            poll_admin_commands()

            for state in servers_to_probe():
                update_running_status(state)

            for state in online_servers():
                poll_chat(state)

            handle_autosaves()
            handle_empty_shutdowns()
            handle_manual_stop_timers()
            handle_cluster_shutdown_timer()
            handle_scheduled_restart()

            ensure_default_server()
            write_cluster_status()
            _save_running_maps()
            print_summary()

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("Controller stopped by user")
            _write_stop_file()
            return 0
        except Exception as exc:
            log(f"ERROR: {exc}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())