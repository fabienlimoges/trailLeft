from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests


BASE_URL = "https://www.finishers.com"
SITEMAP_URL = f"{BASE_URL}/sitemap/events.xml"
USER_AGENT = (
    "Mozilla/5.0 (compatible; trailLeft/1.0; "
    "+https://www.finishers.com/courses)"
)
TIMEOUT = 30

_THREAD_LOCAL = threading.local()


class FinishersScraperError(RuntimeError):
    pass


@dataclass(frozen=True)
class Window:
    start: date
    end: date


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def build_window(start_month: date, months: int) -> Window:
    start = date(start_month.year, start_month.month, 1)
    end_year = start.year + ((start.month - 1 + months) // 12)
    end_month = ((start.month - 1 + months) % 12) + 1
    _, end = month_bounds(end_year, end_month)
    return Window(start=start, end=end)


def resolve_start_month(value: str | None) -> date:
    if not value:
        today = date.today()
        return date(today.year, today.month, 1)

    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise FinishersScraperError("--start-month doit être au format YYYY-MM") from exc

    return date(parsed.year, parsed.month, 1)


def get_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json",
            }
        )
        _THREAD_LOCAL.session = session
    return session


def fetch_text(url: str) -> str:
    response = get_session().get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def fetch_sitemap_urls(url: str = SITEMAP_URL) -> list[str]:
    xml = fetch_text(url)
    return [unescape(match) for match in re.findall(r"<loc>(.*?)</loc>", xml)]


def is_french_course_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc == "www.finishers.com" and parsed.path.startswith("/course/")


def extract_next_data_from_html(html: str) -> dict[str, Any]:
    marker = '__NEXT_DATA__'
    marker_index = html.find(marker)
    if marker_index == -1:
        raise FinishersScraperError("Balise __NEXT_DATA__ introuvable.")

    start_tag_index = html.rfind("<script", 0, marker_index)
    if start_tag_index == -1:
        raise FinishersScraperError("Début de balise script introuvable.")

    payload_start = html.find(">", start_tag_index)
    if payload_start == -1:
        raise FinishersScraperError("Fin de balise script introuvable.")

    payload_end = html.find("</script>", payload_start)
    if payload_end == -1:
        raise FinishersScraperError("Fin de payload JSON introuvable.")

    raw = html[payload_start + 1 : payload_end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FinishersScraperError("JSON __NEXT_DATA__ invalide.") from exc


def fetch_page_props(url: str) -> dict[str, Any]:
    html = fetch_text(url)
    data = extract_next_data_from_html(html)
    props = data.get("props", {}).get("pageProps")
    if not isinstance(props, dict):
        raise FinishersScraperError("pageProps introuvable dans __NEXT_DATA__.")
    return props


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def edition_payload(props: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    next_edition = props.get("nextEdition")
    if isinstance(next_edition, dict) and parse_iso_date(next_edition.get("dateRange", {}).get("start")):
        return "nextEdition", next_edition

    last_edition = props.get("lastEdition")
    if isinstance(last_edition, dict) and parse_iso_date(last_edition.get("dateRange", {}).get("start")):
        return "lastEdition", last_edition

    return None, None


def overlaps_window(edition: dict[str, Any] | None, window: Window) -> bool:
    if not edition:
        return False

    date_range = edition.get("dateRange", {})
    start_date = parse_iso_date(date_range.get("start"))
    end_date = parse_iso_date(date_range.get("end")) or start_date
    if not start_date:
        return False

    return end_date >= window.start and start_date < window.end


def breadcrumb_labels(event: dict[str, Any]) -> dict[str, str | None]:
    labels = {"country": None, "region": None, "department": None, "city": None}
    for crumb in event.get("breadcrumb", []):
        if not isinstance(crumb, dict):
            continue
        label = clean_text(crumb.get("label"))
        crumb_type = crumb.get("type")
        if crumb_type == "country":
            labels["country"] = label
        elif crumb_type == "level1AdminArea":
            labels["region"] = label
        elif crumb_type == "level2AdminArea":
            labels["department"] = label
        elif crumb_type == "city":
            labels["city"] = label
    return labels


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\xa0", " ").split())
    return text or None


def format_location(labels: dict[str, str | None]) -> str | None:
    parts = [labels["city"], labels["department"] or labels["region"], labels["country"]]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen) or None


def normalize_url(url: str | None) -> str | None:
    cleaned = clean_text(url)
    if not cleaned:
        return None
    return urljoin(BASE_URL, cleaned)


def resolve_external_url(url: str | None) -> str | None:
    absolute = normalize_url(url)
    if not absolute:
        return None

    parsed = urlparse(absolute)
    if parsed.path != "/external":
        return absolute

    target = parse_qs(parsed.query).get("url", [])
    if not target:
        return absolute
    return unquote(target[0])


def first_non_empty(values: list[Any]) -> Any | None:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None

