"""Download horse photos from Wikimedia Commons and record their attribution.

Reads backend/horse_tinder/horses.json, fetches a resized copy of each
`photo_title` into frontend/img/<slug>.jpg and writes the author, license and
source URL back into the JSON file. Stdlib only, so it runs anywhere.

    python3 scripts/fetch_photos.py
"""

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HORSES = ROOT / "backend" / "horse_tinder" / "horses.json"
IMG_DIR = ROOT / "frontend" / "img"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "horse-tinder/0.1 (demo app; photo fetcher)"
WIDTH = 900


def get(url: str, attempts: int = 6) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                time.sleep(1)  # be polite to Wikimedia
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code != 429 or attempt == attempts - 1:
                raise
            delay = int(err.headers.get("Retry-After") or 0) or 2**attempt * 5
            print(f"  rate limited, waiting {delay}s")
            time.sleep(delay)
    raise AssertionError("unreachable")


def strip_tags(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value)).split())


def image_info(title: str) -> dict:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": WIDTH,
        }
    )
    data = json.loads(get(f"{API}?{query}"))
    page = next(iter(data["query"]["pages"].values()))
    return page["imageinfo"][0]


def main() -> None:
    horses = json.loads(HORSES.read_text())
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for horse in horses:
        info = image_info(horse["photo_title"])
        meta = info["extmetadata"]
        target = IMG_DIR / f"{horse['slug']}.jpg"
        if not target.exists():
            target.write_bytes(get(info["thumburl"]))
        horse["photo"] = f"img/{target.name}"
        horse["photo_artist"] = strip_tags(meta.get("Artist", {}).get("value", "Unknown"))
        horse["photo_license"] = meta.get("LicenseShortName", {}).get("value", "Unknown")
        horse["photo_source"] = info["descriptionurl"]
        print(f"{horse['slug']}: {horse['photo_artist']} ({horse['photo_license']})")
    HORSES.write_text(json.dumps(horses, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
