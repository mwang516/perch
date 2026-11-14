#!/bin/zsh
# Installs Perch as a menu bar app that starts at login.
#
#   alwayson/install.sh            build Perch.app, register it to start at login, and start it now
#   alwayson/install.sh --no-login build Perch.app only (start it yourself from ~/Applications)
#
# Stop a running `python desk.py` first: two agents would both write observations.
# Undo with alwayson/uninstall.sh.
set -euo pipefail

PROJECT="${0:A:h:h}"
APP="$HOME/Applications/Perch.app"
LABEL="com.perch.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/Perch.log"

if pgrep -f "desk.py" >/dev/null; then
  echo "A 'python desk.py' agent is still running. Stop it with Ctrl+C first, then run this again." >&2
  exit 1
fi

echo "1/4 Python and dashboard"
"$PROJECT/.venv/bin/python" -m pip install -q -r "$PROJECT/requirements.txt"
npm --prefix "$PROJECT/dashboard" install --silent
npm --prefix "$PROJECT/dashboard" run build --silent

echo "2/4 Building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
clang -O2 -DPROJECT_DIR="\"$PROJECT\"" -o "$APP/Contents/MacOS/Perch" "$PROJECT/alwayson/launcher.c"
cat > "$APP/Contents/Info.plist" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Perch</string>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleExecutable</key><string>Perch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSUIElement</key><true/>
  <key>NSCameraUsageDescription</key>
  <string>Perch watches your desk through the camera to log how you spend your desk time.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>Perch reads the domain of the active Chrome tab to tag coding time.</string>
</dict>
</plist>
PLIST_END
codesign --force --sign - "$APP"

if [[ "${1:-}" == "--no-login" ]]; then
  echo "Built. Start it with: open \"$APP\""
  exit 0
fi

echo "3/4 Registering to start at login"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Perch</string></array>
  <key>AssociatedBundleIdentifiers</key><string>$LABEL</string>
  <key>RunAtLoad</key><true/>
  <!-- Restart after a failure, but stay stopped after Quit Perch. -->
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
</dict>
</plist>
PLIST_END
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

echo "4/4 Started"
cat <<DONE

Perch is in the menu bar (a bird icon) and will start at login.
  - macOS will ask for Camera access, and for access to the Desktop folder (the project lives there).
    Allow both. The first time Chrome is frontmost it also asks to control Chrome.
  - If the menu says "Waiting for Perch Camera" after you allowed the camera, choose Quit Perch
    and run: launchctl kickstart gui/$UID/$LABEL
  - Dashboard: http://localhost:8765   Log: $LOG
DONE
