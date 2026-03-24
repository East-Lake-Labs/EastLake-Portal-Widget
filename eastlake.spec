# PyInstaller spec file for East Lake Time Tracker

import os
import sys

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('assets/icon.png', 'assets'),
        ('assets/icon_menubar.png', 'assets'),
        ('assets/icon.icns', 'assets'),
    ],
    hiddenimports=[
        'rumps',
        'requests',
        'certifi',
        'Quartz',
        'AppKit',
        'Foundation',
        'objc',
        'eastlake',
        'eastlake.app',
        'eastlake.api_client',
        'eastlake.config',
        'eastlake.export',
        'eastlake.hotkey',
        'eastlake.idle_monitor',
        'eastlake.launch_agent',
        'eastlake.notifications',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy'],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='East Lake Time Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='East Lake Time Tracker',
)

app = BUNDLE(
    coll,
    name='East Lake Time Tracker.app',
    icon='assets/icon.icns',
    bundle_identifier='io.eastlake.time-tracker',
    info_plist={
        'CFBundleName': 'East Lake Time Tracker',
        'CFBundleDisplayName': 'East Lake Time Tracker',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,
        'NSAppleEventsUsageDescription': 'East Lake needs permission to send notifications.',
        'LSMinimumSystemVersion': '12.0',
    },
)
