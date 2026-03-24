"""macOS native notifications via NSUserNotificationCenter."""

import logging
import objc
import AppKit
from Foundation import NSObject

log = logging.getLogger(__name__)


class _NotificationDelegate(NSObject):
    """Delegate that ensures notifications display even when app is frontmost."""

    def userNotificationCenter_shouldPresentNotification_(self, center, notification):
        return True


_delegate = None


def _get_center():
    """Get the notification center and install our delegate."""
    global _delegate
    center = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
    if _delegate is None:
        _delegate = _NotificationDelegate.alloc().init()
        center.setDelegate_(_delegate)
    return center


def send(title: str, message: str, sound: bool = True):
    """Send a native macOS notification with the app's icon."""
    try:
        notification = AppKit.NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        if sound:
            notification.setSoundName_(AppKit.NSUserNotificationDefaultSoundName)

        center = _get_center()
        center.deliverNotification_(notification)
    except Exception as e:
        log.debug("Notification failed: %s", e)
