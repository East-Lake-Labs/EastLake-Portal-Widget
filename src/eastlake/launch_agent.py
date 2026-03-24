"""LaunchAgent management for Launch at Login."""

import logging
import os
import plistlib
import subprocess
import sys

log = logging.getLogger(__name__)

LABEL = "io.eastlake.time-tracker"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def is_enabled() -> bool:
    """Check if the launch agent plist exists."""
    return os.path.exists(PLIST_PATH)


def enable():
    """Create the LaunchAgent plist to run the app at login."""
    plist = {
        "Label": LABEL,
        "ProgramArguments": _get_program_args(),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": f"/tmp/{LABEL}.log",
        "StandardErrorPath": f"/tmp/{LABEL}.error.log",
    }

    # If running as a script, set working directory
    if not getattr(sys, "frozen", False):
        plist["WorkingDirectory"] = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)

    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)
    os.chmod(PLIST_PATH, 0o644)

    log.info("Launch agent created at %s", PLIST_PATH)


def disable():
    """Remove the LaunchAgent plist."""
    if os.path.exists(PLIST_PATH):
        os.remove(PLIST_PATH)
        log.info("Launch agent removed")


def _get_program_args() -> list[str]:
    """Determine the correct program arguments for the launch agent."""
    if getattr(sys, "frozen", False):
        # Bundled .app - use the binary inside the bundle
        return [sys.executable]
    else:
        # Running as a script - use the venv python + app.py
        return [sys.executable, os.path.abspath("app.py")]
