# Chrono-Start scraper

Script Python pour récupérer les événements affichés dans `Inscriptions & Listing` sur Chrono-Start, pour les 6 prochains mois, mois courant inclus.

## Données exportées

Le script génère un fichier `events.json` avec les champs suivants :

- `nom_evenement`
- `categorie`
- `date_evenement`
- `heure_evenement`
- `lieu_evenement`
- `url_detail`

Un second script enrichit ce fichier avec :

- `url_inscription`
- `courses[]`
- `courses[].nom_course`
- `courses[].distance`
- `courses[].prix`
- `courses[].date_cloture_inscriptions`
- `courses[].places_restantes`
- `courses[].inscriptions_fermees`

## Prérequis

- `uv` installé
- accès réseau vers `https://chrono-start.com`

## Installation

```bash
uv sync
```

## Exécution

Commande par défaut :

```bash
uv run chrono-start-scraper
```

Commande équivalente :

```bash
uv run python scrape_chrono_start.py
```

Le script écrit par défaut `events.json` dans le dossier courant.

Pour enrichir chaque événement avec ses courses associées :

```bash
uv run chrono-start-race-scraper
```

Commande équivalente :

```bash
uv run python scrape_chrono_start_races.py
```

Ce script lit `events.json` par défaut et écrit `events_with_races.json`.

## Options

Choisir un fichier de sortie :

```bash
uv run chrono-start-scraper --output data/events.json
```

Choisir le mois de départ et la fenêtre :

```bash
uv run chrono-start-scraper --start-month 2026-03 --months 6
```

Filtrer par catégorie :

```bash
uv run chrono-start-scraper --category Trail
```

Plusieurs catégories :

```bash
uv run chrono-start-scraper --category Trail --category VTT
```

Paramètres disponibles :

- `--output` : chemin du JSON de sortie
- `--start-month` : mois de départ au format `YYYY-MM`
- `--months` : nombre de mois à inclure, mois courant inclus
- `--category` : filtre sur la catégorie, insensible à la casse et aux accents, option répétable

Pour le scraper des courses :

- `--input` : chemin du fichier `events.json` à enrichir
- `--output` : chemin du JSON enrichi

## Fonctionnement

Le script :

1. interroge l’API publique WordPress de Chrono-Start pour récupérer les événements taggés `INSCRIPTION`
2. visite chaque page détail événement
3. extrait les informations depuis le HTML de la page
4. filtre les événements dont la date tombe dans la fenêtre demandée
5. exporte le résultat dans `events.json`

Le scraper des courses :

1. lit chaque entrée de `events.json`
2. retrouve le lien `Inscription` depuis la page détail de l'événement
3. récupère la page d'inscription Chrono-Start
4. extrait les épreuves simples et les variantes éventuelles
5. exporte le résultat enrichi dans `events_with_races.json`

## Exemple de sortie

```json
[
  {
    "nom_evenement": "EDUCARUN – TOULOUSE",
    "categorie": "Relais - Ekiden",
    "date_evenement": "21 Mar 2026",
    "heure_evenement": "10h30",
    "lieu_evenement": "Toulouse (31)",
    "url_detail": "https://chrono-start.com/events/educarun/"
  }
]
```
