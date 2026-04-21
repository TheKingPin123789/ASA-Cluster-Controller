import os
import sys
import json
import shutil
import signal
import hashlib
import logging
import secrets
import subprocess
import configparser
from functools import wraps
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR        = os.path.dirname(BASE_DIR)          # one level up from controller/
LOGS_DIR        = os.path.join(BASE_DIR, "logs")
STATUS_JSON     = os.path.join(BASE_DIR, "cluster_status.json")
LOG_FILE        = os.path.join(LOGS_DIR, "controller.log")
ADMIN_LOG_FILE  = os.path.join(LOGS_DIR, "admin_log.txt")
ADMIN_CMD       = os.path.join(BASE_DIR, "admin_commands.txt")
CONFIG_FILE     = os.path.join(BASE_DIR, "config.ini")
WHITELIST_FILE      = os.path.join(BASE_DIR, "whitelist.txt")
SEEN_PLAYERS_FILE     = os.path.join(BASE_DIR, "seen_players.json")
COMMAND_CATEGORIES_FILE = os.path.join(BASE_DIR, "command_categories.json")
ADMIN_LIST_FILE         = os.path.join(BASE_DIR, "admin_list.txt")
CONTROLLER_PID_FILE        = os.path.join(BASE_DIR, "controller.pid")
DASHBOARD_PID_FILE         = os.path.join(BASE_DIR, "dashboard.pid")
CONTROLLER_RESTART_FILE    = os.path.join(BASE_DIR, "controller.restart")

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_auth_cfg():
    """Read auth settings fresh from config.ini each call."""
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    return cfg


def _ensure_secret_key() -> str:
    """Return the session secret key, auto-generating and saving it if missing."""
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    if cfg.has_option("auth", "secret_key"):
        key = cfg.get("auth", "secret_key").strip()
        if key:
            return key
    # Generate a new key and persist it
    key = secrets.token_hex(32)
    if not cfg.has_section("auth"):
        cfg.add_section("auth")
    cfg.set("auth", "secret_key", key)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception:
        pass
    return key


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _check_credentials(username: str, password: str) -> bool:
    cfg = _get_auth_cfg()
    stored_user = cfg.get("auth", "username", fallback="admin").strip()
    stored_hash = cfg.get("auth", "password_hash", fallback="").strip()
    if not stored_hash:
        # No hash stored — refuse login rather than silently accepting a default.
        # This protects against config corruption resetting access to 'admin'.
        # Run reset_password.bat (or restart the dashboard fresh) to restore defaults.
        return False
    return username == stored_user and _hash_password(password) == stored_hash


def _auth_enabled() -> bool:
    """Auth is enabled only when a password hash is present in config.
    If the wizard was run without setting credentials, the dashboard opens freely."""
    cfg = _get_auth_cfg()
    return bool(cfg.get("auth", "password_hash", fallback="").strip())


def _safe_next(url: str) -> str:
    """Return url only if it is a local path — prevents open-redirect attacks."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc or url.startswith("//") or url.startswith("\\"):
        return "/"
    return url or "/"


def login_required(f):
    """Decorator — bypassed entirely when no password is configured.
    When auth is enabled: redirects to /login for page routes, returns 401 for API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if _auth_enabled() and not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            # Use no-store so browsers never cache the login redirect
            resp = redirect(url_for("login_page", next=request.path))
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return f(*args, **kwargs)
    return decorated

def _get_web_port() -> int:
    """Read web_status_port from config.ini, defaulting to 5000."""
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
        return int(cfg.get("network", "web_status_port"))
    except Exception:
        return 5000

# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cluster Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f0f1a; color: #dde1e7; font-family: 'Segoe UI', sans-serif; font-size: 16px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* Header */
#header { background: #1a1f36; padding: 8px 14px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2a3050; flex-shrink: 0; }
#header .title { font-weight: 700; font-size: 18px; color: #93c5fd; }
#status-line { font-size: 14px; color: #6b7280; }

/* Server cards */
#cards { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #2a3050; flex-shrink: 0; }
.card { background: #1a1f36; border: 1px solid #2a3050; border-radius: 6px; padding: 9px 11px; min-width: 130px; flex: 0 1 150px; max-width: 155px; transition: border-color .2s, opacity .4s; }
.card.online   { border-color: #16a34a; }
.card.starting { border-color: #d97706; }
/* When controller is offline all cards dim and buttons are disabled */
#cards.stale .card { opacity: 0.45; pointer-events: none; }
#cards.stale .card.online  { border-color: #2a3050; }
#cards.stale .card.starting { border-color: #2a3050; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.card-name { font-weight: 600; font-size: 14px; }
.badge { padding: 2px 6px; border-radius: 3px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
.badge.online   { background: #14532d; color: #4ade80; }
.badge.starting { background: #78350f; color: #fbbf24; }
.badge.offline  { background: #1f2937; color: #6b7280; }
.card-players { font-size: 13px; color: #6b7280; margin-bottom: 6px; min-height: 14px; }
.card-btns { display: flex; gap: 4px; flex-wrap: wrap; }

/* Main layout */
#main { display: flex; flex: 1; overflow: hidden; gap: 8px; padding: 8px 12px; }
#left  { width: clamp(280px, 28%, 360px); min-width: 280px; display: flex; flex-direction: column; overflow: hidden; }
#right { flex: 1; display: flex; flex-direction: column; overflow: hidden; gap: 8px; }

/* Tabs */
.tab-bar { display: flex; gap: 2px; flex-shrink: 0; }
.tab-btn { padding: 6px 10px; flex: 1; text-align: center; background: #1a1f36; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 14px; color: #9ca3af; }
.tab-btn.active { background: #222840; color: #fff; border-color: #3b4a7a; }
.tab-panel { display: none; flex: 1; background: #222840; border: 1px solid #3b4a7a; border-radius: 0 4px 4px 4px; padding: 10px; overflow-y: auto; flex-direction: column; gap: 8px; }
.tab-panel.active { display: flex; }

/* Buttons */
.btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 600; transition: opacity .15s; }
.btn:disabled { opacity: .35; cursor: not-allowed; }
.btn:not(:disabled):hover { opacity: .85; }
.btn-green  { background: #166534; color: #4ade80; }
.btn-red    { background: #7f1d1d; color: #fca5a5; }
.btn-orange { background: #78350f; color: #fdba74; }
.btn-blue   { background: #1e3a5f; color: #93c5fd; }
.btn-gray   { background: #374151; color: #9ca3af; }
.btn-bright-green  { background: #16a34a; color: #ffffff; }
.btn-bright-red    { background: #dc2626; color: #ffffff; }
.btn-bright-orange { background: #ea580c; color: #ffffff; }
/* Disabled bright buttons switch to gray so colour alone signals availability */
.btn-bright-green:disabled  { background: #374151; color: #6b7280; opacity: 1; }
.btn-bright-red:disabled    { background: #374151; color: #6b7280; opacity: 1; }
.btn-bright-orange:disabled { background: #374151; color: #6b7280; opacity: 1; }
.btn-full { width: 100%; }
.btn-sm { padding: 4px 8px; font-size: 13px; }

/* Section dividers */
.sec { border-top: 1px solid #3b4a7a; padding-top: 8px; }
.sec-title { font-size: 12px; color: #4b5563; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.row   { display: flex; gap: 5px; align-items: flex-end; }

/* Form controls */
input[type=text], select, textarea {
  background: #131825; border: 1px solid #2a3050; color: #dde1e7;
  padding: 6px 10px; border-radius: 4px; font-size: 14px; width: 100%;
  font-family: inherit;
}
select { cursor: pointer; }
label { font-size: 13px; color: #6b7280; display: block; margin-bottom: 3px; }

/* Player list */
#player-list { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; max-height: 200px; overflow-y: auto; }
.pl-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 5px; }
.pl-info  { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.pl-name  { font-size: 14px; color: #dde1e7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-id    { font-family: Consolas, monospace; font-size: 12px; color: #4b5563; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-map   { font-size: 12px; color: #6b7280; white-space: nowrap; flex-shrink: 0; }
.pl-empty { font-size: 13px; color: #4b5563; font-style: italic; padding: 4px 2px; }

/* Whitelist panel */
#wl-panel { display: flex; flex-direction: column; gap: 3px; max-height: 200px; overflow-y: auto; }
.wl-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 6px; }
.wl-info  { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.wl-name  { font-size: 13px; color: #dde1e7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wl-id    { font-family: Consolas, monospace; font-size: 12px; color: #a3e635; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wl-empty { font-size: 13px; color: #4b5563; font-style: italic; padding: 4px 2px; }

/* Right panel: tabbed console / log */
#right-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #222840; border: 1px solid #3b4a7a; border-radius: 0 4px 4px 4px; }
#console-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 8px; }
#console-out  { flex: 1; background: #0a0a12; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; padding: 6px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 14px; color: #93c5fd; white-space: pre-wrap; word-break: break-all; }
#console-input-bar { display: flex; gap: 5px; background: #131825; border: 1px solid #2a3050; border-radius: 0 0 4px 4px; padding: 5px 7px; flex-shrink: 0; }
#console-input-bar input { flex: 1; background: transparent; border: none; outline: none; color: #dde1e7; font-size: 14px; font-family: Consolas, monospace; }
#console-input-bar input::placeholder { color: #4b5563; }
.quick-cmds { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; flex-shrink: 0; }
#log-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 8px; }
#log { flex: 1; background: #0a0a12; border: 1px solid #2a3050; border-radius: 4px; padding: 8px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 14px; color: #a3e635; white-space: pre-wrap; word-break: break-all; }
.log-header { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 4px; flex-shrink: 0; }

/* All players panel */
#ap-panel { display: none; margin-top: 6px; flex-direction: column; gap: 3px; max-height: 250px; overflow-y: auto; }
#ap-panel.open { display: flex; }
.ap-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 6px; cursor: pointer; }
.ap-entry:hover { border-color: #3b4a7a; }
.ap-dot  { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.ap-dot.online  { background: #4ade80; }
.ap-dot.offline { background: #374151; }
.ap-name { font-size: 14px; color: #dde1e7; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ap-map  { font-size: 12px; color: #6b7280; white-space: nowrap; flex-shrink: 0; }

/* Player modal */
#player-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:1000; align-items:center; justify-content:center; }
#player-modal.open { display:flex; }
#player-modal-box { background:#1a1f36; border:1px solid #3b4a7a; border-radius:8px; padding:20px 22px; min-width:340px; max-width:420px; width:90%; display:flex; flex-direction:column; gap:12px; }
.pm-title { font-size:17px; font-weight:700; color:#93c5fd; }
.pm-row { display:flex; flex-direction:column; gap:2px; }
.pm-label { font-size:12px; color:#4b5563; text-transform:uppercase; letter-spacing:.06em; }
.pm-value { font-size:15px; color:#dde1e7; word-break:break-all; }
.pm-value.mono { font-family:Consolas,monospace; font-size:14px; color:#a3e635; }
.pm-actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
.pm-close { align-self:flex-end; cursor:pointer; font-size:20px; color:#4b5563; line-height:1; margin-top:-8px; }

/* Force-shutdown confirm modal */
#confirm-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.75); z-index:2000; align-items:center; justify-content:center; }
#confirm-modal.open { display:flex; }
#confirm-modal-box { background:#1a1f36; border:2px solid #7f1d1d; border-radius:8px; padding:24px 26px; max-width:460px; width:90%; display:flex; flex-direction:column; gap:14px; }
.cm-title { font-size:18px; font-weight:700; color:#f87171; display:flex; align-items:center; gap:8px; }
.cm-body { font-size:14px; color:#dde1e7; line-height:1.65; }
.cm-body ul { margin:8px 0 0 18px; color:#fca5a5; }
.cm-actions { display:flex; gap:10px; justify-content:flex-end; margin-top:4px; }

/* Controller auto-restart banner */
#controller-alert-banner.restarting { background:#1c2340; border:1px solid #3b4a7a; color:#93c5fd; }
#controller-alert-banner.failed     { background:#2d0f0f; border:1px solid #7f1d1d; color:#fca5a5; }

/* Card action confirm modal */
#card-confirm-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.75); z-index:2000; align-items:center; justify-content:center; }
#card-confirm-modal.open { display:flex; }
#card-confirm-box { background:#1a1f36; border:2px solid #374151; border-radius:8px; padding:22px 24px; max-width:380px; width:90%; display:flex; flex-direction:column; gap:14px; }
#card-confirm-box.danger { border-color: #7f1d1d; }
.ccm-title { font-size:16px; font-weight:700; color:#e2e8f0; }
.ccm-body  { font-size:14px; color:#9ca3af; line-height:1.55; }
.ccm-actions { display:flex; gap:8px; justify-content:flex-end; }

/* Uptime badge on cards */
.card-uptime { font-size:11px; color:#4b5563; margin-top:1px; min-height:13px; }

/* RAM warning banner */
#ram-warning-banner { display:none; margin:4px 12px 0; padding:9px 14px; background:#2d1a00; border:1px solid #92400e; border-radius:6px; color:#fbbf24; font-size:13px; line-height:1.5; }

/* Toast notifications */
#toast-container { position:fixed; bottom:16px; right:16px; display:flex; flex-direction:column-reverse; gap:6px; z-index:3000; pointer-events:none; }
.toast { background:#1a1f36; border:1px solid #3b4a7a; border-radius:6px; padding:8px 14px; font-size:13px; color:#dde1e7; max-width:280px; animation:toastIn .15s ease; }
.toast.join  { border-color:#16a34a; color:#4ade80; }
.toast.leave { border-color:#4b5563; color:#9ca3af; }
@keyframes toastIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }

/* Settings window */
.settings-section { margin-top: 10px; }
.settings-section .sec-title { margin-bottom: 6px; padding-bottom:3px; border-bottom:1px solid #2a3050; }
.settings-row { margin-bottom: 5px; }
.settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:5px; }

/* Responsive layout */
@media (max-width: 720px) {
  .btn { padding: 10px 12px; }
  .btn-sm { padding: 8px 10px; }
  /* Prevent any element from causing a horizontal scrollbar */
  html { overflow-x: hidden; }
  body { font-size: 15px; overflow-x: hidden; overflow-y: auto; height: auto; max-width: 100vw; }
  #header, #cards, #main, #left, #right, #right-tab-content,
  #console-wrap, #log-wrap, .tab-panel { max-width: 100%; box-sizing: border-box; }
  #main { flex-direction: column; overflow: visible; gap: 6px; padding: 6px 8px; }
  #left  { width: 100% !important; min-width: 0 !important; max-height: none; }
  #right { min-height: 0; }
  /* Cap the output areas so tabs + input bar stay visible without huge scrolling */
  #console-out { flex: none; height: 38vh; max-height: 380px; }
  #log         { flex: none; height: 38vh; max-height: 380px; }
  #cards { gap: 6px; padding: 8px; }
  #cards .card { flex: 1 1 140px; max-width: none; }
  .settings-grid { grid-template-columns: 1fr; }
  /* Remove fixed min-width so modals don't bleed off narrow screens */
  #player-modal-box { min-width: 0; width: 96%; padding: 16px; }
  #card-confirm-box, #confirm-modal-box { width: 96%; padding: 16px; }
}
@media (max-width: 480px) {
  #header { flex-wrap: wrap; gap: 6px; }
  #header .title { font-size: 16px; }
  .btn-sm { font-size: 12px; padding: 8px 10px; }
  .card-name { font-size: 13px; }
  #cards .card { flex: 1 1 100%; max-width: none; }
}
</style>
</head>
<body>

<div id="header">
  <span class="title" id="page-title">Cluster Dashboard</span>
  <div style="display:flex; align-items:center; gap:12px;">
    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px;">
      <span id="status-line">Connecting...</span>
      <span id="restart-timer" style="font-size:14px; font-family:Consolas,monospace;"></span>
    </div>
    <button onclick="openSettings()" title="Settings"
            style="background:none; border:none; cursor:pointer; font-size:20px; color:#6b7280; line-height:1; padding:2px 4px; border-radius:4px;"
            onmouseover="this.style.color='#93c5fd'" onmouseout="this.style.color='#6b7280'">⚙</button>
    <a href="/logout" title="Sign out"
       style="background:none; border:none; cursor:pointer; font-size:18px; color:#6b7280; line-height:1; padding:2px 4px; border-radius:4px; text-decoration:none;"
       onmouseover="this.style.color='#f87171'" onmouseout="this.style.color='#6b7280'">⏻</a>
  </div>
</div>

<div id="cards"><!-- injected by JS --></div>

<div id="ram-warning-banner"></div>

<div id="cluster-offline-banner" style="display:none; margin:10px 12px 0; padding:12px 16px; background:#131825; border:1px solid #2a3050; border-radius:6px; color:#9ca3af; font-size:13px; line-height:1.6;">
  <span style="font-size:15px; font-weight:600; color:#e2e8f0;">Cluster is offline</span><br>
  Press <strong style="color:#16a34a;">Start Cluster</strong> to bring all maps online, or use the <strong style="color:#16a34a;">Start</strong> button on any map card above to start a single map.
</div>

<div id="controller-alert-banner" style="display:none; margin:6px 12px 0; padding:11px 16px; border-radius:6px; font-size:13px; line-height:1.6;"></div>

<div id="main">
  <!-- LEFT: controls / whitelist / settings tabs -->
  <div id="left">
    <div class="tab-bar">
      <div class="tab-btn active"  onclick="switchTab('controls')">Controls</div>
      <div class="tab-btn"         onclick="switchTab('whitelist')">Commands</div>
    </div>

    <!-- Controls tab -->
    <div id="tab-controls" class="tab-panel active">
      <button id="btn-start-cluster" class="btn btn-bright-green btn-full" onclick="cmd('start cluster')">Start Cluster</button>

      <div class="sec">
        <div class="sec-title">Cluster Actions</div>
        <div class="grid2">
          <button class="btn btn-orange btn-full" onclick="cmd('restart')">Restart (sched.)</button>
          <button class="btn btn-red btn-full"    onclick="cmd('restart now')">Restart Now</button>
          <button class="btn btn-orange btn-full" onclick="cmd('shutdown cluster')">Shutdown (sched.)</button>
          <button class="btn btn-red btn-full"    onclick="cmd('shutdown cluster now')">Shutdown Now</button>
        </div>
      </div>

      <div class="sec">
        <div class="sec-title">Maintenance</div>
        <div class="grid2">
          <button class="btn btn-blue btn-full" onclick="cmd('save all')">Save All</button>
          <button class="btn btn-blue btn-full" onclick="cmd('backup now')">Backup Now</button>
          <button class="btn btn-full" onclick="restartProcess('controller')"
                  style="background:#1e2a1e; border:1px solid #2d6a2d; color:#4ade80;"
                  onmouseover="this.style.background='#2d6a2d'" onmouseout="this.style.background='#1e2a1e'">↺ Restart Controller</button>
          <button class="btn btn-full" onclick="restartProcess('dashboard')"
                  style="background:#1e2038; border:1px solid #2d4a8a; color:#93c5fd;"
                  onmouseover="this.style.background='#2d4a8a'" onmouseout="this.style.background='#1e2038'">↺ Restart Dashboard</button>
        </div>
      </div>

      <div class="sec">
        <div class="sec-title" style="margin-bottom:6px;">Online Players</div>
        <div id="player-list"><span class="pl-empty">No players online</span></div>
      </div>

      <div class="sec">
        <div style="display:flex; align-items:center; justify-content:space-between; cursor:pointer;" onclick="toggleApPanel()">
          <div class="sec-title" style="margin-bottom:0;">All Players</div>
          <span id="ap-chevron" style="font-size:12px; color:#4b5563;">▶ show</span>
        </div>
        <div id="ap-panel"></div>
      </div>
    </div>

    <!-- Whitelist tab -->
    <div id="tab-whitelist" class="tab-panel">
      <!-- !start whitelist toggle -->
      <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 0 8px;">
        <span style="font-size:14px; color:#9ca3af;">Require whitelist for !start</span>
        <button id="btn-wl" class="btn btn-gray btn-sm" onclick="toggleWhitelist()">...</button>
      </div>

      <!-- In-game commands -->
      <div class="sec">
        <div class="sec-title">In-Game Commands</div>

        <div class="sec-title" style="color:#4ade80; margin-top:4px;">Default — everyone</div>
        <div id="cmd-default" style="display:flex; flex-direction:column; gap:3px; margin-bottom:4px;"></div>
        <div style="display:flex; gap:5px; margin-bottom:8px;">
          <select id="cmd-add-default" style="flex:1;"><option value="">Add...</option></select>
          <button class="btn btn-green btn-sm" onclick="addCmd('default')">Add</button>
        </div>

        <div class="sec-title" style="color:#fbbf24; margin-top:4px;">Whitelist only</div>
        <div id="cmd-whitelist" style="display:flex; flex-direction:column; gap:3px; margin-bottom:4px;"></div>
        <div style="display:flex; gap:5px; margin-bottom:8px;">
          <select id="cmd-add-whitelist" style="flex:1;"><option value="">Add...</option></select>
          <button class="btn btn-green btn-sm" onclick="addCmd('whitelist')">Add</button>
        </div>

        <div class="sec-title" style="color:#f87171; margin-top:4px;">Admin only</div>
        <div id="cmd-admin" style="display:flex; flex-direction:column; gap:3px; margin-bottom:4px;"></div>
        <div style="display:flex; gap:5px;">
          <select id="cmd-add-admin" style="flex:1;"><option value="">Add...</option></select>
          <button class="btn btn-green btn-sm" onclick="addCmd('admin')">Add</button>
        </div>
      </div>

      <!-- Whitelisted players -->
      <div class="sec">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
          <div class="sec-title" style="margin-bottom:0;">Whitelisted Players</div>
          <button class="btn btn-blue btn-sm" onclick="whitelistAllOnline()" title="Add all currently online players to whitelist">+ All Online</button>
        </div>
        <div style="display:flex; gap:5px; margin-bottom:6px;">
          <input type="text" id="wl-add-input" placeholder="Steam ID to add..." style="flex:1;">
          <button class="btn btn-green btn-sm" onclick="addWlPlayer()">Add</button>
        </div>
        <div id="wl-panel"></div>
      </div>

      <!-- Admin players -->
      <div class="sec">
        <div class="sec-title">Admin Players</div>
        <div style="display:flex; gap:5px; margin-bottom:6px;">
          <input type="text" id="admin-add-input" placeholder="Steam ID to add..." style="flex:1;">
          <button class="btn btn-green btn-sm" onclick="addAdminPlayer()">Add</button>
        </div>
        <div id="admin-panel" style="display:flex; flex-direction:column; gap:3px; max-height:180px; overflow-y:auto;"></div>
      </div>
    </div>

  </div>

  <!-- RIGHT: tabbed console / log -->
  <div id="right">
    <div class="tab-bar">
      <div class="tab-btn active" onclick="switchRightTab('console')">Admin Console</div>
      <div class="tab-btn"        onclick="switchRightTab('log')">Controller Log</div>
    </div>
    <div id="right-tab-content">

      <!-- Admin console panel -->
      <div id="right-console" style="flex:1; display:flex; flex-direction:column; overflow:hidden;">
        <div id="console-wrap">
          <div id="console-out"></div>
          <div id="console-input-bar">
            <span style="color:#4b5563; font-size:14px; font-family:Consolas;">$</span>
            <input id="cmd-input" type="text" placeholder="e.g. start ragnarok"
                   onkeydown="if(event.key==='Enter')sendConsole()">
            <button class="btn btn-blue btn-sm" onclick="sendConsole()">Send</button>
          </div>
          <div class="quick-cmds">
            <button class="btn btn-gray btn-sm" onclick="runCmd('help')">help</button>
          </div>
        </div>
      </div>

      <!-- Log panel -->
      <div id="right-log" style="flex:1; display:none; flex-direction:column; overflow:hidden;">
        <div id="log-wrap">
          <div class="log-header">
            <label style="display:flex; align-items:center; gap:4px; cursor:pointer; font-size:13px; color:#4b5563;">
              <input type="checkbox" id="auto-scroll" checked onchange="autoScroll=this.checked">
              Auto-scroll
            </label>
          </div>
          <div id="log"></div>

        </div>
      </div>

    </div>
  </div>
</div>

<div id="toast-container"></div>

<!-- Card action (Stop / Restart) confirmation modal -->
<div id="card-confirm-modal" onclick="if(event.target===this)closeCcm()">
  <div id="card-confirm-box">
    <div class="ccm-title" id="ccm-title">Confirm</div>
    <div class="ccm-body"  id="ccm-body"></div>
    <div class="ccm-actions">
      <button class="btn btn-gray" onclick="closeCcm()">Cancel</button>
      <button class="btn" id="ccm-confirm-btn" onclick="confirmCcm()">Confirm</button>
    </div>
  </div>
</div>

<!-- Force-shutdown confirmation modal -->
<div id="confirm-modal" onclick="if(event.target===this)cancelForceShutdown()">
  <div id="confirm-modal-box">
    <div class="cm-title">&#9888; Force Shutdown Cluster</div>
    <div class="cm-body">
      This will <strong>immediately kill all server processes</strong> with no grace period.
      <ul>
        <li>No world save &mdash; unsaved progress will be <strong>lost</strong></li>
        <li>No DoExit &mdash; processes terminated with taskkill&nbsp;/F</li>
        <li>Servers still starting up are killed instantly</li>
        <li>All players disconnected without any in-game warning</li>
      </ul>
    </div>
    <div class="cm-actions">
      <button class="btn btn-gray" onclick="cancelForceShutdown()">Cancel</button>
      <button class="btn" style="background:#7f1d1d;color:#fca5a5;border:1px solid #991b1b"
              onclick="confirmForceShutdown()">Force Shutdown</button>
    </div>
  </div>
</div>

<!-- Player detail modal -->
<div id="player-modal" onclick="if(event.target===this)closePlayerModal()">
  <div id="player-modal-box">
    <span class="pm-close" onclick="closePlayerModal()">✕</span>
    <div style="display:flex; align-items:center; gap:8px;">
      <span id="pm-status-dot" class="ap-dot"></span>
      <div class="pm-title" id="pm-name"></div>
    </div>
    <div class="pm-row"><div class="pm-label">Steam ID</div><div style="display:flex;align-items:center;gap:6px;"><div class="pm-value mono" id="pm-id"></div><button class="btn btn-gray btn-sm" id="pm-copy-btn" onclick="copyPmId()" title="Copy Steam ID">⎘</button></div></div>
    <div class="pm-row"><div class="pm-label">Map</div><div class="pm-value" id="pm-map"></div></div>
    <div class="pm-row"><div class="pm-label">Last Seen</div><div class="pm-value" id="pm-last-seen"></div></div>
    <div class="pm-row"><div class="pm-label">Whitelist</div><div class="pm-value" id="pm-wl"></div></div>
    <div class="pm-actions" id="pm-actions"></div>
  </div>
</div>

<script>
const MAPS = ['ragnarok','thecenter','valguero','theisland','scorchedearth','aberration','extinction','lostcolony','astraeos'];
const MAP_DISPLAY = {
  ragnarok:'Ragnarok', thecenter:'The Center', valguero:'Valguero',
  theisland:'The Island', scorchedearth:'Scorched Earth', aberration:'Aberration',
  extinction:'Extinction', lostcolony:'Lost Colony', astraeos:'Astraeos'
};

let autoScroll           = true;
let whitelistActive      = false;
let lastLogLine          = '';
let lastAdminLine        = '';
let timerTarget          = null;   // unix seconds
let timerLabel           = '';
let timerColor           = '#6b7280';

// ── Toast notifications ───────────────────────────────────────────────────────
let _prevPlayers   = {};   // steamId -> {name, map}
let _initialPoll   = true; // suppress toasts on first load

function _showToast(msg, type) {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  const container = document.getElementById('toast-container');
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 4000);
  setTimeout(() => el.remove(), 4400);
}

function _checkPlayerChanges(data) {
  if (!data || !data.servers) return;
  const current = {};
  for (const [, s] of Object.entries(data.servers)) {
    for (const p of (s.player_list || [])) {
      if (p.id) current[p.id] = { name: p.name || p.id, map: s.display_name };
    }
  }
  if (!_initialPoll) {
    for (const [id, info] of Object.entries(current)) {
      if (!_prevPlayers[id]) _showToast(`${info.name} joined ${info.map}`, 'join');
    }
    for (const [id, info] of Object.entries(_prevPlayers)) {
      if (!current[id]) _showToast(`${info.name} left ${info.map}`, 'leave');
    }
  }
  _prevPlayers  = current;
  _initialPoll  = false;
}

// ── Command debounce ──────────────────────────────────────────────────────────
let _lastCmdStr  = '';
let _lastCmdTime = 0;
const _CMD_DEBOUNCE_MS = 3000;

// ── Copy Steam ID ─────────────────────────────────────────────────────────────
function copyPmId() {
  const id  = document.getElementById('pm-id').textContent;
  const btn = document.getElementById('pm-copy-btn');
  navigator.clipboard.writeText(id).then(() => {
    btn.textContent = '✓';
    setTimeout(() => { btn.textContent = '⎘'; }, 1500);
  }).catch(() => {});
}

// ── Whitelist all online ──────────────────────────────────────────────────────
async function whitelistAllOnline() {
  const r = await apiFetch('/api/whitelist/add-all-online', { method: 'POST' });
  if (!r) return;
  const d = await r.json();
  if (d.error)   { alert('Error: ' + d.error); return; }
  if (!d.added || !d.added.length) { alert('No players are currently online.'); return; }
  const names = d.added.map(p => p.name || p.id).join(', ');
  alert(`Added ${d.added.length} player(s) to whitelist:\n${names}`);
  loadWlTab();
}

// ── RAM warning ───────────────────────────────────────────────────────────────
let _ramMaxMaps = null;  // raw RAM-based limit, updated each poll

function _updateRamWarning(data) {
  if (data.ram_max_maps != null) _ramMaxMaps = data.ram_max_maps;
  const el = document.getElementById('ram-warning-banner');
  if (!el) return;
  const maxMaps = data.max_concurrent_maps;
  const total   = data.ram_total_gb;
  if (!maxMaps || total == null) { el.style.display = 'none'; return; }
  const running = Object.values(data.servers || {}).filter(s => s.is_running || s.is_starting).length;
  // Warn when at capacity — the system RAM can't comfortably handle another map
  if (running >= maxMaps) {
    const avail = data.ram_available_gb != null ? data.ram_available_gb.toFixed(1) + ' GB' : '? GB';
    const used  = running * 12 + 15;
    el.style.display = 'block';
    el.innerHTML = `&#9888; <strong>Low RAM:</strong> ${avail} available, ` +
      `${running} of ${maxMaps} map(s) + 15 GB overhead = ${used} GB. ` +
      `Servers may crash or fail to start.`;
  } else {
    el.style.display = 'none';
  }
}

// ── Left tabs ────────────────────────────────────────────────────────────────
const LEFT_TABS = ['controls','whitelist'];
function switchTab(name) {
  document.querySelectorAll('#left .tab-btn').forEach((b, i) => {
    b.classList.toggle('active', LEFT_TABS[i] === name);
  });
  document.querySelectorAll('#left .tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  if (name === 'whitelist') loadWlTab();
}

// ── Settings ──────────────────────────────────────────────────────────────────
function openSettings() {
  window.location.href = '/settings';
}

// ── Whitelist tab ─────────────────────────────────────────────────────────────
async function loadWlTab() {
  await Promise.all([loadCmdCategories(), loadWlPanel(), loadAdminPanel()]);
}

async function loadCmdCategories() {
  try {
    const r = await apiFetch('/api/command_categories');
    if (!r || !r.ok) return;
    const data = await r.json();
    renderCmdCategories(data.categories || {}, data.available || []);
  } catch(e) {}
}

function renderCmdCategories(cats, available) {
  const tiers = ['default', 'whitelist', 'admin'];
  // Group by tier
  const grouped = {default:[], whitelist:[], admin:[]};
  for (const [c, t] of Object.entries(cats)) {
    if (grouped[t]) grouped[t].push(c);
  }
  // Assigned commands (for dropdown filtering)
  const assigned = new Set(Object.keys(cats));

  for (const tier of tiers) {
    const listEl = document.getElementById('cmd-' + tier);
    const selEl  = document.getElementById('cmd-add-' + tier);
    // Render list
    listEl.innerHTML = grouped[tier].length
      ? grouped[tier].map(c =>
          `<div class="wl-entry">
             <div class="wl-info"><span class="wl-id" style="color:#93c5fd;">${escHtml(c)}</span></div>
             <button class="btn btn-red btn-sm" onclick="removeCmd('${escHtml(c)}')">Remove</button>
           </div>`
        ).join('')
      : '<span class="wl-empty">None</span>';
    // Populate dropdown with unassigned commands
    selEl.innerHTML = '<option value="">Add...</option>';
    for (const c of available) {
      if (!assigned.has(c)) {
        const opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        selEl.appendChild(opt);
      }
    }
  }
}

async function addCmd(tier) {
  const sel = document.getElementById('cmd-add-' + tier);
  const val = sel.value;
  if (!val) return;
  await apiFetch('/api/command_categories', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command: val, tier})
  });
  loadCmdCategories();
}

async function removeCmd(c) {
  await apiFetch('/api/command_categories', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command: c, tier: null})
  });
  loadCmdCategories();
}

async function addWlPlayer() {
  const inp = document.getElementById('wl-add-input');
  const id  = inp.value.trim();
  if (!id) return;
  cmd('whitelist add ' + id);
  inp.value = '';
  // Wait slightly longer than the controller's poll interval so the command
  // is processed before we re-fetch the whitelist (avoids showing stale data).
  setTimeout(loadWlPanel, 6000);
}

async function loadAdminPanel() {
  try {
    const r = await apiFetch('/api/admin_list');
    if (!r || !r.ok) return;
    const data = await r.json();
    renderAdminPanel(data.entries || []);
  } catch(e) {}
}

function renderAdminPanel(entries) {
  const el = document.getElementById('admin-panel');
  if (!entries.length) {
    el.innerHTML = '<span class="wl-empty">No admins configured</span>';
    return;
  }
  el.innerHTML = entries.map(id =>
    `<div class="wl-entry">
       <div class="wl-info">
         ${_onlinePlayerNames[id] ? `<span class="wl-name">${escHtml(_onlinePlayerNames[id])}</span>` : ''}
         <span class="wl-id" title="${escHtml(id)}">${escHtml(id)}</span>
       </div>
       <button class="btn btn-red btn-sm" onclick="removeAdminPlayer('${escHtml(id)}')">Remove</button>
     </div>`
  ).join('');
}

async function addAdminPlayer() {
  const inp = document.getElementById('admin-add-input');
  const id  = inp.value.trim();
  if (!id) return;
  await apiFetch('/api/admin_list', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'add', id})
  });
  inp.value = '';
  loadAdminPanel();
}

async function removeAdminPlayer(id) {
  await apiFetch('/api/admin_list', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'remove', id})
  });
  loadAdminPanel();
}

// ── Right tabs ───────────────────────────────────────────────────────────────
function switchRightTab(name) {
  document.querySelectorAll('#right .tab-bar .tab-btn').forEach((b, i) => {
    b.classList.toggle('active', ['console','log'][i] === name);
  });
  document.getElementById('right-console').style.display = name === 'console' ? 'flex' : 'none';
  document.getElementById('right-log').style.display     = name === 'log'     ? 'flex' : 'none';
}

// ── Commands ─────────────────────────────────────────────────────────────────
// Commands that cause the controller to be busy (saving/stopping servers)
// for an extended period — suppress auto-restart while they're running.
const _BUSY_COMMANDS = ['shutdown cluster', 'shutdown cluster now', 'force shutdown cluster',
                        'restart', 'restart now'];
const _BUSY_SUPPRESS_MS = 10 * 60 * 1000; // 10 minutes

function cmd(command) {
  // Debounce — ignore the same command if sent within 3 seconds (accidental double-click)
  const now = Date.now();
  if (command === _lastCmdStr && now - _lastCmdTime < _CMD_DEBOUNCE_MS) return;
  _lastCmdStr  = command;
  _lastCmdTime = now;

  const lower = command.trim().toLowerCase();
  if (_BUSY_COMMANDS.some(c => lower === c || lower.startsWith(c + ' '))) {
    // Controller will be busy — suppress auto-restart for the busy window.
    // Using a timestamp instead of a boolean so overlapping commands each
    // extend the deadline rather than racing to clear a shared flag.
    _suppressUntil   = Date.now() + _BUSY_SUPPRESS_MS;
    _restartAttempts = 0;
    _stopWatcher();
    _clearControllerBanner();
  }
  apiFetch('/api/command', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command})
  });
}

// Restart controller or dashboard process independently
function restartProcess(which) {
  const label = which === 'controller' ? 'Controller' : 'Dashboard';
  if (!confirm('Restart the ' + label + ' process?\n\nThe ' + label.toLowerCase() + ' window will close and reopen automatically.')) return;
  // Mark as deliberate so the auto-restart logic doesn't also fire
  if (which === 'controller') { _suppressUntil = Date.now() + _BUSY_SUPPRESS_MS; _restartAttempts = 0; _stopWatcher(); _clearControllerBanner(); }
  apiFetch('/api/restart/' + which, {method: 'POST'})
    .then(r => r ? r.json() : null)
    .then(d => {
      if (!d) return; // null = 401, redirect already fired by apiFetch
      if (d.ok) {
        if (which === 'dashboard') {
          // Page will go offline briefly — show a reconnect banner
          document.body.innerHTML = '<div style="display:flex;height:100vh;align-items:center;justify-content:center;background:#0f0f1a;color:#93c5fd;font-family:Segoe UI,sans-serif;font-size:18px;flex-direction:column;gap:16px;">' +
            '<div>Dashboard is restarting…</div>' +
            '<div style="font-size:14px;color:#6b7280;">This page will reload automatically.</div>' +
            '</div>';
          // Use raw fetch during restart polling — dashboard is coming back up so
          // there is no valid session yet; apiFetch would redirect to /login instead.
          const poll = setInterval(() => {
            fetch('/api/status').then(r => { if (r.ok) { clearInterval(poll); location.reload(); } }).catch(() => {});
          }, 2000);
        }
      } else {
        alert('Restart failed: ' + (d.error || 'unknown error'));
      }
    })
    .catch(() => alert('Could not reach dashboard API.'));
}

// Send from console input — echo locally, then wait for admin_log to show response
function sendConsole() {
  const el = document.getElementById('cmd-input');
  const v = el.value.trim();
  if (!v) return;
  if (v.toLowerCase() === 'force shutdown cluster') {
    el.value = '';
    openForceShutdownConfirm();
    return;
  }
  echoConsole('> ' + v);
  cmd(v);
  el.value = '';
}

// ── Force-shutdown confirm modal ──────────────────────────────────────────────
function openForceShutdownConfirm() {
  document.getElementById('confirm-modal').classList.add('open');
}

function cancelForceShutdown() {
  document.getElementById('confirm-modal').classList.remove('open');
  echoConsole('> force shutdown cluster (cancelled)');
}

function confirmForceShutdown() {
  document.getElementById('confirm-modal').classList.remove('open');
  echoConsole('> force shutdown cluster');
  cmd('force shutdown cluster');
}

// Run a quick-command button
function runCmd(c) {
  echoConsole('> ' + c);
  cmd(c);
  document.getElementById('cmd-input').focus();
}

// Append a local echo line (command typed by user) in gray
function echoConsole(line) {
  const el = document.getElementById('console-out');
  const span = document.createElement('span');
  span.style.color = '#6b7280';
  span.textContent = line;
  if (el.childNodes.length) el.appendChild(document.createTextNode('\n'));
  el.appendChild(span);
  el.scrollTop = el.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Whitelist toggle ──────────────────────────────────────────────────────────
function toggleWhitelist() { cmd(whitelistActive ? 'whitelist off' : 'whitelist on'); }

// ── Whitelist panel ───────────────────────────────────────────────────────────
let apPanelOpen = false;
let _onlinePlayerNames = {};   // id -> name, refreshed each status poll
let _playerModalCache  = {};   // id -> {name,id,map,mapKey,isOnline,last_seen}

async function loadWlPanel() {
  try {
    const r = await apiFetch('/api/whitelist');
    if (!r || !r.ok) return;
    const data = await r.json();
    renderWlPanel(data.entries || []);
  } catch(e) {}
}

function renderWlPanel(entries) {
  const el = document.getElementById('wl-panel');
  if (!entries.length) {
    el.innerHTML = '<span class="wl-empty">No entries — whitelist is empty</span>';
    return;
  }
  el.innerHTML = entries.map(id => {
    const name = _onlinePlayerNames[id];
    const nameHtml = name
      ? `<span class="wl-name" title="${escHtml(name)}">${escHtml(name)}</span>`
      : '';
    return `<div class="wl-entry">
       <div class="wl-info">
         ${nameHtml}
         <span class="wl-id" title="${escHtml(id)}">${escHtml(id)}</span>
       </div>
       <button class="btn btn-red btn-sm" onclick="wlRemove('${escHtml(id)}')">Remove</button>
     </div>`;
  }).join('');
}

function wlRemove(id) {
  cmd('whitelist remove ' + id);
  setTimeout(loadWlPanel, 6000);
}

// ── All Players panel ─────────────────────────────────────────────────────────
function toggleApPanel() {
  apPanelOpen = !apPanelOpen;
  const panel   = document.getElementById('ap-panel');
  const chevron = document.getElementById('ap-chevron');
  panel.classList.toggle('open', apPanelOpen);
  chevron.textContent = apPanelOpen ? '▼ hide' : '▶ show';
  if (apPanelOpen) loadApPanel();
}

async function loadApPanel() {
  try {
    const r = await apiFetch('/api/seen_players');
    if (!r || !r.ok) return;
    const data = await r.json();
    renderApPanel(data.players || {});
  } catch(e) {}
}

function renderApPanel(players) {
  const el = document.getElementById('ap-panel');
  const entries = Object.entries(players);
  if (!entries.length) {
    el.innerHTML = '<span class="wl-empty">No players recorded yet</span>';
    return;
  }
  entries.sort((a, b) => (b[1].last_seen || 0) - (a[1].last_seen || 0));
  el.innerHTML = entries.map(([id, p]) => {
    const isOnline = !!_onlinePlayerNames[id];
    const mapDisplay = p.last_map ? (MAP_DISPLAY[p.last_map] || p.last_map) : '—';
    _playerModalCache[id] = {
      name: p.name || id, id,
      map: mapDisplay,
      mapKey: p.last_map, isOnline,
      last_seen: p.last_seen,
    };
    return `<div class="ap-entry" data-pid="${escHtml(id)}" onclick="openPlayerModal(this.dataset.pid)">
      <span class="ap-dot ${isOnline ? 'online' : 'offline'}"></span>
      <span class="ap-name" title="${escHtml(p.name || id)}">${escHtml(p.name || id)}</span>
      <span class="ap-map">${escHtml(mapDisplay)}</span>
    </div>`;
  }).join('');
}

// ── Player list ───────────────────────────────────────────────────────────────
function renderPlayerList(data) {
  const el = document.getElementById('player-list');
  // Clear online flags before re-marking current online set
  for (const k in _playerModalCache) _playerModalCache[k].isOnline = false;
  _onlinePlayerNames = {};
  for (const [key, s] of Object.entries(data.servers || {})) {
    for (const p of (s.player_list || [])) {
      _onlinePlayerNames[p.id] = p.name;
      _playerModalCache[p.id] = {
        name: p.name, id: p.id,
        map: MAP_DISPLAY[key] || key, mapKey: key,
        isOnline: true, last_seen: Date.now() / 1000,
      };
    }
  }
  const online = Object.values(_playerModalCache).filter(p => p.isOnline);
  if (!online.length) {
    el.innerHTML = '<span class="pl-empty">No players online</span>';
    return;
  }
  el.innerHTML = online.map(p =>
    `<div class="pl-entry" style="cursor:pointer;" data-pid="${escHtml(p.id)}" onclick="openPlayerModal(this.dataset.pid)" title="Click for details">
       <div class="pl-info">
         <span class="pl-name">${escHtml(p.name)}</span>
         <span class="pl-id">${escHtml(p.id)}</span>
       </div>
       <span class="pl-map">${escHtml(p.map)}</span>
     </div>`
  ).join('');
}

// ── Player modal ──────────────────────────────────────────────────────────────
function fmtAgo(ts) {
  if (!ts) return '—';
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60)   return 'Just now';
  if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
  if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
  return Math.floor(secs / 86400) + 'd ago';
}

async function openPlayerModal(id) {
  const p = _playerModalCache[id];
  if (!p) return;

  // Mark all cached entries as offline first; re-mark online ones
  for (const k in _playerModalCache) _playerModalCache[k].isOnline = !!_onlinePlayerNames[k];

  const isOnline = !!_onlinePlayerNames[id];
  const dot = document.getElementById('pm-status-dot');
  dot.className = 'ap-dot ' + (isOnline ? 'online' : 'offline');

  document.getElementById('pm-name').textContent = p.name;
  document.getElementById('pm-id').textContent   = p.id;
  document.getElementById('pm-map').textContent  =
    isOnline ? p.map : (p.map ? 'Last seen: ' + p.map : '—');
  document.getElementById('pm-last-seen').textContent =
    isOnline ? 'Currently online' : fmtAgo(p.last_seen);

  // Fetch whitelist status fresh
  let onWl = false;
  try {
    const r = await apiFetch('/api/whitelist');
    if (r) {
      const wlData = await r.json();
      onWl = (wlData.entries || []).includes(id);
    }
  } catch(e) {}

  renderPmWl(id, onWl);
  document.getElementById('player-modal').classList.add('open');
}

function renderPmWl(id, onWl) {
  document.getElementById('pm-wl').innerHTML = onWl
    ? '<span style="color:#4ade80">✔ Whitelisted</span>'
    : '<span style="color:#6b7280">Not whitelisted</span>';

  const safeId = escHtml(id);
  document.getElementById('pm-actions').innerHTML = `
    <button class="btn btn-green btn-sm" ${onWl  ? 'disabled' : ''}
            onclick="cmd('whitelist add ${safeId}'); renderPmWl('${safeId}', true); setTimeout(loadWlPanel,6000)">+WL Add</button>
    <button class="btn btn-red btn-sm"   ${!onWl ? 'disabled' : ''}
            onclick="cmd('whitelist remove ${safeId}'); renderPmWl('${safeId}', false); setTimeout(loadWlPanel,6000)">−WL Remove</button>
  `;
}

function closePlayerModal() {
  document.getElementById('player-modal').classList.remove('open');
}

// ── Card-action confirm modal ─────────────────────────────────────────────────
let _ccmAction = null;
function openCcm(key, action, displayName) {
  _ccmAction = { key, action };
  const box = document.getElementById('card-confirm-box');
  const isStop = action === 'stop';
  box.className = isStop ? 'danger' : '';
  document.getElementById('ccm-title').textContent =
    isStop ? `Stop ${displayName}?` : `Restart ${displayName}?`;
  document.getElementById('ccm-body').textContent =
    isStop
      ? `This will warn online players then shut down ${displayName}. Continue?`
      : `${displayName} will save, restart, and be unavailable for a few minutes. Continue?`;
  const btn = document.getElementById('ccm-confirm-btn');
  btn.textContent  = isStop ? 'Stop' : 'Restart';
  btn.className    = 'btn ' + (isStop ? 'btn-bright-red' : 'btn-bright-orange');
  document.getElementById('card-confirm-modal').classList.add('open');
}
function closeCcm() {
  document.getElementById('card-confirm-modal').classList.remove('open');
  _ccmAction = null;
}
function confirmCcm() {
  if (!_ccmAction) return;
  const { key, action } = _ccmAction;
  closeCcm();
  // Per-map stop/restart also keeps the controller busy — suppress auto-restart
  _suppressUntil   = Date.now() + _BUSY_SUPPRESS_MS;
  _restartAttempts = 0;
  _stopWatcher();
  _clearControllerBanner();
  if (action === 'stop')    cmd('stop '    + key);
  if (action === 'restart') cmd('restart ' + key);
}

// ── Uptime helper ─────────────────────────────────────────────────────────────
function fmtUptime(onlineSince) {
  if (!onlineSince) return '';
  const secs = Math.floor(Date.now() / 1000 - onlineSince);
  if (!isFinite(secs) || secs < 0) return '';
  if (secs < 60)  return `↑ ${secs}s`;
  const m = Math.floor(secs / 60) % 60;
  const h = Math.floor(secs / 3600) % 24;
  const d = Math.floor(secs / 86400);
  if (d > 0) return `↑ ${d}d ${h}h`;
  if (h > 0) return `↑ ${h}h ${m}m`;
  return `↑ ${m}m`;
}

// ── Server cards ─────────────────────────────────────────────────────────────
function cardAction(key, action, displayName) {
  if (action === 'start') { cmd('start ' + key); return; }
  openCcm(key, action, displayName || key);
}

const cardEls = {};
let _titleSet = false;
function renderCards(data) {
  if (!data || !data.servers) return;

  if (!_titleSet && data.cluster_name) {
    const t = data.cluster_name + ' Dashboard';
    document.getElementById('page-title').textContent = t;
    document.title = t;
    _titleSet = true;
  }

  whitelistActive = !!data.whitelist_active;
  const wlBtn = document.getElementById('btn-wl');
  wlBtn.textContent = whitelistActive ? 'ON' : 'OFF';
  wlBtn.className = 'btn btn-sm ' + (whitelistActive ? 'btn-green' : 'btn-gray');

  const anyActive = Object.values(data.servers).some(s => s.is_running || s.is_starting);
  const startBtn = document.getElementById('btn-start-cluster');
  startBtn.disabled = anyActive;
  startBtn.className = 'btn btn-full ' + (anyActive ? 'btn-gray' : 'btn-bright-green');

  document.getElementById('cluster-offline-banner').style.display = anyActive ? 'none' : '';

  const runCount = Object.values(data.servers).filter(s => s.is_running).length;
  const maxMaps = data.max_concurrent_maps ? ` / ${data.max_concurrent_maps} max` : '';
  document.getElementById('status-line').textContent =
    runCount + maxMaps + ' server(s) online \u00b7 ' + (data.total_players||0) + ' player(s)';

  const container = document.getElementById('cards');
  for (const [key, s] of Object.entries(data.servers)) {
    const cls    = s.is_running ? 'online' : (s.is_starting ? 'starting' : 'offline');
    const label  = s.is_running ? 'Online' : (s.is_starting ? 'Starting' : 'Offline');
    const players = s.is_running ? s.player_count + ' / ' + (data.max_players || 70) + ' player(s)' : '';
    const uptime  = s.is_running ? fmtUptime(s.online_since) : '';
    const dn      = s.display_name;
    const crashBadge = (s.crash_restart_count > 0)
      ? `<span title="Crash restarts this window" style="font-size:11px;color:#f87171;margin-left:4px;">&#128293; ${s.crash_restart_count}</span>`
      : '';
    // Per-server stop countdown — shown when an admin has scheduled a map shutdown
    const stopMins = (s.manual_stop_in != null)
      ? Math.ceil(s.manual_stop_in / 60)
      : null;
    const stopBadge = (stopMins != null)
      ? `<span title="Scheduled shutdown" style="font-size:11px;color:#fbbf24;margin-left:4px;">&#9201; ${stopMins}m</span>`
      : '';
    const safeKey = escHtml(key);
    const safeDn  = escHtml(dn);

    if (cardEls[key]) {
      const c = cardEls[key];
      c.className = 'card ' + cls;
      c.querySelector('.badge').className = 'badge ' + cls;
      c.querySelector('.badge').textContent = label;
      c.querySelector('.card-players').textContent = players;
      c.querySelector('.card-uptime').textContent  = uptime;
      c.querySelector('.card-crash').innerHTML = crashBadge;
      c.querySelector('.card-stop-timer').innerHTML = stopBadge;
      c.querySelector('.btn-start').disabled   = s.is_running || s.is_starting;
      c.querySelector('.btn-stop').disabled    = !s.is_running;
      c.querySelector('.btn-restart').disabled = !s.is_running;
    } else {
      const c = document.createElement('div');
      c.className = 'card ' + cls;
      c.dataset.key = key;
      c.innerHTML = `
        <div class="card-head">
          <span class="card-name">${safeDn}</span>
          <span class="badge ${cls}">${label}</span>
        </div>
        <div style="display:flex;align-items:center;min-height:16px;">
          <span class="card-players">${players}</span>
          <span class="card-crash">${crashBadge}</span>
          <span class="card-stop-timer">${stopBadge}</span>
        </div>
        <div class="card-uptime">${uptime}</div>
        <div class="card-btns">
          <button class="btn btn-bright-green  btn-sm btn-start"   onclick="cardAction('${safeKey}','start','${safeDn}')"   ${s.is_running||s.is_starting?'disabled':''}>Start</button>
          <button class="btn btn-bright-red    btn-sm btn-stop"    onclick="cardAction('${safeKey}','stop','${safeDn}')"    ${!s.is_running?'disabled':''}>Stop</button>
          <button class="btn btn-bright-orange btn-sm btn-restart" onclick="cardAction('${safeKey}','restart','${safeDn}')" ${!s.is_running?'disabled':''}>Restart</button>
        </div>`;
      container.appendChild(c);
      cardEls[key] = c;
    }
  }
}

// ── Restart countdown ────────────────────────────────────────────────────────
function setTimerFromStatus(data) {
  if (data.cluster_shutdown_in != null) {
    // Active scheduled shutdown/restart already counting down
    const targetTs = Date.now() / 1000 + data.cluster_shutdown_in;
    timerTarget = targetTs;
    timerLabel  = data.cluster_restart_pending ? 'Restart in' : 'Shutdown in';
    timerColor  = data.cluster_restart_pending ? '#fbbf24' : '#f87171';
  } else if (data.next_scheduled_restart) {
    timerTarget = data.next_scheduled_restart;
    timerLabel  = 'Next restart in';
    timerColor  = '#6b7280';
  } else {
    timerTarget = null;
    timerLabel  = '';
    timerColor  = '#6b7280';
  }
}

function tickTimer() {
  const el = document.getElementById('restart-timer');
  if (!timerTarget) { el.textContent = ''; el.title = ''; return; }
  const secs = Math.max(0, Math.round(timerTarget - Date.now() / 1000));
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  el.textContent = timerLabel + ' ' + h + ':' + m + ':' + s;
  el.style.color = secs < 900 ? '#f87171' : secs < 3600 ? '#fbbf24' : timerColor;
  // Tooltip shows the actual wall-clock time so admin knows when it fires
  const at = new Date(timerTarget * 1000);
  el.title = 'At ' + at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

setInterval(tickTimer, 1000);

// ── Session expiry handling ───────────────────────────────────────────────────
// Wraps fetch() — redirects to /login automatically on 401 (session expired)
async function apiFetch(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { window.location.href = '/login'; return null; }
  return r;
}

// ── Controller auto-restart ───────────────────────────────────────────────────
// Timeline:
//   0 s      — page loads, 120 s startup grace starts (controller may be booting)
//   120 s+   — grace over; stale data triggers attempt #1
//   120 s later — if still offline, attempt #2
//   120 s later — if still offline, attempt #3
//   after 3 failed attempts — permanent error banner, manual action required
//
// Deliberate restarts (Restart Controller button) suppress auto-restart entirely.

const _STARTUP_GRACE_MS  = 120_000;  // wait before first auto-restart attempt
const _RETRY_INTERVAL_MS = 120_000;  // wait between subsequent attempts
const _MAX_RETRIES       = 3;

let _suppressUntil      = 0;   // epoch ms — auto-restart suppressed while Date.now() < this
let _restartAttempts    = 0;
let _autoRestartWatcher = null;
const _startupGraceUntil = Date.now() + _STARTUP_GRACE_MS;

function _showControllerBanner(cls, html) {
  const b = document.getElementById('controller-alert-banner');
  b.className = cls;
  b.innerHTML = html;
  b.style.display = cls ? '' : 'none';
}

function _clearControllerBanner() { _showControllerBanner('', ''); }

function _stopWatcher() {
  if (_autoRestartWatcher) { clearInterval(_autoRestartWatcher); _autoRestartWatcher = null; }
}

function _startRecoveryWatcher() {
  _stopWatcher();
  const deadline = Date.now() + _RETRY_INTERVAL_MS;
  _autoRestartWatcher = setInterval(() => {
    if (!_controllerLost) {
      // Controller is back — clean up everything
      _stopWatcher();
      _restartAttempts = 0;
      _clearControllerBanner();
      return;
    }
    if (Date.now() >= deadline) {
      _stopWatcher();
      if (_restartAttempts < _MAX_RETRIES) {
        // Try again
        _attemptAutoRestart();
      } else {
        // Exhausted all retries
        _showControllerBanner('failed',
          '<strong>&#9888; Controller could not restart after ' + _MAX_RETRIES + ' attempts.</strong><br>' +
          'Please restart it manually by running <em>start_controller.bat</em> or clicking ' +
          '<em>Restart Controller</em> in the Controls panel.');
      }
    }
  }, 3000);
}

async function _attemptAutoRestart() {
  _restartAttempts++;
  const attemptLabel = _MAX_RETRIES > 1
    ? ` (attempt ${_restartAttempts} of ${_MAX_RETRIES})`
    : '';
  _showControllerBanner('restarting',
    `<strong>&#8635; Controller went offline — attempting automatic restart${attemptLabel}…</strong><br>` +
    `Waiting up to ${_RETRY_INTERVAL_MS / 1000} seconds for it to come back.`);
  try {
    const r = await fetch('/api/restart/controller', { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    _startRecoveryWatcher();
  } catch(e) {
    // Dashboard unreachable — can't restart, show error immediately
    _showControllerBanner('failed',
      '<strong>&#9888; Auto-restart failed — could not reach the restart endpoint.</strong><br>' +
      'Please restart manually via <em>start_controller.bat</em>.');
  }
}

// ── Connection-lost / stale-data indicator ────────────────────────────────────
// The dashboard and controller are separate processes. The dashboard keeps
// serving the last cluster_status.json even after the controller closes, so
// HTTP polls keep succeeding with stale data. We detect this by comparing
// the "timestamp" field written into the JSON by the controller against now.
// Cards still render with whatever data is available — the warning sits on
// top so the user knows it may be out of date.
const _STALE_THRESHOLD_SECONDS = 25; // controller writes every ~5 s normally
let _controllerLost = false;

function _checkStaleness(data) {
  if (!data.timestamp) return;
  const ageSeconds = Date.now() / 1000 - data.timestamp;
  const isStale = ageSeconds > _STALE_THRESHOLD_SECONDS;
  const sl = document.getElementById('status-line');
  const cardsEl = document.getElementById('cards');
  if (isStale && !_controllerLost) {
    _controllerLost = true;
    sl.textContent = '⚠ Controller offline — attempting restart…';
    sl.style.color = '#f87171';
    cardsEl.classList.add('stale');
    // Auto-restart unless deliberate or still within the startup grace window
    if (Date.now() >= _suppressUntil && _restartAttempts === 0 && Date.now() > _startupGraceUntil) {
      _attemptAutoRestart();
    }
  } else if (!isStale && _controllerLost) {
    _controllerLost  = false;
    _suppressUntil   = 0;
    _restartAttempts = 0;
    _stopWatcher();
    sl.style.color = '';
    cardsEl.classList.remove('stale');
    // Show a brief green confirmation so the admin knows recovery worked
    _showControllerBanner('restarting',
      '<strong>&#10003; Controller is back online.</strong>');
    setTimeout(_clearControllerBanner, 4000);
  }
}

let _pollFailures = 0;
const _MAX_POLL_FAILURES = 3;
function _markPollOk() {
  if (_pollFailures >= _MAX_POLL_FAILURES) {
    document.getElementById('status-line').style.color = '';
  }
  _pollFailures = 0;
}
function _markPollFail() {
  _pollFailures++;
  if (_pollFailures >= _MAX_POLL_FAILURES) {
    const sl = document.getElementById('status-line');
    sl.textContent = '⚠ Dashboard unreachable — retrying…';
    sl.style.color = '#f87171';
  }
}

// ── Polling ───────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await apiFetch('/api/status');
    if (!r || !r.ok) { _markPollFail(); return; }
    const data = await r.json();
    if (data.error) { _markPollFail(); return; }
    _markPollOk();
    _checkStaleness(data);
    _checkPlayerChanges(data);
    _updateRamWarning(data);
    // Always render cards so the UI is never blank — the staleness warning
    // in the header is enough to communicate that data may be out of date.
    renderCards(data);
    renderPlayerList(data);
    if (!_controllerLost) setTimerFromStatus(data);
  } catch(e) { _markPollFail(); }
}

async function pollLogs() {
  try {
    const r = await apiFetch('/api/logs?n=300');
    if (!r || !r.ok) return;
    const data = await r.json();
    const lines = data.lines || [];
    if (!lines.length) return;
    const lastLine = lines[lines.length-1];
    if (lastLine === lastLogLine) return;
    lastLogLine = lastLine;
    const el = document.getElementById('log');
    const wasBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 30;
    el.textContent = lines.join('\n');
    if (autoScroll && wasBottom) el.scrollTop = el.scrollHeight;
  } catch(e) {}
}

function colorizeAdminLine(ln) {
  const esc = escHtml(ln);
  // Strip timestamp prefix for matching: "[HH:MM:SS] REST OF LINE"
  const body = ln.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').toLowerCase();

  if (/^admin cmd:/.test(body))
    return `<span style="color:#38bdf8;font-weight:700">${esc}</span>`;
  if (/^admin commands:/.test(body) || /^maps:/.test(body))
    return `<span style="color:#38bdf8">${esc}</span>`;
  if (/^\s{2}/.test(ln.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')))
    return `<span style="color:#94a3b8">${esc}</span>`;
  if (/\bfail\b|\berror\b|\bfailed\b|\btimed out\b/.test(body))
    return `<span style="color:#f87171">${esc}</span>`;
  if (/^chat /.test(body))
    return `<span style="color:#fbbf24">${esc}</span>`;
  if (/^backup/.test(body) || /backing up/.test(body))
    return `<span style="color:#c084fc">${esc}</span>`;
  if (/^executing/.test(body) || /^restarting/.test(body))
    return `<span style="color:#fb923c;font-weight:600">${esc}</span>`;
  if (/^starting /.test(body) || /^stopping /.test(body))
    return `<span style="color:#4ade80">${esc}</span>`;
  if (/saveworld|waiting \d+s|save before|post.shutdown/.test(body))
    return `<span style="color:#94a3b8">${esc}</span>`;
  if (/gameusersettings/.test(body))
    return `<span style="color:#64748b">${esc}</span>`;
  return `<span style="color:#cbd5e1">${esc}</span>`;
}

async function pollAdminLogs() {
  try {
    const r = await apiFetch('/api/admin_logs?n=200');
    if (!r || !r.ok) return;
    const data = await r.json();
    const lines = data.lines || [];
    if (!lines.length) return;
    const lastLine = lines[lines.length-1];
    if (lastLine === lastAdminLine) return;
    lastAdminLine = lastLine;

    const el = document.getElementById('console-out');
    const parts = [];
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      // Insert a divider before each new ADMIN CMD block
      if (/\] ADMIN CMD:/.test(ln) && i > 0)
        parts.push('<span style="color:#1e3a5f;user-select:none">' + '─'.repeat(60) + '</span>');
      parts.push(colorizeAdminLine(ln));
    }
    el.innerHTML = parts.join('\n');
    el.scrollTop = el.scrollHeight;
  } catch(e) {}
}



// ── Init ─────────────────────────────────────────────────────────────────────
pollStatus();
pollLogs();
pollAdminLogs();
setInterval(pollStatus,    3000);
setInterval(pollLogs,      2000);
setInterval(pollAdminLogs, 1500);
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template_string(HTML)


@app.route("/health")
@login_required
def health():
    """Health-check endpoint — requires login when auth is enabled."""
    try:
        with open(STATUS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("servers", {})
        running = [k for k, v in servers.items() if v.get("is_running")]
        return jsonify({
            "ok": True,
            "running_servers": running,
            "total_players": data.get("total_players", 0),
            "cluster_shutdown_scheduled": data.get("cluster_shutdown_scheduled", False),
        })
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "controller not ready"}), 503
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/status")
@login_required
def get_status():
    try:
        with open(STATUS_JSON, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "status not available yet"}), 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/logs")
@login_required
def get_logs():
    n = min(max(request.args.get("n", 300, type=int), 1), 2000)
    try:
        with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return jsonify({"lines": [ln.rstrip() for ln in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as exc:
        return jsonify({"lines": [], "error": str(exc)})


@app.route("/api/admin_logs")
@login_required
def get_admin_logs():
    n = min(max(request.args.get("n", 200, type=int), 1), 2000)
    try:
        with open(ADMIN_LOG_FILE, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return jsonify({"lines": [ln.rstrip() for ln in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as exc:
        return jsonify({"lines": [], "error": str(exc)})


@app.route("/api/whitelist")
@login_required
def get_whitelist():
    try:
        if not os.path.exists(WHITELIST_FILE):
            return jsonify({"entries": []})
        with open(WHITELIST_FILE, encoding="utf-8") as f:
            entries = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        return jsonify({"entries": entries})
    except Exception as exc:
        return jsonify({"entries": [], "error": str(exc)})


@app.route("/api/whitelist/add-all-online", methods=["POST"])
@login_required
def whitelist_add_all_online():
    """Add every currently online player to the whitelist in one shot."""
    try:
        with open(STATUS_JSON, encoding="utf-8") as f:
            status = json.load(f)
    except Exception:
        return jsonify({"error": "Status not available"}), 503

    players = []
    for server in status.get("servers", {}).values():
        for p in server.get("player_list", []):
            sid = str(p.get("id", "")).strip()
            if sid:
                players.append({"id": sid, "name": p.get("name", sid)})

    if not players:
        return jsonify({"ok": True, "added": [], "message": "No players online"})

    try:
        with open(ADMIN_CMD, "a", encoding="utf-8") as f:
            for p in players:
                f.write(f"whitelist add {p['id']}\n")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "added": players})


@app.route("/api/command", methods=["POST"])
@login_required
def post_command():
    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "empty command"}), 400
    try:
        with open(ADMIN_CMD, "a", encoding="utf-8") as f:
            f.write(command + "\n")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    result = {section: dict(cfg.items(section)) for section in cfg.sections()}
    # Strip sensitive auth fields — never send hashed password or secret key to browser
    if "auth" in result:
        result["auth"].pop("password_hash", None)
        result["auth"].pop("secret_key",    None)
    return jsonify(result)


@app.route("/api/settings", methods=["POST"])
@login_required
def post_settings():
    data = request.get_json(silent=True) or {}
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    # Validate max_active_servers against the RAM-based hard limit
    try:
        requested_max = int(data.get("limits", {}).get("max_active_servers", 0) or 0)
        if requested_max > 0:
            ram_max = None
            try:
                with open(STATUS_JSON, encoding="utf-8") as _sf:
                    ram_max = json.load(_sf).get("ram_max_maps")
            except Exception:
                pass
            if ram_max is not None and requested_max > ram_max:
                return jsonify({
                    "error": f"max_active_servers cannot exceed {ram_max} — "
                             f"your system RAM only supports {ram_max} map(s) "
                             f"(15 GB overhead + 12 GB per map)."
                }), 400
    except (ValueError, TypeError):
        pass

    for section, kvs in data.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for key, value in kvs.items():
            # Block sensitive auth fields — must never be set directly via the API
            if section == "auth" and key in ("password_hash", "secret_key"):
                continue
            # new_password is a UI-only field — hash it and store as password_hash
            if section == "auth" and key == "new_password":
                if str(value).strip():
                    cfg.set("auth", "password_hash", _hash_password(str(value).strip()))
                # Never persist the plaintext new_password field
                continue
            cfg.set(section, key, str(value))
    try:
        # Back up the current config before overwriting so bad settings can be recovered
        if os.path.exists(CONFIG_FILE):
            try:
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".bak")
            except Exception:
                pass
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


AVAILABLE_COMMANDS = ["!help", "!status", "!start", "!stop", "!restart"]
_DEFAULT_CATEGORIES = {"!help": "default", "!status": "default", "!start": "whitelist"}

def _read_categories():
    if not os.path.exists(COMMAND_CATEGORIES_FILE):
        return dict(_DEFAULT_CATEGORIES)
    try:
        with open(COMMAND_CATEGORIES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if data else dict(_DEFAULT_CATEGORIES)
    except Exception:
        return dict(_DEFAULT_CATEGORIES)


@app.route("/api/command_categories", methods=["GET"])
@login_required
def get_command_categories():
    return jsonify({"categories": _read_categories(), "available": AVAILABLE_COMMANDS})


@app.route("/api/command_categories", methods=["POST"])
@login_required
def post_command_categories():
    data    = request.get_json(silent=True) or {}
    command = data.get("command", "").strip().lower()
    tier    = data.get("tier")           # "default"|"whitelist"|"admin"|None=remove
    if not command:
        return jsonify({"error": "missing command"}), 400
    cats = _read_categories()
    if tier:
        cats[command] = tier
    else:
        cats.pop(command, None)
    try:
        with open(COMMAND_CATEGORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cats, f, indent=2)
        return jsonify({"ok": True, "categories": cats})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _read_list_file(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except Exception:
        return []


@app.route("/api/admin_list", methods=["GET"])
@login_required
def get_admin_list():
    return jsonify({"entries": _read_list_file(ADMIN_LIST_FILE)})


@app.route("/api/admin_list", methods=["POST"])
@login_required
def post_admin_list():
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "")
    entry  = data.get("id", "").strip()
    if not entry:
        return jsonify({"error": "missing id"}), 400
    entries = set(_read_list_file(ADMIN_LIST_FILE))
    if action == "add":
        entries.add(entry)
    elif action == "remove":
        entries.discard(entry)
    else:
        return jsonify({"error": "action must be add or remove"}), 400
    try:
        with open(ADMIN_LIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(entries)) + "\n")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/seen_players")
@login_required
def get_seen_players():
    try:
        if not os.path.exists(SEEN_PLAYERS_FILE):
            return jsonify({"players": {}})
        with open(SEEN_PLAYERS_FILE, encoding="utf-8") as f:
            return jsonify({"players": json.load(f)})
    except Exception as exc:
        return jsonify({"players": {}, "error": str(exc)})


@app.route("/api/defaults")
@login_required
def get_defaults():
    return jsonify({
        "cluster": {
            "cluster_name": "MyCluster",
            "rcon_password": "ChangeMe123",
            "default_map": "ragnarok",
        },
        "network": {
            "rcon_host": "127.0.0.1",
            "web_status_port": "5000",
        },
        "paths": {
            "server_root": r"C:\ASA_Cluster\asa_server",
            "cluster_dir": r"C:\ASA_Cluster\asa_server\cluster",
            "steamcmd_path": r"C:\ASA_Cluster\SteamCMD\steamcmd.exe",
        },
        "limits": {
            "max_active_servers": "3",
            "max_players": "70",
            "max_tamed_dinos": "5000",
            "max_personal_tamed_dinos": "40",
            "low_memory_mode": "true",
            "no_sound": "true",
            "gc_purge_interval": "30",
        },
        "timers": {
            "map_shutdown_minutes": "15",
            "startup_grace_minutes": "15",
            "autosave_minutes": "15",
            "cluster_shutdown_minutes": "30",
            "server_start_timeout_seconds": "300",
            "save_before_exit_seconds": "10",
            "post_shutdown_wait_seconds": "60",
            "crash_detection_threshold": "5",
        },
        "backup": {
            "backup_dir": r"C:\ASA_Cluster\backups",
            "max_backups": "10",
            "max_logs": "10",
        },
        "crash": {
            "auto_restart_on_crash": "true",
            "crash_grace_seconds": "120",
            "crash_cooldown_minutes": "5",
            "max_crash_restarts": "3",
            "crash_window_minutes": "60",
        },
        "discord": {
            "discord_enabled": "false",
            "use_bot": "false",
            "webhook_url": "",
            "bot_token": "",
            "notification_channel_id": "",
            "command_channel_id": "",
            "admin_role_name": "Admin",
            "notify_server_events": "true",
            "notify_crash_events": "true",
            "notify_cluster_events": "true",
        },
        "schedule": {
            "poll_seconds": "5",
            "check_updates_on_startup": "true",
            "restart_time": "06:00",
        },
        "rates": {
            "xp_multiplier": "1.0",
            "taming_speed_multiplier": "1.0",
            "harvest_amount_multiplier": "1.0",
            "difficulty_offset": "1.0",
            "mating_interval_multiplier": "1.0",
            "egg_hatch_speed_multiplier": "1.0",
            "global_spoiling_time_multiplier": "1.0",
            "global_item_decomposition_time_multiplier": "1.0",
            "global_corpse_decomposition_time_multiplier": "1.0",
            "crop_growth_speed_multiplier": "1.0",
            "mating_speed_multiplier": "1.0",
            "fuel_consumption_interval_multiplier": "1.0",
        },
        "breeding": {
            "baby_mature_speed_multiplier": "1.0",
            "baby_cuddle_interval_multiplier": "1.8",
            "baby_cuddle_grace_period_multiplier": "1.0",
            "baby_imprint_amount_multiplier": "20.0",
        },
        "flags": {
            "allow_third_person": "false",
            "show_map_player_location": "true",
            "always_allow_structure_pickup": "true",
            "disable_structure_decay_pve": "false",
            "allow_cave_building_pve": "false",
            "allow_anyone_baby_imprint_cuddle": "false",
            "allow_flyer_carry_pve": "true",
            "prevent_download_survivors": "false",
            "prevent_download_items": "false",
        },
    })


SETTINGS_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Settings</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { background:#0f0f1a; color:#dde1e7; font-family:'Segoe UI',sans-serif; font-size:16px; min-height:100vh; padding:16px; display:flex; flex-direction:column; }
h1 { font-size:18px; font-weight:700; color:#93c5fd; margin-bottom:0; }
.notice { background:#78350f; color:#fdba74; padding:8px 10px; border-radius:4px; font-size:14px; margin-bottom:10px; display:none; }
.hint   { font-size:13px; color:#4b5563; margin-bottom:10px; }
.tab-bar { display:flex; gap:2px; flex-wrap:wrap; flex-shrink:0; }
.s-tab  { padding:7px 13px; background:#1a1f36; border:1px solid #2a3050; border-bottom:none;
           border-radius:4px 4px 0 0; cursor:pointer; font-size:14px; color:#9ca3af; white-space:nowrap; }
.s-tab.active { background:#222840; color:#fff; border-color:#3b4a7a; }
.s-tab:hover:not(.active) { color:#dde1e7; }
.tab-content { flex:1; background:#222840; border:1px solid #3b4a7a; border-radius:0 4px 4px 4px; padding:14px 16px; overflow-y:auto; }
.group  { display:none; }
.group.active { display:block; }
.page-wrap { max-width:960px; width:100%; margin:0 auto; display:flex; flex-direction:column; flex:1; }
.grid2  { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.grid3  { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
.stack  { display:flex; flex-direction:column; max-width:520px; }
@media (max-width:800px) { .grid3 { grid-template-columns:1fr 1fr; } }
@media (max-width:600px) { .grid2, .grid3 { grid-template-columns:1fr; } }
.field  { margin-bottom:8px; }
.field.wide { grid-column:1 / -1; }
label   { font-size:13px; color:#6b7280; display:block; margin-bottom:4px; }
input   { width:100%; background:#131825; border:1px solid #2a3050; color:#dde1e7;
          padding:6px 10px; border-radius:4px; font-size:14px; font-family:inherit; }
input:focus { outline:none; border-color:#3b4a7a; }
.footer { padding:12px 0 0; margin-top:10px; border-top:1px solid #2a3050; flex-shrink:0; }
.btn    { padding:8px 16px; border:none; border-radius:4px; cursor:pointer; font-size:14px;
          font-weight:600; width:100%; background:#1e3a5f; color:#93c5fd; transition:opacity .15s; }
.btn:hover { opacity:.85; }
.btn.saved { background:#14532d; color:#4ade80; }
.sec-head { font-size:12px; color:#4b5563; text-transform:uppercase; letter-spacing:.06em;
            padding-bottom:5px; border-bottom:1px solid #2a3050; margin:14px 0 8px; }
.sec-head:first-child { margin-top:0; }
input::placeholder { color:#3d4a62; }
.breed-hint { font-size:12px; color:#4ade80; display:block; margin-top:3px; }

/* Toggle switch */
.toggle-label { display:flex; align-items:center; gap:10px; cursor:pointer; user-select:none; font-size:14px; padding:4px 0; }
.toggle-cb { display:none; }
.toggle-track { width:42px; height:22px; background:#374151; border-radius:11px; position:relative; flex-shrink:0; transition:background .2s; }
.toggle-thumb { width:18px; height:18px; background:#fff; border-radius:50%; position:absolute; top:2px; left:2px; transition:left .2s; }
.toggle-cb:checked + .toggle-track { background:#3b82f6; }
.toggle-cb:checked + .toggle-track .toggle-thumb { left:22px; }

/* Info box */
.info-box { background:#1a2540; border:1px solid #3b4a7a; border-radius:6px; padding:12px 14px; font-size:13px; line-height:1.7; color:#c9d1e0; }
.info-box b { color:#93c5fd; }
</style>
</head>
<body>
<div class="page-wrap">
<div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
  <a href="/" style="color:#4b5563; font-size:22px; text-decoration:none; line-height:1;"
     onmouseover="this.style.color='#93c5fd'" onmouseout="this.style.color='#4b5563'">←</a>
  <h1>⚙ Settings</h1>
</div>
<div class="notice" id="notice">No config.ini found — defaults loaded. Fill in your values and save.</div>
<div class="hint">Most changes apply on the next server start. Schedule, network, and path changes require a controller restart.</div>
<div class="tab-bar" id="tab-bar"></div>
<div class="tab-content">
  <div id="form"></div>
</div>
<div class="footer"><button class="btn" id="save-btn" onclick="save()">Save Settings</button></div>
</div>
<script>
// Wraps fetch() — redirects to /login automatically on 401 (session expired)
async function apiFetch(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { window.location.href = '/login'; return null; }
  return r;
}

const SCHEMA = [
  { group:'Cluster', sections:[
    { title:'Identity', fields:[
      {s:'cluster',    k:'cluster_name',   label:'Cluster Name',   ph:'MyCluster'},
      {s:'cluster',    k:'rcon_password',  label:'RCON Password',  ph:'ChangeMe123'},
      {s:'cluster',    k:'default_map',    label:'Default Map',    ph:'ragnarok'},
      {s:'network',    k:'rcon_host',      label:'RCON Host',           ph:'127.0.0.1'},
      {s:'network',    k:'web_status_port',label:'Dashboard Port',       ph:'5000',  hint:'Port the web dashboard listens on — requires a dashboard restart to take effect'},
    ]},
    { title:'Dashboard Login', fields:[
      {s:'auth', k:'username',      label:'Username',         ph:'admin',   hint:'Login username for the dashboard'},
      {s:'auth', k:'new_password',  label:'New Password',     ph:'',        type:'password', hint:'Leave blank to keep current password — fill in to change it'},
    ]},
    { title:'Paths', fields:[
      {s:'paths', k:'server_root',   label:'Server Root',   ph:'C:\\ASA_Cluster\\asa_server',              wide:true},
      {s:'paths', k:'cluster_dir',   label:'Cluster Dir',   ph:'C:\\ASA_Cluster\\asa_server\\cluster',     wide:true},
      {s:'paths', k:'steamcmd_path', label:'SteamCMD Path', ph:'C:\\ASA_Cluster\\SteamCMD\\steamcmd.exe', wide:true},
    ]},
    { title:'Mods & Events', fields:[
      {s:'mods',  k:'mod_ids',      label:'Mod IDs (comma-separated Steam IDs)', ph:'',      wide:true},
      {s:'mods',  k:'crossplay',    label:'Enable Crossplay (Epic + Steam)',      ph:'false'},
      {s:'world', k:'active_event', label:'Active Event',                         ph:''},
    ]},
  ]},
  { group:'Server', sections:[
    { title:'Limits', grid:true, fields:[
      {s:'limits', k:'max_active_servers',     label:'Max Active Maps',        ph:'3'},
      {s:'limits', k:'max_players',            label:'Max Players per Map',    ph:'70'},
      {s:'limits', k:'max_tamed_dinos',        label:'Max Tamed Dinos (total)',ph:'5000'},
      {s:'limits', k:'max_personal_tamed_dinos',label:'Max Tamed (per player)',ph:'40'},
      {s:'limits', k:'low_memory_mode',             label:'Low Memory Mode',           ph:'true',  hint:'Adds -lowmemory -nomemorybias to server launch (~30% less RAM)'},
      {s:'limits', k:'no_sound',                    label:'Disable Sound System',      ph:'true',  hint:'Adds -nosound — server has no speakers, saves ~200 MB per server'},
      {s:'limits', k:'gc_purge_interval',           label:'GC Purge Interval (s)',     ph:'30',    hint:'How often ARK runs garbage collection — lower = more frequent cleanup'},
    ]},
    { title:'Schedule', grid:true, fields:[
      {s:'schedule', k:'poll_seconds',            label:'Poll Interval (s)',      ph:'5'},
      {s:'schedule', k:'restart_time',            label:'Daily Restart (HH:MM)',  ph:'06:00'},
      {s:'schedule', k:'check_updates_on_startup',label:'Check Updates on Start', ph:'true'},
    ]},
    { title:'Timers', grid:true, fields:[
      {s:'timers', k:'map_shutdown_minutes',         label:'Empty Map Shutdown (min)',    ph:'15'},
      {s:'timers', k:'autosave_minutes',             label:'Autosave Interval (min)',     ph:'15'},
      {s:'timers', k:'startup_grace_minutes',        label:'Startup Grace (min)',         ph:'15'},
      {s:'timers', k:'cluster_shutdown_minutes',     label:'Cluster Shutdown Warn (min)', ph:'30'},
      {s:'timers', k:'server_start_timeout_seconds', label:'Start Timeout (s)',           ph:'300'},
      {s:'timers', k:'save_before_exit_seconds',     label:'Save Before Exit (s)',        ph:'10'},
      {s:'timers', k:'post_shutdown_wait_seconds',   label:'Post-Shutdown Wait (s)',      ph:'30'},
      {s:'timers', k:'crash_detection_threshold',    label:'Crash Threshold',             ph:'5'},
    ]},
    { title:'Backup', grid:true, fields:[
      {s:'backup', k:'backup_dir',   label:'Backup Directory', ph:'C:\\ASA_Cluster\\backups', wide:true},
      {s:'backup', k:'max_backups',  label:'Max Backups',       ph:'10'},
      {s:'backup', k:'max_logs',     label:'Max Saved Logs',    ph:'10', hint:'Logs are archived on each restart — oldest deleted when over this limit'},
    ]},
    { title:'Auto-Restart on Crash', grid:true, fields:[
      {s:'crash', k:'auto_restart_on_crash',  label:'Auto-Restart on Crash', ph:'true',  hint:'Automatically restart a server if it crashes (true/false)'},
      {s:'crash', k:'crash_grace_seconds',    label:'Online Grace (s)',       ph:'120',   hint:'Seconds after a server comes online before crash detection activates'},
      {s:'crash', k:'crash_cooldown_minutes', label:'Cooldown (min)',         ph:'5',     hint:'Minimum minutes between crash-restarts — prevents rapid restart loops'},
      {s:'crash', k:'max_crash_restarts',     label:'Max Restarts',          ph:'3',     hint:'Max times to restart within the window before giving up'},
      {s:'crash', k:'crash_window_minutes',   label:'Window (min)',          ph:'60',    hint:'Time window for counting crash restarts — resets after this many minutes'},
    ]},
    { title:'Discord Notifications', fields:[
      {s:'discord', k:'discord_enabled', label:'Enable Discord Notifications', type:'checkbox', ph:'false',
        hint:'Master switch — off by default. Turn on to send notifications to Discord via webhook or bot.'},
      {s:'discord', k:'use_bot', label:'Enable Two-Way Bot (advanced)', type:'checkbox', ph:'false', visGroup:'discord-settings',
        hint:'Off = simple webhook (one-way notifications). On = full Discord bot with commands from Discord.'},
      {s:'discord', k:'webhook_url', label:'Webhook URL', ph:'https://discord.com/api/webhooks/...', wide:true, visGroup:'webhook',
        hint:'Paste your Discord channel webhook URL — Discord → channel settings → Integrations → Webhooks → New Webhook → Copy URL'},
    ]},
    { title:'Notification Events', fields:[
      {s:'discord', k:'notify_server_events',  label:'Server Online',  ph:'true', visGroup:'discord-settings', hint:'Notify when a server comes online'},
      {s:'discord', k:'notify_crash_events',   label:'Crash Events',   ph:'true', visGroup:'discord-settings', hint:'Notify on crash, auto-restart, and crash limit reached'},
      {s:'discord', k:'notify_cluster_events', label:'Cluster Events', ph:'true', visGroup:'discord-settings', hint:'Notify on cluster restarts, shutdowns, and scheduled events'},
    ]},
    { title:'Bot Setup (Two-Way)', fields:[
      {type:'info', visGroup:'bot', html:`
        <b>How to set up the Discord bot:</b><br>
        1. Go to <a href="https://discord.com/developers/applications" target="_blank" style="color:#93c5fd">discord.com/developers/applications</a> → New Application<br>
        2. Go to <b>Bot</b> → enable <b>Message Content Intent</b> → copy the <b>Token</b><br>
        3. Go to <b>OAuth2 → URL Generator</b> → tick <b>bot</b> scope → tick <b>Send Messages, Embed Links, Read Message History</b> → copy the URL → paste in browser to invite the bot to your server<br>
        4. In Discord: User Settings → Advanced → enable <b>Developer Mode</b> → right-click a channel → <b>Copy Channel ID</b><br>
        5. Fill in the fields below and save
      `},
      {s:'discord', k:'bot_token',               label:'Bot Token',               ph:'your-bot-token-here', wide:true, visGroup:'bot',
        hint:'From Discord Developer Portal → Your App → Bot → Token'},
      {s:'discord', k:'notification_channel_id', label:'Notification Channel ID', ph:'123456789012345678',   visGroup:'bot',
        hint:'Channel where the bot posts events — right-click channel → Copy Channel ID'},
      {s:'discord', k:'command_channel_id',      label:'Command Channel ID',      ph:'123456789012345678',   visGroup:'bot',
        hint:'Channel where admins type !commands — leave blank to use the notification channel'},
      {s:'discord', k:'admin_role_name',         label:'Admin Role Name',         ph:'Admin',                visGroup:'bot',
        hint:'Discord role name required to use bot commands (e.g. Admin)'},
    ]},
  ]},
  { group:'World & Rates', sections:[
    { title:'World', grid:true, fields:[
      {s:'world', k:'day_time_speed_scale',               label:'Day Speed',                ph:'1.0'},
      {s:'world', k:'night_time_speed_scale',             label:'Night Speed',              ph:'1.0'},
      {s:'world', k:'dino_count_multiplier',              label:'Wild Dino Count',          ph:'1.0'},
      {s:'world', k:'resources_respawn_period_multiplier',label:'Resources Respawn',        ph:'1.0'},
    ]},
    { title:'Experience & Gathering', grid3:true, fields:[
      {s:'rates', k:'xp_multiplier',             label:'XP',               ph:'1.0',               hint:'✦ Rec: 1.5 — less grind'},
      {s:'rates', k:'harvest_amount_multiplier', label:'Harvest Amount',   ph:'1.0',               hint:'✦ Rec: 5.0 — less farming'},
      {s:'rates', k:'taming_speed_multiplier',   label:'Taming Speed',     ph:'1.0',               hint:'✦ Rec: 5.0 — reasonable tame times'},
      {s:'rates', k:'difficulty_offset',         label:'Difficulty Offset',ph:'1.0',               hint:'✦ Rec: 1.0 — enables max lvl 150 dinos'},
      {s:'rates', k:'item_stack_size_multiplier',label:'Item Stack Size',  ph:'1.0',               hint:'✦ Rec: 5.0 — less inventory juggling'},
      {s:'rates', k:'crop_growth_speed_multiplier',label:'Crop Growth',    ph:'1.0',               hint:'✦ Rec: 5.0 — faster crops'},
    ]},
    { title:'Loot Quality', grid3:true, fields:[
      {s:'rates', k:'loot_quality_multiplier',               label:'General Loot',    ph:'1.0', hint:'✦ Rec: 3.0 — better drops'},
      {s:'rates', k:'fishing_loot_quality_multiplier',       label:'Fishing Loot',    ph:'1.0', hint:'✦ Rec: 3.0 — worth fishing'},
      {s:'rates', k:'supply_crate_loot_quality_multiplier',  label:'Supply Crate',    ph:'1.0', hint:'✦ Rec: 3.0 — rewarding drops'},
    ]},
    { title:'Decay & Fuel', grid3:true, fields:[
      {s:'rates', k:'global_spoiling_time_multiplier',             label:'Spoiling Time',   ph:'1.0'},
      {s:'rates', k:'global_item_decomposition_time_multiplier',   label:'Item Decomp',     ph:'1.0'},
      {s:'rates', k:'global_corpse_decomposition_time_multiplier', label:'Corpse Decomp',   ph:'1.0'},
      {s:'rates', k:'fuel_consumption_interval_multiplier',        label:'Fuel Consumption',ph:'1.0'},
    ]},
  ]},
  { group:'Survival', sections:[
    { title:'Player Stats', grid:true, fields:[
      {s:'survival', k:'player_food_drain_multiplier',      label:'Food Drain',     ph:'1.0'},
      {s:'survival', k:'player_water_drain_multiplier',     label:'Water Drain',    ph:'1.0'},
      {s:'survival', k:'player_stamina_drain_multiplier',   label:'Stamina Drain',  ph:'1.0'},
      {s:'survival', k:'player_health_recovery_multiplier', label:'Health Regen',   ph:'1.0'},
    ]},
    { title:'Dino Stats', grid:true, fields:[
      {s:'survival', k:'dino_food_drain_multiplier',        label:'Dino Food Drain',  ph:'1.0'},
      {s:'survival', k:'dino_health_recovery_multiplier',   label:'Dino Health Regen',ph:'1.0'},
    ]},
    { title:'Combat', grid:true, fields:[
      {s:'combat', k:'player_damage_multiplier',        label:'Player Damage',         ph:'1.0', hint:'✦ Rec: 1.5 — players hit harder'},
      {s:'combat', k:'player_resistance_multiplier',    label:'Player Resistance',     ph:'1.0', hint:'✦ Rec: 1.0 — vanilla damage taken'},
      {s:'combat', k:'dino_damage_multiplier',          label:'Wild Dino Damage',      ph:'1.0', hint:'✦ Rec: 0.75 — less brutal early game'},
      {s:'combat', k:'dino_resistance_multiplier',      label:'Wild Dino Resistance',  ph:'1.0', hint:'✦ Rec: 1.0 — vanilla dino toughness'},
      {s:'combat', k:'tamed_dino_damage_multiplier',    label:'Tamed Dino Damage',     ph:'1.0', hint:'✦ Rec: 1.5 — tames hit harder'},
      {s:'combat', k:'tamed_dino_resistance_multiplier',label:'Tamed Dino Resistance', ph:'1.0', hint:'✦ Rec: 0.6 — tames survive longer'},
      {s:'combat', k:'structure_damage_multiplier',     label:'Structure Damage',      ph:'1.0', hint:'✦ Rec: 1.0 — vanilla structure damage'},
    ]},
    { title:'Structures', grid:true, fields:[
      {s:'structures', k:'structure_pickup_time_after_placement',    label:'Pickup Time After Place (s)',   ph:'30'},
      {s:'structures', k:'per_platform_max_structures_multiplier',   label:'Platform Saddle Struct Mult',   ph:'1.0'},
    ]},
  ]},
  { group:'Breeding', sections:[
    { title:'Mating & Hatching', grid:true, fields:[
      {s:'breeding', k:'mating_interval_multiplier', label:'Mating Interval',  ph:'1.0', hint:'✦ Rec: 0.001 — near instant cooldown'},
      {s:'breeding', k:'mating_speed_multiplier',    label:'Mating Speed',     ph:'1.0', hint:'✦ Rec: 1.0 — vanilla speed'},
      {s:'breeding', k:'egg_hatch_speed_multiplier', label:'Egg Hatch Speed',  ph:'1.0', hint:'✦ Rec: 100.0 — fast hatching'},
      {s:'breeding', k:'lay_egg_interval_multiplier',label:'Lay Egg Interval', ph:'1.0', hint:'✦ Rec: 0.5 — eggs more often'},
    ]},
    { title:'Raising & Imprinting', grid:true, fields:[
      {s:'breeding', k:'baby_mature_speed_multiplier',        label:'Mature Speed',        ph:'1.0', hint:'✦ Rec: 50.0 — fast maturation'},
      {s:'breeding', k:'baby_cuddle_interval_multiplier',     label:'Cuddle Interval',     ph:'1.8 ÷ mature speed', rec:'interval'},
      {s:'breeding', k:'baby_cuddle_grace_period_multiplier', label:'Cuddle Grace Period', ph:'max(5.0, mature÷10)', rec:'grace'},
      {s:'breeding', k:'baby_imprint_amount_multiplier',      label:'Imprint Amount',      ph:'20.0',               rec:'imprint'},
    ]},
  ]},
  { group:'Flags', sections:[
    { title:'Player & Camera', grid:true, fields:[
      {s:'flags', k:'allow_third_person',     label:'Allow Third Person',        ph:'false'},
      {s:'flags', k:'show_map_player_location',label:'Show Map Player Location', ph:'true'},
      {s:'combat', k:'allow_hit_markers',       label:'Allow Hit Markers',        ph:'true'},
      {s:'combat', k:'show_floating_damage_text',label:'Floating Damage Numbers', ph:'false'},
    ]},
    { title:'Structures & Decay', grid:true, fields:[
      {s:'flags', k:'always_allow_structure_pickup', label:'Always Allow Structure Pickup', ph:'true'},
      {s:'flags', k:'disable_structure_decay_pve',   label:'Disable Structure Decay PvE',  ph:'false'},
      {s:'flags', k:'disable_dino_decay_pve',        label:'Disable Dino Decay PvE',       ph:'false'},
      {s:'flags', k:'allow_cave_building_pve',       label:'Allow Cave Building PvE',      ph:'false'},
      {s:'flags', k:'force_allow_cave_flyers',       label:'Force Allow Cave Flyers',      ph:'false'},
    ]},
    { title:'Dinos', grid:true, fields:[
      {s:'flags', k:'allow_flyer_carry_pve',      label:'Allow Flyer Carry PvE',      ph:'true'},
      {s:'flags', k:'allow_flyer_speed_leveling', label:'Allow Flyer Speed Leveling', ph:'false'},
    ]},
    { title:'Breeding', grid:true, fields:[
      {s:'flags', k:'allow_anyone_baby_imprint_cuddle',label:'Anyone Can Imprint Cuddle', ph:'false'},
      {s:'flags', k:'require_powered_cryofridge',      label:'Require Powered Cryofridge',ph:'true'},
      {s:'flags', k:'disable_cryo_sickness_pvp',       label:'Disable Cryo Sickness PvP', ph:'false'},
    ]},
    { title:'Downloads & Access', grid:true, fields:[
      {s:'flags', k:'prevent_download_survivors',label:'Prevent Download Survivors', ph:'false'},
      {s:'flags', k:'prevent_download_items',    label:'Prevent Download Items',     ph:'false'},
      {s:'flags', k:'exclusive_join',            label:'Whitelist Only (Exclusive Join)', ph:'false'},
    ]},
  ]},
];

let activeTab = 0;

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function buildTabBar() {
  document.getElementById('tab-bar').innerHTML = SCHEMA.map((g, i) =>
    `<div class="s-tab${i === activeTab ? ' active' : ''}" onclick="switchTab(${i})">${esc(g.group)}</div>`
  ).join('');
}

function switchTab(idx) {
  activeTab = idx;
  document.querySelectorAll('#tab-bar .s-tab').forEach((b, i) => b.classList.toggle('active', i === idx));
  document.querySelectorAll('#form .group').forEach((g, i) => g.classList.toggle('active', i === idx));
}

function render(data) {
  const form = document.getElementById('form');
  form.innerHTML = '';
  SCHEMA.forEach((g, i) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'group' + (i === activeTab ? ' active' : '');
    const multi = g.sections.length > 1;
    g.sections.forEach((sec, si) => {
      if (multi) {
        const h = document.createElement('div');
        h.className = 'sec-head';
        h.textContent = sec.title;
        groupEl.appendChild(h);
      }
      const wrap = document.createElement('div');
      if (sec.grid3) wrap.className = 'grid3';
      else if (sec.grid) wrap.className = 'grid2';
      else wrap.className = 'stack';
      for (const f of sec.fields) {
        const saved = (data[f.s] || {})[f.k] || '';
        const ph    = saved || f.ph || '';
        const d = document.createElement('div');
        let cls = 'field' + (f.wide ? ' wide' : '');
        if (f.visGroup) cls += ' vis-group-' + f.visGroup;
        d.className = cls;
        if (f.visGroup) d.dataset.visGroup = f.visGroup;

        const hint = f.rec
          ? `<span class="breed-hint" data-rec="${f.rec}"></span>`
          : f.hint
            ? `<span class="breed-hint">${esc(f.hint)}</span>`
            : '';

        // Auto-detect boolean fields: explicit type:'checkbox', or placeholder is 'true'/'false'
        const isBoolean = f.type === 'checkbox' || f.ph === 'true' || f.ph === 'false';
        if (isBoolean && f.type !== 'info') {
          // Toggle switch — value stored as "true"/"false" string in config
          const val = (saved || f.ph || 'false').trim().toLowerCase();
          const checked = val === 'true';
          // Wire Discord visibility toggles
          const onchg = (f.s === 'discord' && f.k === 'discord_enabled') ? ' onchange="onDiscordEnabledToggle(this)"'
                      : (f.s === 'discord' && f.k === 'use_bot')         ? ' onchange="onDiscordToggle(this)"'
                      : '';
          d.innerHTML = `<label class="toggle-label">
            <input type="checkbox" class="toggle-cb" data-s="${f.s}" data-k="${f.k}"${checked ? ' checked' : ''}${onchg}>
            <span class="toggle-track"><span class="toggle-thumb"></span></span>
            ${esc(f.label)}
          </label>${hint}`;
        } else if (f.type === 'info') {
          d.innerHTML = `<div class="info-box">${f.html}</div>`;
        } else {
          // Field is always empty — placeholder shows the current config value
          const inputType = f.type === 'password' ? 'password' : 'text';
          const autoComp  = f.type === 'password' ? 'new-password' : 'off';
          d.innerHTML = `<label>${esc(f.label)}</label><input type="${inputType}" autocomplete="${autoComp}" data-s="${f.s}" data-k="${f.k}" value="" placeholder="${esc(ph)}">${hint}`;
        }
        wrap.appendChild(d);
      }
      groupEl.appendChild(wrap);
    });
    form.appendChild(groupEl);
  });
}

function updateBreedHints() {
  const msInput = document.querySelector('input[data-s="breeding"][data-k="baby_mature_speed_multiplier"]');
  if (!msInput) return;
  const ms = parseFloat(msInput.value) || 1.0;
  const recs = {
    interval: ms > 0 ? (1.8 / ms).toFixed(4) : '1.8000',
    grace:    Math.max(5.0, ms / 10).toFixed(1),
    imprint:  '20.0',
  };
  document.querySelectorAll('.breed-hint').forEach(el => {
    const r = el.dataset.rec;
    if (recs[r] !== undefined) el.textContent = '✦ Recommended: ' + recs[r];
  });
}

function wireBreedingHints() {
  const msInput = document.querySelector('input[data-s="breeding"][data-k="baby_mature_speed_multiplier"]');
  if (msInput) {
    msInput.addEventListener('input', updateBreedHints);
    updateBreedHints();
  }
}

// ── Discord webhook / bot toggle ────────────────────────────────────────────
function applyDiscordVisibility(botEnabled) {
  document.querySelectorAll('[data-vis-group="webhook"]').forEach(el => {
    el.style.display = botEnabled ? 'none' : '';
  });
  document.querySelectorAll('[data-vis-group="bot"]').forEach(el => {
    el.style.display = botEnabled ? '' : 'none';
  });
}

function applyDiscordEnabledVisibility(enabled) {
  document.querySelectorAll('[data-vis-group="discord-settings"]').forEach(el => {
    el.style.display = enabled ? '' : 'none';
  });
  // Also hide webhook/bot sub-groups when Discord is fully disabled
  if (!enabled) {
    document.querySelectorAll('[data-vis-group="webhook"],[data-vis-group="bot"]').forEach(el => {
      el.style.display = 'none';
    });
  } else {
    // Re-apply bot/webhook split based on current use_bot value
    const useBotCb = document.querySelector('input[data-s="discord"][data-k="use_bot"]');
    if (useBotCb) applyDiscordVisibility(useBotCb.checked);
  }
}

function onDiscordEnabledToggle(cb) {
  applyDiscordEnabledVisibility(cb.checked);
}

function onDiscordToggle(cb) {
  applyDiscordVisibility(cb.checked);
}

function wireDiscordToggle() {
  const enabledCb = document.querySelector('input[data-s="discord"][data-k="discord_enabled"]');
  const enabled = enabledCb ? enabledCb.checked : false;
  applyDiscordEnabledVisibility(enabled);
  if (enabled) {
    const useBotCb = document.querySelector('input[data-s="discord"][data-k="use_bot"]');
    if (useBotCb) applyDiscordVisibility(useBotCb.checked);
  }
}

async function load() {
  let data = {};
  try {
    const r = await apiFetch('/api/settings');
    if (r) data = await r.json();
    if (!Object.keys(data).length) {
      const dr = await apiFetch('/api/defaults');
      if (dr) data = await dr.json();
      document.getElementById('notice').style.display = 'block';
    }
  } catch(e) { console.error('Settings load error:', e); }
  buildTabBar();
  render(data);
  wireBreedingHints();
  wireDiscordToggle();
}

async function save() {
  const btn = document.getElementById('save-btn');
  btn.textContent = 'Saving…'; btn.disabled = true;
  const payload = {};
  document.querySelectorAll('#form input').forEach(i => {
    const s = i.dataset.s, k = i.dataset.k;
    if (!s || !k) return; // skip inputs without data-s / data-k
    if (!payload[s]) payload[s] = {};
    // Checkboxes store "true"/"false" strings; password fields send exact value
    if (i.type === 'checkbox') {
      payload[s][k] = i.checked ? 'true' : 'false';
    } else if (i.type === 'password') {
      // Only include password fields when the user actually typed something
      if (i.value !== '') payload[s][k] = i.value;
    } else {
      // Use !== '' so a user can intentionally clear a field (e.g. mod_ids,
      // active_event, restart_time). Only fall back to placeholder when the
      // field is completely untouched (empty because we never set i.value).
      payload[s][k] = i.value !== '' ? i.value : i.placeholder;
    }
  });
  // Validate max_active_servers before sending
  const requestedMax = parseInt((payload.limits || {}).max_active_servers || '0', 10);
  if (_ramMaxMaps && requestedMax > 0 && requestedMax > _ramMaxMaps) {
    btn.textContent = 'Save Settings'; btn.disabled = false;
    alert(
      `Cannot set Max Active Maps to ${requestedMax}.\n\n` +
      `Your system RAM only supports ${_ramMaxMaps} map(s) ` +
      `(15 GB overhead + 12 GB per map).\n\n` +
      `Set a value between 1 and ${_ramMaxMaps}, or leave it at 0 for automatic.`
    );
    return;
  }

  const reset = () => { btn.textContent = 'Save Settings'; btn.disabled = false; btn.style.background = ''; btn.className = 'btn'; };
  try {
    const r = await apiFetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r) return; // 401 — apiFetch already redirected to /login
    if (r.ok) {
      document.getElementById('notice').style.display = 'none';
      btn.textContent = 'Saved!'; btn.className = 'btn saved'; btn.disabled = false;
      setTimeout(reset, 2000);
    } else {
      const body = await r.json().catch(() => ({}));
      btn.textContent = 'Error — try again'; btn.style.background = '#7f1d1d'; btn.disabled = false;
      if (body.error) alert('Save failed:\n\n' + body.error);
      console.error('Settings save failed:', r.status, body);
      setTimeout(reset, 2500);
    }
  } catch (e) {
    btn.textContent = 'Error — try again'; btn.style.background = '#7f1d1d'; btn.disabled = false;
    console.error('Settings save error:', e);
    setTimeout(reset, 2500);
  }
}

load();
</script>
</body>
</html>"""


@app.route("/api/restart/controller", methods=["POST"])
@login_required
def restart_controller():
    """Signal the controller to exit cleanly, then re-launch it via BAT."""
    # Write the restart signal file — the controller detects it on its next
    # poll iteration, exits with code 0, and cmd /c closes the window cleanly.
    try:
        with open(CONTROLLER_RESTART_FILE, "w") as f:
            f.write("restart")
    except Exception as exc:
        return jsonify({"error": f"Could not write restart signal: {exc}"}), 500

    bat = os.path.join(ROOT_DIR, "restart_controller.bat")
    try:
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=ROOT_DIR,
        )
    except Exception as exc:
        return jsonify({"error": f"Could not launch restart script: {exc}"}), 500

    return jsonify({"ok": True, "message": "Controller is restarting…"})


@app.route("/api/restart/dashboard", methods=["POST"])
@login_required
def restart_dashboard():
    """Re-launch the dashboard in a new window, then exit this process."""
    bat = os.path.join(ROOT_DIR, "restart_dashboard.bat")
    try:
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=ROOT_DIR,
        )
    except Exception as exc:
        return jsonify({"error": f"Could not restart dashboard: {exc}"}), 500

    # Give the response a moment to reach the browser before we exit.
    # Remove the PID file here rather than relying on the finally block —
    # on Windows, SIGTERM triggers os._exit() which bypasses finally.
    def _delayed_exit():
        import time as _t
        _t.sleep(1)
        try:
            os.remove(DASHBOARD_PID_FILE)
        except FileNotFoundError:
            pass
        os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=_delayed_exit, daemon=True).start()
    return jsonify({"ok": True, "message": "Dashboard is restarting…"})


@app.route("/settings")
@login_required
def settings_page():
    return SETTINGS_PAGE


# ---------------------------------------------------------------------------
# Login page HTML
# ---------------------------------------------------------------------------

LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login — Cluster Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f0f1a; color: #dde1e7; font-family: 'Segoe UI', sans-serif;
       display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.card { background: #1a1f36; border: 1px solid #2a3050; border-radius: 10px;
        padding: 40px 36px; width: 360px; }
h1 { font-size: 22px; color: #93c5fd; margin-bottom: 6px; }
.sub { font-size: 13px; color: #6b7280; margin-bottom: 28px; }
label { display: block; font-size: 13px; color: #9ca3af; margin-bottom: 5px; }
input[type=text], input[type=password] {
  width: 100%; padding: 10px 12px; background: #0f0f1a; border: 1px solid #2a3050;
  border-radius: 6px; color: #dde1e7; font-size: 15px; margin-bottom: 18px; outline: none; }
input:focus { border-color: #3b82f6; }
button { width: 100%; padding: 11px; background: #2563eb; border: none; border-radius: 6px;
         color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; transition: background .2s; }
button:hover { background: #1d4ed8; }
.error { background: #450a0a; border: 1px solid #7f1d1d; border-radius: 6px;
         color: #fca5a5; padding: 10px 12px; font-size: 13px; margin-bottom: 18px; }
</style>
</head>
<body>
<div class="card">
  <h1>🦕 Cluster Dashboard</h1>
  <p class="sub">Sign in to continue</p>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST" action="/login">
    <input type="hidden" name="next" value="{{ next }}">
    <label>Username</label>
    <input type="text" name="username" autocomplete="username" autofocus>
    <label>Password</label>
    <input type="password" name="password" autocomplete="current-password">
    <button type="submit">Sign In</button>
  </form>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET"])
def login_page():
    if not _auth_enabled() or session.get("logged_in"):
        return redirect("/")
    next_url = _safe_next(request.args.get("next", "/"))
    return render_template_string(LOGIN_PAGE, error=None, next=next_url)


@app.route("/login", methods=["POST"])
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    next_url = request.form.get("next", "/")
    if _check_credentials(username, password):
        session["logged_in"] = True
        session.permanent = True
        return redirect(_safe_next(next_url))
    return render_template_string(LOGIN_PAGE, error="Invalid username or password.", next=next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    import socket
    import datetime

    # Write Python PID so restart scripts can find and close the CMD window
    try:
        with open(DASHBOARD_PID_FILE, "w") as _pf:
            _pf.write(str(os.getpid()))
    except Exception:
        pass

    # Set Flask secret key (auto-generated and saved to config on first run)
    app.secret_key = _ensure_secret_key()
    app.permanent_session_lifetime = datetime.timedelta(hours=24)

    # Report auth state — credentials are set by the setup wizard or Settings page.
    # Never auto-create default credentials here; if no password_hash is present,
    # the dashboard opens without a login page (user opted out during wizard).
    _auth_cfg = configparser.RawConfigParser()
    try:
        _auth_cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    _has_hash = bool(_auth_cfg.get("auth", "password_hash", fallback="").strip())
    if _has_hash:
        _stored_user = _auth_cfg.get("auth", "username", fallback="admin")
        print(f"Dashboard login enabled — username: {_stored_user}")
    else:
        print("Dashboard login disabled — set a password in Settings to enable it.")

    port = _get_web_port()
    try:
        # Probe the port before Flask tries to bind — gives a clear error message
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", port))
    except OSError:
        print(f"ERROR: Port {port} is already in use.")
        print(f"       Either stop the process using port {port}, or change")
        print(f"       'web_status_port' in controller/config.ini to a free port.")
        input("\nPress Enter to close...")
        raise SystemExit(1)
    print(f"Dashboard running at http://localhost:{port}")
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    finally:
        try:
            os.remove(DASHBOARD_PID_FILE)
        except FileNotFoundError:
            pass
