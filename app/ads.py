"""Side-rail ad slots, one image per side.

Drop an image into app/static/ads/ named after its slot — left.png, right.jpg —
and it appears on every page. Any format in AD_EXTENSIONS works, and the image
is scaled to fit the rail, so it does not have to be exactly 160x600. With no
file present the slot renders a dashed "your ad here" box instead, so the
layout looks the same whether or not artwork has been picked yet.

An optional click-through and alt text come from the environment:

    AD_LEFT_HREF=https://example.com
    AD_LEFT_ALT=Some sponsor

Slots are resolved once at startup, like the draft CSVs, so rendering a page
costs no filesystem calls. Adding an image means restarting the app to see it.
"""
from __future__ import annotations

import os

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ADS_DIR = os.path.join(STATIC_DIR, "ads")

# Browser-safe formats. Order decides the winner if a slot has two files.
AD_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")

SLOTS = ("left", "right")


def _find_image(slot: str) -> str | None:
    """URL for this slot's image, or None when nothing has been dropped in yet."""
    for ext in AD_EXTENSIONS:
        name = f"{slot}{ext}"
        if os.path.exists(os.path.join(ADS_DIR, name)):
            return f"/static/ads/{name}"
    return None


def ad_slots() -> dict[str, dict]:
    """Both slots, ready to render.

    Call this after load_dotenv() — the href and alt come from the environment.
    """
    return {
        slot: {
            "side": slot,
            "src": _find_image(slot),
            "href": os.getenv(f"AD_{slot.upper()}_HREF", ""),
            "alt": os.getenv(f"AD_{slot.upper()}_ALT", f"{slot.title()} advertisement"),
        }
        for slot in SLOTS
    }
