#!/bin/bash
# Build a distributable DMG with styled drag-to-Applications layout
# Requires: brew install create-dmg
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_NAME="East Lake Time Tracker"
APP_PATH="$PROJECT_ROOT/dist/$APP_NAME.app"
DMG_NAME="East-Lake-Time-Tracker"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$PROJECT_ROOT/src'); from eastlake import __version__; print(__version__)")
DMG_FINAL="$PROJECT_ROOT/dist/${DMG_NAME}-v${VERSION}.dmg"

echo "Building DMG for $APP_NAME v$VERSION..."

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run PyInstaller first."
    exit 1
fi

rm -f "$DMG_FINAL"

create-dmg \
    --volname "$APP_NAME" \
    --volicon "$PROJECT_ROOT/assets/icon.icns" \
    --background "$PROJECT_ROOT/assets/dmg_background.png" \
    --window-pos 200 120 \
    --window-size 835 600 \
    --icon-size 128 \
    --text-size 13 \
    --icon "$APP_NAME.app" 230 295 \
    --hide-extension "$APP_NAME.app" \
    --app-drop-link 593 295 \
    --no-internet-enable \
    --filesystem HFS+ \
    "$DMG_FINAL" \
    "$APP_PATH"

echo ""
echo "DMG created: $DMG_FINAL"
echo "Size: $(du -h "$DMG_FINAL" | cut -f1)"
echo ""
echo "To distribute:"
echo "  1. Upload to GitHub Releases"
echo "  2. Users download the .dmg, open it, drag to Applications"
