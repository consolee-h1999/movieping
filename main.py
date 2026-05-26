import json
import os
import re
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

VENUES = [
    {
        "id": "miracle",
        "name": "Miracle Theatre",
        "url": "https://themiracletheatre.com/event-category/in-theatre-movies/",
        "parser": "mec",
    },
    {
        "id": "alamo_dc",
        "name": "Alamo Drafthouse DC",
        "url": "https://drafthouse.com/dc-metro-area#now-playing",
        "parser": "alamo",
    },
    {
        "id": "loc",
        "name": "Library of Congress",
        "url": (
            "https://www.loc.gov/programs/audio-visual-conservation/"
            "events-and-screenings/screenings/"
        ),
        "parser": "loc",
    },
    {
        "id": "sunset",
        "name": "Sunset Cinema",
        "url": "https://www.wharfdc.com/sunsetcinema/",
        "parser": "sunset",
    },
    {
        "id": "kennedy",
        "name": "Kennedy Center",
        "url": "https://www.kennedy-center.org/whats-on/millennium-stage/films/",
        "parser": "kennedy",
    },
]

SUNSET_SCHEDULE_PATTERN = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}):\s*([^(]+?\(\d{4}\))",
    re.IGNORECASE,
)


def load_users(users_file=None):
    """A method to load users from users.json or users.example.json. More functions will be added in v2."""
    path = Path(users_file or os.environ.get("USERS_FILE", "users.json"))
    if not path.exists():
        path = Path("users.example.json")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return [u for u in data.get("users", []) if u.get("enabled", True)]


def find_matches(watchlist, screenings):
    """A method to find matches between a user's watchlist and screenings."""
    grouped = defaultdict(list)
    for screening in screenings:
        grouped[normalize(screening["title"])].append(screening)

    matches = []
    for film in watchlist:
        key = normalize(film["title"])
        if key in grouped:
            matches.append({
                "title": film["title"],
                "year": film.get("year"),
                "screenings": grouped[key],
            })
    return matches


def format_discord_message(user, matches, watchlist_size):
    lines = [f"**Movieping — {user['name']}**"]

    if not matches:
        lines.append(
            f"No matches today ({watchlist_size} films checked "
            f"against DC-area screenings)."
        )
        return "\n".join(lines)

    lines.append(f"{len(matches)} match(es) from {watchlist_size} films:")
    for match in matches:
        lines.append(f"\n**{match['title']}**")
        for screening in match["screenings"]:
            when = format_screening_when(screening)
            lines.append(f"• {when} @ {screening['venue']}")

    content = "\n".join(lines)
    if len(content) > 1900:
        content = content[:1897] + "..."
    return content


def send_discord(webhook_url, content):
    if not webhook_url:
        logger.info("Discord: skipped (no webhook URL)")
        return False

    response = requests.post(
        webhook_url,
        json={"content": content},
        timeout=15,
    )
    if response.status_code not in (200, 204):
        logger.error(f"Discord webhook: failed HTTP {response.status_code}")
        return False
    logger.info("Screening schedule sent!")
    return True


def run_for_user(user, screenings, default_webhook=None):
    username = user["letterboxd_username"]
    list_name = user.get("letterboxd_list") or None
    source = f"list '{list_name}'" if list_name else "watchlist"

    logger.info(f"\n--- {user['name']} (@{username}, {source}) ---")
    watchlist = get_watchlist(username, list_name)
    logger.info(f"Loaded {len(watchlist)} films from Letterboxd")

    matches = find_matches(watchlist, screenings)
    for match in matches:
        logger.info(f"MATCH: {match['title']}")
        for screening in match["screenings"]:
            logger.info(f"  {format_screening_when(screening)} @ {screening['venue']}")

    webhook = user.get("discord_webhook_url") or default_webhook
    message = format_discord_message(user, matches, len(watchlist))
    send_discord(webhook, message)
    return matches


def main():
    users = load_users()
    if not users:
        logger.warning("No enabled users in users.json")
        return

    default_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    logger.info("Fetching screenings from all venues...")
    screenings = get_all_screenings()
    logger.info(f"Loaded {len(screenings)} screenings from {len(VENUES)} venues")

    for user in users:
        run_for_user(user, screenings, default_webhook)


def fetch_html(url, timeout=15):
    url = url.split("#", 1)[0]

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
    )

    if response.status_code != 200 or _is_bot_challenge_page(response.text):
        reason = f"HTTP {response.status_code}"
        if _is_bot_challenge_page(response.text):
            reason = "bot challenge (Cloudflare)"
        logger.warning(f"Failed to fetch {url}: {reason}")
        return None

    return response.text


def _is_bot_challenge_page(html):
    if not html:
        return False
    return (
        "Just a moment..." in html
        or "cf-challenge" in html
        or "/cdn-cgi/challenge-platform/" in html
    )


def get_screenings_for_venue(venue):
    html = fetch_html(venue["url"])
    if not html:
        return []

    parser = PARSERS.get(venue["parser"])
    if not parser:
        logger.info(f"No parser for {venue['name']} ({venue['parser']})")
        return []

    soup = BeautifulSoup(html, "html.parser")
    screenings = parser(soup)
    for screening in screenings:
        screening["venue"] = venue["name"]
        screening["venue_id"] = venue["id"]
        screening["source_url"] = venue["url"]
    return screenings


def get_all_screenings(venues=None):
    venues = venues if venues is not None else VENUES
    all_screenings = []

    for venue in venues:
        try:
            venue_screenings = get_screenings_for_venue(venue)
            logger.info(f"{venue['name']}: {len(venue_screenings)} screenings")
            all_screenings.extend(venue_screenings)
        except Exception as exc:
            logger.warning(f"{venue['name']}: skipped ({exc})")

    return all_screenings


def get_screenings(url=None):
    """Fetch screenings for one URL, or all venues when url is None."""
    if url is None:
        return get_all_screenings()

    venue = next((v for v in VENUES if v["url"] == url), None)
    if venue:
        return get_screenings_for_venue(venue)

    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    if soup.select("article.mec-event-article"):
        return parse_mec_events(soup)
    if soup.find("a", href=re.compile(r"/item/event-")):
        return parse_loc_events(soup)

    schedule_matches = SUNSET_SCHEDULE_PATTERN.findall(soup.get_text(" ", strip=True))
    if schedule_matches:
        return [
            screening_from_display(title.strip(), date=date.strip())
            for date, title in schedule_matches
        ]

    return []


def format_screening_when(screening):
    parts = [p for p in (screening.get("date"), screening.get("time")) if p]
    return " ".join(parts) if parts else "date TBD"


def normalize(title):
    return (title or "").strip().casefold()


def parse_year(display_name):
    match = re.search(r"\((\d{4})\)\s*$", display_name or "")
    return int(match.group(1)) if match else None


def strip_year(display_name):
    return re.sub(r"\s*\(\d{4}\)\s*$", "", display_name or "").strip()


def screening_from_display(display, date=None, time=None):
    return {
        "title": strip_year(display),
        "year": parse_year(display),
        "date": date,
        "time": time,
    }


def parse_mec_events(soup):
    screenings = []

    for article in soup.select("article.mec-event-article"):
        title_el = article.select_one(".mec-event-title, h3, h4")
        if not title_el:
            continue

        display = title_el.get_text(strip=True)
        if not display:
            continue

        date_el = article.select_one(".mec-event-d")
        date = date_el.get_text(strip=True) if date_el else None

        time_el = article.select_one(".mec-time-details")
        time = time_el.get_text(" ", strip=True) if time_el else None

        screenings.append(screening_from_display(display, date, time))

    return screenings


def parse_alamo_events(soup):
    # Now-playing is a JS SPA; requests only receives the app shell.
    return []


def parse_loc_events(soup):
    screenings = []
    seen = set()

    for link in soup.find_all("a", href=re.compile(r"/item/event-")):
        display = link.get_text(strip=True).rstrip("*").strip()
        if not display or "(" not in display:
            continue

        card = link.find_parent("div", class_="card-body")
        date = None
        if card:
            date_el = card.select_one("li.date span")
            if date_el:
                date = date_el.get_text(strip=True)

        if not date:
            date_match = re.search(r"/(\d{4}-\d{2}-\d{2})/?", link["href"])
            if date_match:
                date = date_match.group(1)

        key = (normalize(strip_year(display)), date)
        if key in seen:
            continue
        seen.add(key)

        screenings.append(screening_from_display(display, date=date))

    return screenings


def parse_sunset_events(soup):
    best_matches = []

    for el in soup.find_all(["p", "div"]):
        text = el.get_text(" ", strip=True)
        matches = SUNSET_SCHEDULE_PATTERN.findall(text)
        if len(matches) > len(best_matches):
            best_matches = matches

    return [
        screening_from_display(
            title.strip(),
            date=date.strip(),
            time="7:00 pm",
        )
        for date, title in best_matches
    ]


def parse_kennedy_events(soup):
    screenings = []

    for heading in soup.select("h2, h3, h4, a"):
        display = heading.get_text(strip=True)
        if not display or len(display) > 120:
            continue
        if re.search(r"\(\d{4}\)", display):
            screenings.append(screening_from_display(display))

    return screenings


PARSERS = {
    "mec": parse_mec_events,
    "alamo": parse_alamo_events,
    "loc": parse_loc_events,
    "sunset": parse_sunset_events,
    "kennedy": parse_kennedy_events,
}


def get_watchlist(username, list_name=None):
    """A method to fetch movies from a user's watchlist or pre-specified list."""
    movies = []
    page = 1

    if list_name:
        base_url = f"https://letterboxd.com/{username}/list/{list_name}/"
        item_class = "posteritem"
    else:
        base_url = f"https://letterboxd.com/{username}/watchlist/"
        item_class = "griditem"

    while True:
        url = base_url if page == 1 else f"{base_url}page/{page}/"

        response = requests.get(url, headers={"User-Agent": USER_AGENT})

        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.find_all("li", class_=item_class)

        if not items:
            break

        for li in items:
            react = li.find("div", class_="react-component")
            if not react:
                continue

            display = react.get("data-item-full-display-name") or react.get(
                "data-item-name"
            )
            if not display:
                img = li.find("img")
                display = img.get("alt") if img else None
            if not display:
                continue

            movies.append({
                "title": strip_year(display),
                "year": parse_year(display),
                "slug": react.get("data-item-slug"),
            })

        page += 1

    return movies


if __name__ == "__main__":
    main()
