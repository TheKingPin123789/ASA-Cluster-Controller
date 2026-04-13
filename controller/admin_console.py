import os
import re
import time
import threading
import configparser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ADMIN_COMMAND_FILE = BASE_DIR / "admin_commands.txt"
CONTROLLER_FILE = BASE_DIR / "asa_cluster_controller.py"
STATUS_FILE = BASE_DIR / "cluster_status.txt"
CONFIG_FILE = BASE_DIR / "config.ini"
STOP_FILE = BASE_DIR / "controller.stop"

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

MAP_SHORT_NAMES = {
    "ragnarok":     ["rag"],
    "thecenter":    ["tc", "center"],
    "valguero":     ["val"],
    "theisland":    ["ti", "island"],
    "scorchedearth": ["se", "scorched"],
    "aberration":   ["ab"],
    "extinction":   ["ext"],
    "lostcolony":   ["lost"],
    "astraeos":     [],
}


def get_cluster_shutdown_minutes() -> int:
    # Prefer reading from config.ini (set by setup wizard)
    try:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE, encoding="utf-8")
        return int(cfg.get("timers", "cluster_shutdown_minutes"))
    except Exception:
        pass

    # Fallback: parse the constant out of the controller source
    try:
        src = CONTROLLER_FILE.read_text(encoding="utf-8")
        m = re.search(r"CLUSTER_SHUTDOWN_DELAY_SECONDS\s*=\s*(\d+)\s*\*\s*60", src)
        if m:
            return int(m.group(1))
        m = re.search(r"CLUSTER_SHUTDOWN_DELAY_SECONDS\s*=\s*(\d+)", src)
        if m:
            return max(1, int(m.group(1)) // 60)
    except Exception:
        pass

    return 30


def print_help() -> None:
    minutes = get_cluster_shutdown_minutes()

    print("Admin commands:")
    print("  start <map>")
    print("  stop <map>")
    print("  cancel <map>")
    print("  restart <map>           (per-map restart)")
    print("  shutdown cluster")
    print("  shutdown cluster now")
    print("  shutdown cluster <time>")
    print("  restart")
    print("  restart now")
    print("  restart <time>")
    print("  cancel shutdown")
    print("  save all")
    print("  backup now")
    print("  whitelist on / whitelist off")
    print("  whitelist add <id>")
    print("  whitelist remove <id>")
    print("  setup                   (re-run the setup wizard)")
    print("  help")
    print("  exit")
    print()
    print(f"Default scheduled shutdown/restart delay: {minutes} minutes")
    print()
    print("Maps:")
    for m in MAPS:
        shorts = MAP_SHORT_NAMES.get(m, [])
        if shorts:
            print(f"  {m} ({', '.join(shorts)})")
        else:
            print(f"  {m}")


def write_command(cmd: str) -> None:
    with ADMIN_COMMAND_FILE.open("a", encoding="utf-8") as f:
        f.write(cmd + "\n")


def cluster_has_players() -> bool:
    if not STATUS_FILE.exists():
        return False

    try:
        text = STATUS_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return False

    for line in text.splitlines():
        if line.startswith("PLAYERS_ONLINE="):
            try:
                return int(line.split("=", 1)[1].strip()) > 0
            except ValueError:
                return False

    return False


def confirm(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def _watch_for_stop() -> None:
    """Background thread — closes the admin console when the controller stops.
    Ignores any stop file that existed before this session started."""
    started_at = time.time()
    while True:
        time.sleep(1)
        try:
            if STOP_FILE.exists() and STOP_FILE.stat().st_mtime > started_at:
                print("\n[Controller has stopped. Closing admin console...]")
                os._exit(0)
        except Exception:
            pass


def main() -> None:
    ADMIN_COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_COMMAND_FILE.touch(exist_ok=True)

    threading.Thread(target=_watch_for_stop, daemon=True).start()

    print("Type help for more commands")

    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            continue

        lowered = cmd.lower()

        if lowered == "help":
            print_help()
            continue

        if lowered == "exit":
            break

        if lowered == "setup":
            try:
                from setup_wizard import run_wizard, load_config
                existing = load_config()
                run_wizard(existing)
                print("Setup complete. Restart the controller to apply changes.")
            except Exception as exc:
                print(f"Setup wizard error: {exc}")
            continue

        if lowered == "shutdown cluster":
            if cluster_has_players():
                minutes = get_cluster_shutdown_minutes()
                if confirm("Shutdown instantly? (y/n): "):
                    write_command("shutdown cluster now")
                else:
                    print(f"Scheduling shutdown in {minutes} minutes.")
                    write_command("shutdown cluster")
            else:
                write_command("shutdown cluster now")
            continue

        if lowered == "restart":
            if cluster_has_players():
                minutes = get_cluster_shutdown_minutes()
                if confirm("Restart instantly? (y/n): "):
                    write_command("restart now")
                else:
                    print(f"Scheduling restart in {minutes} minutes.")
                    write_command("restart")
            else:
                write_command("restart now")
            continue

        write_command(cmd)


if __name__ == "__main__":
    main()