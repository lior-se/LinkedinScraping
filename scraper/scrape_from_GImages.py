import re
import base64
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from utils.json_store import (
    load_person,
    upsert_candidate,
    candidate_has_photo,
    NO_IMAGE_TOKEN,
)

GOOGLE_IMG = "https://www.google.com/search?udm=2&tbm=isch&hl=en&q={q}"



def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "image"


def _profile_handle(url: str) -> str:
    try:
        parts = [x for x in urlparse(url).path.split("/") if x]
        if len(parts) >= 2 and parts[0] == "in":
            return parts[1]
    except Exception:
        pass
    return _slugify(url)


def _unwrap_google_href(href: str) -> str:
    """Unwrap /url?url=... style Google redirects to the real URL if present."""
    try:
        p = urlparse(href)
        if p.path == "/url":
            target = (parse_qs(p.query).get("url") or [None])[0]
            if target:
                return unquote(target)
    except Exception:
        pass
    return href


def _normalize_profile_url(u: str) -> str | None:
    """Canonicalize to https://www.linkedin.com/in/<handle> when possible."""
    try:
        p = urlparse(u)
        if "linkedin.com" not in p.netloc:
            return None
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] == "in":
            return f"https://www.linkedin.com/in/{parts[1]}"
        return f"{p.scheme}://{p.netloc}{p.path}"
    except Exception:
        return None


def _parse_data_url(data_url: str) -> tuple[str, bytes] | None:
    if not (data_url and data_url.startswith("data:image/")):
        return None
    m = re.match(r"^data:(image/[^;]+);base64,(.+)$", data_url, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    mime = m.group(1).lower()
    b64 = m.group(2)
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    ext = ".bin"
    if mime in ("image/jpeg", "image/jpg"):
        ext = ".jpg"
    elif mime == "image/png":
        ext = ".png"
    elif mime == "image/webp":
        ext = ".webp"
    return ext, raw


def _title_to_name(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        return ""
    return re.split(r"\s[-–—]\s", title, maxsplit=1)[0].strip()


def _is_tiny_icon(img_el) -> bool:
    try:
        w = img_el.get_attribute("width")
        h = img_el.get_attribute("height")
        w = int(w) if (w and w.isdigit()) else 0
        h = int(h) if (h and h.isdigit()) else 0
        return (w and w < 80) or (h and h < 80)
    except Exception:
        return False


def _class_contains_xpath(cls: str) -> str:
    # contains(concat(' ', normalize-space(@class), ' '), ' cls ')
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')"


def _collect_by_forward_scan_python(page, max_collect: int) -> list[dict]:
    """
    For each base64 <img> (jpeg/webp, not tiny):
      - find the first following element that is <a> or <img>:
          xpath: ./following::*[self::a or self::img][1]
      - if it's <img> → skip this tile
      - if it's <a> → unwrap+normalize href; must contain linkedin.com/in
        and fetch the visible title: .//div[class has toI8Rb and OSrXXb]
    Returns list of dicts: {data_url, href, title}
    """
    results = []
    imgs = page.query_selector_all('img[src^="data:image/"]')
    for img in imgs:
        if len(results) >= max_collect:
            break

        src = (img.get_attribute("src") or "").strip()
        if not src:
            continue
        # Prefer real thumbs; skip the little png site icons
        if not re.match(r"^data:image/(jpeg|jpg|webp);base64,", src, flags=re.I):
            continue
        if _is_tiny_icon(img):
            continue

        # First following element that is either A or IMG
        nxt = img.query_selector('xpath=./following::*[self::a or self::img][1]')
        if not nxt:
            continue

        href = (nxt.get_attribute("href") or "").strip()
        if not href:
            # If no href, that "nxt" is an IMG → this tile is not a profile card
            continue

        href = _unwrap_google_href(href)
        prof = _normalize_profile_url(href) or href
        if "linkedin.com/in/" not in prof:
            continue
        prof = prof.split("?")[0].split("#")[0]

        # Inside the <a>, get <div class="toI8Rb OSrXXb">…</div>
        title_xpath = (
            f'xpath=.//div[{_class_contains_xpath("toI8Rb")} and '
            f'{_class_contains_xpath("OSrXXb")}]'
        )
        title_el = nxt.query_selector(title_xpath)
        title = title_el.inner_text().strip() if title_el else ""

        results.append({"data_url": src, "href": prof, "title": title})

    return results


def scrape_linkedin_images_into_json(json_path: str | Path, *,
                                     headless: bool = False,
                                     limit: int = 10,
                                     ) -> int:
    """
    Main function that scrapes the LinkedIn images and links from Google Images.
    :param json_path: Path to a person JSON (with query_name).
    :param headless: Headless mode.
    :param limit: Maximum profiles retrieved
    :return:
    """
    json_path = Path(json_path)
    data = load_person(json_path)
    full_name = (data.get("query_name") or "").strip()
    if not full_name:
        print("JSON must contain 'query_name'")
        return 0

    query = f'{full_name} site:linkedin.com/in'
    url = GOOGLE_IMG.format(q=urllib.parse.quote_plus(query))
    dest_dir = Path("Persons_photos") / _slugify(str(full_name))

    saved = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            locale="en-US",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # wait for some base64 images to appear
            page.wait_for_selector('img[src^="data:image/"]', timeout=15_000)
        except PWTimeout:
            browser.close()
            return 0

        # Collect a bit more than limit, we'll filter/skip dupes later
        cards = _collect_by_forward_scan_python(page, max_collect=limit * 5)

        seen_profiles = set()
        for card in cards:
            if saved >= limit:
                break

            data_url = card.get("data_url") or ""
            prof = card.get("href") or ""
            title = card.get("title") or ""

            if not prof or prof in seen_profiles:
                continue
            seen_profiles.add(prof)

            # Guess name from the Google tile title (text before " - ")
            name_guess = _title_to_name(title)

            # ensure candidate exists + stash name
            upsert_candidate(json_path, prof, name_guess)

            # If we already have a good photo, skip heavy work
            if candidate_has_photo(json_path, prof):
                continue

            # Decode the base64 thumbnail
            parsed = _parse_data_url(data_url)
            if not parsed:
                # mark as processed to avoid rework
                upsert_candidate(json_path, prof, name_guess, photo_path=NO_IMAGE_TOKEN)
                continue

            ext, raw = parsed
            handle = _profile_handle(prof)
            out_path = (dest_dir / handle).with_suffix(ext)

            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(raw)

                # single call: update name (if provided) + set photo path
                upsert_candidate(json_path, prof, name_guess, photo_path=str(out_path))
                print(f"Saved photo for url:'{prof}' and name '{name_guess}' to path: '{out_path}'")
                saved += 1
            except Exception:
                upsert_candidate(json_path, prof, name_guess, photo_path=NO_IMAGE_TOKEN)


        context.close()
        browser.close()

    return saved


# ---------- CLI ----------
def _cli():
    import argparse
    ap = argparse.ArgumentParser(
        description="Find LinkedIn profiles & save base64 thumbnails from Google Images"
                    " by forward DOM scan."
    )
    ap.add_argument("json_path", help="Path to a person JSON (with query_name).")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()

    n = scrape_linkedin_images_into_json(
        args.json_path,
        headless=args.headless,
        limit=args.limit,
    )
    print(f"Processed {n} candidates.")


if __name__ == "__main__":
    _cli()
