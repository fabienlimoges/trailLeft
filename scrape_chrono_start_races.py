#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://chrono-start.com"
INSCRIPTION_BASE_URL = "https://chrono-start.fr"
USER_AGENT = (
    "Mozilla/5.0 (compatible; trailLeft/1.0; "
    "+https://chrono-start.com/inscriptions-listing/)"
)
TIMEOUT = 30


class ChronoStartRaceScraperError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lit events.json et enrichit chaque événement avec les courses "
            "de la page d'inscription Chrono-Start."
        )
    )
    parser.add_argument(
        "--input",
        default="events.json",
        help="Chemin du fichier JSON d'entrée. Défaut: events.json",
    )
    parser.add_argument(
        "--output",
        default="events_with_races.json",
        help="Chemin du fichier JSON de sortie. Défaut: events_with_races.json",
    )
    return parser.parse_args()


def build_event_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml",
        }
    )
    return session


def build_registration_session() -> cloudscraper.CloudScraper:
    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    return session


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def load_events(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ChronoStartRaceScraperError("Le fichier d'entrée doit contenir une liste JSON.")

    events: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            events.append(dict(item))
        else:
            raise ChronoStartRaceScraperError(
                "Chaque entrée du fichier d'entrée doit être un objet JSON."
            )
    return events


def normalize_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/Inscription/"):
        return urljoin(INSCRIPTION_BASE_URL, url)
    return urljoin(BASE_URL, url)


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(unescape(value).replace("\xa0", " ").split())
    return normalized or None


def extract_distance(name: str | None) -> str | None:
    if not name:
        return None
    match = re.search(r"\b\d+(?:[.,]\d+)?\s*(?:km|kms?)\b", name, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(0).upper().replace("KMS", "KM")


def parse_price(text: str | None) -> str | None:
    cleaned = clean_text(text)
    if not cleaned:
        return None
    return cleaned.replace(".00€", "€")


def parse_places(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"Places?\s+Restantes?\s*:\s*(\d+)", unescape(text), flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def parse_closure_date(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(
        r"Clôture des inscriptions\s*le\s*([0-9]{2}/[0-9]{2}/[0-9]{4})",
        unescape(text),
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


def parse_price_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(
        r"Prix de l'inscription:\s*([0-9.,]+\s*€)",
        unescape(text),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return parse_price(match.group(1))


def is_closed_text(text: str | None) -> bool:
    if not text:
        return False
    normalized = clean_text(text) or ""
    lowered = normalized.lower()
    return "inscriptions internet fermees" in lowered or "complet" in lowered


def extract_title_from_row(row: Tag) -> str | None:
    title_node = row.find("div")
    if title_node:
        bold = title_node.find("b")
        if bold:
            return clean_text(bold.get_text(" ", strip=True))
    return None


def extract_badge_price(row: Tag) -> str | None:
    badge = row.select_one(".badge-big")
    if not badge:
        return None
    return parse_price(badge.get_text(" ", strip=True))


def extract_button_title(row: Tag) -> str | None:
    image = row.select_one("button img[title]")
    if image and image.has_attr("title"):
        return clean_text(image["title"])
    return None


def build_course_record(
    *,
    name: str | None,
    price: str | None,
    closure_date: str | None,
    places_remaining: int | None,
    registration_closed: bool,
) -> dict[str, Any]:
    return {
        "nom_course": name,
        "distance": extract_distance(name),
        "prix": price,
        "date_cloture_inscriptions": closure_date,
        "places_restantes": None if registration_closed else places_remaining,
        "inscriptions_fermees": registration_closed,
    }


def parse_grouped_course_rows(rows: list[Tag], start_index: int) -> tuple[list[dict[str, Any]], int]:
    main_row = rows[start_index]
    base_title = extract_title_from_row(main_row)
    base_price = extract_badge_price(main_row)
    select = main_row.find("select")
    if not select or not select.has_attr("id"):
        return [], start_index

    group_id = select["id"]
    grouped_courses: list[dict[str, Any]] = []
    index = start_index + 1
    current_option_key: str | None = None
    current_closure_date: str | None = None

    while index < len(rows):
        row = rows[index]
        row_id = row.get("id")
        if row.find("img", src=re.compile(r"icon-epreuve-1\.png")):
            break

        if row_id == f"tr-group-{group_id}":
            current_closure_date = parse_closure_date(row.get_text(" ", strip=True))
            index += 1
            continue

        if row_id and row_id.startswith("tr1-"):
            current_option_key = row_id.removeprefix("tr1-")
            detail_text = row.get_text(" ", strip=True)
            grouped_courses.append(
                build_course_record(
                    name=None,
                    price=parse_price_from_text(detail_text) or base_price,
                    closure_date=parse_closure_date(detail_text) or current_closure_date,
                    places_remaining=parse_places(detail_text),
                    registration_closed=is_closed_text(detail_text),
                )
            )
            index += 1
            continue

        if row_id and row_id.startswith("tr2-") and current_option_key:
            current_course = grouped_courses[-1]
            current_course["nom_course"] = extract_button_title(row) or base_title
            current_course["distance"] = extract_distance(current_course["nom_course"])
            index += 1
            continue

        index += 1

    for course in grouped_courses:
        if not course["nom_course"]:
            course["nom_course"] = base_title
            course["distance"] = extract_distance(base_title)

    return grouped_courses, index - 1


def parse_simple_course_row(row: Tag) -> dict[str, Any]:
    text = row.get_text(" ", strip=True)
    title = extract_title_from_row(row)
    price = parse_price_from_text(text) or extract_badge_price(row)
    return build_course_record(
        name=title,
        price=price,
        closure_date=parse_closure_date(text),
        places_remaining=parse_places(text),
        registration_closed=is_closed_text(text),
    )


def parse_registration_courses(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    details = soup.find(id="CourseInscDetails")
    if not details:
        return []

    rows = list(details.find_all("tr"))
    courses: list[dict[str, Any]] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if not row.find("img", src=re.compile(r"icon-epreuve-1\.png")):
            index += 1
            continue

        if row.find("select"):
            grouped_courses, last_index = parse_grouped_course_rows(rows, index)
            courses.extend(grouped_courses)
            index = last_index + 1
            continue

        courses.append(parse_simple_course_row(row))
        index += 1

    return courses


def extract_registration_url(event_session: requests.Session, event_url: str) -> str | None:
    html = fetch_html(event_session, event_url)
    soup = BeautifulSoup(html, "html.parser")

    candidates = [
        "a#linkInscription",
        "#idInscription a[href]",
        'a[href*="/Inscription/Course/detail/c/"]',
        'a[href*="chrono-start.fr/Inscription/Course/detail/c/"]',
    ]

    for selector in candidates:
        anchor = soup.select_one(selector)
        if anchor and anchor.has_attr("href"):
            href = clean_text(anchor["href"])
            if href:
                return normalize_url(href)

    for anchor in soup.find_all("a", href=True):
        label = clean_text(anchor.get_text(" ", strip=True)) or ""
        href = clean_text(anchor["href"]) or ""
        if "inscription" in label.lower() and "/Inscription/Course/detail/" in href:
            return normalize_url(href)

    return None


def course_detail_url_from_event(event: dict[str, Any]) -> str | None:
    for key in ("url_inscription", "inscription_url"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_url(value.strip())
    return None


def ensure_registration_url(
    event_session: requests.Session, event: dict[str, Any]
) -> str | None:
    existing = course_detail_url_from_event(event)
    if existing:
        return existing

    detail_url = event.get("url_detail")
    if not isinstance(detail_url, str) or not detail_url.strip():
        return None

    return extract_registration_url(event_session, detail_url.strip())


def main() -> int:
    args = parse_args()

    try:
        events = load_events(args.input)
        event_session = build_event_session()
        registration_session = build_registration_session()

        enriched_events: list[dict[str, Any]] = []
        for event in events:
            event_name = clean_text(str(event.get("nom_evenement", ""))) or "<sans nom>"
            try:
                registration_url = ensure_registration_url(event_session, event)
            except requests.RequestException as exc:
                print(
                    f"[warn] impossible de récupérer la page événement pour {event_name}: {exc}",
                    file=sys.stderr,
                )
                enriched = dict(event)
                enriched["url_inscription"] = None
                enriched["courses"] = []
                enriched_events.append(enriched)
                continue

            enriched = dict(event)
            enriched["url_inscription"] = registration_url

            if not registration_url:
                enriched["courses"] = []
                enriched_events.append(enriched)
                continue

            try:
                registration_html = fetch_html(registration_session, registration_url)
                enriched["courses"] = parse_registration_courses(registration_html)
            except requests.RequestException as exc:
                print(
                    f"[warn] impossible de récupérer la page d'inscription pour "
                    f"{event_name}: {exc}",
                    file=sys.stderr,
                )
                enriched["courses"] = []

            enriched_events.append(enriched)

        Path(args.output).write_text(
            json.dumps(enriched_events, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        total_courses = sum(len(event.get("courses", [])) for event in enriched_events)
        print(
            f"{len(enriched_events)} événements enrichis dans {args.output} "
            f"({total_courses} courses détectées)"
        )
        return 0
    except FileNotFoundError as exc:
        print(f"[error] fichier introuvable: {exc.filename}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[error] JSON invalide dans {args.input}: {exc}", file=sys.stderr)
        return 1
    except ChronoStartRaceScraperError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"[error] requête HTTP en échec: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
