import io

from PIL import Image as PILImage, ImageOps
from typesafe_sdk import Choice, Noul

MODEL = "jev-1.14.0"
HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}

QUESTIONS = {
    "person_present": Noul(
        instructions="Is a person sitting in the desk chair in `desk`?",
        criteria={"true": "A person is physically in the chair, not on a screen.", "false": None},
    ),
    "tablet_gaming": Noul(
        instructions="Is the person in `desk` playing a game on an iPad lying flat on the desk?",
        criteria={
            "true": "Tapping on an iPad lying flat on the desk in front of the keyboard. The iPad may be partly hidden by the person's body or arms.",
            "false": "No iPad in use. Typing, using the mouse, using a phone, or holding any other object doesn't count.",
        },
    ),
    "activity": Choice(
        instructions="What is the person at the desk in `desk` doing?",
        criteria={
            "computer": "Using the computer: typing on the keyboard, using the mouse, or looking at the monitor or laptop.",
            "gaming": (
                "Playing a game in one of exactly three ways: tapping on an iPad lying flat on the desk, or the iPad is open with game content; "
                "a pair of purple hexagonal controllers with white keys are fully visible (may or may not be in use) on the desk; "
                "or drawing with a pen on a pen tablet while the other hand is on the keyboard."
            ),
            "other": (
                "At the desk doing something else, such as holding or fiddling with a small object "
                "(a toy, a puzzle, a Rubik's cube), using a phone, eating or drinking, or resting."
            ),
            "nobody": "No one at the desk.",
        },
    ),
    "camera_ok": Noul(
        instructions="Is the camera working normally in `desk`?",
        criteria={
            "true": "The image clearly shows a room with a desk. A person may or may not be sitting at the desk, and covering part of it is normal.",
            "false": "The image is mostly black, covered, blurry, or pointed away from the desk.",
        },
    ),
    "controllers_out": Noul(
        instructions="Are the two purple hexagonal controllers on the desk in `desk`?",
        criteria={"true": "Two purple hexagonal boxes with white keys are on the desk.", "false": None},
    ),
}

NOULS = ["person_present", "tablet_gaming", "controllers_out", "camera_ok"]


def prep(img: PILImage.Image) -> bytes | None:
    img = ImageOps.exif_transpose(img)
    img.thumbnail((1568, 1568))
    if min(img.size) < 280:
        return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()
