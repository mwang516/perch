#!/bin/zsh
# Removes the menu bar app and its start-at-login entry. Data (perch.db, thumbnails) is untouched.
set -uo pipefail
LABEL="com.perch.agent"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && echo "stopped $LABEL"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Perch.app"
echo "Removed. Run the agent by hand again with: .venv/bin/python desk.py"
