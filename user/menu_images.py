"""Small, local WebP menu photos shared by API and dummy menus."""
import base64
from functools import lru_cache
from html import escape
from pathlib import Path


ASSET_DIR = Path(__file__).resolve().parent / "assets" / "menu"
PHOTO_IDS = frozenset({
    "c1", "c1-seasoned", "c1-halfhalf", "c2", "c3", "c4", "c5", "c6", "c7",
    *(f"a{i}" for i in range(1, 12)),
    *(f"s{i}" for i in range(1, 6)),
    *(f"d{i}" for i in range(1, 9)),
    *(f"b{i}" for i in range(1, 10)),
    *(f"j{i}" for i in range(1, 8)),
    "j5-grapefruit", "j5-ginger", "j6-grape", "j6-peach",
})
PHOTO_ALIASES = {
    "c1-whole-seasoned": "c1-seasoned",
    "c1-whole-halfhalf": "c1-halfhalf",
    "c1-half-fried": "c1",
    "c1-half-seasoned": "c1-seasoned",
    "c1-half-halfhalf": "c1-halfhalf",
    "a2-medium": "a2", "a2-hot": "a2",
    "a3-medium": "a3", "a3-hot": "a3",
}


@lru_cache(maxsize=64)
def _photo_uri(photo_id):
    """Encode once per shared photo; load only photos requested by the screen."""
    path = ASSET_DIR / f"{photo_id}.webp"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")


def bundled_photo_uri(menu_id):
    """Data URI of the bundled photo for a menu id (aliases resolved), or None."""
    photo_id = PHOTO_ALIASES.get(menu_id, menu_id)
    return _photo_uri(photo_id) if photo_id in PHOTO_IDS else None


def menu_image_html(item, photo_class="menu-photo", fallback_class=None):
    """Prefer a configured photo, then a bundled photo, then the menu emoji."""
    source = item.get("image_url") or ""
    if not source.startswith(("https://", "http://")):
        source = bundled_photo_uri(item["id"])
    if source:
        if item.get("cat") in {"beer", "soju"} or item["id"] in {"d1", "d2"}:
            photo_class += " beverage-photo"
        return (f'<img class="{escape(photo_class, quote=True)}" '
                f'src="{escape(source, quote=True)}" '
                f'alt="{escape(item["name"], quote=True)}" '
                'width="308" height="308" loading="lazy" decoding="async">')
    emoji = escape(item.get("emoji", "🍽️"))
    if fallback_class:
        return f'<span class="{escape(fallback_class, quote=True)}">{emoji}</span>'
    return emoji
