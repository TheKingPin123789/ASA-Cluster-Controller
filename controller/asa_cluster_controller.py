import io
import os
import re
import sys
import json
import time
import shutil
import ctypes
import asyncio
import datetime
import threading
import subprocess
import configparser
import urllib.request
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from setup_wizard import prompt_setup_on_startup
from config_crypt import decrypt_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

MCRCON_EXE = os.path.join(BASE_DIR, "mcrcon.exe")
ADMIN_COMMAND_FILE = os.path.join(BASE_DIR, "admin_commands.txt")
STATUS_FILE = os.path.join(BASE_DIR, "cluster_status.txt")
STATUS_JSON_FILE = os.path.join(BASE_DIR, "cluster_status.json")
LOG_FILE       = os.path.join(LOGS_DIR, "controller.log")
ADMIN_LOG_FILE = os.path.join(LOGS_DIR, "admin_log.txt")
STOP_FILE            = os.path.join(BASE_DIR, "controller.stop")
CONTROLLER_RESTART_FILE = os.path.join(BASE_DIR, "controller.restart")
RESTART_MAPS_FILE = os.path.join(BASE_DIR, "restart_maps.txt")
WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.txt")
WHITELIST_DISABLED_FLAG = os.path.join(BASE_DIR, "whitelist_disabled.flag")
SEEN_PLAYERS_FILE        = os.path.join(BASE_DIR, "seen_players.json")
COMMAND_CATEGORIES_FILE  = os.path.join(BASE_DIR, "command_categories.json")
ADMIN_LIST_FILE          = os.path.join(BASE_DIR, "admin_list.txt")
CONTROLLER_PID_FILE      = os.path.join(BASE_DIR, "controller.pid")

# ── Load config (wizard runs here if needed) ──────────────
_cfg = prompt_setup_on_startup()
decrypt_config(_cfg)   # decrypt ENC: fields in-memory (never writes back)

def _ci(section: str, key: str, fallback: str = "") -> str:
    try:
        return _cfg.get(section, key)
    except Exception:
        return fallback

def _ci2(section: str, key: str, fallback: str, alt_section: str) -> str:
    """Try section first, then alt_section (backward compat for renamed sections)."""
    v = _ci(section, key, None)
    return v if v is not None else _ci(alt_section, key, fallback)

def _ci_int(section: str, key: str, fallback: int, *, multiplier: int = 1) -> int:
    """Like _ci() but converts to int safely — bad values log a warning and use the fallback."""
    raw = _ci(section, key, None)
    if raw is None:
        return fallback * multiplier
    try:
        return int(raw) * multiplier
    except ValueError:
        print(f"WARNING: config [{section}] {key} = {raw!r} is not a valid integer "
              f"— using default {fallback * multiplier}")
        return fallback * multiplier

# ── Cluster / network / paths ─────────────────────────────────────────────────
CLUSTER_NAME   = _ci("cluster", "cluster_name",  "MyCluster")
CLUSTER_ID     = CLUSTER_NAME.replace(" ", "") + "Cluster"
RCON_PASSWORD  = _ci("cluster", "rcon_password", "ChangeMe123")
SERVER_ROOT    = _ci("paths",   "server_root",   os.path.join(os.path.dirname(BASE_DIR), "asa_server"))
CLUSTER_DIR    = _ci("paths",   "cluster_dir",   rf"{SERVER_ROOT}\cluster")
STEAMCMD_EXE   = _ci("paths",   "steamcmd_path", os.path.join(os.path.splitdrive(BASE_DIR)[0] + os.sep, "SteamCMD", "steamcmd.exe"))
HOST           = _ci("network", "rcon_host",     "127.0.0.1")
DEFAULT_SERVER_KEY = _ci("cluster", "default_map", "ragnarok")

# ── Limits (formerly [performance]) ───────────────────────────────────────────
_USER_MAX_ACTIVE_SERVERS = _ci_int("limits", "max_active_servers",    0)  # 0 = auto from RAM
MAX_PLAYERS              = _ci_int("limits", "max_players",           70)
MAX_TAMED_DINOS          = _ci_int("limits", "max_tamed_dinos",       5000)
MAX_PERSONAL_TAMED_DINOS = _ci_int("limits", "max_personal_tamed_dinos", 40)

# ── Schedule ──────────────────────────────────────────────────────────────────
POLL_SECONDS             = _ci_int("schedule", "poll_seconds",            5)
RESTART_TIME             = _ci("schedule", "restart_time",                "")
CHECK_UPDATES_ON_STARTUP = _ci("schedule", "check_updates_on_startup",   "true").lower() == "true"

# ── Timers ────────────────────────────────────────────────────────────────────
MAP_SHUTDOWN_DELAY_SECONDS      = _ci_int("timers", "map_shutdown_minutes",          15,  multiplier=60)
STARTUP_GRACE_SECONDS           = _ci_int("timers", "startup_grace_minutes",         15,  multiplier=60)
AUTOSAVE_SECONDS                = _ci_int("timers", "autosave_minutes",              15,  multiplier=60)
CLUSTER_SHUTDOWN_DELAY_SECONDS  = _ci_int("timers", "cluster_shutdown_minutes",      30,  multiplier=60)
SERVER_START_TIMEOUT_SECONDS    = _ci_int("timers", "server_start_timeout_seconds",  300)
SAVE_BEFORE_EXIT_WAIT_SECONDS   = _ci_int("timers", "save_before_exit_seconds",      10)
POST_SHUTDOWN_WAIT_SECONDS      = _ci_int("timers", "post_shutdown_wait_seconds",    60)
CRASH_DETECTION_THRESHOLD       = _ci_int("timers", "crash_detection_threshold",     5)
SHUTDOWN_WARNING_MINUTES        = {60, 30, 15, 10, 5, 4, 3, 2, 1}

# ── Auto-restart on crash ─────────────────────────────────────────────────────
AUTO_RESTART_ON_CRASH    = _ci("crash", "auto_restart_on_crash",  "true").lower() == "true"
CRASH_COOLDOWN_MINUTES   = _ci_int("crash", "crash_cooldown_minutes",  5)
MAX_CRASH_RESTARTS       = _ci_int("crash", "max_crash_restarts",      3)
CRASH_WINDOW_MINUTES     = _ci_int("crash", "crash_window_minutes",    60)

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN              = _ci("discord", "bot_token",                "")
DISCORD_NOTIFICATION_CHANNEL   = _ci("discord", "notification_channel_id",  "")
DISCORD_COMMAND_CHANNEL        = _ci("discord", "command_channel_id",       "")
DISCORD_ADMIN_ROLE             = _ci("discord", "admin_role_name",          "Admin")
DISCORD_NOTIFY_SERVER          = _ci("discord", "notify_server_events",     "true").lower() == "true"
DISCORD_NOTIFY_CRASH           = _ci("discord", "notify_crash_events",      "true").lower() == "true"
DISCORD_NOTIFY_CLUSTER         = _ci("discord", "notify_cluster_events",    "true").lower() == "true"

# ── Backup ────────────────────────────────────────────────────────────────────
BACKUP_DIR  = _ci("backup", "backup_dir",   os.path.join(os.path.dirname(SERVER_ROOT), "backups"))
MAX_BACKUPS = int(_ci("backup", "max_backups", "10"))
MAX_LOGS    = int(_ci("backup", "max_logs",    "10"))

# ── Performance ───────────────────────────────────────────────────────────────
LOW_MEMORY_MODE   = _ci("limits", "low_memory_mode",  "true").lower() == "true"
NO_SOUND          = _ci("limits", "no_sound",         "true").lower() == "true"
GC_PURGE_INTERVAL = _ci("limits", "gc_purge_interval","30")

# ── World ─────────────────────────────────────────────────────────────────────
DAY_TIME_SPEED       = _ci("world", "day_time_speed_scale",               "1.0")
NIGHT_TIME_SPEED     = _ci("world", "night_time_speed_scale",             "1.0")
DINO_COUNT_MULT      = _ci("world", "dino_count_multiplier",              "1.0")
RESOURCES_RESPAWN    = _ci("world", "resources_respawn_period_multiplier","1.0")
ACTIVE_EVENT         = _ci("world", "active_event",                       "").strip()
DISABLE_WEATHER_FOG  = _ci("world", "disable_weather_fog",                "false").lower() == "true"

# ── Rates ─────────────────────────────────────────────────────────────────────
XP_MULTIPLIER             = _ci("rates", "xp_multiplier",                              "1.0")
TAMING_SPEED_MULTIPLIER   = _ci("rates", "taming_speed_multiplier",                    "1.0")
HARVEST_AMOUNT_MULTIPLIER = _ci("rates", "harvest_amount_multiplier",                  "1.0")
DIFFICULTY_OFFSET         = _ci("rates", "difficulty_offset",                          "1.0")
ITEM_STACK_SIZE_MULT      = _ci("rates", "item_stack_size_multiplier",                 "1.0")
LOOT_QUALITY_MULT         = _ci("rates", "loot_quality_multiplier",                    "1.0")
FISHING_LOOT_MULT         = _ci("rates", "fishing_loot_quality_multiplier",            "1.0")
SUPPLY_CRATE_LOOT_MULT    = _ci("rates", "supply_crate_loot_quality_multiplier",       "1.0")
GLOBAL_SPOILING_TIME_MULT = _ci("rates", "global_spoiling_time_multiplier",            "1.0")
GLOBAL_ITEM_DECOMP_MULT   = _ci("rates", "global_item_decomposition_time_multiplier",  "1.0")
GLOBAL_CORPSE_DECOMP_MULT = _ci("rates", "global_corpse_decomposition_time_multiplier","1.0")
CROP_GROWTH_SPEED_MULT    = _ci("rates", "crop_growth_speed_multiplier",               "1.0")
FUEL_CONSUMPTION_MULT     = _ci("rates", "fuel_consumption_interval_multiplier",       "1.0")

# ── Survival ──────────────────────────────────────────────────────────────────
PLAYER_FOOD_DRAIN    = _ci("survival", "player_food_drain_multiplier",         "1.0")
PLAYER_WATER_DRAIN   = _ci("survival", "player_water_drain_multiplier",        "1.0")
PLAYER_STAMINA_DRAIN = _ci("survival", "player_stamina_drain_multiplier",      "1.0")
PLAYER_HEALTH_REGEN  = _ci("survival", "player_health_recovery_multiplier",    "1.0")
DINO_FOOD_DRAIN      = _ci("survival", "dino_food_drain_multiplier",           "1.0")
DINO_HEALTH_REGEN    = _ci("survival", "dino_health_recovery_multiplier",      "1.0")

# ── Combat ────────────────────────────────────────────────────────────────────
PLAYER_DAMAGE_MULT     = _ci("combat", "player_damage_multiplier",        "1.0")
PLAYER_RESISTANCE_MULT = _ci("combat", "player_resistance_multiplier",    "1.0")
DINO_DAMAGE_MULT       = _ci("combat", "dino_damage_multiplier",          "1.0")
DINO_RESISTANCE_MULT   = _ci("combat", "dino_resistance_multiplier",      "1.0")
TAMED_DINO_DAMAGE_MULT = _ci("combat", "tamed_dino_damage_multiplier",    "1.0")
TAMED_DINO_RES_MULT    = _ci("combat", "tamed_dino_resistance_multiplier","1.0")
STRUCT_DAMAGE_MULT     = _ci("combat", "structure_damage_multiplier",     "1.0")
FLAG_FLOAT_DAMAGE      = _ci("combat", "show_floating_damage_text",       "false").lower() == "true"
FLAG_HIT_MARKERS       = _ci("combat", "allow_hit_markers",               "true").lower()  == "true"

# ── Breeding ─────────────────────────────────────────────────────────────────
MATING_INTERVAL_MULT      = _ci2("breeding","mating_interval_multiplier", "1.0","rates")
MATING_SPEED_MULT         = _ci2("breeding","mating_speed_multiplier",    "1.0","rates")
EGG_HATCH_SPEED_MULT      = _ci2("breeding","egg_hatch_speed_multiplier", "1.0","rates")
LAY_EGG_INTERVAL_MULT     = _ci("breeding", "lay_egg_interval_multiplier",        "1.0")
BABY_MATURE_SPEED_MULT        = _ci("breeding","baby_mature_speed_multiplier",        "1.0")
BABY_CUDDLE_INTERVAL_MULT     = _ci("breeding","baby_cuddle_interval_multiplier",     "1.0")
BABY_CUDDLE_GRACE_PERIOD_MULT = _ci("breeding","baby_cuddle_grace_period_multiplier", "1.0")
BABY_IMPRINT_AMOUNT_MULT      = _ci("breeding","baby_imprint_amount_multiplier",      "1.0")

# ── Structures ────────────────────────────────────────────────────────────────
STRUCT_PICKUP_TIME  = _ci("structures", "structure_pickup_time_after_placement",       "30")
PER_PLATFORM_STRUCT = _ci("structures", "per_platform_max_structures_multiplier",      "1.0")

# ── Flags ─────────────────────────────────────────────────────────────────────
FLAG_THIRD_PERSON         = _ci("flags","allow_third_person",              "false").lower() == "true"
FLAG_SHOW_MAP_LOC         = _ci("flags","show_map_player_location",        "true").lower()  == "true"
FLAG_STRUCTURE_PICKUP     = _ci("flags","always_allow_structure_pickup",   "true").lower()  == "true"
FLAG_DISABLE_STRUCT_DECAY = _ci("flags","disable_structure_decay_pve",     "false").lower() == "true"
FLAG_DISABLE_DINO_DECAY   = _ci("flags","disable_dino_decay_pve",          "false").lower() == "true"
FLAG_CAVE_BUILDING        = _ci("flags","allow_cave_building_pve",         "false").lower() == "true"
FLAG_ANYONE_IMPRINT       = _ci("flags","allow_anyone_baby_imprint_cuddle","false").lower() == "true"
FLAG_FLYER_CARRY          = _ci("flags","allow_flyer_carry_pve",           "true").lower()  == "true"
FLAG_FLYER_SPEED          = _ci("flags","allow_flyer_speed_leveling",      "false").lower() == "true"
FLAG_NO_DL_SURVIVORS      = _ci("flags","prevent_download_survivors",      "false").lower() == "true"
FLAG_NO_DL_ITEMS          = _ci("flags","prevent_download_items",          "false").lower() == "true"
FLAG_REQUIRE_CRYOFRIDGE   = _ci("flags","require_powered_cryofridge",      "true").lower()  == "true"
FLAG_CRYO_SICKNESS        = _ci("flags","disable_cryo_sickness_pvp",       "false").lower() == "true"
FLAG_CAVE_FLYERS          = _ci("flags","force_allow_cave_flyers",          "false").lower() == "true"
FLAG_EXCLUSIVE_JOIN       = _ci("flags","exclusive_join",                   "false").lower() == "true"

# ── Mods ─────────────────────────────────────────────────────────────────────
CROSSPLAY = _ci("mods", "crossplay", "false").lower() == "true"
MOD_IDS   = _ci("mods", "mod_ids",   "").strip()

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
        ("aberration",     "Aberration",     "Aberration_WP",     7827,      27065,      27029),
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
    seen_log_lines: deque = field(default_factory=lambda: deque(maxlen=500))
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
    # ── Crash restart tracking ──────────────────────────────────────────────
    crash_restart_count: int = 0
    last_crash_restart_at: Optional[float] = None
    crash_window_start: Optional[float] = None
    # True only when the server went offline due to a crash (not a manual stop)
    # — guards the cooldown-retry so intentional shutdowns don't auto-restart
    crash_offline: bool = False
    # Set when crash_restart_count hits the max — cleared on manual restart
    crash_limit_reached: bool = False
    # PID of the last Popen'd server process — used to force-kill on shutdown
    process_pid: int = 0


@dataclass
class ClusterState:
    shutdown_scheduled: bool = False
    shutdown_at: Optional[float] = None
    last_announcement_remaining: Optional[int] = None
    cluster_stopped: bool = False
    restart_pending: bool = False
    # Set to True after the shutdown Discord message is sent so no further
    # Discord notifications go out while servers are winding down / starting
    discord_silent: bool = False


SERVER_STATES: Dict[str, ServerState] = {k: ServerState(cfg=v) for k, v in SERVERS.items()}
CLUSTER = ClusterState()

# Reentrant lock — ensures the Discord bot thread and the main loop never
# modify SERVER_STATES / CLUSTER at the same time.  RLock allows the same
# thread to acquire it multiple times (e.g. handle_admin_command → start_server).
_cluster_lock = threading.RLock()


def _rotate_log() -> None:
    """On controller startup: archive the current log with a timestamp, then
    delete the oldest archived logs if the count exceeds MAX_LOGS."""
    if not os.path.exists(LOG_FILE):
        return
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    archived = os.path.join(LOGS_DIR, f"controller_{ts}.log")
    try:
        os.rename(LOG_FILE, archived)
    except Exception:
        return
    # Prune oldest archived logs
    old_logs = sorted(Path(LOGS_DIR).glob("controller_*.log"), key=lambda p: p.name)
    while len(old_logs) > MAX_LOGS:
        try:
            old_logs.pop(0).unlink()
        except Exception:
            pass


_last_log_rotate_day: Optional[int] = None

def _maybe_rotate_log_daily() -> None:
    """If no scheduled restart is configured, rotate the log once per calendar day."""
    global _last_log_rotate_day
    if RESTART_TIME:
        return  # scheduled restart handles rotation via controller reboot
    today = time.localtime().tm_yday
    if _last_log_rotate_day is None:
        _last_log_rotate_day = today
        return
    if today != _last_log_rotate_day:
        _last_log_rotate_day = today
        _rotate_log()


def log(msg: str) -> None:
    _maybe_rotate_log_daily()
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    target = ADMIN_LOG_FILE if _is_admin_context else LOG_FILE
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# Discord embed colour constants
_DC_GREEN  = 3066993   # server online
_DC_RED    = 15158332  # crash / offline
_DC_ORANGE = 16744272  # warning / cooldown
_DC_BLUE   = 3447003   # cluster restart / info
_DC_GREY   = 10070709  # cluster shutdown


def _dc_flag(key: str, default: str = "true") -> bool:
    """Read a discord toggle from config (re-read each call for live changes)."""
    c = _read_live_cfg()
    return (c.get("discord", key) if c.has_option("discord", key) else default).lower() == "true"


class DiscordBot:
    """Runs a discord.py client in a background daemon thread.

    Call start() once from main() — it no-ops if the bot is not configured.
    Use send() from any thread to post an embed to the notification channel.
    Commands typed in the command channel are dispatched to handle_admin_command().
    """

    def __init__(self) -> None:
        self._loop:          Optional[asyncio.AbstractEventLoop] = None
        self._client                                             = None
        self._notif_channel                                      = None
        self._notif_channel_id: int                              = 0
        self._cmd_channel_id:   int                              = 0
        self._ready:            bool                             = False

    # ── startup ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spin the bot up in a daemon thread. Silent no-op if not configured or use_bot=false."""
        use_bot  = (_cfg.get("discord", "use_bot")                 if _cfg.has_option("discord", "use_bot")                 else "false").strip().lower() == "true"
        token    = (_cfg.get("discord", "bot_token")               if _cfg.has_option("discord", "bot_token")               else "").strip()
        notif_id = (_cfg.get("discord", "notification_channel_id") if _cfg.has_option("discord", "notification_channel_id") else "").strip()
        cmd_id   = (_cfg.get("discord", "command_channel_id")      if _cfg.has_option("discord", "command_channel_id")      else "").strip()

        if not use_bot or not token or not notif_id:
            return  # webhook mode or not configured — stay silent

        try:
            self._notif_channel_id = int(notif_id)
            self._cmd_channel_id   = int(cmd_id) if cmd_id else self._notif_channel_id
        except ValueError:
            log("Discord: invalid channel ID in config — bot not started")
            return

        t = threading.Thread(target=self._run, args=(token,), daemon=True, name="DiscordBot")
        t.start()

    def _run(self, token: str) -> None:
        try:
            import discord  # type: ignore
        except ImportError:
            log("Discord: discord.py not installed — run: pip install discord.py")
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            self._notif_channel = self._client.get_channel(self._notif_channel_id)
            if not self._notif_channel:
                log(f"Discord: notification channel {self._notif_channel_id} not found — "
                    f"check the channel ID and that the bot has access to it")
            else:
                self._ready = True
            log(f"Discord bot online as {self._client.user}")

        @self._client.event
        async def on_message(message) -> None:
            if message.author == self._client.user:
                return
            if message.channel.id != self._cmd_channel_id:
                return
            if not message.content.strip().startswith("!"):
                return
            await self._dispatch(message)

        try:
            self._loop.run_until_complete(self._client.start(token))
        except Exception as exc:
            log(f"Discord bot error: {exc}")

    # ── command dispatch ──────────────────────────────────────────────────────

    async def _dispatch(self, message) -> None:
        import discord  # type: ignore

        # Guard: bot commands only work in guild (server) channels, not DMs
        if not hasattr(message.author, "roles"):
            await message.reply("❌ Bot commands only work in a server channel, not in DMs.")
            return

        # Guard: event loop must be ready
        if not self._loop:
            await message.reply("❌ Bot is still initialising — try again in a moment.")
            return

        # Role check — re-read from config so changes take effect without restart
        _rc = _read_live_cfg()
        admin_role = (_rc.get("discord", "admin_role_name") if _rc.has_option("discord", "admin_role_name") else "Admin").strip()
        role_names = [r.name for r in message.author.roles]
        if admin_role not in role_names:
            await message.reply(f"❌ You need the **{admin_role}** role to use bot commands.")
            return

        parts = message.content.strip().split()
        base  = parts[0].lower()   # e.g. "!status"
        arg   = parts[1].lower() if len(parts) > 1 else ""

        if base == "!help":
            map_list = ", ".join(SERVERS.keys())
            embed = discord.Embed(title="ASA Controller Commands", color=_DC_BLUE)
            embed.add_field(name="!status",         value="Cluster overview",                    inline=False)
            embed.add_field(name="!players",        value="Who's online on each server",         inline=False)
            embed.add_field(name="!start",          value="Start the cluster",                   inline=False)
            embed.add_field(name="!start <map>",    value="Start a specific map",                inline=False)
            embed.add_field(name="!stop",           value="Shutdown the cluster (with warning)", inline=False)
            embed.add_field(name="!stop <map>",     value="Stop a specific map (with warning)",  inline=False)
            embed.add_field(name="!restart",        value="Restart the cluster (with warning)",  inline=False)
            embed.add_field(name="Maps",            value=f"`{map_list}`",                       inline=False)
            await message.channel.send(embed=embed)
            return


        if base == "!status":
            # Snapshot to avoid race condition if main thread modifies SERVER_STATES
            states = list(SERVER_STATES.values())
            lines = []
            for state in states:
                if state.is_running:
                    lines.append(f"🟢 **{state.cfg.display_name}** — {state.player_count} player(s)")
                elif state.is_starting:
                    lines.append(f"🟡 **{state.cfg.display_name}** — starting…")
                else:
                    lines.append(f"🔴 **{state.cfg.display_name}** — offline")
            total = sum(s.player_count for s in states)
            embed = discord.Embed(
                title=f"{CLUSTER_NAME} — Status",
                description="\n".join(lines) or "No servers configured",
                color=_DC_BLUE,
            )
            embed.set_footer(text=f"Total players online: {total}")
            await message.channel.send(embed=embed)
            return

        if base == "!players":
            # Snapshot to avoid race condition
            states = list(SERVER_STATES.values())
            embed = discord.Embed(title=f"{CLUSTER_NAME} — Players Online", color=_DC_BLUE)
            any_online = False
            for state in states:
                if state.is_running and state.player_list:
                    names = "\n".join(p.get("name", "Unknown") for p in list(state.player_list))
                    embed.add_field(name=state.cfg.display_name, value=names, inline=True)
                    any_online = True
            if not any_online:
                embed.description = "No players online right now."
            await message.channel.send(embed=embed)
            return

        if base == "!start":
            if arg:
                map_key = normalize_map_name(arg)
                if not map_key or map_key not in SERVER_STATES:
                    await message.reply(f"❌ Unknown map: `{arg}`")
                    return
                display = SERVER_STATES[map_key].cfg.display_name
                await self._loop.run_in_executor(None, handle_admin_command, f"start {map_key}")
                await message.reply(f"✅ Starting **{display}**…")
            else:
                await self._loop.run_in_executor(None, handle_admin_command, "start cluster")
                await message.reply("✅ Starting cluster…")
            return

        if base == "!stop":
            if arg:
                map_key = normalize_map_name(arg)
                if not map_key or map_key not in SERVER_STATES:
                    await message.reply(f"❌ Unknown map: `{arg}`")
                    return
                display = SERVER_STATES[map_key].cfg.display_name
                await self._loop.run_in_executor(None, handle_admin_command, f"stop {map_key}")
                await message.reply(f"✅ Stopping **{display}** (warning sent to players)…")
            else:
                await self._loop.run_in_executor(None, handle_admin_command, "shutdown cluster")
                await message.reply("✅ Cluster shutdown initiated (players warned)…")
            return

        if base == "!restart":
            await self._loop.run_in_executor(None, handle_admin_command, "restart")
            await message.reply("✅ Cluster restart initiated (players warned)…")
            return

        await message.reply("❌ Unknown command. Type `!help` for the list.")

    # ── send (thread-safe) ────────────────────────────────────────────────────

    def send(self, message: str, color: int = _DC_BLUE, title: str = "") -> None:
        """Post an embed to the notification channel. Safe to call from any thread."""
        if not self._ready or not self._notif_channel or not self._loop:
            log("Discord: bot not ready — notification dropped (bot still starting or channel not found)")
            return
        try:
            import discord  # type: ignore
            embed = discord.Embed(description=message, color=color)
            if title:
                embed.title = title
            asyncio.run_coroutine_threadsafe(
                self._notif_channel.send(embed=embed),
                self._loop,
            )
        except Exception as exc:
            log(f"Discord send failed: {exc}")


# Global bot instance — started in main()
DISCORD_BOT = DiscordBot()


def discord_notify(message: str, color: int = _DC_BLUE, title: str = "") -> None:
    """Send a Discord notification via bot or webhook depending on config."""
    # Master switch — disabled by default, must be explicitly enabled in settings
    enabled = (_cfg.get("discord", "discord_enabled") if _cfg.has_option("discord", "discord_enabled") else "false").strip().lower() == "true"
    if not enabled:
        return

    # Silenced after cluster shutdown message — suppress notifications while
    # servers wind down or starting maps come online during a shutdown sequence
    if CLUSTER.discord_silent:
        return

    use_bot = (_cfg.get("discord", "use_bot") if _cfg.has_option("discord", "use_bot") else "false").strip().lower() == "true"

    if use_bot:
        DISCORD_BOT.send(message, color, title)
        return

    # Webhook fallback — run in a daemon thread so it never blocks the main loop
    url = (_cfg.get("discord", "webhook_url") if _cfg.has_option("discord", "webhook_url") else "").strip()
    if not url:
        return

    def _post() -> None:
        try:
            embed: dict = {"description": message, "color": color}
            if title:
                embed["title"] = title
            payload = json.dumps({"embeds": [embed]}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "ASA-Cluster-Controller"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as exc:
            log(f"Discord webhook failed: {exc}")

    threading.Thread(target=_post, daemon=True).start()


def _is_valid_steam_id(sid: str) -> bool:
    """Steam IDs are exactly 17 decimal digits."""
    return bool(re.match(r'^\d{17}$', sid.strip()))


def load_whitelist() -> set:
    """Return set of whitelisted Steam IDs. Empty set = whitelist disabled (all allowed)."""
    if not os.path.exists(WHITELIST_FILE):
        return set()
    try:
        with open(WHITELIST_FILE, encoding="utf-8") as f:
            valid = set()
            for line in f:
                sid = line.strip()
                if not sid or sid.startswith("#"):
                    continue
                if _is_valid_steam_id(sid):
                    valid.add(sid)
                else:
                    log(f"Whitelist: ignoring malformed entry '{sid}'")
            return valid
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


def _read_live_cfg() -> configparser.RawConfigParser:
    """Re-read config.ini from disk so settings-page changes apply on the next server start
    without needing a full controller restart."""
    c = configparser.RawConfigParser()
    try:
        c.read(os.path.join(BASE_DIR, "config.ini"), encoding="utf-8")
    except Exception:
        pass
    decrypt_config(c)
    return c


def _lci(c: configparser.RawConfigParser, section: str, key: str, fallback: str) -> str:
    try:
        return c.get(section, key)
    except Exception:
        return fallback


def _patch_game_user_settings() -> None:
    """Write controlled settings from config.ini into GameUserSettings.ini before server launch.

    Uses a line-by-line rewriter instead of configparser so that:
    - Keys are matched case-insensitively (ARK writes lowercase; we use CamelCase)
    - Values are written as key=value with no spaces (ARK's native format)
    - Duplicate lowercase keys left by ARK are replaced, not appended
    """
    settings_path = os.path.join(
        SERVER_ROOT, "ShooterGame", "Saved", "Config", "WindowsServer", "GameUserSettings.ini"
    )
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    # Re-read config fresh so dashboard edits take effect without a controller restart
    c = _read_live_cfg()
    def r(s, k, fb): return _lci(c, s, k, fb)
    def _b(s, k, fb): return "True" if r(s, k, fb).lower() == "true" else "False"

    # Helper: try new section, fall back to old (compat for mating/egg moved from [rates])
    def r2(new_s, old_s, k, fb):
        v = _lci(c, new_s, k, None)
        return v if v is not None else _lci(c, old_s, k, fb)

    desired = {
        # ── Limits ────────────────────────────────────────────────────────────
        "MaxPlayers":                              r2("limits",    "performance","max_players",                               str(MAX_PLAYERS)),
        "MaxTamedDinos":                           r("limits",     "max_tamed_dinos",                                        "5000"),
        "MaxPersonalTamedDinos":                   r("limits",     "max_personal_tamed_dinos",                               "40"),
        # ── World ─────────────────────────────────────────────────────────────
        "DayTimeSpeedScale":                       r("world",      "day_time_speed_scale",                                   DAY_TIME_SPEED),
        "NightTimeSpeedScale":                     r("world",      "night_time_speed_scale",                                 NIGHT_TIME_SPEED),
        "DinoCountMultiplier":                     r("world",      "dino_count_multiplier",                                  DINO_COUNT_MULT),
        "ResourcesRespawnPeriodMultiplier":        r("world",      "resources_respawn_period_multiplier",                   RESOURCES_RESPAWN),
        # ── Rates ─────────────────────────────────────────────────────────────
        "XPMultiplier":                            r("rates",      "xp_multiplier",                                          XP_MULTIPLIER),
        "TamingSpeedMultiplier":                   r("rates",      "taming_speed_multiplier",                                TAMING_SPEED_MULTIPLIER),
        "HarvestAmountMultiplier":                 r("rates",      "harvest_amount_multiplier",                              HARVEST_AMOUNT_MULTIPLIER),
        "DifficultyOffset":                        r("rates",      "difficulty_offset",                                      DIFFICULTY_OFFSET),
        "ItemStackSizeMultiplier":                 r("rates",      "item_stack_size_multiplier",                             ITEM_STACK_SIZE_MULT),
        "LootQualityMultiplier":                   r("rates",      "loot_quality_multiplier",                                LOOT_QUALITY_MULT),
        "FishingLootQualityMultiplier":            r("rates",      "fishing_loot_quality_multiplier",                        FISHING_LOOT_MULT),
        "SupplyCrateLootQualityMultiplier":        r("rates",      "supply_crate_loot_quality_multiplier",                   SUPPLY_CRATE_LOOT_MULT),
        # ── Survival ──────────────────────────────────────────────────────────
        "PlayerCharacterFoodDrainMultiplier":      r("survival",   "player_food_drain_multiplier",                           PLAYER_FOOD_DRAIN),
        "PlayerCharacterWaterDrainMultiplier":     r("survival",   "player_water_drain_multiplier",                          PLAYER_WATER_DRAIN),
        "PlayerCharacterStaminaDrainMultiplier":   r("survival",   "player_stamina_drain_multiplier",                        PLAYER_STAMINA_DRAIN),
        "PlayerCharacterHealthRecoveryMultiplier": r("survival",   "player_health_recovery_multiplier",                      PLAYER_HEALTH_REGEN),
        "DinoCharacterFoodDrainMultiplier":        r("survival",   "dino_food_drain_multiplier",                             DINO_FOOD_DRAIN),
        "DinoCharacterHealthRecoveryMultiplier":   r("survival",   "dino_health_recovery_multiplier",                        DINO_HEALTH_REGEN),
        # ── Combat ────────────────────────────────────────────────────────────
        "PlayerDamageMultiplier":                  r("combat",     "player_damage_multiplier",                               PLAYER_DAMAGE_MULT),
        "PlayerResistanceMultiplier":              r("combat",     "player_resistance_multiplier",                           PLAYER_RESISTANCE_MULT),
        "DinoDamageMultiplier":                    r("combat",     "dino_damage_multiplier",                                 DINO_DAMAGE_MULT),
        "DinoResistanceMultiplier":                r("combat",     "dino_resistance_multiplier",                             DINO_RESISTANCE_MULT),
        "TamedDinoDamageMultiplier":               r("combat",     "tamed_dino_damage_multiplier",                           TAMED_DINO_DAMAGE_MULT),
        "TamedDinoResistanceMultiplier":           r("combat",     "tamed_dino_resistance_multiplier",                       TAMED_DINO_RES_MULT),
        "StructureDamageMultiplier":               r("combat",     "structure_damage_multiplier",                            STRUCT_DAMAGE_MULT),
        "ShowFloatingDamageText":                  _b("combat",    "show_floating_damage_text",                              "false"),
        "AllowHitMarkers":                         _b("combat",    "allow_hit_markers",                                      "true"),
        # ── Structures ────────────────────────────────────────────────────────
        "StructurePickupTimeAfterPlacement":       r("structures", "structure_pickup_time_after_placement",                  STRUCT_PICKUP_TIME),
        "PerPlatformMaxStructuresMultiplier":      r("structures", "per_platform_max_structures_multiplier",                 PER_PLATFORM_STRUCT),
        # ── Flags ─────────────────────────────────────────────────────────────
        "AlwaysAllowStructurePickup":              _b("flags",     "always_allow_structure_pickup",                          "true"),
        "DisableStructureDecayPvE":                _b("flags",     "disable_structure_decay_pve",                            "false"),
        "DisableDinoDecayPvE":                     _b("flags",     "disable_dino_decay_pve",                                 "false"),
        "AllowCaveBuildingPvE":                    _b("flags",     "allow_cave_building_pve",                                "false"),
        "AllowAnyoneBabyImprintCuddle":            _b("flags",     "allow_anyone_baby_imprint_cuddle",                       "false"),
        "AllowFlyerCarryPvE":                      _b("flags",     "allow_flyer_carry_pve",                                  "true"),
        "AllowFlyerSpeedLeveling":                 _b("flags",     "allow_flyer_speed_leveling",                             "false"),
        "DisableCryoSicknessPVP":                  _b("flags",     "disable_cryo_sickness_pvp",                              "false"),
        # bDisableCryopodEnemyCheck=True removes the powered-fridge-nearby requirement (inverted flag)
        "bDisableCryopodEnemyCheck":               "False" if r("flags","require_powered_cryofridge","true").lower() == "true" else "True",
    }

    # Build a lowercase lookup so we can match ARK's own lowercase key names
    desired_lower = {k.lower(): (k, v) for k, v in desired.items()}

    # ── Read existing file ─────────────────────────────────────────────────────
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            orig_lines = f.readlines()
    else:
        orig_lines = ["[ServerSettings]\n"]

    # ── Rewrite line-by-line, replacing keys case-insensitively ───────────────
    in_ss       = False          # are we inside [ServerSettings]?
    seen        = set()          # lowercase keys already written
    result      = []

    for line in orig_lines:
        stripped = line.strip()

        # Section header?
        if stripped.startswith("["):
            if in_ss:
                # Leaving [ServerSettings] — flush any keys not yet seen
                for lk, (ck, val) in desired_lower.items():
                    if lk not in seen:
                        result.append(f"{ck}={val}\n")
                        seen.add(lk)
            in_ss = stripped.lower() == "[serversettings]"
            result.append(line)
            continue

        # Inside [ServerSettings] and looks like a key=value line?
        if in_ss and "=" in stripped and not stripped.startswith(";"):
            key_part = stripped.split("=", 1)[0].strip().lower()
            if key_part in desired_lower:
                ck, val = desired_lower[key_part]
                if key_part not in seen:          # write once; skip duplicates
                    result.append(f"{ck}={val}\n")
                    seen.add(key_part)
                continue                          # drop original line
            # Unmanaged key — keep as-is
            result.append(line)
        else:
            result.append(line)

    # If we reached EOF still inside [ServerSettings] (or it was the last section)
    if in_ss:
        for lk, (ck, val) in desired_lower.items():
            if lk not in seen:
                result.append(f"{ck}={val}\n")
                seen.add(lk)

    # If [ServerSettings] was never found at all, append it
    if not seen:
        result.append("\n[ServerSettings]\n")
        for ck, val in desired.items():
            result.append(f"{ck}={val}\n")

    # ── Write only if content changed ─────────────────────────────────────────
    new_text = "".join(result)
    old_text  = "".join(orig_lines)
    if new_text == old_text:
        return

    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    log(f"GameUserSettings.ini patched ({settings_path})")


def _patch_game_ini() -> None:
    """Write breeding multipliers from config.ini into Game.ini before server launch.

    Breeding settings belong in Game.ini under [/Script/ShooterGame.ShooterGameMode],
    NOT in GameUserSettings.ini — the server ignores them if placed there.
    """
    game_ini_path = os.path.join(
        SERVER_ROOT, "ShooterGame", "Saved", "Config", "WindowsServer", "Game.ini"
    )
    os.makedirs(os.path.dirname(game_ini_path), exist_ok=True)

    c = _read_live_cfg()
    def r(s, k, fb): return _lci(c, s, k, fb)
    def r2(new_s, old_s, k, fb):
        v = _lci(c, new_s, k, None)
        return v if v is not None else _lci(c, old_s, k, fb)

    desired = {
        "MatingIntervalMultiplier":        r2("breeding", "rates", "mating_interval_multiplier",         MATING_INTERVAL_MULT),
        "MatingSpeedMultiplier":           r2("breeding", "rates", "mating_speed_multiplier",            MATING_SPEED_MULT),
        "EggHatchSpeedMultiplier":         r2("breeding", "rates", "egg_hatch_speed_multiplier",         EGG_HATCH_SPEED_MULT),
        "LayEggIntervalMultiplier":        r( "breeding",          "lay_egg_interval_multiplier",        LAY_EGG_INTERVAL_MULT),
        "BabyMatureSpeedMultiplier":       r( "breeding",          "baby_mature_speed_multiplier",       BABY_MATURE_SPEED_MULT),
        "BabyCuddleIntervalMultiplier":    r( "breeding",          "baby_cuddle_interval_multiplier",    BABY_CUDDLE_INTERVAL_MULT),
        "BabyCuddleGracePeriodMultiplier": r( "breeding",          "baby_cuddle_grace_period_multiplier",BABY_CUDDLE_GRACE_PERIOD_MULT),
        "BabyImprintAmountMultiplier":     r( "breeding",          "baby_imprint_amount_multiplier",     BABY_IMPRINT_AMOUNT_MULT),
        # ── Rates (Game.ini only) ─────────────────────────────────────────────
        "GlobalSpoilingTimeMultiplier":            r("rates", "global_spoiling_time_multiplier",             GLOBAL_SPOILING_TIME_MULT),
        "GlobalItemDecompositionTimeMultiplier":   r("rates", "global_item_decomposition_time_multiplier",   GLOBAL_ITEM_DECOMP_MULT),
        "GlobalCorpseDecompositionTimeMultiplier": r("rates", "global_corpse_decomposition_time_multiplier", GLOBAL_CORPSE_DECOMP_MULT),
        "CropGrowthSpeedMultiplier":               r("rates", "crop_growth_speed_multiplier",                CROP_GROWTH_SPEED_MULT),
        "FuelConsumptionIntervalMultiplier":       r("rates", "fuel_consumption_interval_multiplier",        FUEL_CONSUMPTION_MULT),
    }

    section = "[/Script/ShooterGame.ShooterGameMode]"
    desired_lower = {k.lower(): (k, v) for k, v in desired.items()}

    if os.path.exists(game_ini_path):
        with open(game_ini_path, "r", encoding="utf-8") as f:
            orig_lines = f.readlines()
    else:
        orig_lines = [f"{section}\n"]

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
            in_sec = stripped.lower() == section.lower()
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
        result.append(f"\n{section}\n")
        for ck, val in desired.items():
            result.append(f"{ck}={val}\n")

    new_text = "".join(result)
    if new_text != "".join(orig_lines):
        with open(game_ini_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        log(f"Game.ini patched ({game_ini_path})")


def _patch_engine_ini() -> None:
    """Tune GC frequency in Engine.ini before server launch."""
    engine_ini_path = os.path.join(
        SERVER_ROOT, "ShooterGame", "Saved", "Config", "WindowsServer", "Engine.ini"
    )
    os.makedirs(os.path.dirname(engine_ini_path), exist_ok=True)

    c = _read_live_cfg()
    def r(s, k, fb): return _lci(c, s, k, fb)

    section   = "[/Script/Engine.GarbageCollectionSettings]"
    desired   = {
        "gc.TimeBetweenPurgingPendingKillObjects": r("limits", "gc_purge_interval", GC_PURGE_INTERVAL),
    }
    desired_lower = {k.lower(): (k, v) for k, v in desired.items()}

    if os.path.exists(engine_ini_path):
        with open(engine_ini_path, "r", encoding="utf-8") as f:
            orig_lines = f.readlines()
    else:
        orig_lines = []

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
            in_sec = stripped.lower() == section.lower()
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
        result.append(f"\n{section}\n")
        for ck, val in desired.items():
            result.append(f"{ck}={val}\n")

    new_text = "".join(result)
    if new_text != "".join(orig_lines):
        with open(engine_ini_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        log(f"Engine.ini patched ({engine_ini_path})")


def start_server(key: str) -> bool:
    with _cluster_lock:
        return _start_server_locked(key)


def _start_server_locked(key: str) -> bool:
    # Never launch a server while a shutdown or cluster-stop is in progress
    if CLUSTER.shutdown_scheduled or CLUSTER.cluster_stopped:
        log(f"start_server({key}) blocked — cluster shutdown in progress")
        return False
    state = SERVER_STATES[key]
    if state.is_running or state.is_starting:
        return False

    exe = os.path.join(SERVER_ROOT, "ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
    if not os.path.exists(exe):
        log(f"ArkAscendedServer.exe not found at: {exe}")
        return False

    try:
        _patch_game_user_settings()
        _patch_game_ini()
        _patch_engine_ini()
    except Exception as _patch_exc:
        log(f"ERROR: Failed to patch server config files for {key}: {_patch_exc}")
        log(f"       Server will not start — fix the path/permissions issue and retry.")
        return False

    # Re-read config fresh so settings-page changes apply without a controller restart
    _lc = _read_live_cfg()
    def _lr(s, k, fb):       return _lci(_lc, s, k, fb)
    def _lr2(s, k, fb, alt): v = _lci(_lc, s, k, None); return v if v is not None else _lci(_lc, alt, k, fb)

    _max_players    = _lr2("limits",  "max_players",              str(MAX_PLAYERS),   "performance")
    _low_memory     = _lr("limits", "low_memory_mode",            "true").lower()  == "true"
    _no_sound       = _lr("limits", "no_sound",                   "true").lower()  == "true"
    _third_person   = _lr("flags",  "allow_third_person",         "false").lower() == "true"
    _show_map_loc   = _lr("flags",  "show_map_player_location",   "true").lower()  == "true"
    _no_dl_surv     = _lr("flags",  "prevent_download_survivors", "false").lower() == "true"
    _no_dl_items    = _lr("flags",  "prevent_download_items",     "false").lower() == "true"
    _cave_flyers    = _lr("flags",  "force_allow_cave_flyers",    "false").lower() == "true"
    _excl_join      = _lr("flags",  "exclusive_join",             "false").lower() == "true"
    _crossplay      = _lr("mods",   "crossplay",                  "false").lower() == "true"
    _mod_ids        = _lr("mods",   "mod_ids",                    "").strip()
    _active_event   = _lr("world",  "active_event",               "").strip()

    session_name = f"{CLUSTER_NAME}_{state.cfg.display_name.replace(' ', '')}"
    map_arg = (
        f"{state.cfg.map_name}"
        f"?SessionName={session_name}"
        f"?MaxPlayers={_max_players}"
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
    if _low_memory:     flags.extend(["-lowmemory", "-nomemorybias"])
    if _no_sound:       flags.append("-nosound")
    if _third_person:   flags.append("-AllowThirdPersonPlayer")
    if _show_map_loc:   flags.append("-ShowMapPlayerLocation")
    if _no_dl_surv:     flags.append("-PreventDownloadSurvivors")
    if _no_dl_items:    flags.append("-PreventDownloadItems")
    if _cave_flyers:    flags.append("-ForceAllowCaveFlyers")
    if _excl_join:      flags.append("-exclusivejoin")
    if _crossplay:      flags.append("-crossplay")
    if _mod_ids:        flags.append(f"-GameModIds={_mod_ids}")
    if _active_event:   flags.append(f"-ActiveEvent={_active_event}")

    log(f"Starting {key}")
    # CREATE_BREAKAWAY_FROM_JOB (0x01000000) ensures the server process is
    # fully detached from the controller's job object so it keeps running
    # if the controller is restarted or killed.
    proc = subprocess.Popen(
        [exe, map_arg] + flags,
        cwd=os.path.dirname(exe),
        creationflags=subprocess.CREATE_NEW_CONSOLE | 0x01000000,
    )
    state.process_pid = proc.pid
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
    state.process_pid = 0
    # Intentional stop — disarm crash auto-restart so it doesn't come back up
    state.crash_offline          = False
    state.last_crash_restart_at  = None
    state.crash_window_start     = None
    state.crash_restart_count    = 0
    state.crash_limit_reached    = False


def split_chat_sender_and_message(line: str):
    line = line.strip()
    cmd_match = re.search(r"!(start|status|stop|restart|help)\b.*$", line, re.IGNORECASE)
    if not cmd_match:
        return None, line

    message = cmd_match.group(0).strip()
    prefix = line[:cmd_match.start()].strip().rstrip(": ")
    prefix = re.sub(r"^\[[^\]]+\]\s*", "", prefix).strip()
    sender = prefix.split(":")[-1].strip() if ":" in prefix else prefix.strip()
    sender = re.sub(r"\s*\([^)]*\)\s*$", "", sender).strip()
    return sender or None, message


_DEFAULT_CATEGORIES: Dict[str, str] = {
    "!help":    "default",
    "!status":  "default",
    "!start":   "whitelist",
}


def _get_command_categories() -> Dict[str, str]:
    """Return {command: tier} dict.  Tier is 'default', 'whitelist', or 'admin'."""
    if not os.path.exists(COMMAND_CATEGORIES_FILE):
        return dict(_DEFAULT_CATEGORIES)
    try:
        with open(COMMAND_CATEGORIES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if data else dict(_DEFAULT_CATEGORIES)
    except Exception:
        return dict(_DEFAULT_CATEGORIES)


def _is_admin(steam_id: Optional[str]) -> bool:
    if not steam_id:
        return False
    if not os.path.exists(ADMIN_LIST_FILE):
        return False
    try:
        with open(ADMIN_LIST_FILE, encoding="utf-8") as f:
            return steam_id in {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    except Exception:
        return False


def _check_access(tier: str, steam_id: Optional[str], origin: ServerState) -> bool:
    """Return True if the player may use a command of the given tier."""
    if tier == "default":
        return True
    if tier == "whitelist":
        if is_whitelisted(steam_id):
            return True
        announce(origin, "You are not whitelisted to use this command")
        return False
    if tier == "admin":
        if _is_admin(steam_id):
            return True
        announce(origin, "You do not have permission to use this command")
        return False
    return False


def handle_command(origin: ServerState, sender_name: Optional[str], steam_id: Optional[str], message: str) -> None:
    lowered = message.strip().lower()
    cats    = _get_command_categories()

    if lowered == "!help":
        tier = cats.get("!help")
        if not tier or not _check_access(tier, steam_id, origin):
            return
        visible = sorted(
            c for c, t in cats.items()
            if t == "default"
            or (t == "whitelist" and is_whitelisted(steam_id))
            or (t == "admin"     and _is_admin(steam_id))
        )
        announce(origin, f"Commands: {' | '.join(visible)}")
        announce(origin, f"Maps: {', '.join(SERVERS.keys())}")
        return

    if lowered == "!status":
        tier = cats.get("!status")
        if not tier or not _check_access(tier, steam_id, origin):
            return
        active = [s for s in SERVER_STATES.values() if s.is_running]
        if active:
            parts = [f"{s.cfg.key}:{s.player_count}" for s in active]
            announce(origin, f"Active maps: {', '.join(parts)}")
        else:
            announce(origin, "No active maps")
        return

    start_match = re.match(r"!start\s+(.+)", lowered)
    if start_match:
        tier = cats.get("!start")
        if not tier or not _check_access(tier, steam_id, origin):
            return
        requested = normalize_map_name(start_match.group(1))
        if not requested:
            announce(origin, f"Unknown map '{start_match.group(1)}'. Type !help for map names.")
            return
        state = SERVER_STATES.get(requested)
        if not state:
            return
        if state.is_running or state.is_starting:
            announce(origin, f"{state.cfg.display_name} is already online or starting.")
            return
        active = len(active_servers())
        _limit = _get_effective_max_servers()
        if active >= _limit:
            announce(origin, f"Max servers active ({active}/{_limit}) — not enough RAM to start another")
            return
        start_server(requested)
        announce(origin, f"{state.cfg.display_name} is starting up — give it a few minutes.")
        return

    stop_match = re.match(r"!stop\s+(.+)", lowered)
    if stop_match:
        tier = cats.get("!stop")
        if not tier or not _check_access(tier, steam_id, origin):
            return
        requested = normalize_map_name(stop_match.group(1))
        if not requested:
            return
        state = SERVER_STATES.get(requested)
        if not state or not state.is_running:
            announce(origin, f"{requested} is not running")
            return
        log(f"IN-GAME STOP {requested}: requested by {sender_name} ({steam_id})")
        announce_all_online(f"{state.cfg.display_name} is being stopped by an admin")
        stop_server_safe(state, "admin !stop command")
        return

    restart_match = re.match(r"!restart\s+(.+)", lowered)
    if restart_match:
        tier = cats.get("!restart")
        if not tier or not _check_access(tier, steam_id, origin):
            return
        requested = normalize_map_name(restart_match.group(1))
        if not requested:
            announce(origin, f"Unknown map '{restart_match.group(1)}'. Type !help for map names.")
            return
        log(f"IN-GAME RESTART {requested}: requested by {sender_name} ({steam_id})")
        restart_single_server(requested, origin=origin)
        return



def restart_single_server(key: str, origin: Optional["ServerState"] = None) -> None:
    state = SERVER_STATES.get(key)
    if state is None:
        log(f"restart_single_server: unknown key '{key}'")
        if origin is not None:
            announce(origin, f"Unknown map: {key}")
        return
    if not state.is_running:
        log(f"{key} is not running")
        if origin is not None:
            announce(origin, f"{state.cfg.display_name} is not running.")
        return
    log(f"RESTART {key}: saving and restarting...")
    announce(state, f"{state.cfg.display_name} is restarting now. Be back in a moment!")
    if origin is not None and origin.cfg.key != key and origin.is_running:
        announce(origin, f"{state.cfg.display_name} is restarting now.")
    stop_server_safe(state, "map restart")
    start_server(key)


def _add_to_whitelist(steam_id: str) -> None:
    if not _is_valid_steam_id(steam_id):
        log(f"Whitelist: rejected invalid Steam ID '{steam_id}' — must be exactly 17 digits")
        return
    try:
        existing: set = set()
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, encoding="utf-8") as f:
                existing = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        existing.add(steam_id.strip())
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
    log("  force shutdown cluster    (kills all immediately — dashboard shows a confirm dialog; direct console command is immediate with no confirmation)")
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



def perform_force_cluster_shutdown() -> None:
    """Immediately kill every server process — no save, no DoExit, no waiting.
    Use this when you need everything dead right now (e.g. stuck-starting maps).
    Only available as an admin command, never triggered automatically."""
    CLUSTER.shutdown_scheduled = True

    if _dc_flag("notify_cluster_events"):
        discord_notify(
            f"**{CLUSTER_NAME}** is being **force-stopped** ⛔\nAll server processes will be killed immediately.",
            _DC_GREY, "Cluster Force Shutdown")
    CLUSTER.discord_silent = True

    log("FORCE SHUTDOWN — killing all server processes immediately")
    announce_all_online("EMERGENCY SHUTDOWN — killing all servers now")

    for key, state in SERVER_STATES.items():
        if state.process_pid:
            log(f"Force-killing {key} (PID {state.process_pid})")
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(state.process_pid)],
                capture_output=True,
            )
        # Reset ALL state flags regardless of whether we had a PID stored
        state.process_pid = 0
        state.is_starting = False
        state.is_running = False
        state.start_requested_at = None
        state.pending_online_announcement = False
        state.players.clear()
        state.player_list = []
        state.player_count = 0
        state.crash_offline = False
        state.last_crash_restart_at = None
        state.crash_window_start = None
        state.crash_restart_count = 0
        # Clear any pending manual-stop countdown — otherwise handle_manual_stop_timers()
        # would fire on the next Start Cluster and immediately stop the freshly started server.
        state.manual_stop_since = None
        state.manual_stop_last_announcement_remaining = None
        state.manual_stop_duration_seconds = 0

    # Catch any adopted servers (process_pid=0) or processes that survived
    # the PID kill — wipe all ArkAscendedServer.exe processes still running.
    log("Force-killing any remaining ArkAscendedServer.exe processes...")
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", "ArkAscendedServer.exe"],
        capture_output=True,
    )

    CLUSTER.shutdown_scheduled = False
    CLUSTER.shutdown_at = None
    CLUSTER.last_announcement_remaining = None
    CLUSTER.cluster_stopped = True
    log("Force shutdown complete. Controller is idle — use Start Cluster to bring it back up.")


def perform_cluster_shutdown() -> None:
    # Lock out any new server starts immediately.  For instant shutdowns
    # (delay_seconds=0) shutdown_scheduled was never set by the scheduler, so
    # set it here so start_server() and ensure_default_server() both bail out.
    CLUSTER.shutdown_scheduled = True

    if _dc_flag("notify_cluster_events"):
        discord_notify(
            f"**{CLUSTER_NAME}** is shutting down ⛔\nAll servers will be stopped.",
            _DC_GREY, "Cluster Shutdown")
    # Silence all further Discord messages — a map that finishes starting up
    # during the shutdown sequence should not post an "online" notification.
    CLUSTER.discord_silent = True

    # Wait for any servers that are mid-startup to come fully online so they
    # can be stopped cleanly via RCON.  The main loop is blocked while we run,
    # so actively poll each starting server ourselves.
    starting_keys = [k for k, s in SERVER_STATES.items() if s.is_starting]
    if starting_keys:
        log(f"Shutdown waiting for server(s) to finish starting: {starting_keys}")
        announce_all_online(
            f"Shutdown pending — waiting for {', '.join(starting_keys)} to come online...")
        deadline = time.time() + SERVER_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            still_starting = [k for k in starting_keys if SERVER_STATES[k].is_starting]
            if not still_starting:
                log("All starting servers are now online — proceeding with shutdown.")
                break
            for k in still_starting:
                state = SERVER_STATES[k]
                update_running_status(state)
                # If this server has individually exceeded its own startup timeout,
                # stop waiting for it and let the force-kill block handle it.
                if (state.is_starting and state.start_requested_at
                        and time.time() - state.start_requested_at > SERVER_START_TIMEOUT_SECONDS):
                    log(f"Startup timeout exceeded for {k} during shutdown wait — will force-kill.")
                    state.is_starting = False
                    state.start_requested_at = None
            time.sleep(5)
        else:
            timed_out = [k for k in starting_keys if SERVER_STATES[k].is_starting]
            if timed_out:
                log(f"Startup wait timed out for: {timed_out} — proceeding with shutdown.")

    backup_world()
    log("Executing cluster shutdown")
    announce_all_online("Saving world...")

    for state in list(online_servers()):
        save_world(state)

    time.sleep(SAVE_BEFORE_EXIT_WAIT_SECONDS)

    announce_all_online("Cluster shutting down now")

    for state in list(online_servers()):
        stop_server_safe(state, "cluster shutdown")

    log(f"Waiting {POST_SHUTDOWN_WAIT_SECONDS}s for server processes to fully stop...")
    time.sleep(POST_SHUTDOWN_WAIT_SECONDS)

    # Force-kill any server processes still alive after the wait — this covers
    # maps that were starting up when shutdown was triggered and never came
    # online (so DoExit was never sent to them).
    for key, state in SERVER_STATES.items():
        if state.process_pid:
            log(f"Force-killing lingering server process PID {state.process_pid} for {key}")
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(state.process_pid)],
                capture_output=True,
            )
            state.process_pid = 0
        # Clear starting/running flags for ALL servers — a server that was mid-
        # startup when shutdown triggered will have is_starting=True but never
        # went through stop_server_safe(), so its state must be wiped here.
        state.is_starting = False
        state.is_running = False
        state.start_requested_at = None
        state.pending_online_announcement = False
        state.players.clear()
        state.player_list = []
        state.player_count = 0

    # Clear crash tracking on ALL servers — including any that were already
    # offline/crashed before the shutdown was triggered.  Without this, a
    # server that crashed mid-countdown would still have crash_offline=True
    # and could auto-restart after the cooldown even though the cluster was
    # intentionally stopped.
    for state in SERVER_STATES.values():
        state.crash_offline          = False
        state.last_crash_restart_at  = None
        state.crash_window_start     = None
        state.crash_restart_count    = 0

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
        # Set the flag before announcing so start_server() guards fire immediately,
        # even if the Discord bot races to call start_server() in its thread.
        CLUSTER.shutdown_scheduled = True
        announce_all_online("Cluster shutting down now")
        perform_cluster_shutdown()
        return

    CLUSTER.shutdown_scheduled = True
    CLUSTER.shutdown_at = time.time() + delay_seconds

    total_minutes = max(1, int(delay_seconds // 60))
    announce_all_online(f"Cluster shutdown scheduled in {total_minutes} minutes")
    # Mark this minute as already announced so handle_cluster_shutdown_timer()
    # doesn't immediately fire a second identical message on the next poll.
    CLUSTER.last_announcement_remaining = total_minutes
    log(f"Cluster shutdown scheduled in {total_minutes} minutes")
    if _dc_flag("notify_cluster_events"):
        discord_notify(
            f"**{CLUSTER_NAME}** shutdown scheduled in **{total_minutes} minutes** ⏳",
            _DC_GREY, "Cluster Shutdown Scheduled")


def cancel_cluster_shutdown() -> None:
    if not CLUSTER.shutdown_scheduled:
        log("cancel shutdown: no shutdown is currently scheduled — nothing to cancel.")
        return
    if CLUSTER.shutdown_scheduled:
        CLUSTER.shutdown_scheduled = False
        CLUSTER.shutdown_at = None
        CLUSTER.last_announcement_remaining = None
        CLUSTER.cluster_stopped = False
        CLUSTER.restart_pending = False
        # Re-enable Discord in case perform_cluster_shutdown() had already set
        # discord_silent before being interrupted (e.g. exception mid-shutdown)
        CLUSTER.discord_silent = False
        announce_all_online("Cluster shutdown cancelled")
        log("Cluster shutdown cancelled")



def perform_cluster_restart() -> None:
    if _dc_flag("notify_cluster_events"):
        discord_notify(
            f"**{CLUSTER_NAME}** is restarting 🔄\nServers will be back shortly.",
            _DC_BLUE, "Cluster Restart")
    backup_world()
    log("Executing cluster restart")
    announce_all_online("Server restarting. Saving world...")

    for state in list(online_servers()):
        save_world(state)

    time.sleep(SAVE_BEFORE_EXIT_WAIT_SECONDS)

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
    CLUSTER.discord_silent = False

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
    CLUSTER.last_announcement_remaining = total_minutes
    log(f"Server restart scheduled in {total_minutes} minutes")
    if _dc_flag("notify_cluster_events"):
        discord_notify(
            f"**{CLUSTER_NAME}** restart scheduled in **{total_minutes} minutes** ⏳",
            _DC_BLUE, "Cluster Restart Scheduled")


def handle_admin_command(command: str) -> None:
    with _cluster_lock:
        _handle_admin_command_locked(command)


def _handle_admin_command_locked(command: str) -> None:
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
        CLUSTER.discord_silent = False
        CLUSTER.cluster_stopped = False
        start_server(DEFAULT_SERVER_KEY)
        return

    if lowered == "shutdown cluster":
        schedule_cluster_shutdown(CLUSTER_SHUTDOWN_DELAY_SECONDS)
        return

    if lowered == "shutdown cluster now":
        schedule_cluster_shutdown(0)
        return

    if lowered == "force shutdown cluster":
        perform_force_cluster_shutdown()
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
        _limit = _get_effective_max_servers()
        if active >= _limit:
            log(f"Max servers active ({active}/{_limit}) — not enough RAM to start another")
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
        # Open in r+ so read and truncate happen on the same file handle,
        # closing the race window where the dashboard could write new commands
        # between a separate read-close and write-open.
        with open(ADMIN_COMMAND_FILE, "r+", encoding="utf-8") as f:
            commands = [line.strip() for line in f if line.strip()]
            f.seek(0)
            f.truncate()

        if not commands:
            return

        for command in commands:
            global _is_admin_context
            _is_admin_context = True
            try:
                log(f"ADMIN CMD: {command}")
                handle_admin_command(command)
            except Exception as exc:
                log(f"ADMIN CMD ERROR ({command}): {exc}")
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
        state.seen_log_lines.append(line)
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
            state.online_since  = now
            state.crash_offline = False   # server recovered — reset crash flag

        state.is_running = True
        state.is_starting = False
        state.last_seen_online_at = now
        state.player_list = parse_list_players_detailed(raw_players or "")
        state.player_count = len(state.player_list)
        if state.player_list:
            _update_seen_players(state)

        # On first contact only: replay the game log to recover who is
        # currently online. This handles controller restarts while players
        # are already in-game. ListPlayers is too unreliable in ASA for this.
        if just_came_online:
            sync_players_from_game_log(state)
            # sync_players_from_game_log overwrites player_count (via the log)
            # but not player_list (from ListPlayers). Re-align player_count so
            # the dashboard card and the player list always agree.
            state.player_count = len(state.player_list)

        if just_came_online and state.pending_online_announcement:
            announce_all_online(f"{state.cfg.display_name} is up and running")
            state.pending_online_announcement = False
            if _dc_flag("notify_server_events"):
                discord_notify(f"**{state.cfg.display_name}** is now online 🟢", _DC_GREEN)

        if state.last_autosave_at == 0:
            state.last_autosave_at = now
    else:
        if state.is_running:
            # Never run crash detection during an intentional cluster shutdown
            # or when the cluster has been stopped — avoid spurious restarts.
            # Still clear is_running so the dashboard doesn't show stale ONLINE
            # status and perform_cluster_shutdown() stops sending RCON to dead servers.
            if CLUSTER.cluster_stopped or CLUSTER.shutdown_scheduled:
                state.is_running = False
                state.players.clear()
                state.player_count = 0
                return

            # Brief settling grace after coming online — lets RCON stabilise
            # without falsely declaring a crash. Much shorter than the full
            # startup grace; rcon_fail_count handles transient hiccups.
            _crash_grace = int(_ci("crash", "crash_grace_seconds", "120"))
            if not state.online_since or (now - state.online_since) <= _crash_grace:
                return

            # Past grace: accumulate consecutive failures before acting
            state.rcon_fail_count += 1
            if state.rcon_fail_count < CRASH_DETECTION_THRESHOLD:
                return  # not enough failures yet — keep waiting

            # Threshold reached — crash detected
            log(f"CRASH DETECTED: {state.cfg.key} ({state.rcon_fail_count} consecutive RCON failures)")
            state.is_running = False
            state.is_starting = False
            state.process_pid = 0    # clear stale PID — process is gone
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

            # ── Auto-restart logic ────────────────────────────────────────
            _lr = lambda s, k, d: (_cfg.get(s, k) if _cfg.has_option(s, k) else d)
            _auto   = _lr("crash", "auto_restart_on_crash", "true").lower() == "true"
            _cool   = int(_lr("crash", "crash_cooldown_minutes", "5"))  * 60
            _maxr   = int(_lr("crash", "max_crash_restarts",     "3"))
            _window = int(_lr("crash", "crash_window_minutes",   "60")) * 60

            if not _auto:
                log(f"AUTO-RESTART DISABLED: {state.cfg.key} will stay offline")
                announce_all_online(f"{state.cfg.display_name} has crashed (auto-restart is disabled)")
                if _dc_flag("notify_crash_events"):
                    discord_notify(
                        f"**{state.cfg.display_name}** has crashed 🔴\nAuto-restart is disabled — manual action required.",
                        _DC_RED, "Server Crash")
                return

            # Reset crash window counter if the window has expired
            if state.crash_window_start and (now - state.crash_window_start) > _window:
                state.crash_restart_count = 0
                state.crash_window_start  = None

            # Start crash window on first crash
            if state.crash_window_start is None:
                state.crash_window_start = now

            # Check max restarts within the window
            if state.crash_restart_count >= _maxr:
                log(f"CRASH LIMIT REACHED: {state.cfg.key} has crashed "
                    f"{state.crash_restart_count}x in the last "
                    f"{int(_window // 60)} min — staying offline")
                state.crash_limit_reached = True
                announce_all_online(
                    f"{state.cfg.display_name} has crashed too many times and will stay offline")
                if _dc_flag("notify_crash_events"):
                    discord_notify(
                        f"**{state.cfg.display_name}** has crashed {state.crash_restart_count}x in "
                        f"{int(_window // 60)} minutes ⛔\nMax restart limit reached — staying offline. Manual intervention needed.",
                        _DC_RED, "Crash Limit Reached")
                return

            # Enforce cooldown between crash-restarts
            if state.last_crash_restart_at and (now - state.last_crash_restart_at) < _cool:
                remaining = int(_cool - (now - state.last_crash_restart_at))
                log(f"CRASH COOLDOWN: {state.cfg.key} — waiting {remaining}s before restart")
                announce_all_online(
                    f"{state.cfg.display_name} has crashed — restarting in {remaining // 60 + 1} min")
                if _dc_flag("notify_crash_events"):
                    discord_notify(
                        f"**{state.cfg.display_name}** has crashed 🔴\n"
                        f"Restarting in {remaining // 60 + 1} minute(s) (cooldown).",
                        _DC_ORANGE, "Server Crash")
                # Mark as crash-offline so the cooldown retry block can pick
                # it up later — but only if manually stopped will this clear.
                state.crash_offline = True
                return

            # All checks passed — restart
            state.crash_restart_count    += 1
            state.last_crash_restart_at   = now
            state.crash_offline           = True
            log(f"CRASH RESTART {state.crash_restart_count}/{_maxr}: {state.cfg.key}")
            announce_all_online(
                f"{state.cfg.display_name} has crashed and is being restarted "
                f"({state.crash_restart_count}/{_maxr})")
            if _dc_flag("notify_crash_events"):
                discord_notify(
                    f"**{state.cfg.display_name}** has crashed and is being restarted 🔄 "
                    f"({state.crash_restart_count}/{_maxr})",
                    _DC_ORANGE, "Server Crash — Auto Restart")
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
            # Keep all three manual-stop fields together — duration was previously
            # outside this block and zeroed even when is_starting=True, which caused
            # handle_manual_stop_timers() to fall back to MAP_SHUTDOWN_DELAY_SECONDS.
            state.manual_stop_duration_seconds = 0

            # ── Crash cooldown retry ──────────────────────────────────────
            # Only retry if the server went offline due to a crash.
            # crash_offline is cleared by stop_server_safe() so intentional
            # shutdowns never trigger an auto-restart here.
            # Also guard against cluster_stopped / shutdown_scheduled so that
            # a server which crashed mid-countdown never auto-restarts after
            # the cluster is intentionally brought down.
            if (state.crash_offline and state.last_crash_restart_at is not None
                    and not CLUSTER.cluster_stopped
                    and not CLUSTER.shutdown_scheduled):
                _lc2    = _read_live_cfg()
                _lr2    = lambda s, k, d: (_lc2.get(s, k) if _lc2.has_option(s, k) else d)
                _auto2  = _lr2("crash", "auto_restart_on_crash", "true").lower() == "true"
                _cool2  = int(_lr2("crash", "crash_cooldown_minutes", "5")) * 60
                _maxr2  = int(_lr2("crash", "max_crash_restarts",     "3"))
                _win2   = int(_lr2("crash", "crash_window_minutes",   "60")) * 60
                _exp    = (state.crash_window_start is not None and (now - state.crash_window_start) > _win2)
                _ok_cnt = _exp or (state.crash_restart_count < _maxr2)
                _ok_cd  = (now - state.last_crash_restart_at) >= _cool2
                if _auto2 and _ok_cnt and _ok_cd:
                    if _exp:
                        state.crash_restart_count = 0
                        state.crash_window_start  = None
                    log(f"CRASH COOLDOWN EXPIRED: retrying {state.cfg.key}")
                    state.crash_restart_count   += 1
                    state.last_crash_restart_at  = now
                    if state.crash_window_start is None:
                        state.crash_window_start = now
                    # Clear crash_offline BEFORE starting so the next poll cycle
                    # doesn't re-enter this block and attempt a duplicate start.
                    state.crash_offline = False
                    announce_all_online(
                        f"{state.cfg.display_name} is being restarted after crash cooldown "
                        f"({state.crash_restart_count}/{_maxr2})")
                    if _dc_flag("notify_crash_events"):
                        discord_notify(
                            f"**{state.cfg.display_name}** is being restarted after crash cooldown 🔄 "
                            f"({state.crash_restart_count}/{_maxr2})",
                            _DC_ORANGE, "Server Crash — Cooldown Retry")
                    start_server(state.cfg.key)


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
        state.seen_log_lines.append(ln)
        new_lines.append(ln)

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
        if not any(cmd in lower for cmd in ["!start", "!status", "!help", "!stop", "!restart"]):
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


class _MEMSTATEX(ctypes.Structure):
    _fields_ = [
        ("dwLength",                 ctypes.c_ulong),
        ("dwMemoryLoad",             ctypes.c_ulong),
        ("ullTotalPhys",             ctypes.c_ulonglong),
        ("ullAvailPhys",             ctypes.c_ulonglong),
        ("ullTotalPageFile",         ctypes.c_ulonglong),
        ("ullAvailPageFile",         ctypes.c_ulonglong),
        ("ullTotalVirtual",          ctypes.c_ulonglong),
        ("ullAvailVirtual",          ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _get_ram_gb() -> tuple:
    """Return (total_gb, available_gb) from the Windows memory API."""
    try:
        stat = _MEMSTATEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total     = round(stat.ullTotalPhys  / (1024 ** 3), 1)
        available = round(stat.ullAvailPhys  / (1024 ** 3), 1)
        return total, available
    except Exception:
        return None, None


def _get_effective_max_servers() -> int:
    """Auto-calculate concurrent map limit from total RAM (12 GB/map + 15 GB overhead).
    If the user sets max_active_servers > 0 in config it is used as an additional
    lower cap — they can never exceed what the RAM supports."""
    total, _ = _get_ram_gb()
    if total and total > 15:
        ram_limit = max(1, int((total - 15) / 12))
    else:
        ram_limit = len(SERVER_STATES)  # RAM unknown — don't block
    if _USER_MAX_ACTIVE_SERVERS > 0:
        return min(_USER_MAX_ACTIVE_SERVERS, ram_limit)
    return ram_limit


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
            "crash_restart_count": state.crash_restart_count,
            "crash_limit_reached": state.crash_limit_reached,
            "online_since": state.online_since,
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

    ram_total, ram_available = _get_ram_gb()
    running_map_count = sum(
        1 for s in SERVER_STATES.values() if s.is_running or s.is_starting
    )
    # 12 GB per running/starting map + 15 GB for OS and other services
    ram_required = running_map_count * 12 + 15

    payload = {
        "cluster_name": CLUSTER_NAME,
        "max_players": MAX_PLAYERS,
        "servers": servers_data,
        "total_players": total_players,
        "cluster_shutdown_scheduled": CLUSTER.shutdown_scheduled,
        "cluster_shutdown_in": cluster_shutdown_in,
        "cluster_restart_pending": CLUSTER.restart_pending,
        "next_scheduled_restart": next_scheduled_restart,
        "whitelist_active": whitelist_active,
        "steamcmd_found": steamcmd_found,
        "server_found": server_found,
        "ram_total_gb": ram_total,
        "ram_available_gb": ram_available,
        "ram_required_gb": ram_required,
        "max_concurrent_maps": _get_effective_max_servers(),
        "ram_max_maps": max(1, int((ram_total - 15) / 12)) if ram_total and ram_total > 15 else None,
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


# ── Seen-players tracking ──────────────────────────────────────────────────────
_seen_players: Dict[str, dict] = {}   # steam_id -> {name, last_map, last_seen}
_seen_players_last_save: float = 0.0


def _load_seen_players() -> None:
    global _seen_players
    if not os.path.exists(SEEN_PLAYERS_FILE):
        return
    try:
        with open(SEEN_PLAYERS_FILE, encoding="utf-8") as f:
            _seen_players = json.load(f)
    except Exception:
        _seen_players = {}


def _update_seen_players(state: ServerState) -> None:
    """Record each currently online player's name, map, and last-seen time."""
    now = time.time()
    for p in state.player_list:
        pid = p.get("id", "").strip()
        if not pid:
            continue
        _seen_players[pid] = {
            "name":      p.get("name", _seen_players.get(pid, {}).get("name", "Unknown")),
            "last_map":  state.cfg.key,
            "last_seen": now,
        }


def _save_seen_players() -> None:
    global _seen_players_last_save
    if not _seen_players:
        return
    now = time.time()
    if now - _seen_players_last_save < 60:   # write at most once per minute
        return
    try:
        tmp = SEEN_PLAYERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_seen_players, f, indent=2)
        os.replace(tmp, SEEN_PLAYERS_FILE)
        _seen_players_last_save = now
    except Exception as exc:
        log(f"Failed to save seen players: {exc}")


def main() -> int:
    global SHOULD_EXIT

    # Write Python PID so restart scripts can find and close the CMD window
    try:
        with open(CONTROLLER_PID_FILE, "w") as _pf:
            _pf.write(str(os.getpid()))
    except Exception:
        pass

    # Archive the previous log and prune old ones
    _rotate_log()

    # Clean up any leftover stop file from a previous run
    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    check_and_update_on_startup()

    _load_seen_players()
    log("Controller started")
    DISCORD_BOT.start()
    adopt_running_servers()
    restore_maps_after_restart()

    while True:
        try:
            # Restart signal written by dashboard — exit cleanly so the CMD
            # window closes on its own (cmd /c sees exit code 0 and closes)
            if os.path.exists(CONTROLLER_RESTART_FILE):
                try:
                    os.remove(CONTROLLER_RESTART_FILE)
                except OSError:
                    pass
                log("Restart requested — controller exiting cleanly")
                try:
                    os.remove(CONTROLLER_PID_FILE)
                except FileNotFoundError:
                    pass
                return 0

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
            _save_seen_players()
            print_summary()

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("Controller stopped by user")
            _write_stop_file()
            try:
                os.remove(CONTROLLER_PID_FILE)
            except FileNotFoundError:
                pass
            return 0
        except Exception as exc:
            log(f"ERROR: {exc}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())