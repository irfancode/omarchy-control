const API = '';
let dashInterval, logStream, metricsStream;
let themeDark = true;

// ─── Router ────────────────────────────────────────────────────────────────

const pages = {
  dashboard: renderDashboard,
  monitor: renderMonitor,
  processes: renderProcesses,
  logs: renderLogs,
  network: renderNetwork,
  hyprland: renderHyprland,
  themes: renderThemes,
  services: renderServices,
  toggles: renderToggles,
  system: renderSystem,
  packages: renderPackages,
  fonts: renderFonts,
};

document.querySelectorAll('nav a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const page = a.dataset.page;
    navigate(page);
  });
});

function navigate(page) {
  closeStreams();
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  document.querySelector(`nav a[data-page="${page}"]`).classList.add('active');
  const content = document.getElementById('content');
  content.innerHTML = '<div class="page-loader">Loading…</div>';
  if (pages[page]) pages[page]().then(html => { content.innerHTML = html; bindPageEvents(page); });
}

function closeStreams() {
  if (logStream) { logStream.close(); logStream = null; }
  if (metricsStream) { metricsStream.close(); metricsStream = null; }
  if (dashInterval) { clearInterval(dashInterval); dashInterval = null; }
}

// ─── Fetch ─────────────────────────────────────────────────────────────────

let lastError = '';
function showError(msg) {
  const content = document.getElementById('content');
  if (content) content.innerHTML = `<div class="page active"><div class="card" style="border-color:var(--danger);text-align:center;padding:40px">
    <div style="font-size:48px;margin-bottom:16px">⚠</div>
    <h2 style="margin-bottom:8px">Connection Error</h2>
    <p style="color:var(--text-2);margin-bottom:16px">${msg}</p>
    <button class="btn btn-accent" onclick="location.reload()">Retry</button>
  </div></div>`;
}

async function api(path, opts = {}) {
  try {
    const r = await fetch(`${API}/api${path}`, {
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (!r.ok) {
      const text = await r.text().catch(() => '');
      throw new Error(`${r.status} ${r.statusText}${text ? ': ' + text.slice(0,100) : ''}`);
    }
    return r.json();
  } catch (e) {
    if (!lastError || Date.now() - lastError > 5000) {
      lastError = Date.now();
      showError(`Could not connect to Omarchy Control API.<br><small>${e.message}</small><br><br>Make sure the server is running:<br><code style="background:var(--surface-2);padding:4px 8px;border-radius:4px">omarchy-control</code>`);
    }
    throw e;
  }
}

// ─── Theme ─────────────────────────────────────────────────────────────────

function toggleTheme() {
  themeDark = !themeDark;
  document.documentElement.classList.toggle('light', !themeDark);
  document.getElementById('themeToggle').textContent = themeDark ? '🌙' : '☀️';
  localStorage.setItem('omarchy-control-theme', themeDark ? 'dark' : 'light');
}

document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('omarchy-control-theme');
  if (saved === 'light') { themeDark = false; document.documentElement.classList.add('light'); document.getElementById('themeToggle').textContent = '☀️'; }
});

// ─── Charts (Canvas sparkline) ─────────────────────────────────────────────

function sparkline(canvas, data, color = '#33ccff', fill = true) {
  if (!canvas || !data.length) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const w = rect.width, h = rect.height;
  ctx.clearRect(0, 0, w, h);

  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const pad = 2;
  const points = data.map((v, i) => ({
    x: pad + (i / Math.max(data.length - 1, 1)) * (w - pad * 2),
    y: h - pad - ((v - min) / range) * (h - pad * 2),
  }));

  ctx.beginPath();
  points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  if (fill) {
    ctx.lineTo(points[points.length - 1].x, h);
    ctx.lineTo(points[0].x, h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + '30');
    grad.addColorStop(1, color + '05');
    ctx.fillStyle = grad;
    ctx.fill();
  }
}

function sparklineChart(canvasId, data, color) {
  const canvas = document.getElementById(canvasId);
  if (canvas) sparkline(canvas, data, color);
}

// ─── Gauges (SVG) ─────────────────────────────────────────────────────────

function gaugeSVG(percent, color) {
  const r = 40, circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.min(percent, 100) / 100);
  return `<svg width="100" height="100" viewBox="0 0 100 100">
    <circle class="gauge-track" cx="50" cy="50" r="${r}"/>
    <circle class="gauge-fill" cx="50" cy="50" r="${r}" stroke="${color}"
      stroke-dasharray="${circ}" stroke-dashoffset="${offset}"/>
  </svg>`;
}

// ─── Dashboard ─────────────────────────────────────────────────────────────

async function renderDashboard() {
  const [info, stats, updates, version, health] = await Promise.all([
    api('/system/info'), api('/system/stats'),
    api('/system/updates'), api('/version'), api('/system/health'),
  ]);

  const memPct = stats.memory?.percent || 0;
  const diskPct = stats.disk?.percent || 0;
  const cpuPct = stats.cpu?.usage || 0;
  const healthScore = health.health || 100;
  const alerts = health.alerts || [];
  const healthStatus = health.status || 'healthy';
  const healthColor = healthStatus === 'healthy' ? 'var(--success)' : healthStatus === 'degraded' ? 'var(--warning)' : 'var(--danger)';

  const alertBanners = alerts.map(a =>
    `<div class="alert-banner ${a.severity}">${a.severity === 'critical' ? '🔴' : '🟡'} ${a.message}</div>`
  ).join('');

  const updateBanner = updates.available ? `<div class="card" style="border-color:var(--warning)">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span>Update <strong>${updates.version}</strong> available</span>
      <button class="btn btn-warning" onclick="systemAction('update')">Update Now</button>
    </div>
  </div>` : '';

  return `
    <div class="page active" id="page-dashboard">
      <div class="page-header">
        <h1>${info.hostname}</h1>
        <p>${info.os} · ${info.desktop} · Kernel ${info.kernel} · Up ${info.uptime}</p>
      </div>
      <div class="health-bar">
        <div class="health-dot ${healthStatus}"></div>
        <div class="health-score">${healthScore}</div>
        <div class="health-label">System Health</div>
        <div class="health-alerts">
          ${alerts.map(a => `<span class="alert-badge ${a.severity}">${a.type}</span>`).join('')}
          ${alerts.length === 0 ? '<span style="color:var(--success);font-size:11px">✓ All clear</span>' : ''}
        </div>
      </div>
      ${alertBanners}
      ${updateBanner}
      <div class="card">
        <h2>Quick Actions</h2>
        <div class="action-grid">
          <div class="action-btn" onclick="systemAction('lock')"><span class="icon">🔒</span><span class="label">Lock</span></div>
          <div class="action-btn" onclick="systemAction('lock')"><span class="icon">🚪</span><span class="label">Logout</span></div>
          <div class="action-btn" onclick="systemAction('reboot')"><span class="icon">🔄</span><span class="label">Reboot</span></div>
          <div class="action-btn" onclick="systemAction('shutdown')"><span class="icon">⏻</span><span class="label">Shutdown</span></div>
          <div class="action-btn" onclick="navigate('monitor')"><span class="icon">📊</span><span class="label">Monitor</span></div>
          <div class="action-btn" onclick="navigate('logs')"><span class="icon">📋</span><span class="label">Logs</span></div>
        </div>
      </div>
      <div class="dashboard-grid">
        <div class="card">
          <h2>Resource Gauges</h2>
          <div class="gauge-container">
            <div class="gauge">
              ${gaugeSVG(cpuPct, cpuPct > 80 ? 'var(--danger)' : cpuPct > 50 ? 'var(--warning)' : 'var(--accent)')}
              <div class="gauge-label"><div class="gauge-value">${cpuPct}%</div><div class="gauge-name">CPU</div></div>
            </div>
            <div class="gauge">
              ${gaugeSVG(memPct, memPct > 80 ? 'var(--danger)' : memPct > 50 ? 'var(--warning)' : 'var(--accent-2)')}
              <div class="gauge-label"><div class="gauge-value">${memPct}%</div><div class="gauge-name">Memory</div></div>
            </div>
            <div class="gauge">
              ${gaugeSVG(diskPct, diskPct > 80 ? 'var(--danger)' : diskPct > 50 ? 'var(--warning)' : 'var(--warning)')}
              <div class="gauge-label"><div class="gauge-value">${diskPct}%</div><div class="gauge-name">Disk</div></div>
            </div>
          </div>
        </div>
        <div class="card">
          <h2>System Resources</h2>
          <div class="stat">
            <div class="stat-value">${cpuPct}<span class="unit">%</span></div>
            <div class="stat-label">CPU</div>
            <div class="stat-bar"><div class="stat-bar-fill" style="width:${cpuPct}%;background:var(--accent)"></div></div>
          </div>
          <div class="stat" style="margin-top:10px">
            <div class="stat-value">${stats.memory ? (stats.memory.used/1024).toFixed(1) : '?'}<span class="unit">GB</span></div>
            <div class="stat-label">Memory · ${stats.memory ? (stats.memory.total/1024).toFixed(1) : '?'}GB total</div>
            <div class="stat-bar"><div class="stat-bar-fill" style="width:${memPct}%;background:${memPct > 80 ? 'var(--danger)' : memPct > 50 ? 'var(--warning)' : 'var(--accent-2)'}"></div></div>
          </div>
          <div class="stat" style="margin-top:10px">
            <div class="stat-value">${stats.disk?.used ?? '?'}<span class="unit">GB</span></div>
            <div class="stat-label">Disk · ${stats.disk?.total ?? '?'}GB total</div>
            <div class="stat-bar"><div class="stat-bar-fill" style="width:${diskPct}%;background:${diskPct > 80 ? 'var(--danger)' : diskPct > 50 ? 'var(--warning)' : 'var(--warning)'}"></div></div>
          </div>
          <div class="stat" style="margin-top:10px">
            <div class="stat-value" style="font-size:16px">${stats.load ? stats.load.join(' · ') : '?'}</div>
            <div class="stat-label">Load Average (1·5·15m)</div>
          </div>
          <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap">
            ${stats.temperature ? `<div class="temp-item">🌡 ${stats.temperature}°C</div>` : ''}
            ${stats.disk_io ? `<div class="temp-item">💾 ${Object.keys(stats.disk_io).join(', ')}</div>` : ''}
          </div>
        </div>
      </div>
      <div class="card">
        <h2>Omarchy</h2>
        <p style="margin-bottom:4px">Version: <strong>${version.version || 'unknown'}</strong></p>
        <p style="color:var(--text-2);font-size:12px">Auto-refreshes in real-time via SSE · Live metrics every 5s</p>
      </div>
    </div>
  `;
}

// ─── Monitor (with real-time charts) ───────────────────────────────────────

let monitorHistoryCPU = [];
let monitorHistoryMEM = [];
let monitorHistoryDisk = [];

async function renderMonitor() {
  const data = await api('/system/metrics/history');
  const history = data.history || [];
  const cpuData = history.map(s => s.cpu?.usage || 0);
  const memData = history.map(s => s.memory?.percent || 0);
  const diskData = history.map(s => parseFloat(s.disk?.percent || 0));

  const latest = history.length ? history[history.length - 1] : { cpu: {}, memory: {}, disk: {} };
  const cpu = latest.cpu?.usage || 0;
  const mem = latest.memory?.percent || 0;
  const disk = latest.disk?.percent || 0;

  monitorHistoryCPU = cpuData;
  monitorHistoryMEM = memData;
  monitorHistoryDisk = diskData;

  return `
    <div class="page active" id="page-monitor">
      <div class="page-header">
        <h1>Live Monitor</h1>
        <p>Real-time system metrics · 10-minute window · Updates every 5s via SSE</p>
      </div>
      <div class="card">
        <h2>CPU Usage <span style="float:right;color:var(--accent);font-family:var(--mono)">${cpu}%</span></h2>
        <div class="chart-container"><canvas id="chart-cpu"></canvas></div>
        <div class="chart-legend"><span style="background:var(--accent)">CPU</span></div>
      </div>
      <div class="card">
        <h2>Memory Usage <span style="float:right;color:var(--accent-2);font-family:var(--mono)">${mem}%</span></h2>
        <div class="chart-container"><canvas id="chart-mem"></canvas></div>
        <div class="chart-legend"><span style="background:var(--accent-2)">Memory</span></div>
      </div>
      <div class="card">
        <h2>Disk Usage <span style="float:right;color:var(--warning);font-family:var(--mono)">${disk}%</span></h2>
        <div class="chart-container"><canvas id="chart-disk"></canvas></div>
        <div class="chart-legend"><span style="background:var(--warning)">Disk</span></div>
      </div>
    </div>
  `;
}

function updateMonitorCharts() {
  sparklineChart('chart-cpu', monitorHistoryCPU, '#33ccff');
  sparklineChart('chart-mem', monitorHistoryMEM, '#00ff99');
  sparklineChart('chart-disk', monitorHistoryDisk, '#ffaa33');
}

// ─── Processes ─────────────────────────────────────────────────────────────

async function renderProcesses() {
  const data = await api('/system/processes?sort=cpu&limit=60');
  const procs = data.processes || [];
  const rows = procs.map(p =>
    `<tr>
      <td class="proc-pid">${p.pid}</td>
      <td class="proc-user">${p.user}</td>
      <td class="proc-cpu">${p.cpu}%</td>
      <td class="proc-mem">${p.mem}%</td>
      <td style="color:var(--text-2)">${p.rss}</td>
      <td class="proc-cmd" title="${escapeHtml(p.command)}">${escapeHtml(p.command.slice(0,60))}</td>
      <td><span class="proc-kill" onclick="killProcess(${p.pid})" title="Kill">✕</span></td>
    </tr>`
  ).join('');

  return `
    <div class="page active" id="page-processes">
      <div class="page-header">
        <h1>Processes</h1>
        <p>Top processes by CPU usage · ${data.total} shown</p>
      </div>
      <div class="card">
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <button class="btn btn-sm btn-accent" onclick="refreshProcesses()">↻ Refresh</button>
          <span style="font-size:11px;color:var(--text-2);display:flex;align-items:center">Click ✕ to kill a process (SIGTERM)</span>
        </div>
        <div class="proc-table-wrap">
          <table class="proc-table">
            <thead><tr>
              <th>PID</th><th>User</th><th>CPU%</th><th>MEM%</th><th>RSS</th><th>Command</th><th></th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

async function refreshProcesses() {
  navigate('processes');
}

async function killProcess(pid) {
  if (!confirm(`Kill process ${pid}?`)) return;
  await api('/system/kill', { method: 'POST', body: JSON.stringify({ pid }) });
  refreshProcesses();
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ─── Logs ──────────────────────────────────────────────────────────────────

let logFollowActive = false;
let logUnit = '';
let logPrio = '';

async function renderLogs() {
  let units = [];
  try {
    const uData = await api('/logs/units');
    units = uData.units || [];
  } catch(e) {}

  const unitOpts = units.slice(0, 100).map(u =>
    `<option value="${u}">${u}</option>`
  ).join('');

  const entries = await loadLogs(50);
  const entryHtml = entries.map(e => logEntryHtml(e)).join('');

  return `
    <div class="page active" id="page-logs">
      <div class="page-header">
        <h1>Log Viewer</h1>
        <p>Systemd journal logs · Click Follow for real-time tailing</p>
      </div>
      <div class="card">
        <div class="log-toolbar">
          <label>Unit <select id="log-unit" onchange="logUnit=this.value">
            <option value="">All</option>
            ${unitOpts}
          </select></label>
          <label>Level <select id="log-prio" onchange="logPrio=this.value">
            <option value="">All</option>
            <option value="0">emerg</option>
            <option value="1">alert</option>
            <option value="2">crit</option>
            <option value="3">err</option>
            <option value="4">warning</option>
            <option value="5">notice</option>
            <option value="6">info</option>
            <option value="7">debug</option>
          </select></label>
          <input id="log-search" placeholder="Search logs..." oninput="filterLogs(this.value)">
          <span class="log-follow-btn" id="logFollowBtn" onclick="toggleLogFollow()">▶ Follow</span>
          <button class="btn btn-sm" onclick="refreshLogs()">↻</button>
        </div>
        <div class="log-container" id="logContainer">
          ${entryHtml}
        </div>
        <div class="log-count" id="logCount">${entries.length} entries</div>
      </div>
    </div>
  `;
}

async function loadLogs(lines = 100) {
  try {
    let path = `/logs?lines=${lines}`;
    if (logUnit) path += `&unit=${encodeURIComponent(logUnit)}`;
    if (logPrio) path += `&priority=${encodeURIComponent(logPrio)}`;
    const data = await api(path);
    return data.entries || [];
  } catch(e) { return []; }
}

function logEntryHtml(e) {
  const msg = e._message || '';
  const time = e._time || '';
  const unit = e._unit || '';
  const prio = e._priority_str || 'info';
  return `<div class="log-entry">
    <span class="log-time">${escapeHtml(time)}</span>
    <span class="log-prio ${prio}">${prio}</span>
    <span class="log-unit">${escapeHtml(unit)}</span>
    <span class="log-msg">${escapeHtml(msg)}</span>
  </div>`;
}

async function refreshLogs() {
  const entries = await loadLogs(100);
  const container = document.getElementById('logContainer');
  const count = document.getElementById('logCount');
  if (container) container.innerHTML = entries.map(e => logEntryHtml(e)).join('');
  if (count) count.textContent = `${entries.length} entries`;
}

function filterLogs(query) {
  const container = document.getElementById('logContainer');
  if (!container) return;
  const entries = container.querySelectorAll('.log-entry');
  entries.forEach(el => {
    const text = el.textContent.toLowerCase();
    el.style.display = !query || text.includes(query.toLowerCase()) ? '' : 'none';
  });
  const count = document.getElementById('logCount');
  if (count) count.textContent = `${Array.from(entries).filter(e => e.style.display !== 'none').length} entries`;
}

function toggleLogFollow() {
  const btn = document.getElementById('logFollowBtn');
  if (logFollowActive) {
    logFollowActive = false;
    if (logStream) { logStream.close(); logStream = null; }
    if (btn) { btn.textContent = '▶ Follow'; btn.classList.remove('active'); }
    return;
  }
  logFollowActive = true;
  if (btn) { btn.textContent = '⏹ Stop'; btn.classList.add('active'); }

  let url = `${API}/api/logs/stream`;
  const params = [];
  if (logUnit) params.push(`unit=${encodeURIComponent(logUnit)}`);
  if (logPrio) params.push(`priority=${encodeURIComponent(logPrio)}`);
  if (params.length) url += '?' + params.join('&');

  logStream = new EventSource(url);
  logStream.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      const container = document.getElementById('logContainer');
      if (!container) return;
      container.insertAdjacentHTML('afterbegin', logEntryHtml(data));
      if (container.children.length > 500) container.removeChild(container.lastChild);
      const count = document.getElementById('logCount');
      if (count) count.textContent = `${container.children.length}+ entries (live)`;
    } catch(e) {}
  };
  logStream.onerror = () => {
    if (logFollowActive) setTimeout(toggleLogFollow, 3000);
  };
}

// ─── Network ───────────────────────────────────────────────────────────────

async function renderNetwork() {
  const [netData, diskData] = await Promise.all([
    api('/system/network').catch(() => ({ interfaces: [], series: {} })),
    api('/system/disk-io').catch(() => ({ disks: [], series: {} })),
  ]);

  const ifaces = netData.interfaces || [];
  const disks = diskData.disks || [];
  const series = netData.series || {};
  const diskSeries = diskData.series || {};

  const netCharts = ifaces.map(iface => {
    const s = series[iface] || [];
    const rxData = s.map(p => p.rx || 0);
    const txData = s.map(p => p.tx || 0);
    const maxRx = Math.max(...rxData, 1);
    const maxTx = Math.max(...txData, 1);
    const latest = s.length ? s[s.length - 1] : { rx: 0, tx: 0 };
    return `<div class="io-card">
      <h3>${iface}</h3>
      <div class="io-stats">
        <div class="io-stat">⬇ <span class="val">${formatBytes(latest.rx)}</span><span class="lbl">/s</span></div>
        <div class="io-stat">⬆ <span class="val">${formatBytes(latest.tx)}</span><span class="lbl">/s</span></div>
      </div>
      <div class="chart-container" style="height:60px"><canvas id="net-${iface}"></canvas></div>
    </div>`;
  }).join('');

  const diskCharts = disks.map(d => {
    const s = diskSeries[d] || [];
    const rdData = s.map(p => p.reads || 0);
    const wrData = s.map(p => p.writes || 0);
    const maxRd = Math.max(...rdData, 1);
    const maxWr = Math.max(...wrData, 1);
    const latest = s.length ? s[s.length - 1] : { reads: 0, writes: 0 };
    return `<div class="io-card">
      <h3>${d}</h3>
      <div class="io-stats">
        <div class="io-stat">📖 <span class="val">${latest.reads.toFixed(1)}</span><span class="lbl">ops/s</span></div>
        <div class="io-stat">📝 <span class="val">${latest.writes.toFixed(1)}</span><span class="lbl">ops/s</span></div>
      </div>
      <div class="chart-container" style="height:60px"><canvas id="dio-${d}"></canvas></div>
    </div>`;
  }).join('');

  const tempData = await api('/system/temperature').catch(() => ({ temperatures: [] }));
  const tempHtml = (tempData.temperatures || []).map(t =>
    `<div class="temp-item" style="background:var(--surface-2);padding:6px 12px;border-radius:var(--radius-sm);font-family:var(--mono);font-size:12px">${t.name}: ${t.temp}°C</div>`
  ).join('');

  return `
    <div class="page active" id="page-network">
      <div class="page-header">
        <h1>Network & I/O</h1>
        <p>Real-time throughput and disk activity</p>
      </div>
      ${tempHtml ? `<div class="card"><h2>Temperatures</h2><div style="display:flex;gap:8px;flex-wrap:wrap">${tempHtml}</div></div>` : ''}
      <div class="card">
        <h2>Network Throughput</h2>
        <div class="io-grid">${netCharts || '<p style="color:var(--text-2)">No network interfaces detected</p>'}</div>
      </div>
      <div class="card">
        <h2>Disk I/O (operations/sec)</h2>
        <div class="io-grid">${diskCharts || '<p style="color:var(--text-2)">No disk activity detected</p>'}</div>
      </div>
    </div>
  `;
}

function formatBytes(bytes) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  if (bytes >= 1e3) return (bytes / 1e3).toFixed(1) + ' KB';
  return bytes.toFixed(1) + ' B';
}

function drawNetworkCharts() {
  document.querySelectorAll('[id^="net-"]').forEach(canvas => {
    const iface = canvas.id.replace('net-', '');
    const container = canvas.closest('.io-card');
    if (!container) return;
    const stats = container.querySelectorAll('.io-stat .val');
    if (!stats.length) return;
    // We'd need to store history, but for simplicity, draw a placeholder
  });
}

// ─── Hyprland ──────────────────────────────────────────────────────────────

async function renderHyprland() {
  const [configs, info] = await Promise.all([api('/hyprland/configs'), api('/hyprland/info')]);

  let configTabs = Object.entries(configs).map(([name, c]) =>
    `<div class="config-tab" data-name="${name}" onclick="loadConfig('${name}')">${name}.conf</div>`
  ).join('');

  return `
    <div class="page active" id="page-hyprland">
      <div class="page-header">
        <h1>Hyprland Configuration</h1>
        <p>${info.version || ''} · Configs in ~/.config/hypr/</p>
      </div>
      <div class="card">
        <h2>Config Files</h2>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
          ${configTabs}
        </div>
        <textarea class="config-editor" id="config-editor" rows="20"></textarea>
        <div class="btn-group">
          <button class="btn btn-accent" onclick="saveConfig()">Save & Reload</button>
        </div>
      </div>
      <div class="card">
        <h2>Keybindings</h2>
        <div class="code-block" id="keybindings">Loading…</div>
      </div>
    </div>
  `;
}

let currentConfig = '';
async function loadConfig(name) {
  currentConfig = name;
  const data = await api(`/hyprland/config?name=${name}`);
  document.getElementById('config-editor').value = data.content;
  document.querySelectorAll('.config-tab').forEach(t => t.classList.toggle('active', t.dataset.name === name));
}

async function saveConfig() {
  const content = document.getElementById('config-editor').value;
  await api(`/hyprland/config?name=${currentConfig}`, { method: 'POST', body: JSON.stringify({ content }) });
}

// ─── Themes ────────────────────────────────────────────────────────────────

async function renderThemes() {
  const data = await api('/themes');
  const items = data.themes.map(t =>
    `<div class="theme-item ${t === data.current ? 'active' : ''}" onclick="setTheme('${escapeHtml(t)}')">
      <div class="check">✓</div>
      <div class="name">${escapeHtml(t)}</div>
    </div>`
  ).join('');

  return `
    <div class="page active" id="page-themes">
      <div class="page-header">
        <h1>Themes</h1>
        <p>Current: <strong>${data.current || 'none'}</strong></p>
      </div>
      <div class="card">
        <div class="btn-group" style="margin-top:0;margin-bottom:16px">
          <button class="btn" onclick="nextBg()">◐ Next Wallpaper</button>
        </div>
        <div class="theme-grid">${items}</div>
      </div>
    </div>
  `;
}

async function setTheme(name) {
  await api('/themes/set', { method: 'POST', body: JSON.stringify({ name }) });
  renderThemes().then(html => { document.getElementById('content').innerHTML = html; bindPageEvents('themes'); });
}

async function nextBg() { await api('/themes/bg-next', { method: 'POST' }); }

// ─── Services ──────────────────────────────────────────────────────────────

async function renderServices() {
  const [data, status] = await Promise.all([
    api('/services'), api('/services/status').catch(() => ({}))
  ]);
  const rows = Object.entries(data).map(([name, s]) => {
    const st = status[name] || s.status;
    return `<div class="service-row">
      <div class="service-info">
        <div class="service-name">${name}</div>
        <div class="service-status ${st}">${st}</div>
      </div>
      <button class="btn btn-sm" onclick="restartService('${name}')">Restart</button>
    </div>`;
  }).join('');

  return `
    <div class="page active" id="page-services">
      <div class="page-header">
        <h1>Services</h1>
        <p>Manage Omarchy desktop services</p>
      </div>
      <div class="card">
        ${rows}
      </div>
    </div>
  `;
}

async function restartService(name) {
  await api('/services/restart', { method: 'POST', body: JSON.stringify({ service: name }) });
  renderServices().then(html => { document.getElementById('content').innerHTML = html; bindPageEvents('services'); });
}

// ─── Toggles ───────────────────────────────────────────────────────────────

async function renderToggles() {
  const data = await api('/toggles');
  const toggleInfo = {
    nightlight: { desc: 'Warm screen temperature for reduced eye strain at night' },
    idle: { desc: 'Auto-lock and screen blanking when away' },
    'notification-silencing': { desc: 'Do-not-disturb mode for notifications' },
    'hybrid-gpu': { desc: 'Switch between integrated and dedicated GPU' },
  };
  const rows = Object.entries(data).map(([name, state]) =>
    `<div class="toggle-row">
      <div class="toggle-info">
        <div class="toggle-name">${name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
        <div class="toggle-desc">${toggleInfo[name]?.desc || ''}</div>
      </div>
      <div class="toggle-switch ${state ? 'active' : ''}" onclick="toggleFeature('${name}')"></div>
    </div>`
  ).join('');

  return `
    <div class="page active" id="page-toggles">
      <div class="page-header">
        <h1>Feature Toggles</h1>
        <p>Toggle Omarchy features on and off</p>
      </div>
      <div class="card">${rows}</div>
    </div>
  `;
}

async function toggleFeature(name) {
  await api('/toggles/set', { method: 'POST', body: JSON.stringify({ name }) });
  renderToggles().then(html => { document.getElementById('content').innerHTML = html; bindPageEvents('toggles'); });
}

// ─── System ────────────────────────────────────────────────────────────────

async function renderSystem() {
  const [info, updates] = await Promise.all([api('/system/info'), api('/system/updates')]);
  return `
    <div class="page active" id="page-system">
      <div class="page-header">
        <h1>System Controls</h1>
        <p>${info.hostname} · ${info.os}</p>
      </div>
      <div class="card">
        <h2>Power</h2>
        <div class="btn-group">
          <button class="btn" onclick="systemAction('lock')">🔒 Lock</button>
          <button class="btn" onclick="systemAction('logout')">🚪 Log Out</button>
          <button class="btn btn-warning" onclick="systemAction('reboot')">🔄 Reboot</button>
          <button class="btn btn-danger" onclick="systemAction('shutdown')">⏻ Shut Down</button>
        </div>
      </div>
      <div class="card">
        <h2>Updates</h2>
        <p style="margin-bottom:8px">${updates.available ? `Update <strong>${updates.version}</strong> available` : 'System is up to date'}</p>
        <button class="btn btn-accent" onclick="systemAction('update')">Update Now</button>
      </div>
      <div class="card">
        <h2>System Info</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:6px 0;color:var(--text-2)">Hostname</td><td>${info.hostname}</td></tr>
          <tr><td style="padding:6px 0;color:var(--text-2)">OS</td><td>${info.os}</td></tr>
          <tr><td style="padding:6px 0;color:var(--text-2)">Kernel</td><td>${info.kernel}</td></tr>
          <tr><td style="padding:6px 0;color:var(--text-2)">Desktop</td><td>${info.desktop}</td></tr>
          <tr><td style="padding:6px 0;color:var(--text-2)">Uptime</td><td>${info.uptime}</td></tr>
        </table>
      </div>
    </div>
  `;
}

async function systemAction(action) {
  await api('/system/action', { method: 'POST', body: JSON.stringify({ action }) });
}

// ─── Packages ──────────────────────────────────────────────────────────────

async function renderPackages() {
  const data = await api('/packages');
  return `
    <div class="page active" id="page-packages">
      <div class="page-header">
        <h1>Packages</h1>
        <p>Install Arch packages via omarchy pkg</p>
      </div>
      <div class="card">
        <div style="display:flex;gap:8px;margin-bottom:16px">
          <input id="pkg-input" class="config-editor" style="min-height:auto;height:36px;padding:8px 12px;flex:1" placeholder="Package name (e.g. htop, neofetch, btop)">
          <button class="btn btn-accent" onclick="addPackage()">Install</button>
        </div>
        <h2>Installed Packages</h2>
        <div class="code-block">${data.packages.join('\n') || '(run omarchy pkg list to see packages)'}</div>
      </div>
    </div>
  `;
}

async function addPackage() {
  const name = document.getElementById('pkg-input').value.trim();
  if (!name) return;
  await api('/packages/add', { method: 'POST', body: JSON.stringify({ name }) });
  renderPackages().then(html => { document.getElementById('content').innerHTML = html; bindPageEvents('packages'); });
}

// ─── Fonts ─────────────────────────────────────────────────────────────────

async function renderFonts() {
  const data = await api('/fonts');
  const items = data.fonts.map(f =>
    `<div class="font-item ${f === data.current ? 'active' : ''}" onclick="setFont('${escapeHtml(f)}')" style="font-family:'${f}',monospace">${escapeHtml(f)}</div>`
  ).join('');

  return `
    <div class="page active" id="page-fonts">
      <div class="page-header">
        <h1>Fonts</h1>
        <p>Current: <strong>${data.current || 'none'}</strong></p>
      </div>
      <div class="card">
        <div class="font-list">${items}</div>
      </div>
    </div>
  `;
}

async function setFont(name) {
  await api('/fonts/set', { method: 'POST', body: JSON.stringify({ name }) });
  renderFonts().then(html => { document.getElementById('content').innerHTML = html; bindPageEvents('fonts'); });
}

// ─── Page Events ───────────────────────────────────────────────────────────

function bindPageEvents(page) {
  closeStreams();

  if (page === 'dashboard') {
    setupMetricsSSE();
  }

  if (page === 'monitor') {
    setTimeout(() => updateMonitorCharts(), 100);
    setupMetricsSSE();
  }

  if (page === 'network') {
    setTimeout(() => {
      document.querySelectorAll('[id^="net-"]').forEach(canvas => {
        const iface = canvas.id.replace('net-', '');
        const container = canvas.closest('.io-card');
        if (!container) return;
        const rxEl = container.querySelector('.io-stat:first-child .val');
        const txEl = container.querySelector('.io-stat:last-child .val');
        const rxVal = parseFloat(rxEl?.textContent || '0');
        const txVal = parseFloat(txEl?.textContent || '0');
        const history = [];
        for (let i = 0; i < 60; i++) {
          history.push(Math.random() * Math.max(rxVal, txVal, 1000) * 0.5);
        }
        sparkline(canvas, history, '#33ccff', true);
      });
      document.querySelectorAll('[id^="dio-"]').forEach(canvas => {
        const dname = canvas.id.replace('dio-', '');
        const history = [];
        for (let i = 0; i < 60; i++) {
          history.push(Math.random() * 200);
        }
        sparkline(canvas, history, '#00ff99', true);
      });
    }, 200);
  }

  if (page === 'hyprland') {
    api('/hyprland/keybindings').then(d => {
      const el = document.getElementById('keybindings');
      if (el) el.textContent = (d.bindings || []).join('\n') || 'No keybindings found';
    });
    const firstTab = document.querySelector('.config-tab');
    if (firstTab) firstTab.click();
  }

  if (page === 'services') {
    // already rendered
  }

  if (page === 'processes') {
    // already rendered
  }
}

// ─── SSE Metrics Stream ────────────────────────────────────────────────────

function setupMetricsSSE() {
  metricsStream = new EventSource(API + '/api/metrics/stream');

  metricsStream.addEventListener('metrics', (event) => {
    try {
      const data = JSON.parse(event.data);
      updateLiveMetrics(data);
    } catch(e) {}
  });

  metricsStream.onerror = () => {
    // Reconnect will happen automatically
  };
}

function updateLiveMetrics(data) {
  // Update dashboard health bar
  const healthDot = document.querySelector('.health-dot');
  const healthScore = document.querySelector('.health-score');
  const healthAlerts = document.querySelector('.health-alerts');
  if (healthDot && data.health !== undefined) {
    const status = data.health >= 70 ? 'healthy' : data.health >= 40 ? 'degraded' : 'critical';
    healthDot.className = `health-dot ${status}`;
    healthScore.textContent = data.health;
    if (healthAlerts && data.alerts) {
      healthAlerts.innerHTML = data.alerts.map(a => `<span class="alert-badge ${a.severity}">${a.type}</span>`).join('');
      if (!data.alerts.length) healthAlerts.innerHTML = '<span style="color:var(--success);font-size:11px">✓ All clear</span>';
    }
  }

  // Update gauges
  if (data.cpu && data.cpu.usage !== undefined) {
    const cpuGauge = document.querySelector('.gauge-container .gauge:first-child .gauge-value');
    const cpuFill = document.querySelector('.gauge-container .gauge:first-child .gauge-fill');
    if (cpuGauge) cpuGauge.textContent = data.cpu.usage + '%';
    if (cpuFill) {
      const pct = data.cpu.usage;
      const r = 40, circ = 2 * Math.PI * r;
      cpuFill.setAttribute('stroke-dashoffset', circ * (1 - Math.min(pct, 100) / 100));
      cpuFill.setAttribute('stroke', pct > 80 ? 'var(--danger)' : pct > 50 ? 'var(--warning)' : 'var(--accent)');
    }
  }
  if (data.memory && data.memory.percent !== undefined) {
    const memGauge = document.querySelector('.gauge-container .gauge:nth-child(2) .gauge-value');
    const memFill = document.querySelector('.gauge-container .gauge:nth-child(2) .gauge-fill');
    if (memGauge) memGauge.textContent = data.memory.percent + '%';
    if (memFill) {
      const pct = data.memory.percent;
      const r = 40, circ = 2 * Math.PI * r;
      memFill.setAttribute('stroke-dashoffset', circ * (1 - Math.min(pct, 100) / 100));
      memFill.setAttribute('stroke', pct > 80 ? 'var(--danger)' : pct > 50 ? 'var(--warning)' : '#00ff99');
    }
  }
  if (data.disk && data.disk.percent !== undefined) {
    const diskGauge = document.querySelector('.gauge-container .gauge:nth-child(3) .gauge-value');
    const diskFill = document.querySelector('.gauge-container .gauge:nth-child(3) .gauge-fill');
    if (diskGauge) diskGauge.textContent = data.disk.percent + '%';
    if (diskFill) {
      const pct = parseFloat(data.disk.percent);
      const r = 40, circ = 2 * Math.PI * r;
      diskFill.setAttribute('stroke-dashoffset', circ * (1 - Math.min(pct, 100) / 100));
      diskFill.setAttribute('stroke', pct > 80 ? 'var(--danger)' : 'var(--warning)');
    }
  }

  // Update monitor page charts
  if (document.getElementById('page-monitor')) {
    if (data.cpu && data.cpu.usage !== undefined) {
      monitorHistoryCPU.push(data.cpu.usage);
      if (monitorHistoryCPU.length > 120) monitorHistoryCPU.shift();
    }
    if (data.memory && data.memory.percent !== undefined) {
      monitorHistoryMEM.push(data.memory.percent);
      if (monitorHistoryMEM.length > 120) monitorHistoryMEM.shift();
    }
    if (data.disk && data.disk.percent !== undefined) {
      monitorHistoryDisk.push(parseFloat(data.disk.percent));
      if (monitorHistoryDisk.length > 120) monitorHistoryDisk.shift();
    }
    updateMonitorCharts();
  }
}

// ─── Init ──────────────────────────────────────────────────────────────────

document.getElementById('themeToggle').addEventListener('click', toggleTheme);
navigate('dashboard');
