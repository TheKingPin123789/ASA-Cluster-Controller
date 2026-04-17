import os
import json
import logging
import configparser
from flask import Flask, jsonify, request, render_template_string

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
STATUS_JSON     = os.path.join(BASE_DIR, "cluster_status.json")
LOG_FILE        = os.path.join(BASE_DIR, "controller.log")
ADMIN_LOG_FILE  = os.path.join(BASE_DIR, "admin_log.txt")
ADMIN_CMD       = os.path.join(BASE_DIR, "admin_commands.txt")
CONFIG_FILE     = os.path.join(BASE_DIR, "config.ini")
WHITELIST_FILE      = os.path.join(BASE_DIR, "whitelist.txt")
SEEN_PLAYERS_FILE     = os.path.join(BASE_DIR, "seen_players.json")
COMMAND_CATEGORIES_FILE = os.path.join(BASE_DIR, "command_categories.json")
ADMIN_LIST_FILE         = os.path.join(BASE_DIR, "admin_list.txt")

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

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
.card { background: #1a1f36; border: 1px solid #2a3050; border-radius: 6px; padding: 9px 11px; min-width: 130px; flex: 0 1 150px; max-width: 155px; transition: border-color .2s; }
.card.online   { border-color: #16a34a; }
.card.starting { border-color: #d97706; }
.card.offline  { opacity: .55; }
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

/* Settings window */
.settings-section { margin-top: 10px; }
.settings-section .sec-title { margin-bottom: 6px; padding-bottom:3px; border-bottom:1px solid #2a3050; }
.settings-row { margin-bottom: 5px; }
.settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:5px; }

/* Responsive layout */
@media (max-width: 720px) {
  #main { flex-direction: column; overflow-y: auto; overflow-x: hidden; }
  #left { width: 100% !important; min-width: 0 !important; max-height: 55vh; }
  #right { min-height: 300px; }
  #cards .card { flex: 1 1 120px; }
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
  </div>
</div>

<div id="cards"><!-- injected by JS --></div>

<div id="main">
  <!-- LEFT: controls / whitelist / settings tabs -->
  <div id="left">
    <div class="tab-bar">
      <div class="tab-btn active"  onclick="switchTab('controls')">Controls</div>
      <div class="tab-btn"         onclick="switchTab('whitelist')">Commands</div>
    </div>

    <!-- Controls tab -->
    <div id="tab-controls" class="tab-panel active">
      <button id="btn-start-cluster" class="btn btn-green btn-full" onclick="cmd('start cluster')">Start Cluster</button>

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
        <div class="sec-title">Whitelisted Players</div>
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

<!-- Player detail modal -->
<div id="player-modal" onclick="if(event.target===this)closePlayerModal()">
  <div id="player-modal-box">
    <span class="pm-close" onclick="closePlayerModal()">✕</span>
    <div style="display:flex; align-items:center; gap:8px;">
      <span id="pm-status-dot" class="ap-dot"></span>
      <div class="pm-title" id="pm-name"></div>
    </div>
    <div class="pm-row"><div class="pm-label">Steam ID</div><div class="pm-value mono" id="pm-id"></div></div>
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
    const r = await fetch('/api/command_categories');
    if (!r.ok) return;
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
  await fetch('/api/command_categories', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command: val, tier})
  });
  loadCmdCategories();
}

async function removeCmd(c) {
  await fetch('/api/command_categories', {
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
  setTimeout(loadWlPanel, 600);
}

async function loadAdminPanel() {
  try {
    const r = await fetch('/api/admin_list');
    if (!r.ok) return;
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
  await fetch('/api/admin_list', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'add', id})
  });
  inp.value = '';
  loadAdminPanel();
}

async function removeAdminPlayer(id) {
  await fetch('/api/admin_list', {
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
function cmd(command) {
  fetch('/api/command', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command})
  });
}

// Send from console input — echo locally, then wait for admin_log to show response
function sendConsole() {
  const el = document.getElementById('cmd-input');
  const v = el.value.trim();
  if (!v) return;
  echoConsole('> ' + v);
  cmd(v);
  el.value = '';
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
    const r = await fetch('/api/whitelist');
    if (!r.ok) return;
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
  setTimeout(loadWlPanel, 600);
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
    const r = await fetch('/api/seen_players');
    if (!r.ok) return;
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
      map: isOnline ? mapDisplay : mapDisplay,
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
    const r = await fetch('/api/whitelist');
    const wlData = await r.json();
    onWl = (wlData.entries || []).includes(id);
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
            onclick="cmd('whitelist add ${safeId}'); renderPmWl('${safeId}', true); setTimeout(loadWlPanel,600)">+WL Add</button>
    <button class="btn btn-red btn-sm"   ${!onWl ? 'disabled' : ''}
            onclick="cmd('whitelist remove ${safeId}'); renderPmWl('${safeId}', false); setTimeout(loadWlPanel,600)">−WL Remove</button>
  `;
}

function closePlayerModal() {
  document.getElementById('player-modal').classList.remove('open');
}

// ── Server cards ─────────────────────────────────────────────────────────────
function cardAction(key, action) {
  if (action === 'start')   cmd('start '   + key);
  else if (action === 'stop')    cmd('stop '    + key);
  else if (action === 'restart') cmd('restart ' + key);
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
  startBtn.className = 'btn btn-full ' + (anyActive ? 'btn-gray' : 'btn-green');

  const runCount = Object.values(data.servers).filter(s => s.is_running).length;
  document.getElementById('status-line').textContent =
    runCount + ' server(s) online \u00b7 ' + (data.total_players||0) + ' player(s)';

  const container = document.getElementById('cards');
  for (const [key, s] of Object.entries(data.servers)) {
    const cls   = s.is_running ? 'online' : (s.is_starting ? 'starting' : 'offline');
    const label = s.is_running ? 'Online' : (s.is_starting ? 'Starting' : 'Offline');
    const players = s.is_running ? s.player_count + ' / ' + (data.max_players || 70) + ' player(s)' : '';

    if (cardEls[key]) {
      const c = cardEls[key];
      c.className = 'card ' + cls;
      c.querySelector('.badge').className = 'badge ' + cls;
      c.querySelector('.badge').textContent = label;
      c.querySelector('.card-players').textContent = players;
      c.querySelector('.btn-start').disabled   = s.is_running || s.is_starting;
      c.querySelector('.btn-stop').disabled    = !s.is_running;
      c.querySelector('.btn-restart').disabled = !s.is_running;
    } else {
      const c = document.createElement('div');
      c.className = 'card ' + cls;
      c.dataset.key = key;
      c.innerHTML = `
        <div class="card-head">
          <span class="card-name">${s.display_name}</span>
          <span class="badge ${cls}">${label}</span>
        </div>
        <div class="card-players">${players}</div>
        <div class="card-btns">
          <button class="btn btn-bright-green  btn-sm btn-start"   onclick="cardAction('${key}','start')"   ${s.is_running||s.is_starting?'disabled':''}>Start</button>
          <button class="btn btn-bright-red    btn-sm btn-stop"    onclick="cardAction('${key}','stop')"    ${!s.is_running?'disabled':''}>Stop</button>
          <button class="btn btn-bright-orange btn-sm btn-restart" onclick="cardAction('${key}','restart')" ${!s.is_running?'disabled':''}>Restart</button>
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
  if (!timerTarget) { el.textContent = ''; return; }
  const secs = Math.max(0, Math.round(timerTarget - Date.now() / 1000));
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  el.textContent = timerLabel + ' ' + h + ':' + m + ':' + s;
  el.style.color = secs < 900 ? '#f87171' : secs < 3600 ? '#fbbf24' : timerColor;
}

setInterval(tickTimer, 1000);

// ── Polling ───────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) return;
    const data = await r.json();
    if (data.error) return;
    renderCards(data);
    renderPlayerList(data);
    setTimerFromStatus(data);
  } catch(e) {}
}

async function pollLogs() {
  try {
    const r = await fetch('/api/logs?n=300');
    if (!r.ok) return;
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
    const r = await fetch('/api/admin_logs?n=200');
    if (!r.ok) return;
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
def index():
    return render_template_string(HTML)


@app.route("/api/status")
def get_status():
    try:
        with open(STATUS_JSON, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "status not available yet"}), 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/logs")
def get_logs():
    n = request.args.get("n", 300, type=int)
    try:
        with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return jsonify({"lines": [ln.rstrip() for ln in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as exc:
        return jsonify({"lines": [], "error": str(exc)})


@app.route("/api/admin_logs")
def get_admin_logs():
    n = request.args.get("n", 200, type=int)
    try:
        with open(ADMIN_LOG_FILE, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return jsonify({"lines": [ln.rstrip() for ln in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as exc:
        return jsonify({"lines": [], "error": str(exc)})


@app.route("/api/whitelist")
def get_whitelist():
    try:
        if not os.path.exists(WHITELIST_FILE):
            return jsonify({"entries": []})
        with open(WHITELIST_FILE, encoding="utf-8") as f:
            entries = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        return jsonify({"entries": entries})
    except Exception as exc:
        return jsonify({"entries": [], "error": str(exc)})


@app.route("/api/command", methods=["POST"])
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
def get_settings():
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    result = {section: dict(cfg.items(section)) for section in cfg.sections()}
    return jsonify(result)


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(silent=True) or {}
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except Exception:
        pass
    for section, kvs in data.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for key, value in kvs.items():
            cfg.set(section, key, str(value))
    try:
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
def get_command_categories():
    return jsonify({"categories": _read_categories(), "available": AVAILABLE_COMMANDS})


@app.route("/api/command_categories", methods=["POST"])
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
def get_admin_list():
    return jsonify({"entries": _read_list_file(ADMIN_LIST_FILE)})


@app.route("/api/admin_list", methods=["POST"])
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
def get_seen_players():
    try:
        if not os.path.exists(SEEN_PLAYERS_FILE):
            return jsonify({"players": {}})
        with open(SEEN_PLAYERS_FILE, encoding="utf-8") as f:
            return jsonify({"players": json.load(f)})
    except Exception as exc:
        return jsonify({"players": {}, "error": str(exc)})


@app.route("/api/defaults")
def get_defaults():
    return jsonify({
        "cluster": {
            "cluster_name": "MyCluster",
            "rcon_password": "ChangeMe123",
            "default_map": "ragnarok",
        },
        "network": {
            "rcon_host": "127.0.0.1",
        },
        "paths": {
            "server_root": r"C:\ASA_Cluster\asa_server",
            "cluster_dir": r"C:\ASA_Cluster\asa_server\cluster",
            "steamcmd_path": r"C:\ASA_Cluster\SteamCMD\steamcmd.exe",
        },
        "performance": {
            "max_active_servers": "3",
            "max_players": "70",
        },
        "timers": {
            "poll_seconds": "5",
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
        },
        "schedule": {
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
<div class="hint">Changes require a controller restart.</div>
<div class="tab-bar" id="tab-bar"></div>
<div class="tab-content">
  <div id="form"></div>
</div>
<div class="footer"><button class="btn" id="save-btn" onclick="save()">Save Settings</button></div>
</div>
<script>
const SCHEMA = [
  { group:'Cluster', sections:[
    { title:'Identity', fields:[
      {s:'cluster',    k:'cluster_name',   label:'Cluster Name',   ph:'e.g. MyCluster'},
      {s:'cluster',    k:'rcon_password',  label:'RCON Password',  ph:'e.g. ChangeMe123'},
      {s:'cluster',    k:'default_map',    label:'Default Map',    ph:'ragnarok'},
      {s:'network',    k:'rcon_host',      label:'RCON Host',      ph:'127.0.0.1'},
    ]},
    { title:'Paths', fields:[
      {s:'paths', k:'server_root',   label:'Server Root',   ph:'C:\\ASA_Cluster\\asa_server',              wide:true},
      {s:'paths', k:'cluster_dir',   label:'Cluster Dir',   ph:'C:\\ASA_Cluster\\asa_server\\cluster',     wide:true},
      {s:'paths', k:'steamcmd_path', label:'SteamCMD Path', ph:'C:\\ASA_Cluster\\SteamCMD\\steamcmd.exe', wide:true},
    ]},
    { title:'Mods & Events', fields:[
      {s:'mods',  k:'mod_ids',      label:'Mod IDs (comma-separated Steam IDs)', ph:'e.g. 12345,67890', wide:true},
      {s:'mods',  k:'crossplay',    label:'Enable Crossplay (Epic + Steam)',      ph:'false'},
      {s:'world', k:'active_event', label:'Active Event',                         ph:'e.g. FearEvolved, WinterWonderland, TurkeyTrial'},
    ]},
  ]},
  { group:'Server', sections:[
    { title:'Limits', grid:true, fields:[
      {s:'limits', k:'max_active_servers',     label:'Max Active Maps',        ph:'3'},
      {s:'limits', k:'max_players',            label:'Max Players per Map',    ph:'70'},
      {s:'limits', k:'max_tamed_dinos',        label:'Max Tamed Dinos (total)',ph:'5000'},
      {s:'limits', k:'max_personal_tamed_dinos',label:'Max Tamed (per player)',ph:'40'},
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
    ]},
  ]},
  { group:'World & Rates', sections:[
    { title:'World', grid:true, fields:[
      {s:'world', k:'day_time_speed_scale',               label:'Day Speed',                ph:'1.0',  hint:'✦ Rec: 1.0 — vanilla day length'},
      {s:'world', k:'night_time_speed_scale',             label:'Night Speed',              ph:'1.0',  hint:'✦ Rec: 3.0 — shorter nights'},
      {s:'world', k:'dino_count_multiplier',              label:'Wild Dino Count',          ph:'1.0',  hint:'✦ Rec: 1.0–1.5 — more wildlife'},
      {s:'world', k:'resources_respawn_period_multiplier',label:'Resources Respawn',        ph:'1.0',  hint:'✦ Rec: 0.5 — faster respawn (lower = quicker)'},
    ]},
    { title:'Experience & Gathering', grid3:true, fields:[
      {s:'rates', k:'xp_multiplier',             label:'XP',               ph:'1.0',               hint:'✦ Rec: 1.5 — less grind'},
      {s:'rates', k:'harvest_amount_multiplier', label:'Harvest Amount',   ph:'1.0',               hint:'✦ Rec: 5.0 — less farming'},
      {s:'rates', k:'taming_speed_multiplier',   label:'Taming Speed',     ph:'1.0',               hint:'✦ Rec: 5.0 — reasonable tame times'},
      {s:'rates', k:'difficulty_offset',         label:'Difficulty Offset',ph:'1.0  (max lvl 150)',hint:'✦ Rec: 1.0 — enables max lvl 150 dinos'},
      {s:'rates', k:'item_stack_size_multiplier',label:'Item Stack Size',  ph:'1.0',               hint:'✦ Rec: 5.0 — less inventory juggling'},
      {s:'rates', k:'crop_growth_speed_multiplier',label:'Crop Growth',    ph:'1.0',               hint:'✦ Rec: 5.0 — faster crops'},
    ]},
    { title:'Loot Quality', grid3:true, fields:[
      {s:'rates', k:'loot_quality_multiplier',               label:'General Loot',    ph:'1.0', hint:'✦ Rec: 3.0 — better drops'},
      {s:'rates', k:'fishing_loot_quality_multiplier',       label:'Fishing Loot',    ph:'1.0', hint:'✦ Rec: 3.0 — worth fishing'},
      {s:'rates', k:'supply_crate_loot_quality_multiplier',  label:'Supply Crate',    ph:'1.0', hint:'✦ Rec: 3.0 — rewarding drops'},
    ]},
    { title:'Decay & Fuel', grid3:true, fields:[
      {s:'rates', k:'global_spoiling_time_multiplier',             label:'Spoiling Time',   ph:'1.0', hint:'✦ Rec: 1.0 — vanilla spoiling'},
      {s:'rates', k:'global_item_decomposition_time_multiplier',   label:'Item Decomp',     ph:'1.0', hint:'✦ Rec: 1.0 — vanilla item decay'},
      {s:'rates', k:'global_corpse_decomposition_time_multiplier', label:'Corpse Decomp',   ph:'1.0', hint:'✦ Rec: 1.0 — vanilla corpse decay'},
      {s:'rates', k:'fuel_consumption_interval_multiplier',        label:'Fuel Consumption',ph:'1.0', hint:'✦ Rec: 5.0 — less refuelling'},
    ]},
  ]},
  { group:'Survival', sections:[
    { title:'Player Stats', grid:true, fields:[
      {s:'survival', k:'player_food_drain_multiplier',      label:'Food Drain',     ph:'1.0', hint:'✦ Rec: 1.0 — vanilla hunger'},
      {s:'survival', k:'player_water_drain_multiplier',     label:'Water Drain',    ph:'1.0', hint:'✦ Rec: 1.0 — vanilla thirst'},
      {s:'survival', k:'player_stamina_drain_multiplier',   label:'Stamina Drain',  ph:'1.0', hint:'✦ Rec: 1.0 — vanilla stamina'},
      {s:'survival', k:'player_health_recovery_multiplier', label:'Health Regen',   ph:'1.0', hint:'✦ Rec: 1.0 — vanilla health regen'},
    ]},
    { title:'Dino Stats', grid:true, fields:[
      {s:'survival', k:'dino_food_drain_multiplier',        label:'Dino Food Drain',  ph:'1.0', hint:'✦ Rec: 1.0 — vanilla dino hunger'},
      {s:'survival', k:'dino_health_recovery_multiplier',   label:'Dino Health Regen',ph:'1.0', hint:'✦ Rec: 1.0 — vanilla dino regen'},
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
        h.className = 'sec-head' + (si === 0 ? ' sec-head:first-child' : '');
        h.textContent = sec.title;
        groupEl.appendChild(h);
      }
      const wrap = document.createElement('div');
      if (sec.grid3) wrap.className = 'grid3';
      else if (sec.grid) wrap.className = 'grid2';
      else wrap.className = 'stack';
      for (const f of sec.fields) {
        const val = esc((data[f.s] || {})[f.k] || '');
        const d = document.createElement('div');
        d.className = 'field' + (f.wide ? ' wide' : '');
        const hint = f.rec
          ? `<span class="breed-hint" data-rec="${f.rec}"></span>`
          : f.hint
            ? `<span class="breed-hint">${esc(f.hint)}</span>`
            : '';
        d.innerHTML = `<label>${esc(f.label)}</label><input type="text" data-s="${f.s}" data-k="${f.k}" value="${val}" placeholder="${esc(f.ph||'')}">${hint}`;
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

async function load() {
  let data = {};
  try {
    const r = await fetch('/api/settings');
    data = await r.json();
    if (!Object.keys(data).length) {
      const dr = await fetch('/api/defaults');
      data = await dr.json();
      document.getElementById('notice').style.display = 'block';
    }
  } catch(e) {}
  buildTabBar();
  render(data);
  wireBreedingHints();
}

async function save() {
  const payload = {};
  document.querySelectorAll('#form input').forEach(i => {
    const s = i.dataset.s, k = i.dataset.k;
    if (!payload[s]) payload[s] = {};
    payload[s][k] = i.value;
  });
  const r = await fetch('/api/settings', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const btn = document.getElementById('save-btn');
  if (r.ok) {
    document.getElementById('notice').style.display = 'none';
    btn.textContent = 'Saved!'; btn.className = 'btn saved';
    setTimeout(() => { btn.textContent = 'Save Settings'; btn.className = 'btn'; }, 2000);
  } else {
    btn.textContent = 'Error — try again'; btn.style.background = '#7f1d1d';
    setTimeout(() => { btn.textContent = 'Save Settings'; btn.style.background = ''; }, 2500);
  }
}

load();
</script>
</body>
</html>"""


@app.route("/settings")
def settings_page():
    return SETTINGS_PAGE


if __name__ == "__main__":
    import socket
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
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
