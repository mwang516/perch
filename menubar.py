"""Menu bar app: the agent plus the dashboard server, with Pause / Resume / Quit.

Run through alwayson/install.sh, which wraps it in Perch.app so macOS can grant it camera access under
its own name and start it at login. For a quick look without installing: `python menubar.py` from a
terminal that already has camera permission.
"""

import subprocess
import sys
import webbrowser

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

import config
from desk import Agent

DASHBOARD_URL = f"http://localhost:{config.DASHBOARD_PORT}"
ICONS = {"computer": "💻", "gaming": "🎮", "other": "☕", "away": "🚪", "unknown": "❔"}


class PerchApp(rumps.App):
    def __init__(self):
        super().__init__("Perch", title="🐦", quit_button=None)
        self.agent = Agent()
        self.end_reason = "quit"
        self.status_item = rumps.MenuItem("Starting…")
        self.pause_item = rumps.MenuItem("Pause tracking", callback=self.toggle_pause)
        self.menu = [
            self.status_item,
            None,
            self.pause_item,
            rumps.MenuItem("Open dashboard", callback=lambda _: webbrowser.open(DASHBOARD_URL)),
            None,
            rumps.MenuItem("Quit Perch", callback=self.quit),
        ]
        # The dashboard API as a child process, so one app gives both. If the port is taken (a dev server
        # is already running) the child just exits and that server is used instead.
        self.api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(config.DASHBOARD_PORT)],
            cwd=config.BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.timer = rumps.Timer(self.tick, config.TICK_S)
        self.timer.start()

    def tick(self, _) -> None:
        try:
            self.agent.tick()
        except Exception as e:
            # Leave through the normal quit path so the session is closed with reason "error";
            # launchd restarts the app after a failure.
            print(f"agent error: {type(e).__name__}: {e}")
            self.end_reason = "error"
            self.quit(None)
            return
        status = self.agent.status
        if self.status_item.title != status:
            self.status_item.title = status
        mode = self.agent.live_mode.state.mode
        title = "⏸" if self.agent.paused else ICONS.get(mode, "🐦") if self.agent.connected else "🐦"
        if self.title != title:
            self.title = title

    def toggle_pause(self, sender) -> None:
        if self.agent.paused:
            self.agent.resume()
            sender.title = "Pause tracking"
        else:
            self.agent.pause()
            sender.title = "Resume tracking"

    def quit(self, _) -> None:
        self.timer.stop()
        self.agent.close(self.end_reason)
        self.api.terminate()
        rumps.quit_application()
        if self.end_reason == "error":
            sys.exit(1)


if __name__ == "__main__":
    # No Dock icon: this is a menu bar app.
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    PerchApp().run()
