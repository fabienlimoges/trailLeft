#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from finishers_common import (
    FinishersScraperError,
    breadcrumb_labels,
    clean_text,
    edition_payload,
    fetch_page_props,
    normalize_url,
    resolve_external_url,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lit finishers_events.json et enrichit chaque événement avec les "
            "informations détaillées embarquées dans la page Finishers."
        )
    )
    parser.add_argument(
        "--input",
        default="finishers_events.json",
        help="Chemin du fichier JSON d'entrée. Défaut: finishers_events.json",
    )
    parser.add_argument(
        "--output",
        default="finishers_events_with_races.json",
        help=(
            "Chemin du fichier JSON de sortie. Défaut: "
            "finishers_events_with_races.json"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Nombre de requêtes parallèles. Défaut: 8",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Nombre maximum d'événements à enrichir.",
    )
    return parser.parse_args()


def load_events(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise FinishersScraperError("Le fichier d'entrée doit contenir une liste JSON.")

    events: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise FinishersScraperError(
                "Chaque entrée du fichier d'entrée doit être un objet JSON."
            )
        events.append(dict(item))
    return events


def extract_results(results_payload: Any) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    if not isinstance(results_payload, list):
        return extracted

    for edition in results_payload:
        if not isinstance(edition, dict):
            continue
        year = edition.get("year")
        races_payload = edition.get("raceEditions")
        races: list[dict[str, Any]] = []
        if isinstance(races_payload, list):
            for race in races_payload:
                if not isinstance(race, dict):
                    continue
                races.append(
                    {
                        "annee": race.get("year"),
                        "nom_course": clean_text(race.get("raceName")),
                        "slug_course": clean_text(race.get("raceSlug")),
                        "race_edition_id": clean_text(race.get("raceEditionId")),
                        "url_resultats_officiels": normalize_url(race.get("officialResultsUrl")),
                        "derniere_edition": bool(race.get("isLastEdition")),
                    }
                )
        extracted.append({"annee": year, "courses": races})
    return extracted


def extract_races(races_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(races_payload, list):
        return []

    races: list[dict[str, Any]] = []
    for race in races_payload:
        if not isinstance(race, dict):
            continue

        distance_m = race.get("distance")
        races.append(
            {
                "id_course": clean_text(race.get("id")),
                "nom_course": clean_text(race.get("name")),
                "nom_affiche": clean_text(race.get("formattedTitle")),
                "discipline": clean_text(race.get("discipline")),
                "date_course": clean_text(race.get("date")),
                "date_fin_course": clean_text(race.get("endDate")),
                "heure_depart": clean_text(race.get("time")),
                "heure_arrivee": clean_text(race.get("endTime")),
                "distance_m": distance_m,
                "distance_km": round(distance_m / 1000, 3) if isinstance(distance_m, (int, float)) else None,
                "unite_distance": clean_text(race.get("distanceUnit")),
                "denivele_positif_m": race.get("elevationGain"),
                "denivele_negatif_m": race.get("elevationLoss"),
                "itra_points": race.get("itraPoints"),
                "prix_min": race.get("minPrice"),
                "statut": clean_text(race.get("status")),
                "description": clean_text(race.get("description")),
                "course_populaire": bool(race.get("isMostPopular")),
                "finishers_derniere_edition": race.get("lastEditionFinisherCount"),
                "url_inscription": resolve_external_url(race.get("registrationUrl")),
                "race_id": clean_text(race.get("raceId")),
                "race_edition_id": clean_text(race.get("raceEditionId")),
                "trace": race.get("trace"),
                "activites": race.get("activities") if isinstance(race.get("activities"), list) else [],
                "tags": race.get("tags") if isinstance(race.get("tags"), list) else [],
                "series": race.get("series") if isinstance(race.get("series"), list) else [],
            }
        )

    return races


def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    detail_url = event.get("url_detail")
    if not isinstance(detail_url, str) or not detail_url.strip():
        raise FinishersScraperError("Événement sans url_detail.")

    props = fetch_page_props(detail_url.strip())
    payload = props.get("event")
    if not isinstance(payload, dict):
        raise FinishersScraperError("Objet event introuvable dans pageProps.")

    labels = breadcrumb_labels(payload)
    edition_source, edition = edition_payload(props)
    links = payload.get("links", {}) if isinstance(payload.get("links"), dict) else {}
    next_edition = props.get("nextEdition") if isinstance(props.get("nextEdition"), dict) else {}
    last_edition = props.get("lastEdition") if isinstance(props.get("lastEdition"), dict) else {}

    enriched = dict(event)
    enriched.update(
        {
            "id_evenement": clean_text(payload.get("id")) or event.get("id_evenement"),
            "short_id_evenement": clean_text(payload.get("shortId")),
            "slug_evenement": clean_text(payload.get("slug")),
            "nom_evenement": clean_text(payload.get("name")) or event.get("nom_evenement"),
            "sous_titre": clean_text(payload.get("subtitle")),
            "premiere_edition": payload.get("firstEditionYear"),
            "edition_source": edition_source or event.get("edition_source"),
            "edition_status": clean_text(edition.get("status")) if edition else event.get("edition_status"),
            "ville": labels["city"] or event.get("ville"),
            "departement": labels["department"] or event.get("departement"),
            "region": labels["region"] or event.get("region"),
            "pays": labels["country"] or event.get("pays"),
            "site_internet": resolve_external_url(links.get("website")),
            "url_inscription": resolve_external_url(links.get("registration")),
            "url_facebook": resolve_external_url(links.get("facebook")),
            "url_marathons_com": resolve_external_url(links.get("marathonsDotCom")),
            "date_prochaine_edition": clean_text(next_edition.get("dateRange", {}).get("start")),
            "date_fin_prochaine_edition": clean_text(next_edition.get("dateRange", {}).get("end")),
            "statut_prochaine_edition": clean_text(next_edition.get("status")),
            "date_derniere_edition": clean_text(last_edition.get("dateRange", {}).get("start")),
            "date_fin_derniere_edition": clean_text(last_edition.get("dateRange", {}).get("end")),
            "statut_derniere_edition": clean_text(last_edition.get("status")),
            "coordonnees_ville": payload.get("cityCoordinates"),
            "coordonnees_evenement": payload.get("coordinates"),
            "liens": links,
            "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
            "series": props.get("series") if isinstance(props.get("series"), list) else [],
            "disciplines": props.get("disciplines") if isinstance(props.get("disciplines"), list) else [],
            "faq": payload.get("faq") if isinstance(payload.get("faq"), list) else [],
            "courses": extract_races(props.get("races")),
            "resultats": extract_results(payload.get("results")),
            "description_longue": clean_text(payload.get("longDescription")),
            "description_kids": clean_text(payload.get("kidsRaceDescription")),
            "message_organisateur": clean_text(payload.get("organizerMessage")),
        }
    )
    return enriched


def main() -> int:
    args = parse_args()

    try:
        events = load_events(args.input)
        if args.limit is not None:
            events = events[: args.limit]

        enriched_events: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {executor.submit(enrich_event, event): event for event in events}
            for future in as_completed(futures):
                source_event = futures[future]
                event_name = clean_text(source_event.get("nom_evenement")) or "<sans nom>"
                try:
                    enriched_events.append(future.result())
                except (requests.RequestException, FinishersScraperError) as exc:
                    print(
                        f"[warn] impossible d'enrichir {event_name}: {exc}",
                        file=sys.stderr,
                    )
                    fallback = dict(source_event)
                    fallback["courses"] = []
                    fallback["resultats"] = []
                    enriched_events.append(fallback)

        enriched_events.sort(
            key=lambda event: (
                event.get("date_evenement") or "9999-12-31",
                event.get("nom_evenement") or "",
            )
        )

        Path(args.output).write_text(
            json.dumps(enriched_events, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        total_races = sum(len(event.get("courses", [])) for event in enriched_events)
        print(
            f"{len(enriched_events)} événements enrichis dans {args.output} "
            f"({total_races} courses détectées)"
        )
        return 0
    except FileNotFoundError as exc:
        print(f"[error] fichier introuvable: {exc.filename}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[error] JSON invalide dans {args.input}: {exc}", file=sys.stderr)
        return 1
    except FinishersScraperError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"[error] requête HTTP en échec: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
