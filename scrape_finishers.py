#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

from finishers_common import (
    FinishersScraperError,
    Window,
    breadcrumb_labels,
    build_window,
    clean_text,
    edition_payload,
    fetch_page_props,
    fetch_sitemap_urls,
    format_location,
    is_french_course_url,
    normalize_url,
    overlaps_window,
    parse_iso_date,
    resolve_external_url,
    resolve_start_month,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape les événements Finishers depuis le sitemap des pages course "
            "et exporte une liste JSON filtrée sur une fenêtre de dates."
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
        default="finishers_events.json",
        help="Chemin du fichier JSON de sortie. Défaut: finishers_events.json",
    )
    parser.add_argument(
        "--start-month",
        help="Mois de départ au format YYYY-MM. Défaut: mois courant",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Nombre maximum d'URLs à traiter depuis le sitemap.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Nombre de requêtes parallèles. Défaut: 8",
    )
    return parser.parse_args()


def summarize_event(url: str, props: dict[str, Any]) -> dict[str, Any] | None:
    event = props.get("event")
    if not isinstance(event, dict):
        return None

    edition_source, edition = edition_payload(props)
    if not edition:
        return None

    labels = breadcrumb_labels(event)
    date_range = edition.get("dateRange", {})
    disciplines = props.get("disciplines")
    races = props.get("races")

    unique_times = sorted(
        {
            clean_text(race.get("time"))
            for race in races or []
            if isinstance(race, dict) and clean_text(race.get("time"))
        }
    )

    return {
        "id_evenement": clean_text(event.get("id")),
        "nom_evenement": clean_text(event.get("name")),
        "categorie": ", ".join(disciplines) if isinstance(disciplines, list) else None,
        "date_evenement": clean_text(date_range.get("start")),
        "date_fin_evenement": clean_text(date_range.get("end")),
        "heure_evenement": unique_times[0] if len(unique_times) == 1 else None,
        "lieu_evenement": format_location(labels),
        "ville": labels["city"],
        "departement": labels["department"],
        "region": labels["region"],
        "pays": labels["country"],
        "url_detail": normalize_url(url),
        "edition_source": edition_source,
        "edition_status": clean_text(edition.get("status")),
        "annee_edition": edition.get("year"),
        "site_internet": resolve_external_url(event.get("links", {}).get("website")),
    }


def worker(url: str, window: Window) -> dict[str, Any] | None:
    props = fetch_page_props(url)
    _, edition = edition_payload(props)
    if not overlaps_window(edition, window):
        return None
    return summarize_event(url, props)


def main() -> int:
    args = parse_args()
    start_month = resolve_start_month(args.start_month)
    window = build_window(start_month, args.months)

    try:
        urls = [url for url in fetch_sitemap_urls() if is_french_course_url(url)]
        if args.limit is not None:
            urls = urls[: args.limit]

        extracted_events: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {executor.submit(worker, url, window): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    event = future.result()
                except (requests.RequestException, FinishersScraperError) as exc:
                    print(
                        f"[warn] impossible de traiter {url}: {exc}",
                        file=sys.stderr,
                    )
                    continue

                if event:
                    extracted_events.append(event)

        extracted_events.sort(
            key=lambda event: (
                parse_iso_date(event.get("date_evenement")) or parse_iso_date("9999-12-31"),
                event.get("nom_evenement") or "",
            )
        )

        Path(args.output).write_text(
            json.dumps(extracted_events, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(
            f"{len(extracted_events)} événements exportés dans {args.output} "
            f"pour la période {window.start.isoformat()} -> "
            f"{(window.end - timedelta(days=1)).isoformat()}"
        )
        return 0
    except requests.RequestException as exc:
        print(f"[error] requête HTTP en échec: {exc}", file=sys.stderr)
        return 1
    except FinishersScraperError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
