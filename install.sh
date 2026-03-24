#!/bin/bash
# Install East Lake Time Tracker to Applications folder
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="East Lake Time Tracker"
APP_SRC="$SCRIPT_DIR/dist/$APP_NAME.app"
APP_DEST="/Applications/$APP_NAME.app"

if [ ! -d "$APP_SRC" ]; then
    echo "Error: $APP_SRC not found."
    echo "Run 'python setup.py py2app -A' first to build the app."
    exit 1
fi

echo "Installing $APP_NAME to /Applications..."

# Remove old version if exists
if [ -d "$APP_DEST" ]; then
    echo "Removing existing installation..."
    rm -rf "$APP_DEST"
fi

cp -R "$APP_SRC" "$APP_DEST"
echo "Installed to $APP_DEST"
echo ""
echo "You can now:"
echo "  - Find it in Spotlight (Cmd+Space, type 'East Lake')"
echo "  - Open it from /Applications"
echo "  - Drag it to your Dock for quick access"
echo "  - Enable 'Launch at Login' from the menu bar widget"
