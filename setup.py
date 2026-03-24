"""py2app setup - bundles the menu bar widget into a standalone .app."""

from setuptools import setup

APP = ["run.py"]
DATA_FILES = [("assets", ["assets/icon_menubar.png", "assets/icon.png"])]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/icon.icns",
    "plist": {
        "CFBundleName": "East Lake Time Tracker",
        "CFBundleDisplayName": "East Lake Time Tracker",
        "CFBundleIdentifier": "io.eastlake.time-tracker",
        "CFBundleIconFile": "icon.icns",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSAppleEventsUsageDescription": "East Lake needs permission to send notifications.",
    },
    "packages": ["rumps", "requests", "certifi", "eastlake"],
    "includes": ["Quartz"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
    package_dir={"": "src"},
)
