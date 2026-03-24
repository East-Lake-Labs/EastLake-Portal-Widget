"""East Lake Time Tracker - macOS menu bar widget."""

import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import AppKit
import rumps
from Foundation import NSTimer

from eastlake.api_client import (
    APIError,
    TimeTrackingClient,
    format_duration,
    format_entry_line,
    format_hours,
    this_week_range,
    today_range,
)
from eastlake.config import (
    add_portal,
    get_active_portal,
    get_active_portal_name,
    get_pref,
    load_portals,
    remove_portal,
    set_active_portal_name,
    set_pref,
    update_portal,
)
from eastlake.export import default_export_path, generate_csv
from eastlake.hotkey import GlobalHotkeyMonitor
from eastlake.idle_monitor import IdleMonitor
from eastlake import launch_agent
from eastlake import notifications

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("eastlake")

API_REFRESH_INTERVAL = 30
TICK_INTERVAL = 1
NOTIFICATION_CHECK_INTERVAL = 60  # seconds between notification checks

# Assets - check PyInstaller bundle, py2app bundle, then source tree
def _find_assets_dir():
    import sys
    # PyInstaller stores data files in sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, "assets")
    # py2app bundles into Contents/Resources/
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Resources", "assets")
    # Running from source - assets/ at project root
    src_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(src_dir)), "assets")

ASSETS_DIR = _find_assets_dir()
ICON_PATH = os.path.join(ASSETS_DIR, "icon_menubar.png")
APP_ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")


class EastLakeApp(rumps.App):
    def __init__(self):
        super().__init__(
            name="East Lake",
            title=None,
            icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
            template=True,
            quit_button=None,
        )

        if os.path.exists(APP_ICON_PATH):
            ns_image = AppKit.NSImage.alloc().initWithContentsOfFile_(APP_ICON_PATH)
            AppKit.NSApplication.sharedApplication().setApplicationIconImage_(ns_image)

        self._active_entry = None
        self._client = None
        self._lock = threading.Lock()
        self._today_stats = None
        self._recent_entries = []
        self._last_notification_hours = 0
        self._connected = True
        self._offline_queue = []  # queued actions for when connection returns

        self._rebuild_menu()

        # Timers
        self._api_timer = rumps.Timer(self._on_api_refresh, API_REFRESH_INTERVAL)
        self._api_timer.start()
        self._tick_timer = rumps.Timer(self._on_tick, TICK_INTERVAL)
        self._tick_timer.start()

        # Idle detection
        idle_timeout = get_pref("idle_timeout_minutes", 5) * 60
        self._idle_monitor = IdleMonitor(
            idle_threshold_seconds=idle_timeout,
            on_idle_return=self._handle_idle_return,
            on_wake=self._handle_wake,
        )

        # Global hotkey (Cmd+Shift+J)
        self._hotkey = GlobalHotkeyMonitor(callback=self._on_hotkey_toggle)
        self._hotkey_ok = self._hotkey.start()

        self._async(self._refresh_active_timer)

        # Deferred first-run check + hotkey warning
        def _deferred_startup(timer):
            timer.stop()
            if not self._hotkey_ok:
                self._alert(
                    "Hotkey Unavailable",
                    "Cmd+Shift+J requires Accessibility permission.\n\n"
                    "Go to System Settings > Privacy & Security > Accessibility "
                    "and add this app (or your Terminal).",
                )
            # First-run onboarding
            portals = load_portals()
            if not portals:
                self._alert(
                    "Welcome to East Lake",
                    "No portals configured yet.\n\n"
                    "Go to Portals > Add Portal to connect your first time tracking backend.",
                )
        rumps.Timer(_deferred_startup, 2).start()

    # ------------------------------------------------------------------ #
    #  Live ticker                                                         #
    # ------------------------------------------------------------------ #

    def _on_tick(self, _timer):
        if not self._active_entry:
            return

        entry = self._active_entry
        start_str = entry.get("start_time", "")
        rate = entry.get("hourly_rate") or 0

        try:
            ts = start_str.replace("Z", "+00:00")
            start = datetime.fromisoformat(ts)
            now = datetime.now(tz=start.tzinfo)
            elapsed_seconds = max(0, int((now - start).total_seconds()))
        except Exception:
            return

        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        elapsed_hours = elapsed_seconds / 3600.0
        dollars = elapsed_hours * rate

        if hours > 0:
            time_str = f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            time_str = f"{minutes}:{secs:02d}"

        self.title = f"{time_str}  ${dollars:.2f}"

        # Idle detection check (only when timer is running)
        self._idle_monitor.check()

        # Periodic notification (every N hours)
        interval = get_pref("notification_interval_hours", 2)
        if interval > 0 and elapsed_hours >= self._last_notification_hours + interval:
            self._last_notification_hours = int(elapsed_hours)
            portal_name = get_active_portal_name() or "Unknown"
            notifications.send(
                "Timer Running",
                f"{portal_name}: {hours}h {minutes:02d}m - ${dollars:.2f}",
            )

    # ------------------------------------------------------------------ #
    #  Menu                                                                #
    # ------------------------------------------------------------------ #

    def _rebuild_menu(self):
        self.menu.clear()

        portal = get_active_portal()
        portal_name = portal["name"] if portal else "No Portal"

        # --- Connection + Status ---
        if not self._connected:
            conn_text = "  ● Offline - connection lost"
        elif not portal:
            conn_text = "  ○ No portal configured"
        else:
            conn_text = None

        if conn_text:
            self.menu.add(rumps.MenuItem(conn_text, callback=None))

        if self._active_entry:
            entry = self._active_entry
            notes = entry.get("notes", "") or "working"
            if len(notes) > 30:
                notes = notes[:27] + "..."
            rate = entry.get("hourly_rate") or 0
            status = f"  {portal_name}: {notes}"
            rate_line = f"  Rate: ${rate:.2f}/hr"
        else:
            self.title = None
            status = f"  {portal_name} - no active timer"
            rate_line = None

        self.menu.add(rumps.MenuItem(status, callback=None))
        if rate_line:
            self.menu.add(rumps.MenuItem(rate_line, callback=None))

        # --- Today summary ---
        if self._today_stats:
            s = self._today_stats
            today_hrs = s.get("total_hours", 0) or 0
            today_amt = s.get("total_amount", 0) or 0
            today_text = f"  Today: {format_hours(today_hrs)} - ${today_amt:.2f}"
        else:
            today_text = "  Today: --"
        self.menu.add(rumps.MenuItem(today_text, callback=None))
        self.menu.add(rumps.separator)

        # --- Timer controls ---
        self.menu.add(rumps.MenuItem("Start Timer", callback=self._on_start_timer))
        self.menu.add(rumps.MenuItem("Stop Timer", callback=self._on_stop_timer))
        self.menu.add(rumps.separator)

        # --- Data views ---
        self.menu.add(rumps.MenuItem("Weekly Stats", callback=self._on_show_stats))
        self.menu.add(rumps.MenuItem("Export Entries", callback=self._on_export))
        self.menu.add(rumps.separator)

        # --- Entry management (opens dialog with entry list) ---
        self.menu.add(rumps.MenuItem("Manage Entries", callback=self._on_manage_entries))
        self.menu.add(rumps.separator)

        # --- Portals ---
        portals_menu = rumps.MenuItem("Portals")
        portals = load_portals()
        active_name = get_active_portal_name()

        for i, p in enumerate(portals):
            check = "✓ " if p["name"] == active_name else "  "
            rate = p.get("default_rate", 150)
            item = rumps.MenuItem(
                f"{check}{p['name']}  (${rate:.0f}/hr)",
                callback=self._make_portal_selector(p["name"]),
            )
            # Set Cmd+1/2/3 shortcuts for first 3 portals
            if i < 3:
                ns_item = item._menuitem
                ns_item.setKeyEquivalent_(str(i + 1))
                ns_item.setKeyEquivalentModifierMask_(AppKit.NSEventModifierFlagCommand)
            portals_menu.add(item)

        if portals:
            portals_menu.add(rumps.separator)
            portals_menu.add(rumps.MenuItem("All Portals Summary", callback=self._on_all_portals))
            portals_menu.add(rumps.separator)
        portals_menu.add(rumps.MenuItem("Add Portal", callback=self._on_add_portal))
        if portals:
            portals_menu.add(rumps.MenuItem("Edit Portal", callback=self._on_edit_portal))
            portals_menu.add(rumps.MenuItem("Remove Portal", callback=self._on_remove_portal))

        self.menu.add(portals_menu)
        self.menu.add(rumps.separator)

        # --- Settings submenu ---
        settings_menu = rumps.MenuItem("Settings")

        login_item = rumps.MenuItem("Launch at Login", callback=self._on_toggle_launch)
        if launch_agent.is_enabled():
            login_item.state = True
        settings_menu.add(login_item)

        settings_menu.add(rumps.separator)

        idle_min = get_pref("idle_timeout_minutes", 5)
        settings_menu.add(rumps.MenuItem(
            f"Idle Timeout: {idle_min}m", callback=self._on_set_idle_timeout,
        ))

        notif_hrs = get_pref("notification_interval_hours", 2)
        notif_label = f"every {notif_hrs}h" if notif_hrs > 0 else "off"
        settings_menu.add(rumps.MenuItem(
            f"Timer Notifications: {notif_label}", callback=self._on_set_notif_interval,
        ))

        refresh_sec = get_pref("refresh_interval", API_REFRESH_INTERVAL)
        settings_menu.add(rumps.MenuItem(
            f"Refresh Interval: {refresh_sec}s", callback=self._on_set_refresh_interval,
        ))

        settings_menu.add(rumps.separator)
        settings_menu.add(rumps.MenuItem(
            "Check for Updates", callback=self._on_check_update,
        ))

        self.menu.add(settings_menu)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh", callback=self._on_manual_refresh))
        self.menu.add(rumps.MenuItem("Quit", callback=self._on_quit))

    # ------------------------------------------------------------------ #
    #  Dialog helpers                                                       #
    # ------------------------------------------------------------------ #

    _ns_icon = None

    def _get_icon(self):
        if self._ns_icon is None and os.path.exists(APP_ICON_PATH):
            img = AppKit.NSImage.alloc().initWithContentsOfFile_(APP_ICON_PATH)
            img.setSize_(AppKit.NSMakeSize(28, 28))
            EastLakeApp._ns_icon = img
        return self._ns_icon

    def _style_alert(self, alert):
        icon = self._get_icon()
        if not icon:
            return
        alert.setIcon_(icon)
        alert.layout()
        window = alert.window()
        content_view = window.contentView()
        self._reposition_icon(content_view)

        def fixup(_timer):
            self._reposition_icon(content_view)
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.01, False, fixup)

    def _reposition_icon(self, view):
        for subview in view.subviews():
            if subview.className() == "_NSAlertImageView":
                parent = subview.superview()
                parent_frame = parent.frame()
                icon_size = 28
                margin = 14
                x = parent_frame.size.width - icon_size - margin
                y = parent_frame.size.height - icon_size - margin
                subview.setFrame_(AppKit.NSMakeRect(x, y, icon_size, icon_size))
                subview.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
                subview.setWantsLayer_(True)
                subview.layer().setCornerRadius_(4.0)
                subview.layer().setMasksToBounds_(True)
                return True
            if self._reposition_icon(subview):
                return True
        return False

    def _activate(self):
        nsapp = AppKit.NSApplication.sharedApplication()
        nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        nsapp.activateIgnoringOtherApps_(True)

    def _deactivate(self):
        nsapp = AppKit.NSApplication.sharedApplication()
        nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    def _prompt(self, title, message, default_text="", ok="OK", cancel="Cancel",
                dimensions=(360, 40)):
        self._activate()
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(ok)
        if cancel:
            alert.addButtonWithTitle_(cancel)
        width, height = dimensions
        text_field = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, width, height)
        )
        text_field.setStringValue_(default_text)
        text_field.setEditable_(True)
        text_field.setSelectable_(True)
        text_field.setBezeled_(True)
        text_field.setBezelStyle_(AppKit.NSTextFieldSquareBezel)
        alert.setAccessoryView_(text_field)
        self._style_alert(alert)
        alert.window().makeFirstResponder_(text_field)
        response_code = alert.runModal()
        self._deactivate()

        class Response:
            def __init__(self, clicked, text):
                self.clicked = clicked
                self.text = text
        clicked = 1 if response_code == AppKit.NSAlertFirstButtonReturn else 0
        return Response(clicked, text_field.stringValue())

    def _confirm(self, title, message, ok="OK", cancel="Cancel"):
        """Show a confirmation dialog. Returns True if OK clicked."""
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(ok)
        alert.addButtonWithTitle_(cancel)
        self._style_alert(alert)
        return alert.runModal() == AppKit.NSAlertFirstButtonReturn

    def _alert(self, title, message=""):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        self._style_alert(alert)
        alert.runModal()

    def _choice(self, title, message, buttons):
        """Show a dialog with multiple button choices. Returns 0-based index of clicked button."""
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        for btn in buttons:
            alert.addButtonWithTitle_(btn)
        self._style_alert(alert)
        result = alert.runModal()
        # NSAlertFirstButtonReturn = 1000, second = 1001, etc.
        return result - AppKit.NSAlertFirstButtonReturn

    def _show_error(self, title: str, error: Exception):
        if isinstance(error, APIError):
            self._alert(title=title, message=str(error))
        else:
            log.exception("Unexpected error in %s", title)
            self._alert(title=title, message=f"Unexpected error: {error}")

    # ------------------------------------------------------------------ #
    #  Client                                                              #
    # ------------------------------------------------------------------ #

    def _get_client(self, silent: bool = False) -> TimeTrackingClient | None:
        portal = get_active_portal()
        if not portal:
            if not silent:
                self._alert("No Portal Selected", "Go to Portals > Add Portal to get started.")
            return None
        with self._lock:
            if self._client and self._client.base_url == portal["url"].rstrip("/"):
                return self._client
            self._client = TimeTrackingClient(portal["url"], portal["api_key"])
            return self._client

    # ------------------------------------------------------------------ #
    #  Async + refresh                                                     #
    # ------------------------------------------------------------------ #

    def _async(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _on_api_refresh(self, _timer):
        self._async(self._refresh_active_timer)

    def _on_manual_refresh(self, _sender):
        self._async(self._refresh_active_timer)

    def _refresh_active_timer(self):
        client = self._get_client(silent=True)
        if not client:
            self._active_entry = None
            self._today_stats = None
            self._recent_entries = []
            self._schedule_rebuild()
            return

        # Fetch active timer - detect external stop/start
        was_connected = self._connected
        prev_entry = self._active_entry
        try:
            result = client.get_active_timer()
            self._active_entry = result.get("entry") if result else None
            self._connected = True
        except APIError as e:
            if e.status_code and 400 <= e.status_code < 500:
                self._connected = True  # server responded, just an error
                self._active_entry = None
            else:
                self._connected = False
                log.debug("Active timer refresh failed: %s", e)
                self._schedule_rebuild()
                return
        except Exception as e:
            self._connected = False
            log.debug("Active timer refresh failed: %s", e)
            self._schedule_rebuild()
            return

        # Connection restored - process queued actions
        if self._connected and not was_connected:
            notifications.send("Connection Restored", "Back online.")
            self._process_offline_queue(client)

        # Timer was running but now it's not - stopped externally (web app, API, etc.)
        if prev_entry and not self._active_entry:
            self._last_notification_hours = 0
            notes = prev_entry.get("notes", "") or "Timer"
            dur = format_duration(prev_entry.get("start_time", ""))
            rate = prev_entry.get("hourly_rate") or 0
            try:
                ts = prev_entry.get("start_time", "").replace("Z", "+00:00")
                start = datetime.fromisoformat(ts)
                elapsed_hrs = (datetime.now(tz=start.tzinfo) - start).total_seconds() / 3600
                amount = elapsed_hrs * rate
                notifications.send("Timer Stopped", f"{notes}\n{dur} - ${amount:.2f}")
            except Exception:
                notifications.send("Timer Stopped", f"{notes} - {dur}")

        # Timer wasn't running but now it is - started externally
        if not prev_entry and self._active_entry:
            self._last_notification_hours = 0
            notes = self._active_entry.get("notes", "") or "Timer started"
            portal_name = get_active_portal_name() or "Unknown"
            notifications.send("Timer Started", f"{portal_name}: {notes}")

        # Fetch today's stats
        try:
            start, end = today_range()
            result = client.get_stats(start_date=start, end_date=end)
            self._today_stats = result.get("stats", result)
        except Exception as e:
            log.debug("Today stats refresh failed: %s", e)

        # Fetch recent entries for the entry management submenu
        try:
            start, end = this_week_range()
            result = client.list_entries(start_date=start, end_date=end)
            self._recent_entries = result.get("entries", [])[:10]
        except Exception as e:
            log.debug("Recent entries refresh failed: %s", e)

        self._schedule_rebuild()

    def _schedule_rebuild(self):
        rumps.Timer(self._do_rebuild, 0.1).start()

    def _do_rebuild(self, timer):
        timer.stop()
        self._rebuild_menu()

    # ------------------------------------------------------------------ #
    #  Idle detection callbacks                                            #
    # ------------------------------------------------------------------ #

    def _handle_idle_return(self, idle_seconds, idle_started_at):
        """Called on main thread when user returns from idle with timer running."""
        if not self._active_entry:
            return
        idle_min = int(idle_seconds / 60)
        if idle_min < 1:
            return
        idle_time_str = idle_started_at.strftime("%H:%M")
        if self._confirm(
            "Idle Detected",
            f"You were idle for {idle_min} minutes (since {idle_time_str}).\n\n"
            "Stop the timer and subtract idle time?",
            ok="Stop & Subtract",
            cancel="Keep Running",
        ):
            notifications.send("Timer Adjusted", f"Subtracted {idle_min}m of idle time")
            # Stop and let user know - actual time adjustment depends on API capabilities
            client = self._get_client(silent=True)
            if client:
                try:
                    result = client.stop_timer()
                    entry = result.get("entry", {})
                    self._active_entry = None
                    self._rebuild_menu()
                    dur = format_hours(entry.get("duration_hours"))
                    amount = entry.get("total_amount") or 0
                    self._alert(
                        "Timer Stopped (Idle Adjusted)",
                        f"Stopped at idle start ({idle_time_str}).\n"
                        f"Duration: {dur}\nTotal: ${amount:.2f}\n\n"
                        f"Note: {idle_min}m of idle time was included. "
                        "You may want to adjust the entry manually.",
                    )
                except Exception as e:
                    self._show_error("Stop Timer", e)

    def _handle_wake(self, sleep_seconds):
        """Called when system wakes from sleep with timer running."""
        if not self._active_entry:
            return
        sleep_min = int(sleep_seconds / 60)
        if sleep_min < 1:
            return
        notifications.send(
            "Timer Still Running",
            f"Your Mac slept for {sleep_min} minutes. Timer is still active.",
        )

    # ------------------------------------------------------------------ #
    #  Global hotkey callback                                              #
    # ------------------------------------------------------------------ #

    def _on_hotkey_toggle(self):
        """Cmd+Shift+J pressed - quick toggle timer."""
        if self._active_entry:
            # Quick stop
            if not self._connected:
                self._queue_action("stop")
                return

            def do_stop():
                client = self._get_client(silent=True)
                if not client:
                    return
                try:
                    result = client.stop_timer()
                    entry = result.get("entry", {})
                    dur = format_hours(entry.get("duration_hours"))
                    amount = entry.get("total_amount") or 0
                    self._active_entry = None
                    self._last_notification_hours = 0
                    self._schedule_rebuild()
                    notifications.send("Timer Stopped", f"{dur} - ${amount:.2f}")
                except Exception as e:
                    log.error("Hotkey stop failed: %s", e)
            self._async(do_stop)
        else:
            # Quick start with default rate, no prompts
            portal = get_active_portal()
            rate = portal.get("default_rate", 150.0) if portal else 150.0

            if not self._connected:
                self._queue_action("start", notes="", hourly_rate=rate)
                return

            def do_start():
                client = self._get_client(silent=True)
                if not client:
                    return
                try:
                    result = client.start_timer(notes="", hourly_rate=rate)
                    self._active_entry = result.get("entry")
                    self._last_notification_hours = 0
                    self._schedule_rebuild()
                    portal_name = portal["name"] if portal else "Unknown"
                    notifications.send("Timer Started", f"{portal_name} @ ${rate:.0f}/hr")
                except Exception as e:
                    log.error("Hotkey start failed: %s", e)
            self._async(do_start)

    # ------------------------------------------------------------------ #
    #  Timer actions                                                       #
    # ------------------------------------------------------------------ #

    def _on_start_timer(self, _sender):
        client = self._get_client()
        if not client:
            return

        if self._active_entry:
            self._alert("Timer Already Running", "Stop the current timer before starting a new one.")
            return

        portal = get_active_portal()
        default_rate = portal.get("default_rate", 150.0) if portal else 150.0

        notes_resp = self._prompt(
            title="Start Timer  (1/2)",
            message="What are you working on?",
            ok="Next",
            dimensions=(360, 60),
        )
        if not notes_resp.clicked:
            return
        notes = notes_resp.text.strip()

        rate_resp = self._prompt(
            title="Start Timer  (2/2)",
            message="Hourly rate ($):",
            default_text=f"{default_rate:.2f}",
            ok="Start",
        )
        if not rate_resp.clicked:
            return

        try:
            hourly_rate = float(rate_resp.text.strip())
            if hourly_rate < 0:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Rate must be a positive number.")
            return

        try:
            result = client.start_timer(notes=notes, hourly_rate=hourly_rate)
            self._active_entry = result.get("entry")
            self._last_notification_hours = 0
            self._rebuild_menu()
        except Exception as e:
            self._show_error("Start Timer", e)

    def _on_stop_timer(self, _sender):
        client = self._get_client()
        if not client:
            return

        if not self._active_entry:
            self._alert("No Timer Running", "There is no active timer to stop.")
            return

        try:
            result = client.stop_timer()
            entry = result.get("entry", {})
            dur = format_hours(entry.get("duration_hours"))
            amount = entry.get("total_amount") or 0
            rate = entry.get("hourly_rate") or 0
            notes = entry.get("notes", "") or "No notes"

            self._active_entry = None
            self._last_notification_hours = 0
            self._rebuild_menu()

            self._alert(
                "Timer Stopped",
                f"{notes}\nDuration: {dur}\nRate: ${rate:.2f}/hr\nTotal: ${amount:.2f}",
            )
            notifications.send("Timer Stopped", f"{dur} - ${amount:.2f}")
        except Exception as e:
            self._show_error("Stop Timer", e)

    # ------------------------------------------------------------------ #
    #  Stats & data views                                                  #
    # ------------------------------------------------------------------ #

    def _on_show_stats(self, _sender):
        client = self._get_client()
        if not client:
            return
        try:
            start, end = this_week_range()
            result = client.get_stats(start_date=start, end_date=end)
            stats = result.get("stats", result)
            total_hours = stats.get("total_hours", 0) or 0
            total_amount = stats.get("total_amount", 0) or 0
            entry_count = stats.get("entry_count", stats.get("total_entries", 0)) or 0
            unpaid = stats.get("unpaid_amount", 0) or 0
            portal_name = get_active_portal_name() or "Unknown"
            msg = (
                f"Portal:    {portal_name}\n"
                f"Week:      {start}  to  {end}\n\n"
                f"Entries:   {entry_count}\n"
                f"Hours:     {total_hours:.1f}h\n"
                f"Earned:    ${total_amount:.2f}\n"
                f"Unpaid:    ${unpaid:.2f}"
            )
            self._alert("Weekly Stats", msg)
        except Exception as e:
            self._show_error("Weekly Stats", e)

    def _on_all_portals(self, _sender):
        """Fetch stats from all portals in parallel and display a summary."""
        portals = load_portals()
        if not portals:
            self._alert("No Portals", "Add a portal first.")
            return

        start, end = this_week_range()
        results = {}

        def fetch_portal(p):
            try:
                c = TimeTrackingClient(p["url"], p["api_key"])
                r = c.get_stats(start_date=start, end_date=end)
                return p["name"], r.get("stats", r)
            except Exception as e:
                return p["name"], {"error": str(e)}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_portal, p) for p in portals]
            for f in as_completed(futures):
                name, stats = f.result()
                results[name] = stats

        # Build display
        lines = []
        total_hours = 0
        total_earned = 0
        total_unpaid = 0

        for p in portals:
            s = results.get(p["name"], {})
            if "error" in s:
                lines.append(f"{p['name']}:  error - {s['error'][:40]}")
                continue
            hrs = s.get("total_hours", 0) or 0
            amt = s.get("total_amount", 0) or 0
            unp = s.get("unpaid_amount", 0) or 0
            lines.append(f"{p['name']}:  {hrs:.1f}h  ${amt:.2f}  (${unp:.2f} unpaid)")
            total_hours += hrs
            total_earned += amt
            total_unpaid += unp

        lines.append("")
        lines.append(f"Total:  {total_hours:.1f}h  ${total_earned:.2f}  (${total_unpaid:.2f} unpaid)")

        self._alert("All Portals - This Week", "\n".join(lines))

    def _on_export(self, _sender):
        """Export entries to CSV for a date range."""
        client = self._get_client()
        if not client:
            return

        start_resp = self._prompt(
            title="Export Entries  (1/2)",
            message="Start date (YYYY-MM-DD):",
            default_text=this_week_range()[0],
            ok="Next",
        )
        if not start_resp.clicked:
            return
        start_date = start_resp.text.strip()

        end_resp = self._prompt(
            title="Export Entries  (2/2)",
            message="End date (YYYY-MM-DD):",
            default_text=datetime.now().date().isoformat(),
            ok="Export",
        )
        if not end_resp.clicked:
            return
        end_date = end_resp.text.strip()

        # Validate dates
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            self._alert("Invalid Date", "Dates must be in YYYY-MM-DD format.")
            return

        try:
            result = client.list_entries(start_date=start_date, end_date=end_date)
            entries = result.get("entries", [])
            if not entries:
                self._alert("No Entries", "No entries found for that date range.")
                return

            portal_name = get_active_portal_name() or "export"
            filepath = default_export_path(portal_name, start_date, end_date)
            generate_csv(entries, filepath)

            self._alert("Export Complete", f"Exported {len(entries)} entries to:\n{filepath}")
            subprocess.Popen(["open", "-R", filepath])
        except Exception as e:
            self._show_error("Export", e)

    # ------------------------------------------------------------------ #
    #  Entry management                                                    #
    # ------------------------------------------------------------------ #

    def _on_manage_entries(self, _sender):
        """Fetch recent entries and let the user pick one to manage."""
        client = self._get_client()
        if not client:
            return

        try:
            start, end = this_week_range()
            result = client.list_entries(start_date=start, end_date=end)
            entries = result.get("entries", [])
        except Exception as e:
            self._show_error("Manage Entries", e)
            return

        if not entries:
            self._alert("Manage Entries", "No entries this week.")
            return

        # Show numbered list, let user pick by number
        lines = []
        for i, e in enumerate(entries[:15], 1):
            line = format_entry_line(e)
            lines.append(f"{i}.  {line}")

        msg = "\n".join(lines)
        if len(entries) > 15:
            msg += f"\n\n... and {len(entries) - 15} more"

        resp = self._prompt(
            title=f"Manage Entries  ({len(entries)} this week)",
            message=f"{msg}\n\nEnter the number of an entry to manage:",
            ok="Select",
            dimensions=(420, 40),
        )
        if not resp.clicked:
            return

        try:
            idx = int(resp.text.strip()) - 1
            if idx < 0 or idx >= min(len(entries), 15):
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Enter a valid entry number.")
            return

        self._manage_single_entry(entries[idx], client)

    def _manage_single_entry(self, entry, client):
        """Show action dialog for a single entry."""
        entry_id = entry.get("_id") or entry.get("id")
        notes = entry.get("notes", "") or "No notes"
        dur = format_hours(entry.get("duration_hours"))
        amount = entry.get("total_amount") or 0
        is_paid = entry.get("is_paid", False)

        detail = (
            f"Notes: {notes}\n"
            f"Duration: {dur}\n"
            f"Amount: ${amount:.2f}\n"
            f"Status: {'Paid' if is_paid else 'Unpaid'}"
        )

        choice = self._choice(
            f"Entry: {notes[:30]}",
            detail,
            ["Edit Notes", f"Mark {'Unpaid' if is_paid else 'Paid'}", "Delete", "Cancel"],
        )

        if choice == 0:  # Edit Notes
            resp = self._prompt(
                title="Edit Notes",
                message="Update notes for this entry:",
                default_text=entry.get("notes", ""),
                ok="Save",
                dimensions=(360, 60),
            )
            if resp.clicked:
                try:
                    client.update_entry(entry_id, notes=resp.text.strip())
                    self._alert("Updated", "Notes updated.")
                    self._async(self._refresh_active_timer)
                except Exception as e:
                    self._show_error("Update Entry", e)

        elif choice == 1:  # Toggle paid
            try:
                if is_paid:
                    client.mark_unpaid(entry_id)
                    self._alert("Updated", "Entry marked as unpaid.")
                else:
                    client.mark_paid(entry_id)
                    self._alert("Updated", "Entry marked as paid.")
                self._async(self._refresh_active_timer)
            except Exception as e:
                self._show_error("Update Entry", e)

        elif choice == 2:  # Delete
            if self._confirm("Delete Entry", f"Delete this entry?\n\n{notes}\n{dur} - ${amount:.2f}"):
                try:
                    client.delete_entry(entry_id)
                    self._alert("Deleted", "Entry deleted.")
                    self._async(self._refresh_active_timer)
                except Exception as e:
                    self._show_error("Delete Entry", e)

    def _make_entry_action(self, entry: dict):
        """Create a callback for clicking a specific entry in the submenu."""
        def callback(_sender):
            entry_id = entry.get("_id") or entry.get("id")
            notes = entry.get("notes", "") or "No notes"
            dur = format_hours(entry.get("duration_hours"))
            amount = entry.get("total_amount") or 0
            is_paid = entry.get("is_paid", False)
            paid_str = "Paid" if is_paid else "Unpaid"

            detail = (
                f"Notes: {notes}\n"
                f"Duration: {dur}\n"
                f"Amount: ${amount:.2f}\n"
                f"Status: {paid_str}"
            )

            choice = self._choice(
                f"Entry: {notes[:30]}",
                detail,
                ["Edit Notes", f"Mark {'Unpaid' if is_paid else 'Paid'}", "Delete", "Cancel"],
            )

            client = self._get_client()
            if not client:
                return

            if choice == 0:  # Edit Notes
                resp = self._prompt(
                    title="Edit Notes",
                    message="Update notes for this entry:",
                    default_text=entry.get("notes", ""),
                    ok="Save",
                    dimensions=(360, 60),
                )
                if resp.clicked:
                    try:
                        client.update_entry(entry_id, notes=resp.text.strip())
                        self._alert("Updated", "Notes updated.")
                        self._async(self._refresh_active_timer)
                    except Exception as e:
                        self._show_error("Update Entry", e)

            elif choice == 1:  # Toggle paid
                try:
                    if is_paid:
                        client.mark_unpaid(entry_id)
                        self._alert("Updated", "Entry marked as unpaid.")
                    else:
                        client.mark_paid(entry_id)
                        self._alert("Updated", "Entry marked as paid.")
                    self._async(self._refresh_active_timer)
                except Exception as e:
                    self._show_error("Update Entry", e)

            elif choice == 2:  # Delete
                if self._confirm("Delete Entry", f"Delete this entry?\n\n{notes}\n{dur} - ${amount:.2f}"):
                    try:
                        client.delete_entry(entry_id)
                        self._alert("Deleted", "Entry deleted.")
                        self._async(self._refresh_active_timer)
                    except Exception as e:
                        self._show_error("Delete Entry", e)

            # choice == 3 is Cancel, do nothing

        return callback

    # ------------------------------------------------------------------ #
    #  Portal management                                                   #
    # ------------------------------------------------------------------ #

    def _on_add_portal(self, _sender):
        name_resp = self._prompt(title="Add Portal  (1/4)", message="Portal name:", ok="Next")
        if not name_resp.clicked:
            return
        name = name_resp.text.strip()
        if not name:
            self._alert("Invalid Input", "Portal name cannot be empty.")
            return
        if any(p["name"] == name for p in load_portals()):
            self._alert("Invalid Input", f"A portal named '{name}' already exists.")
            return

        url_resp = self._prompt(
            title="Add Portal  (2/4)", message=f"Backend URL for '{name}':",
            default_text="https://", ok="Next", dimensions=(420, 40),
        )
        if not url_resp.clicked:
            return
        url = url_resp.text.strip()
        if not url or not url.startswith("http"):
            self._alert("Invalid Input", "URL must start with http:// or https://")
            return

        key_resp = self._prompt(
            title="Add Portal  (3/4)", message=f"API key for '{name}':",
            ok="Next", dimensions=(420, 40),
        )
        if not key_resp.clicked:
            return
        api_key = key_resp.text.strip()
        if not api_key:
            self._alert("Invalid Input", "API key cannot be empty.")
            return

        rate_resp = self._prompt(
            title="Add Portal  (4/4)", message=f"Default hourly rate for '{name}' ($):",
            default_text="150.00", ok="Add Portal",
        )
        if not rate_resp.clicked:
            return
        try:
            default_rate = float(rate_resp.text.strip())
            if default_rate < 0:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Rate must be a positive number. Using $150.00.")
            default_rate = 150.0

        add_portal(name, url, api_key, default_rate=default_rate)
        set_active_portal_name(name)
        with self._lock:
            self._client = None

        client = self._get_client(silent=True)
        if client and client.health_check():
            self._alert("Portal Added", f"'{name}' connected successfully.")
        else:
            self._alert(
                "Portal Added",
                f"'{name}' saved, but could not verify the connection.\n\n"
                "Check the URL and API key if time tracking doesn't work.",
            )

        self._rebuild_menu()
        self._async(self._refresh_active_timer)

    def _on_edit_portal(self, _sender):
        portal = get_active_portal()
        if not portal:
            self._alert("No Portal Selected", "Select a portal first.")
            return

        name = portal["name"]
        changes = {}

        name_resp = self._prompt(
            title=f"Edit '{name}'  (1/4)", message="Portal name:",
            default_text=name, ok="Next",
        )
        if not name_resp.clicked:
            return
        new_name = name_resp.text.strip()
        if not new_name:
            self._alert("Invalid Input", "Portal name cannot be empty.")
            return
        if new_name != name and any(p["name"] == new_name for p in load_portals()):
            self._alert("Invalid Input", f"A portal named '{new_name}' already exists.")
            return
        if new_name != name:
            changes["name"] = new_name

        url_resp = self._prompt(
            title=f"Edit '{name}'  (2/4)", message="Backend URL:",
            default_text=portal["url"], ok="Next", dimensions=(420, 40),
        )
        if not url_resp.clicked:
            return
        new_url = url_resp.text.strip().rstrip("/")
        if not new_url or not new_url.startswith("http"):
            self._alert("Invalid Input", "URL must start with http:// or https://")
            return
        if new_url != portal["url"]:
            changes["url"] = new_url

        key_resp = self._prompt(
            title=f"Edit '{name}'  (3/4)", message="API key:",
            default_text=portal["api_key"], ok="Next", dimensions=(420, 40),
        )
        if not key_resp.clicked:
            return
        new_key = key_resp.text.strip()
        if not new_key:
            self._alert("Invalid Input", "API key cannot be empty.")
            return
        if new_key != portal["api_key"]:
            changes["api_key"] = new_key

        current_rate = portal.get("default_rate", 150.0)
        rate_resp = self._prompt(
            title=f"Edit '{name}'  (4/4)", message="Default hourly rate ($):",
            default_text=f"{current_rate:.2f}", ok="Save",
        )
        if not rate_resp.clicked:
            return
        try:
            new_rate = float(rate_resp.text.strip())
            if new_rate < 0:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Rate must be a positive number.")
            return
        if new_rate != current_rate:
            changes["default_rate"] = new_rate

        if not changes:
            self._alert("No Changes", "Nothing was modified.")
            return

        update_portal(name, **changes)
        if "name" in changes:
            set_active_portal_name(changes["name"])
        if "url" in changes or "api_key" in changes:
            with self._lock:
                self._client = None

        self._rebuild_menu()
        self._alert("Portal Updated", f"Updated: {', '.join(changes.keys())}")

    def _on_remove_portal(self, _sender):
        portals = load_portals()
        if not portals:
            self._alert("No Portals", "Nothing to remove.")
            return

        names = [p["name"] for p in portals]
        portal_list = "\n".join(f"  - {n}" for n in names)
        resp = self._prompt(
            title="Remove Portal",
            message=f"Type the exact name of the portal to remove:\n\n{portal_list}",
            ok="Remove",
        )
        if not resp.clicked:
            return

        target = resp.text.strip()
        if target not in names:
            self._alert("Not Found", f"No portal named '{target}'.")
            return

        remove_portal(target)
        if get_active_portal_name() == target:
            remaining = load_portals()
            set_active_portal_name(remaining[0]["name"] if remaining else None)
            with self._lock:
                self._client = None

        self._rebuild_menu()
        self._alert("Portal Removed", f"'{target}' has been removed.")

    def _make_portal_selector(self, name: str):
        def callback(_sender):
            set_active_portal_name(name)
            with self._lock:
                self._client = None
            self._active_entry = None
            self._today_stats = None
            self._recent_entries = []
            self._rebuild_menu()
            self._async(self._refresh_active_timer)
        return callback

    # ------------------------------------------------------------------ #
    #  Launch at Login                                                     #
    # ------------------------------------------------------------------ #

    def _on_toggle_launch(self, sender):
        if launch_agent.is_enabled():
            launch_agent.disable()
            sender.state = False
            self._alert("Launch at Login", "Disabled - app will not start at login.")
        else:
            launch_agent.enable()
            sender.state = True
            self._alert("Launch at Login", "Enabled - app will start when you log in.")

    def _on_set_idle_timeout(self, _sender):
        current = get_pref("idle_timeout_minutes", 5)
        resp = self._prompt(
            title="Idle Timeout",
            message="Minutes of inactivity before idle prompt (0 to disable):",
            default_text=str(current),
            ok="Save",
        )
        if not resp.clicked:
            return
        try:
            val = int(resp.text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Enter a positive number (or 0 to disable).")
            return
        set_pref("idle_timeout_minutes", val)
        self._idle_monitor.idle_threshold = val * 60
        self._rebuild_menu()

    def _on_set_notif_interval(self, _sender):
        current = get_pref("notification_interval_hours", 2)
        resp = self._prompt(
            title="Timer Notifications",
            message="Notify every N hours while timer runs (0 to disable):",
            default_text=str(current),
            ok="Save",
        )
        if not resp.clicked:
            return
        try:
            val = float(resp.text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Enter a positive number (or 0 to disable).")
            return
        set_pref("notification_interval_hours", val)
        self._rebuild_menu()

    def _on_set_refresh_interval(self, _sender):
        current = get_pref("refresh_interval", API_REFRESH_INTERVAL)
        resp = self._prompt(
            title="Refresh Interval",
            message="Seconds between API polls (minimum 10):",
            default_text=str(current),
            ok="Save",
        )
        if not resp.clicked:
            return
        try:
            val = int(resp.text.strip())
            if val < 10:
                raise ValueError
        except ValueError:
            self._alert("Invalid Input", "Enter a number >= 10.")
            return
        set_pref("refresh_interval", val)
        self._api_timer.stop()
        self._api_timer.interval = val
        self._api_timer.start()
        self._rebuild_menu()

    GITHUB_REPO = "East-Lake-Labs/EastLake-Portal-Widget"

    def _on_check_update(self, _sender):
        """Check GitHub releases for a newer version."""
        from eastlake import __version__
        try:
            import requests as req
            url = f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest"
            r = req.get(url, timeout=10, headers={"Accept": "application/vnd.github.v3+json"})

            if r.status_code == 404:
                self._alert("Update Check", f"Current version: {__version__}\n\nNo releases published yet.")
                return

            r.raise_for_status()
            data = r.json()
            latest_tag = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "")[:200]

            if not latest_tag:
                self._alert("Update Check", f"Current version: {__version__}\n\nCould not parse latest release.")
                return

            if latest_tag != __version__:
                choice = self._choice(
                    "Update Available",
                    f"Current: v{__version__}\n"
                    f"Latest:  v{latest_tag}\n\n"
                    f"{release_notes}",
                    ["Open in Browser", "Later"],
                )
                if choice == 0 and release_url:
                    subprocess.Popen(["open", release_url])
            else:
                self._alert("Up to Date", f"v{__version__} is the latest release.")

        except Exception as e:
            log.debug("Update check failed: %s", e)
            self._alert("Update Check", f"Current version: {__version__}\n\nCould not reach GitHub.")

    # ------------------------------------------------------------------ #
    #  Offline queue                                                       #
    # ------------------------------------------------------------------ #

    def _queue_action(self, action_type: str, **kwargs):
        """Queue an action for when connection returns."""
        self._offline_queue.append({"type": action_type, **kwargs})
        notifications.send("Queued (Offline)", f"{action_type} will sync when online.")

    def _process_offline_queue(self, client):
        """Process queued actions after connection is restored."""
        if not self._offline_queue:
            return
        queue = self._offline_queue[:]
        self._offline_queue.clear()
        processed = 0
        for action in queue:
            try:
                if action["type"] == "start":
                    client.start_timer(
                        notes=action.get("notes", ""),
                        hourly_rate=action.get("hourly_rate"),
                    )
                    processed += 1
                elif action["type"] == "stop":
                    client.stop_timer()
                    processed += 1
            except Exception as e:
                log.warning("Failed to process queued action %s: %s", action["type"], e)
        if processed:
            notifications.send("Synced", f"Processed {processed} queued action(s).")

    # ------------------------------------------------------------------ #
    #  Quit                                                                #
    # ------------------------------------------------------------------ #

    def _on_quit(self, _sender):
        self._hotkey.stop()
        rumps.quit_application()


if __name__ == "__main__":
    EastLakeApp().run()
