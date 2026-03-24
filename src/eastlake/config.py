"""Portal configuration management - load/save portal configs from a local JSON file."""

import json
import logging
import os

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.eastlake-menu-widget")
PORTALS_FILE = os.path.join(CONFIG_DIR, "portals.json")
PREFS_FILE = os.path.join(CONFIG_DIR, "prefs.json")


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _read_json(path: str, default=None):
    """Safely read a JSON file, returning default on any failure."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read %s: %s", path, e)
    return default


def _write_json(path: str, data):
    """Safely write JSON, using atomic write to avoid corruption."""
    _ensure_config_dir()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def load_portals() -> list[dict]:
    """Load portal configs from disk. Returns list of {name, url, api_key}."""
    _ensure_config_dir()
    return _read_json(PORTALS_FILE, default=[])


def save_portals(portals: list[dict]):
    """Persist portal configs to disk."""
    _write_json(PORTALS_FILE, portals)


def add_portal(name: str, url: str, api_key: str, default_rate: float = 150.0) -> list[dict]:
    """Add a new portal and return updated list."""
    portals = load_portals()
    url = url.rstrip("/")
    portals.append({
        "name": name,
        "url": url,
        "api_key": api_key,
        "default_rate": default_rate,
    })
    save_portals(portals)
    return portals


def update_portal(name: str, **fields) -> list[dict]:
    """Update fields on an existing portal by name."""
    portals = load_portals()
    for p in portals:
        if p["name"] == name:
            p.update(fields)
            break
    save_portals(portals)
    return portals


def remove_portal(name: str) -> list[dict]:
    """Remove a portal by name and return updated list."""
    portals = load_portals()
    portals = [p for p in portals if p["name"] != name]
    save_portals(portals)
    return portals


def get_active_portal_name() -> str | None:
    """Get the name of the currently selected portal."""
    _ensure_config_dir()
    prefs = _read_json(PREFS_FILE, default={})
    return prefs.get("active_portal")


def set_active_portal_name(name: str | None):
    """Set the currently selected portal."""
    _ensure_config_dir()
    prefs = _read_json(PREFS_FILE, default={})
    prefs["active_portal"] = name
    _write_json(PREFS_FILE, prefs)


def get_pref(key: str, default=None):
    """Read a single preference value."""
    _ensure_config_dir()
    prefs = _read_json(PREFS_FILE, default={})
    return prefs.get(key, default)


def set_pref(key: str, value):
    """Write a single preference value."""
    _ensure_config_dir()
    prefs = _read_json(PREFS_FILE, default={})
    prefs[key] = value
    _write_json(PREFS_FILE, prefs)


def get_active_portal() -> dict | None:
    """Get the full config for the currently selected portal."""
    name = get_active_portal_name()
    if not name:
        return None
    for p in load_portals():
        if p["name"] == name:
            return p
    return None
