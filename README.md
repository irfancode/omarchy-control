# Omarchy Control

Web-based desktop management panel for **Omarchy** (Hyprland on Arch Linux).

Apple-inspired UI to manage your entire Omarchy desktop from a browser — no terminal needed for day-to-day tasks.

![Dashboard](https://via.placeholder.com/800x400?text=Omarchy+Control+Dashboard)

## Features

| Page | What you can do |
|------|----------------|
| **Dashboard** | Live CPU, memory, disk, load, temperatures |
| **Hyprland** | Edit any `.conf` file with save+reload, view keybindings |
| **Themes** | Browse, preview, and apply Omarchy themes; cycle wallpapers |
| **Services** | Restart Waybar, Walker, Hyprland, Mako, SwayOSD etc. |
| **Toggles** | Toggle nightlight, idle lock, DND, hybrid GPU |
| **System** | Lock, logout, reboot, shutdown; check/run updates |
| **Packages** | Install Arch packages via omarchy pkg |
| **Fonts** | Browse and set monospace fonts |

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│  Python Flask    │────▶│  omarchy CLI     │
│  Backend (API)   │     │  (267 commands)  │
│  :8765           │     └──────────────────┘
└────────┬────────┘     ┌──────────────────┐
         │              │  hyprctl         │
         │              │  (Hyprland IPC)  │
         │              └──────────────────┘
         │              ┌──────────────────┐
         │              │  /proc, df, etc   │
         ▼              └──────────────────┘
┌─────────────────┐
│  Apple-inspired  │
│  Web Frontend    │
│  (vanilla JS)    │
└─────────────────┘
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

## Tech Stack

- **Backend:** Python Flask (REST API, 25+ endpoints)
- **Frontend:** Vanilla HTML + CSS + JS (no build step)
- **Integration:** 267 omarchy CLI commands, hyprctl IPC, /proc filesystem
- **Port:** 8765 (configurable via `OMARCHY_CONTROL_PORT`)

## License

GPL-3.0
