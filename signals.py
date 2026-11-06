from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)


def frontmost_app() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else None


def idle_seconds() -> float:
    return CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType)
