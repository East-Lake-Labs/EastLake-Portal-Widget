"""Global keyboard shortcut registration via NSEvent."""

import logging

import AppKit

log = logging.getLogger(__name__)

# The key character to match (case-insensitive, ignoring modifiers)
HOTKEY_CHAR = "j"


class GlobalHotkeyMonitor:
    """Registers Cmd+Shift+J as a system-wide hotkey.

    Requires Accessibility permission in System Settings > Privacy & Security.
    """

    def __init__(self, callback):
        self._callback = callback
        self._monitor = None

    def start(self) -> bool:
        """Start monitoring. Returns False if permission was likely denied."""
        mask = AppKit.NSEventMaskKeyDown

        def handler(event):
            flags = event.modifierFlags()
            has_cmd = bool(flags & AppKit.NSEventModifierFlagCommand)
            has_shift = bool(flags & AppKit.NSEventModifierFlagShift)
            if has_cmd and has_shift:
                chars = event.charactersIgnoringModifiers()
                if chars and chars.lower() == HOTKEY_CHAR:
                    self._callback()

        self._monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, handler
        )

        if self._monitor is None:
            log.warning("Global hotkey monitor returned None - Accessibility permission likely denied")
            return False

        log.info("Global hotkey Cmd+Shift+J registered successfully")
        return True

    def stop(self):
        if self._monitor:
            AppKit.NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
