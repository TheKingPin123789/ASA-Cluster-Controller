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
WHITELIST_FILE  = os.path.join(BASE_DIR, "whitelist.txt")

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ASA Cluster Dashboard</title>
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
.tab-btn { padding: 5px 13px; background: #1a1f36; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 12px; color: #9ca3af; }
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
.pl-name { font-size: 12px; color: #dde1e7; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl-map  { font-size: 10px; color: #6b7280; white-space: nowrap; flex-shrink: 0; }
.pl-empty { font-size: 11px; color: #4b5563; font-style: italic; padding: 4px 2px; }

/* Right panel: console + log stacked */
#console-wrap { flex-shrink: 0; display: flex; flex-direction: column; }
#console-out  { height: 500px; background: #0a0a12; border: 1px solid #2a3050; border-bottom: none; border-radius: 4px 4px 0 0; padding: 6px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #93c5fd; white-space: pre-wrap; word-break: break-all; }
#console-input-bar { display: flex; gap: 5px; background: #131825; border: 1px solid #2a3050; border-radius: 0 0 4px 4px; padding: 5px 7px; }
#console-input-bar input { flex: 1; background: transparent; border: none; outline: none; color: #dde1e7; font-size: 12px; font-family: Consolas, monospace; }
#console-input-bar input::placeholder { color: #4b5563; }
.console-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; flex-shrink: 0; }
.console-header span { font-size: 11px; color: #4b5563; }
.quick-cmds { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; flex-shrink: 0; }

/* Log panel */
#log-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#log { flex: 1; background: #0a0a12; border: 1px solid #2a3050; border-radius: 4px; padding: 8px 10px; overflow-y: auto; font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #a3e635; white-space: pre-wrap; word-break: break-all; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; flex-shrink: 0; }
.panel-header span { font-size: 11px; color: #4b5563; }

/* Settings form */
.settings-section { margin-top: 6px; }
.settings-section .sec-title { margin-bottom: 4px; }
.settings-row { margin-bottom: 5px; }
</style>
</head>
<body>

<div id="header">
  <span class="title">ASA Cluster Dashboard</span>
  <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px;">
    <span id="status-line">Connecting...</span>
    <span id="restart-timer" style="font-size:12px; font-family:Consolas,monospace;"></span>
  </div>
</div>

<div id="cards"><!-- injected by JS --></div>

<div id="main">
  <!-- LEFT: controls / settings tabs -->
  <div id="left">
    <div class="tab-bar">
      <div class="tab-btn active" onclick="switchTab('controls')">Controls</div>
      <div class="tab-btn" onclick="switchTab('settings')">Settings</div>
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
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
          <div class="sec-title" style="margin-bottom:0;">Online Players</div>
          <div style="display:flex; align-items:center; gap:5px;">
            <span style="font-size:10px; color:#4b5563;">!start whitelist:</span>
            <button id="btn-wl" class="btn btn-gray btn-sm" onclick="toggleWhitelist()">...</button>
          </div>
        </div>
        <div id="player-list"><span class="pl-empty">No players online</span></div>
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

  <!-- RIGHT: admin console + log -->
  <div id="right">

    <!-- Admin console -->
    <div id="console-wrap">
      <div class="console-header">
        <span>Admin Console</span>
      </div>
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

    <!-- Full log -->
    <div id="log-wrap">
      <div class="panel-header">
        <span>Controller Log</span>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer; font-size:11px; color:#4b5563;">
          <input type="checkbox" id="auto-scroll" checked onchange="autoScroll=this.checked">
          Auto-scroll
        </label>
      </div>
      <div id="log"></div>
    </div>

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

// ── Tabs ────────────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach((b, i) => {
    b.classList.toggle('active', ['controls','settings'][i] === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  if (name === 'settings') loadSettings();
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

// ── Player list ───────────────────────────────────────────────────────────────
function renderPlayerList(data) {
  const el = document.getElementById('player-list');
  const players = [];
  for (const [key, s] of Object.entries(data.servers || {})) {
    for (const p of (s.player_list || [])) {
      players.push({ name: p.name, id: p.id, map: MAP_DISPLAY[key] || key });
    }
  }
  if (!players.length) {
    el.innerHTML = '<span class="pl-empty">No players online</span>';
    return;
  }
  el.innerHTML = players.map(p =>
    `<div class="pl-entry">
       <span class="pl-name" title="${escHtml(p.name)}">${escHtml(p.name)}</span>
       <span class="pl-map">${escHtml(p.map)}</span>
       <button class="btn btn-green btn-sm" title="Add to whitelist"  onclick="cmd('whitelist add ${escHtml(p.id)}')">+WL</button>
       <button class="btn btn-red   btn-sm" title="Remove from whitelist" onclick="cmd('whitelist remove ${escHtml(p.id)}')">-WL</button>
     </div>`
  ).join('');
}

// ── Server cards ─────────────────────────────────────────────────────────────
function cardAction(key, action) {
  if (action === 'start')   cmd('start '   + key);
  else if (action === 'stop')    cmd('stop '    + key);
  else if (action === 'restart') cmd('restart ' + key);
}

const cardEls = {};
function renderCards(data) {
  if (!data || !data.servers) return;

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
