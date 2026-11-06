import subprocess
from urllib.parse import urlparse

from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)

_CHROME_URL_SCRIPT = """
tell application "Google Chrome"
    if (count of windows) is 0 then return ""
    if mode of front window is "incognito" then return ""
    return URL of active tab of front window
end tell
"""


def frontmost_app() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else None


def idle_seconds() -> float:
    return CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType)


def chrome_domain() -> str | None:
    try:
        out = subprocess.run(["osascript", "-e", _CHROME_URL_SCRIPT], capture_output=True, text=True, timeout=2)
    except subprocess.TimeoutExpired:
        return None
    host = urlparse(out.stdout.strip()).hostname
    return host.removeprefix("www.") if host else None
