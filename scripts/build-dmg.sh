#!/bin/bash
# Build a distributable DMG with drag-to-Applications layout
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_NAME="East Lake Time Tracker"
APP_PATH="$PROJECT_ROOT/dist/$APP_NAME.app"
DMG_NAME="East-Lake-Time-Tracker"
DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME.dmg"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$PROJECT_ROOT/src'); from eastlake import __version__; print(__version__)")
DMG_FINAL="$PROJECT_ROOT/dist/${DMG_NAME}-v${VERSION}.dmg"

echo "Building DMG for $APP_NAME v$VERSION..."

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run PyInstaller first."
    exit 1
fi

# Clean up any previous DMG
rm -f "$DMG_PATH" "$DMG_FINAL"

# Create a temporary directory for DMG contents
DMG_TEMP="$PROJECT_ROOT/dist/dmg-staging"
rm -rf "$DMG_TEMP"
mkdir -p "$DMG_TEMP"

# Copy the app
cp -R "$APP_PATH" "$DMG_TEMP/"

# Create Applications symlink for drag-to-install
ln -s /Applications "$DMG_TEMP/Applications"

# Create the DMG
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_TEMP" \
    -ov \
    -format UDZO \
    "$DMG_FINAL"

# Clean up staging
rm -rf "$DMG_TEMP"

echo ""
echo "DMG created: $DMG_FINAL"
echo "Size: $(du -h "$DMG_FINAL" | cut -f1)"
echo ""
echo "To distribute:"
echo "  1. Upload to GitHub Releases"
echo "  2. Users download the .dmg, open it, drag to Applications"
