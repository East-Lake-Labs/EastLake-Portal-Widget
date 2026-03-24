# East Lake Portal Widget

A macOS menu bar app for managing time tracking across multiple East Lake client portals.

## Features

- **Live Timer** - Start/stop timers with real-time HH:MM:SS and dollar amount in the menu bar
- **Multi-Portal** - Connect multiple client backends, switch between them with Cmd+1/2/3
- **Global Hotkey** - Cmd+Shift+J to toggle timers from anywhere (no clicking required)
- **Today Summary** - See today's total hours and earnings at a glance
- **Weekly Stats** - View weekly hours, earnings, and unpaid totals per portal
- **Cross-Portal Dashboard** - All Portals Summary shows stats across every portal at once
- **Entry Management** - Edit notes, toggle paid/unpaid, delete entries from the widget
- **CSV Export** - Export time entries for any date range to CSV
- **Idle Detection** - Prompts when you return from idle to adjust your timer
- **Sleep/Wake Awareness** - Notifies you if a timer is still running after your Mac wakes
- **Native Notifications** - Timer start/stop, periodic reminders, external change detection
- **Launch at Login** - Toggle auto-start from the Settings menu
- **Offline Resilience** - Queues start/stop actions when offline, syncs when connection returns
- **Auto-Update Check** - Checks GitHub releases for new versions

## Install

### Download (recommended)

1. Go to [Releases](https://github.com/East-Lake-Labs/EastLake-Portal-Widget/releases/latest)
2. Download `East-Lake-Time-Tracker-vX.X.X.dmg`
3. Open the DMG and drag **East Lake Time Tracker** to **Applications**
4. **First launch only:** Right-click the app > **Open** > click **Open** in the dialog. macOS blocks unsigned apps by default - this is a one-time step.
5. Launch from Spotlight (Cmd+Space, type "East Lake") or /Applications

No Python, terminal, or developer tools required.

> **Note:** The app is not signed with an Apple Developer certificate, so macOS Gatekeeper will show a warning on first launch. The right-click > Open workaround bypasses this safely. Subsequent launches work normally.

### From source (for development)

Requires macOS 12+, Python 3.11+, and [uv](https://github.com/astral-sh/uv) or pip.

```bash
git clone https://github.com/East-Lake-Labs/EastLake-Portal-Widget.git
cd EastLake-Portal-Widget

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run directly
python run.py

# Or build a standalone .app + DMG
pip install pyinstaller
pyinstaller eastlake.spec --noconfirm
bash scripts/build-dmg.sh
```

## Configuration

Portal configs and preferences are stored in `~/.eastlake-menu-widget/`:

- `portals.json` - Portal connections (name, URL, API key, default rate)
- `prefs.json` - App preferences (active portal, idle timeout, notification interval, etc.)

All settings are configurable from the widget's **Settings** submenu.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd+Shift+J | Quick start/stop timer (no prompts, uses default rate) |
| Cmd+1/2/3 | Switch to portal 1, 2, or 3 |

**Note:** Cmd+Shift+J requires Accessibility permission. Grant it in System Settings > Privacy & Security > Accessibility.

## Project Structure

```
src/eastlake/          # Python source
  app.py               # Main menu bar application
  api_client.py        # Time tracking API client
  config.py            # Portal and preferences storage
  export.py            # CSV export
  hotkey.py            # Global hotkey (Cmd+Shift+J)
  idle_monitor.py      # Idle detection + sleep/wake
  launch_agent.py      # Launch at Login management
  notifications.py     # Native macOS notifications
assets/                # Icons
  icon.png             # App icon (2240x2240)
  icon.icns            # macOS bundle icon
  icon_menubar.png     # Menu bar icon (36x36)
run.py                 # Entry point
eastlake.spec          # PyInstaller build spec
setup.py               # py2app build config (dev mode)
install.sh             # Install to /Applications (dev)
scripts/build-dmg.sh   # Build distributable DMG
.github/workflows/     # CI - auto-build DMG on release tags
```

## API Compatibility

Connects to any backend implementing the East Lake time tracking API:

- `POST /api/time-tracking/start` - Start timer
- `POST /api/time-tracking/stop` - Stop timer
- `GET /api/time-tracking/active` - Current timer
- `GET /api/time-tracking/entries` - List entries
- `GET /api/time-tracking/stats` - Summary statistics
- `PATCH /api/time-tracking/entries/{id}` - Update entry
- `DELETE /api/time-tracking/entries/{id}` - Delete entry
- `PATCH /api/time-tracking/entries/{id}/mark-paid` - Mark paid
- `PATCH /api/time-tracking/entries/{id}/mark-unpaid` - Mark unpaid
- `GET /api/health` - Health check

Authentication via Bearer token (API key).

## License

MIT - see [LICENSE](LICENSE)
