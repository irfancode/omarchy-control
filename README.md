# Omarchy Control

Web-based desktop management panel for **Omarchy** (Hyprland on Arch Linux).

Apple-inspired UI to manage your entire Omarchy desktop from a browser — no terminal needed for day-to-day tasks.

## Features

| Page | What you can do |
|------|----------------|
| **Dashboard** | Live system health score, CPU/memory/disk gauges, real-time alerts, quick actions |
| **Monitor** | Real-time sparkline charts for CPU, memory, disk — 10-min window via SSE |
| **Processes** | Top processes table, sort by CPU/memory, kill processes |
| **Logs** | Systemd journal viewer with unit/priority filters, full-text search, real-time SSE follow mode |
| **Network** | Per-interface throughput charts, disk I/O rates, temperature sensors |
| **Hyprland** | Edit any `.conf` file with save+reload, view keybindings |
| **Themes** | Browse, preview, and apply Omarchy themes; cycle wallpapers |
| **Services** | Restart Waybar, Walker, Hyprland, Mako, SwayOSD etc. |
| **Toggles** | Toggle nightlight, idle lock, DND, hybrid GPU |
| **System** | Lock, logout, reboot, shutdown; check/run updates |
| **Packages** | Install Arch packages via omarchy pkg |
| **Fonts** | Browse and set monospace fonts |

### Observability Features

- **Real-time SSE streaming** — Sub-second metrics pushed to browser via Server-Sent Events
- **System health score** — Composite health indicator with color-coded status
- **Configurable alert thresholds** — CPU, memory, disk, temperature warnings and criticals
- **Sparkline charts** — Canvas-based live-updating charts (no external libraries)
- **Resource gauges** — SVG circular gauges for at-a-glance monitoring
- **Process explorer** — Full process table with sorting and kill capability
- **Journald log viewer** — Full-text search, unit/priority filtering, live tail mode
- **Network throughput** — Per-interface RX/TX rates with historical charts
- **Disk I/O monitoring** — Read/write operations per second
- **Temperature sensors** — CPU/GPU/SSD temperature display

### Log Management Features

- **Systemd journal integration** — Native `journalctl` backend
- **Unit filtering** — Select any systemd service
- **Priority/level filtering** — emerg through debug
- **Full-text search** — Client-side filtering with live results
- **Real-time follow mode** — SSE-based log streaming (like `journalctl -f`)
- **Rich log display** — Color-coded priorities, timestamps, unit names

## Architecture

```
┌──────────────────────────────────────────────────┐
│              Browser SPA (vanilla JS)              │
│  index.html + style.css + app.js                  │
│  12 pages · Canvas charts · SVG gauges · SSE      │
└──────────┬──────────────┬────────────┬───────────┘
           │ HTTP/SSE      │ EventSource │ Fetch API
           ▼               ▼            ▼
┌──────────────────────────────────────────────────┐
│           Python Backend (stdlib only)            │
│  ThreadedHTTPServer · REST API · SSE streams     │
│  30+ endpoints · Background metrics collector    │
│  Ring buffer (120 samples) · Alert engine        │
└──────┬──────────────┬──────────────┬─────────────┘
       │              │              │
       ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────────┐
  │ omarchy  │  │ hyprctl  │  │ /proc/*       │
  │ CLI      │  │ journalctl│ │ df, ps        │
  │ 267 cmd  │  │ systemctl │ │ /sys/class/   │
  └──────────┘  └──────────┘  └──────────────┘
```

## Install

```bash
git clone https://github.com/irfancode/omarchy-control.git
cd omarchy-control
./install.sh
```

Or via omarchy (after cloning):

```bash
cp bin/omarchy-install-control ~/.local/share/omarchy/bin/
omarchy install control
```

## Usage

```bash
# Start the web interface
omarchy-control

# Open in browser (auto-opens on start)
# http://localhost:8765
```

## Development

```bash
# Run directly (no install needed)
python3 backend/server.py

# Run tests
python3 -m pytest tests/ -v --cov=backend

# Watch mode (auto-restart on file changes)
find . -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.css' | entr -r python3 backend/server.py
```

## API Endpoints

### System
- `GET /api/system/info` — Hostname, OS, kernel, uptime
- `GET /api/system/stats` — CPU, memory, disk, load, network, disk I/O, temperature
- `GET /api/system/health` — Health score and active alerts
- `GET /api/system/processes` — Process list (sort by cpu/mem)
- `POST /api/system/kill` — Kill a process by PID
- `POST /api/system/action` — Lock, logout, reboot, shutdown, update
- `GET /api/system/updates` — Check for updates
- `GET /api/system/network` — Historical network throughput
- `GET /api/system/disk-io` — Historical disk I/O rates
- `GET /api/system/temperature` — Temperature sensors
- `GET /api/system/alerts` — Get/set alert thresholds
- `GET /api/system/metrics/history` — Full metrics history buffer

### Logs
- `GET /api/logs` — Query journald logs (unit, priority, lines, search, since, until)
- `GET /api/logs/units` — List available systemd units
- `GET /api/logs/stream` — SSE stream of live logs

### SSE Streams
- `GET /api/metrics/stream` — Real-time metrics pushed every 5 seconds
- `GET /api/logs/stream` — Real-time log entries via journalctl -f

### Configuration
- `GET/POST /api/hyprland/configs` — List/edit Hyprland config files
- `GET /api/hyprland/keybindings` — List keybindings
- `GET /api/themes` — List and set themes
- `GET /api/services` — List and restart services
- `GET /api/toggles` — Get/set feature toggles
- `GET /api/fonts` — List and set fonts
- `GET /api/packages` — List and install packages

## Tech Stack

- **Backend:** Python 3 (stdlib only — zero dependencies)
- **Frontend:** Vanilla HTML + CSS + JS (no build step, no frameworks)
- **Charts:** Canvas API with sparkline rendering
- **Gauges:** SVG circle gauges
- **Real-time:** Server-Sent Events (EventSource API)
- **Integration:** omarchy CLI, hyprctl, journalctl, /proc filesystem, /sys/class/thermal
- **Port:** 8765 (configurable via `OMARCHY_CONTROL_PORT`)
- **License:** GPL-3.0

## CI/CD

- **GitHub Actions** — Automated test suite on push/PR
- **Python versions:** 3.10, 3.11, 3.12
- **Linting:** flake8
- **Coverage:** pytest-cov with Codecov upload
- **Release:** Automatic tarball/zip creation on version tags

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ -v --cov=backend --cov-report=term

# Specific test file
python -m pytest tests/test_api.py -v
```
