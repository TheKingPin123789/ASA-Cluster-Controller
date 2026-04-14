# ASA Cluster Controller

A self-contained Windows controller for running and managing an **ARK: Survival Ascended** dedicated server cluster. It handles server startup, shutdown, updates, backups, scheduling, in-game chat commands, and exposes a web dashboard for remote management.

---

## Features

- **Multi-map cluster** — start, stop, and restart individual maps or the whole cluster
- **Auto-install** — downloads SteamCMD and the ASA dedicated server on first run
- **Auto-update** — checks for game updates via SteamCMD on startup (configurable)
- **Crash detection & restore** — automatically restarts a crashed server
- **Scheduled daily restart** — configurable restart time (default 06:00), warns players in-game before shutdown
- **Autosave** — periodically saves all running maps via RCON
- **Backup** — one-command or scheduled backup of all save data, with a configurable keep-N policy
- **Whitelist** — optional `!start` whitelist; per-command tiers (Default / Whitelist-only / Admin-only)
- **In-game chat commands** — players type `!help`, `!status`, `!start <map>`, `!stop`, `!restart` in global chat
- **Web dashboard** — live server status, player list, admin console, controller log, settings editor
- **Player tracking** — remembers every player who has connected (name, Steam ID, last map, last seen)

---

## Requirements

- Windows 10 / 11
- [Python 3.10+](https://www.python.org/downloads/) (must be on PATH)
- Internet connection (first run downloads SteamCMD and the game server)

Python packages (installed automatically by `start_controller.bat`):

```
flask
```

---

## Quick Start

1. Clone or download this repository into a folder, e.g. `C:\ASA_Cluster`
2. Double-click **`start_controller.bat`**
3. On first run the setup wizard walks you through `config.ini` — fill in your cluster name, RCON password, paths, and rates
4. SteamCMD and the ASA dedicated server are downloaded automatically
5. The controller window and the web dashboard both open; your browser navigates to `http://localhost:5000`

---

## File Structure

```
ASA_Cluster/
├── start_controller.bat          # Entry point — run this
├── requirements.txt
├── controller/
│   ├── asa_cluster_controller.py # Main controller loop
│   ├── dashboard.py              # Flask web dashboard (port 5000)
│   ├── setup_wizard.py           # First-run config wizard
│   ├── admin_console.py          # Optional standalone admin console
│   └── mcrcon.exe                # RCON client binary
└── scripts/
    └── start_<map>.bat           # Per-map server launch scripts
```

Files created at runtime (not committed to git):

| File | Purpose |
|---|---|
| `controller/config.ini` | Your cluster configuration |
| `controller/whitelist.txt` | Whitelisted Steam IDs |
| `controller/admin_list.txt` | Admin Steam IDs |
| `controller/seen_players.json` | All-time player history |
| `controller/command_categories.json` | In-game command tiers |
| `controller/controller.log` | Controller log |
| `controller/admin_log.txt` | Admin command log |
| `SteamCMD/` | SteamCMD installation |
| `asa_server/` | ASA dedicated server files |
| `backups/` | Save backups |

---

## Configuration

The setup wizard creates `controller/config.ini` on first run. You can also edit it from the dashboard (⚙ → Settings). Key sections:

| Section | Key settings |
|---|---|
| `[cluster]` | `cluster_name`, `rcon_password`, `default_map` |
| `[paths]` | `server_root`, `cluster_dir`, `steamcmd_path` |
| `[performance]` | `max_active_servers`, `max_players` |
| `[schedule]` | `restart_time` (HH:MM), `check_updates_on_startup` |
| `[timers]` | Shutdown warnings, autosave interval, startup grace period |
| `[rates]` | XP, taming, harvest, difficulty multipliers |
| `[breeding]` | Maturation, cuddle, imprint multipliers |

Changes to `config.ini` require a controller restart to take effect.

---

## Web Dashboard

Open `http://localhost:5000` in your browser.

### Server cards
Each configured map shows its status (Online / Starting / Offline), player count, and Start / Stop / Restart buttons.

### Controls tab
- Start / stop / restart the whole cluster or individual maps
- Save all maps, trigger an immediate backup
- View online players — click any player to see their Steam ID, current map, last-seen time, and whitelist status

### Commands tab
- Toggle the `!start` whitelist on/off
- Assign in-game commands to Default / Whitelist / Admin tiers
- Add or remove players from the whitelist and admin list

### Admin Console
Send commands to the controller (same commands available in-game with `!`) and view the response log with colour-coded output.

### Controller Log
Tail of `controller.log` with auto-scroll.

### Settings (⚙)
Edit all `config.ini` values from the browser, grouped into tabs: Cluster, Paths, Performance, Schedule & Backup, Timers, Game Rates, Breeding.

---

## In-Game Commands

Players type these in **global chat**:

| Command | Default | Whitelist | Admin |
|---|---|---|---|
| `!help` | ✔ | ✔ | ✔ |
| `!status` | ✔ | ✔ | ✔ |
| `!start <map>` | — | ✔ | ✔ |
| `!stop` | — | — | ✔ |
| `!restart` | — | — | ✔ |

Available maps: `ragnarok`, `thecenter`, `valguero`, `theisland`, `scorchedearth`, `aberration`, `extinction`, `lostcolony`, `astraeos`

Command tiers are configurable from the dashboard.

---

## Clean Reset

To wipe all runtime data and start fresh, delete:

```
controller/config.ini
controller/whitelist.txt
controller/admin_list.txt
controller/seen_players.json
controller/command_categories.json
controller/controller.log
controller/admin_log.txt
controller/cluster_status.*
controller/admin_commands.txt
controller/restart_maps.txt
SteamCMD/
asa_server/
backups/
```

Then run `start_controller.bat` — the setup wizard will run again and SteamCMD / the server will be re-downloaded.

---

## License

MIT
