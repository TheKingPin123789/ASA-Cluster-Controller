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
ALLOWED_COMMANDS_FILE = os.path.join(BASE_DIR, "allowed_commands.txt")

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cluster Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f0f1a; color: #dde1e7; font-family: 'Segoe UI', sans-serif; font-size: 14px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* Header */
#header { background: #1a1f36; padding: 8px 14px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2a3050; flex-shrink: 0; }
#header .title { font-weight: 700; font-size: 16px; color: #93c5fd; }
#status-line { font-size: 12px; color: #6b7280; }

/* Server cards */
#cards { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #2a3050; flex-shrink: 0; }
.card { background: #1a1f36; border: 1px solid #2a3050; border-radius: 6px; padding: 9px 11px; min-width: 150px; flex: 1 1 150px; max-width: 220px; transition: border-color .2s; }
.card.online   { border-color: #16a34a; }
.card.starting { border-color: #d97706; }
.card.offline  { opacity: .55; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.card-name { font-weight: 600; font-size: 12px; }
.badge { padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
.badge.online   { background: #14532d; color: #4ade80; }
.badge.starting { background: #78350f; color: #fbbf24; }
.badge.offline  { background: #1f2937; color: #6b7280; }
.card-players { font-size: 11px; color: #6b7280; margin-bottom: 6px; min-height: 14px; }
.card-btns { display: flex; gap: 4px; }

/* Main layout */
#main { display: flex; flex: 1; overflow: hidden; gap: 8px; padding: 8px 12px; }
#left  { width: 290px; min-width: 290px; display: flex; flex-direction: column; overflow: hidden; }
#right { flex: 1; display: flex; flex-direction: column; overflow: hidden; gap: 8px; }

/* Tabs */
.tab-bar { display: flex; gap: 2px; flex-shrink: 0; }
.tab-btn { padding: 5px 8px; flex: 1; text-align: center; background: #1a1f36; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 12px; color: #9ca3af; }
.tab-btn.active { background: #222840; color: #fff; border-color: #3b4a7a; }
.tab-panel { display: none; flex: 1; background: #222840; border: 1px solid #3b4a7a; border-radius: 0 4px 4px 4px; padding: 10px; overflow-y: auto; flex-direction: column; gap: 8px; }
.tab-panel.active { display: flex; }

/* Buttons */
.btn { padding: 5px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; transition: opacity .15s; }
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
.btn-sm { padding: 3px 7px; font-size: 11px; }

/* Section dividers */
.sec { border-top: 1px solid #3b4a7a; padding-top: 8px; }
.sec-title { font-size: 10px; color: #4b5563; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.row   { display: flex; gap: 5px; align-items: flex-end; }

/* Form controls */
input[type=text], select, textarea {
  background: #131825; border: 1px solid #2a3050; color: #dde1e7;
  padding: 5px 8px; border-radius: 4px; font-size: 12px; width: 100%;
  font-family: inherit;
}
select { cursor: pointer; }
label { font-size: 11px; color: #6b7280; display: block; margin-bottom: 3px; }

/* Player list */
#player-list { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; max-height: 200px; overflow-y: auto; }
.pl-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 5px; }
.pl-info  { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.pl-name  { font-size: 12px; color: #dde1e7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-id    { font-family: Consolas, monospace; font-size: 10px; color: #4b5563; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-map   { font-size: 10px; color: #6b7280; white-space: nowrap; flex-shrink: 0; }
.pl-empty { font-size: 11px; color: #4b5563; font-style: italic; padding: 4px 2px; }

/* Whitelist panel */
#wl-panel { display: none; margin-top: 6px; flex-direction: column; gap: 3px; max-height: 200px; overflow-y: auto; }
#wl-panel.open { display: flex; }
.wl-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 6px; }
.wl-info  { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.wl-name  { font-size: 11px; color: #dde1e7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wl-id    { font-family: Consolas, monospace; font-size: 10px; color: #a3e635; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wl-empty { font-size: 11px; color: #4b5563; font-style: italic; padding: 4px 2px; }

/* Right panel: tabbed console / log */
#right-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #222840; border: 1px solid #3b4a7a; border-radius: 0 4px 4px 4px; }
#console-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 8px; }
#console-out  { flex: 1; background: #0a0a12; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; padding: 6px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #93c5fd; white-space: pre-wrap; word-break: break-all; }
#console-input-bar { display: flex; gap: 5px; background: #131825; border: 1px solid #2a3050; border-radius: 0 0 4px 4px; padding: 5px 7px; flex-shrink: 0; }
#console-input-bar input { flex: 1; background: transparent; border: none; outline: none; color: #dde1e7; font-size: 12px; font-family: Consolas, monospace; }
#console-input-bar input::placeholder { color: #4b5563; }
.quick-cmds { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; flex-shrink: 0; }
#log-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 8px; }
#log { flex: 1; background: #0a0a12; border: 1px solid #2a3050; border-radius: 4px; padding: 8px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #a3e635; white-space: pre-wrap; word-break: break-all; }
.log-header { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 4px; flex-shrink: 0; }

/* All players panel */
#ap-panel { display: none; margin-top: 6px; flex-direction: column; gap: 3px; max-height: 250px; overflow-y: auto; }
#ap-panel.open { display: flex; }
.ap-entry { display: flex; align-items: center; background: #131825; border: 1px solid #2a3050; border-radius: 3px; padding: 3px 7px; gap: 6px; cursor: pointer; }
.ap-entry:hover { border-color: #3b4a7a; }
.ap-dot  { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.ap-dot.online  { background: #4ade80; }
.ap-dot.offline { background: #374151; }
.ap-name { font-size: 12px; color: #dde1e7; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ap-map  { font-size: 10px; color: #6b7280; white-space: nowrap; flex-shrink: 0; }

/* Player modal */
#player-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:1000; align-items:center; justify-content:center; }
#player-modal.open { display:flex; }
#player-modal-box { background:#1a1f36; border:1px solid #3b4a7a; border-radius:8px; padding:20px 22px; min-width:340px; max-width:420px; width:90%; display:flex; flex-direction:column; gap:12px; }
.pm-title { font-size:15px; font-weight:700; color:#93c5fd; }
.pm-row { display:flex; flex-direction:column; gap:2px; }
.pm-label { font-size:10px; color:#4b5563; text-transform:uppercase; letter-spacing:.06em; }
.pm-value { font-size:13px; color:#dde1e7; word-break:break-all; }
.pm-value.mono { font-family:Consolas,monospace; font-size:12px; color:#a3e635; }
.pm-actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
.pm-close { align-self:flex-end; cursor:pointer; font-size:18px; color:#4b5563; line-height:1; margin-top:-8px; }

/* Settings form */
.settings-section { margin-top: 6px; }
.settings-section .sec-title { margin-bottom: 4px; }
.settings-row { margin-bottom: 5px; }
</style>
</head>
<body>

<div id="header">
  <span class="title" id="page-title">Cluster Dashboard</span>
  <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px;">
    <span id="status-line">Connecting...</span>
    <span id="restart-timer" style="font-size:12px; font-family:Consolas,monospace;"></span>
  </div>
</div>

<div id="cards"><!-- injected by JS --></div>

<div id="main">
  <!-- LEFT: controls / whitelist / settings tabs -->
  <div id="left">
    <div class="tab-bar">
      <div class="tab-btn active"  onclick="switchTab('controls')">Controls</div>
      <div class="tab-btn"         onclick="switchTab('whitelist')">Whitelist</div>
      <div class="tab-btn"         onclick="switchTab('settings')">Settings</div>
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
          <span id="ap-chevron" style="font-size:10px; color:#4b5563;">▶ show</span>
        </div>
        <div id="ap-panel"></div>
      </div>
    </div>

    <!-- Whitelist tab -->
    <div id="tab-whitelist" class="tab-panel">
      <!-- !start whitelist toggle -->
      <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 0 8px;">
        <span style="font-size:12px; color:#9ca3af;">Require whitelist for !start</span>
        <button id="btn-wl" class="btn btn-gray btn-sm" onclick="toggleWhitelist()">...</button>
      </div>

      <!-- Player commands -->
      <div class="sec">
        <div class="sec-title">Player Commands</div>
        <div id="wl-cmd-list" style="display:flex; flex-direction:column; gap:3px; margin-bottom:6px;"></div>
        <div style="display:flex; gap:5px;">
          <select id="wl-cmd-select" style="flex:1;">
            <option value="">Add command...</option>
          </select>
          <button class="btn btn-green btn-sm" onclick="addWlCmd()">Add</button>
        </div>
      </div>

      <!-- Whitelisted players -->
      <div class="sec">
        <div style="display:flex; align-items:center; justify-content:space-between; cursor:pointer; margin-bottom:4px;" onclick="toggleWlPanel()">
          <div class="sec-title" style="margin-bottom:0;">Whitelisted Players</div>
          <span id="wl-chevron" style="font-size:10px; color:#4b5563;">▶ show</span>
        </div>
        <div id="wl-panel"></div>
        <div style="display:flex; gap:5px; margin-top:6px;">
          <input type="text" id="wl-add-input" placeholder="Steam ID to add..." style="flex:1;">
          <button class="btn btn-green btn-sm" onclick="addWlPlayer()">Add</button>
        </div>
      </div>
    </div>

    <!-- Settings tab -->
    <div id="tab-settings" class="tab-panel">
      <div id="setup-notice" style="display:none; background:#78350f; color:#fdba74; padding:7px 9px; border-radius:4px; font-size:12px; flex-shrink:0;">
        No config.ini found — defaults loaded. Fill in your values and click Save to create it.
        The controller will start automatically once saved.
      </div>
      <div style="font-size:11px; color:#4b5563; flex-shrink:0;">Edits config.ini. Changes require a controller restart.</div>
      <div id="settings-form" style="flex:1; overflow-y:auto;"></div>
      <button class="btn btn-blue btn-full" style="margin-top:6px; flex-shrink:0;" onclick="saveSettings()">Save Settings</button>
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
            <span style="color:#4b5563; font-size:12px; font-family:Consolas;">$</span>
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
            <label style="display:flex; align-items:center; gap:4px; cursor:pointer; font-size:11px; color:#4b5563;">
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
const LEFT_TABS = ['controls','whitelist','settings'];
function switchTab(name) {
  document.querySelectorAll('#left .tab-btn').forEach((b, i) => {
    b.classList.toggle('active', LEFT_TABS[i] === name);
  });
  document.querySelectorAll('#left .tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  if (name === 'settings')  loadSettings();
  if (name === 'whitelist') loadWlTab();
}

// ── Whitelist tab ─────────────────────────────────────────────────────────────
async function loadWlTab() {
  await Promise.all([loadWlCmds(), loadWlPanel()]);
}

async function loadWlCmds() {
  try {
    const r = await fetch('/api/allowed_commands');
    if (!r.ok) return;
    const data = await r.json();
    renderWlCmds(data.enabled || [], data.available || []);
  } catch(e) {}
}

function renderWlCmds(enabled, available) {
  const list = document.getElementById('wl-cmd-list');
  if (!enabled.length) {
    list.innerHTML = '<span class="wl-empty">No commands enabled</span>';
  } else {
    list.innerHTML = enabled.map(c =>
      `<div class="wl-entry">
         <div class="wl-info"><span class="wl-id" style="color:#93c5fd;">${escHtml(c)}</span></div>
         <button class="btn btn-red btn-sm" onclick="removeWlCmd('${escHtml(c)}')">Remove</button>
       </div>`
    ).join('');
  }
  // Populate add dropdown with commands not yet enabled
  const sel = document.getElementById('wl-cmd-select');
  sel.innerHTML = '<option value="">Add command...</option>';
  for (const c of available) {
    if (!enabled.includes(c)) {
      const opt = document.createElement('option');
      opt.value = c; opt.textContent = c;
      sel.appendChild(opt);
    }
  }
}

async function addWlCmd() {
  const sel = document.getElementById('wl-cmd-select');
  const val = sel.value;
  if (!val) return;
  await fetch('/api/allowed_commands', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'add', command: val})
  });
  loadWlCmds();
}

async function removeWlCmd(c) {
  await fetch('/api/allowed_commands', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'remove', command: c})
  });
  loadWlCmds();
}

async function addWlPlayer() {
  const inp = document.getElementById('wl-add-input');
  const id  = inp.value.trim();
  if (!id) return;
  cmd('whitelist add ' + id);
  inp.value = '';
  setTimeout(loadWlPanel, 600);
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
let wlPanelOpen = false;
let apPanelOpen = false;
let _onlinePlayerNames = {};   // id -> name, refreshed each status poll
let _playerModalCache  = {};   // id -> {name,id,map,mapKey,isOnline,last_seen}

function toggleWlPanel() {
  wlPanelOpen = !wlPanelOpen;
  const panel   = document.getElementById('wl-panel');
  const chevron = document.getElementById('wl-chevron');
  panel.classList.toggle('open', wlPanelOpen);
  chevron.textContent = wlPanelOpen ? '▼ hide' : '▶ show';
  if (wlPanelOpen) loadWlPanel();
}

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
    const players = s.is_running ? s.player_count + ' player(s)' : '';

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

// ── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    let data = await r.json();
    const notice = document.getElementById('setup-notice');
    const isEmpty = Object.keys(data).length === 0;
    if (isEmpty) {
      const dr = await fetch('/api/defaults');
      data = await dr.json();
      if (notice) notice.style.display = 'block';
    } else {
      if (notice) notice.style.display = 'none';
    }
    renderSettingsForm(data);
  } catch(e) {}
}

function renderSettingsForm(data) {
  const form = document.getElementById('settings-form');
  form.innerHTML = '';
  for (const [section, kvs] of Object.entries(data)) {
    const div = document.createElement('div');
    div.className = 'settings-section';
    div.innerHTML = '<div class="sec-title">[' + section + ']</div>';
    for (const [k, v] of Object.entries(kvs)) {
      const row = document.createElement('div');
      row.className = 'settings-row';
      row.innerHTML = `<label>${k}</label><input type="text" data-section="${section}" data-key="${k}" value="${String(v).replace(/"/g,'&quot;')}">`;
      div.appendChild(row);
    }
    form.appendChild(div);
  }
}

async function saveSettings() {
  const payload = {};
  document.querySelectorAll('#settings-form input').forEach(inp => {
    const s = inp.dataset.section, k = inp.dataset.key;
    if (!payload[s]) payload[s] = {};
    payload[s][k] = inp.value;
  });
  const r = await fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const notice = document.getElementById('setup-notice');
  if (r.ok) {
    if (notice) notice.style.display = 'none';
    const btn = document.querySelector('#tab-settings .btn-blue');
    const orig = btn.textContent;
    btn.textContent = 'Saved!';
    btn.classList.replace('btn-blue','btn-green');
    setTimeout(() => { btn.textContent = orig; btn.classList.replace('btn-green','btn-blue'); }, 2000);
  }
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


AVAILABLE_COMMANDS = ["!help", "!status", "!start"]

def _read_allowed_commands():
    if not os.path.exists(ALLOWED_COMMANDS_FILE):
        return list(AVAILABLE_COMMANDS)
    try:
        with open(ALLOWED_COMMANDS_FILE, encoding="utf-8") as f:
            cmds = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        return cmds if cmds else list(AVAILABLE_COMMANDS)
    except Exception:
        return list(AVAILABLE_COMMANDS)


@app.route("/api/allowed_commands", methods=["GET"])
def get_allowed_commands():
    enabled = _read_allowed_commands()
    return jsonify({"enabled": enabled, "available": AVAILABLE_COMMANDS})


@app.route("/api/allowed_commands", methods=["POST"])
def post_allowed_commands():
    data    = request.get_json(silent=True) or {}
    action  = data.get("action", "")
    command = data.get("command", "").strip().lower()
    if not command:
        return jsonify({"error": "missing command"}), 400
    enabled = set(_read_allowed_commands())
    if action == "add":
        enabled.add(command)
    elif action == "remove":
        enabled.discard(command)
    else:
        return jsonify({"error": "action must be add or remove"}), 400
    try:
        with open(ALLOWED_COMMANDS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(enabled)) + "\n")
        return jsonify({"ok": True, "enabled": sorted(enabled)})
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
        },
        "breeding": {
            "baby_mature_speed_multiplier": "1.0",
            "baby_cuddle_interval_multiplier": "1.8",
            "baby_cuddle_grace_period_multiplier": "1.0",
            "baby_imprint_amount_multiplier": "20.0",
        },
    })


if __name__ == "__main__":
    print(f"Dashboard running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
