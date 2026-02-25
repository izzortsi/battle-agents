#!/bin/bash
set -euo pipefail

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ICON_PATH="$SCRIPT_DIR/icons/app.png"
LAUNCHER="$SCRIPT_DIR/launch.sh"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/battle-agents.desktop"

echo "=== Battle-Agents Desktop Installer ==="
echo "  App root:  $APP_ROOT"
echo "  Icon:      $ICON_PATH"
echo "  Launcher:  $LAUNCHER"
echo "  Target:    $DESKTOP_FILE"
echo

# Ensure PNG icon exists
if [ ! -f "$ICON_PATH" ]; then
    SVG_PATH="$SCRIPT_DIR/icons/app.svg"
    CONVERT_SCRIPT="$SCRIPT_DIR/icons/convert.sh"

    if [ -f "$CONVERT_SCRIPT" ] && [ -f "$SVG_PATH" ]; then
        echo "[icon] app.png not found — generating from SVG..."
        chmod +x "$CONVERT_SCRIPT"
        "$CONVERT_SCRIPT"
    else
        echo "[warning] No app.png and no convert script. Launcher will use a generic icon."
        ICON_PATH=""
    fi
fi

# Detect npm path (desktop environments don't source shell profiles)
NPM_PATH="$(command -v npm 2>/dev/null || true)"
if [ -z "$NPM_PATH" ]; then
    echo "[error] npm not found on PATH. Install Node.js first."
    exit 1
fi
NODE_BIN_DIR="$(dirname "$NPM_PATH")"

# Create launcher script (bash handles $PATH expansion; env binary does not)
cat > "$LAUNCHER" <<EOF
#!/bin/bash
export PATH="$NODE_BIN_DIR:\$PATH"
cd "$APP_ROOT"
exec npm start
EOF
chmod +x "$LAUNCHER"
echo "[launcher] Created $LAUNCHER"

# Ensure target directory exists
mkdir -p "$DESKTOP_DIR"

# Write .desktop file
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Battle-Agents
Comment=Ontology-driven generative combat agents
Exec=$LAUNCHER
Icon=${ICON_PATH:-application-x-executable}
Terminal=false
StartupNotify=true
Categories=Game;Development;Simulation;
Keywords=battle;agents;llm;tactics;
EOF

chmod +x "$DESKTOP_FILE"

# Update desktop database if available
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo
echo "✓ Desktop entry installed: $DESKTOP_FILE"
echo "  You can now search for 'Battle-Agents' in your application launcher."
echo
echo "  To uninstall:  rm '$DESKTOP_FILE' '$LAUNCHER'"
