#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://chrono-start.com"
EVENTS_API_URL = f"{BASE_URL}/wp-json/wp/v2/mec-events"
INSCRIPTION_TAG_ID = 71
USER_AGENT = (
    "Mozilla/5.0 (compatible; trailLeft/1.0; "
    "+https://chrono-start.com/inscriptions-listing/)"
)
TIMEOUT = 30


@dataclass(frozen=True)
class Window:
    start: date
    end: date


class ChronoStartScraperError(RuntimeError):
    pass


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml",
        }
    )
    return session


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start, next_month


def build_window(start_month: date, months: int) -> Window:
    year = start_month.year
    month = start_month.month

    start = date(year, month, 1)

    end_year = year + ((month - 1 + months) // 12)
    end_month = ((month - 1 + months) % 12) + 1
    end, _ = month_bounds(end_year, end_month)

    return Window(start=start, end=end)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape les événements Chrono-Start visibles dans "
            "'Inscriptions & Listing' pour les 6 prochains mois."
        )
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Nombre de mois à inclure, mois courant compris. Défaut: 6",
    )
    parser.add_argument(
        "--output",
        default="events.json",
        help="Chemin du fichier JSON de sortie. Défaut: events.json",
    )
    parser.add_argument(
        "--start-month",
        help="Mois de départ au format YYYY-MM. Défaut: mois courant",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help=(
            "Catégorie à inclure. Option répétable et compatible avec une liste "
            "séparée par des virgules. Exemples: Trail, VTT, Swimrun"
        ),
    )
    return parser.parse_args()


def resolve_start_month(value: str | None) -> date:
    if not value:
        today = date.today()
        return date(today.year, today.month, 1)

    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ChronoStartScraperError(
            "--start-month doit être au format YYYY-MM"
        ) from exc

    return date(parsed.year, parsed.month, 1)


def fetch_event_index(session: requests.Session) -> list[dict[str, Any]]:
    page = 1
    events: list[dict[str, Any]] = []

    while True:
        response = session.get(
            EVENTS_API_URL,
            params={
                "tags": INSCRIPTION_TAG_ID,
                "per_page": 100,
                "page": page,
                "orderby": "date",
                "order": "asc",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        payload = response.json()
        if not payload:
            break

        events.extend(payload)

        total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break

        page += 1

    return events


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_only.casefold().split())


def parse_category_filters(values: list[str]) -> set[str]:
    filters: set[str] = set()
    for value in values:
        for part in value.split(","):
            candidate = part.strip()
            if candidate:
                filters.add(normalize_text(candidate))
    return filters


def matches_category(category: str | None, filters: set[str]) -> bool:
    if not filters:
        return True
    if not category:
        return False
    return normalize_text(category) in filters


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def select_text(node: BeautifulSoup | Any, selector: str) -> str | None:
    element = node.select_one(selector)
    if not element:
        return None
    return " ".join(element.get_text(" ", strip=True).split())


def parse_event_schema(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue

        raw = raw.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if isinstance(data, dict) and data.get("@type") == "Event":
            return data

    return {}


def parse_date_text(raw: str | None) -> str | None:
    if not raw:
        return None
    return unescape(" ".join(raw.split()))


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None

    candidate = value.split("T", 1)[0]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def extract_location(soup: BeautifulSoup, schema: dict[str, Any]) -> str | None:
    location = schema.get("location", {})
    if isinstance(location, dict):
        for key in ("name", "address"):
            value = location.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    gcal_link = soup.select_one('a[href*="calendar.google.com/calendar/render"]')
    if gcal_link and gcal_link.has_attr("href"):
        match = re.search(r"[?&]location=([^&]+)", gcal_link["href"])
        if match:
            return unescape(match.group(1).replace("+", " "))

    return None


def extract_event_data(session: requests.Session, event_summary: dict[str, Any]) -> dict[str, Any]:
    url = event_summary.get("link")
    if not isinstance(url, str) or not url:
        raise ChronoStartScraperError("Événement sans URL de détail.")

    html = fetch_html(session, url)
    soup = BeautifulSoup(html, "html.parser")
    schema = parse_event_schema(soup)

    title = select_text(soup, ".mec-event-title") or unescape(
        BeautifulSoup(event_summary["title"]["rendered"], "html.parser").get_text(" ", strip=True)
    )
    category = select_text(
        soup, ".mec-single-event-category .mec-events-event-categories a"
    )
    event_date = parse_date_text(select_text(soup, ".mec-single-event-date dd"))
    event_time = parse_date_text(select_text(soup, ".mec-single-event-time dd"))
    location = extract_location(soup, schema)

    start_date = parse_iso_date(schema.get("startDate"))
    end_date = parse_iso_date(schema.get("endDate"))

    return {
        "nom_evenement": title,
        "categorie": category,
        "date_evenement": event_date,
        "heure_evenement": event_time,
        "lieu_evenement": location,
        "url_detail": urljoin(BASE_URL, url),
        "_start_date": start_date,
        "_end_date": end_date or start_date,
    }


def overlaps_window(start_date: date | None, end_date: date | None, window: Window) -> bool:
    if not start_date:
        return False

    effective_end = end_date or start_date
    return effective_end >= window.start and start_date < window.end


def serialize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for event in events:
        serialized.append(
            {
                "nom_evenement": event["nom_evenement"],
                "categorie": event["categorie"],
                "date_evenement": event["date_evenement"],
                "heure_evenement": event["heure_evenement"],
                "lieu_evenement": event["lieu_evenement"],
                "url_detail": event["url_detail"],
            }
        )
    return serialized


def main() -> int:
    args = parse_args()
    start_month = resolve_start_month(args.start_month)
    window = build_window(start_month, args.months)
    category_filters = parse_category_filters(args.category)

    try:
        session = build_session()
        raw_events = fetch_event_index(session)

        extracted_events: list[dict[str, Any]] = []
        for event_summary in raw_events:
            try:
                event = extract_event_data(session, event_summary)
            except requests.RequestException as exc:
                print(
                    f"[warn] impossible de récupérer {event_summary.get('link')}: {exc}",
                    file=sys.stderr,
                )
                continue

            if overlaps_window(event["_start_date"], event["_end_date"], window):
                if matches_category(event["categorie"], category_filters):
                    extracted_events.append(event)

        extracted_events.sort(
            key=lambda event: (
                event["_start_date"] or date.max,
                event["nom_evenement"] or "",
            )
        )

        output = serialize_events(extracted_events)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        print(
            f"{len(output)} événements exportés dans {args.output} "
            f"pour la période {window.start.isoformat()} -> "
            f"{(window.end - date.resolution).isoformat()}"
        )
        return 0
    except requests.RequestException as exc:
        print(f"[error] requête HTTP en échec: {exc}", file=sys.stderr)
        return 1
    except ChronoStartScraperError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
