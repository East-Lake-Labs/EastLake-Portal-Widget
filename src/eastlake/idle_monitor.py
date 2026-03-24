"""Idle detection via Quartz + sleep/wake via NSWorkspace."""

import logging
from datetime import datetime, timedelta

import AppKit
import Quartz

log = logging.getLogger(__name__)


class IdleMonitor:
    """Tracks user idle time and system sleep/wake events.

    Call check() from a 1-second timer. When the user returns from being idle
    longer than the threshold, on_idle_return(idle_seconds, idle_started_at) fires.
    Sleep/wake events call on_wake(sleep_seconds).
    """

    def __init__(
        self,
        idle_threshold_seconds: int = 300,
        on_idle_return=None,
        on_wake=None,
    ):
        self.idle_threshold = idle_threshold_seconds
        self.on_idle_return = on_idle_return
        self.on_wake = on_wake

        self._was_idle = False
        self._idle_started_at = None
        self._sleep_started_at = None

        self._register_sleep_wake()

    def get_idle_seconds(self) -> float:
        """Seconds since the last keyboard/mouse/trackpad event."""
        return Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateCombinedSessionState,
            Quartz.kCGAnyInputEventType,
        )

    def check(self):
        """Call every tick. Detects idle -> active transitions."""
        idle = self.get_idle_seconds()

        if idle > self.idle_threshold:
            if not self._was_idle:
                self._was_idle = True
                self._idle_started_at = datetime.now() - timedelta(seconds=idle)
        elif self._was_idle:
            # User just came back
            self._was_idle = False
            if self.on_idle_return and self._idle_started_at:
                idle_duration = (datetime.now() - self._idle_started_at).total_seconds()
                self.on_idle_return(idle_duration, self._idle_started_at)
            self._idle_started_at = None

    def _register_sleep_wake(self):
        """Register for macOS sleep/wake notifications using block-based API."""
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()

        def on_sleep(notification):
            self._sleep_started_at = datetime.now()
            log.debug("System entering sleep")

        def on_wake(notification):
            if self._sleep_started_at and self.on_wake:
                sleep_duration = (datetime.now() - self._sleep_started_at).total_seconds()
                self.on_wake(sleep_duration)
            self._sleep_started_at = None
            log.debug("System woke up")

        nc.addObserverForName_object_queue_usingBlock_(
            AppKit.NSWorkspaceWillSleepNotification, None, None, on_sleep,
        )
        nc.addObserverForName_object_queue_usingBlock_(
            AppKit.NSWorkspaceDidWakeNotification, None, None, on_wake,
        )
