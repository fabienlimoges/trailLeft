# Event scrapers

Scripts Python pour récupérer et enrichir des événements depuis :

- `Chrono-Start`
- `Finishers`

Les deux intégrations suivent le même principe :

1. un premier script collecte les événements et écrit un JSON de base
2. un second script relit ce JSON et enrichit chaque événement

## Prérequis

- `uv` installé
- accès réseau vers `https://chrono-start.com`
- accès réseau vers `https://www.finishers.com`

## Installation

```bash
uv sync
```

## Chrono-Start

Script Python pour récupérer les événements affichés dans `Inscriptions & Listing` sur Chrono-Start, pour les 6 prochains mois, mois courant inclus.

### Données exportées

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

### Exécution

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

### Options

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

### Fonctionnement

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

### Exemple de sortie

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

## Finishers

Le scraper Finishers s'appuie sur le sitemap public des pages `course` puis lit les données embarquées dans `__NEXT_DATA__` sur chaque fiche événement.

### Données exportées

Le script `finishers-scraper` génère un fichier `finishers_events.json` avec notamment :

- `id_evenement`
- `nom_evenement`
- `categorie`
- `date_evenement`
- `date_fin_evenement`
- `heure_evenement`
- `lieu_evenement`
- `ville`
- `departement`
- `region`
- `pays`
- `url_detail`
- `edition_source`
- `edition_status`
- `annee_edition`
- `site_internet`

Le script `finishers-race-scraper` enrichit ensuite ce fichier avec :

- `short_id_evenement`
- `slug_evenement`
- `sous_titre`
- `premiere_edition`
- `url_inscription`
- `url_facebook`
- `date_prochaine_edition`
- `date_derniere_edition`
- `courses[]`
- `resultats[]`

### Exécution

Commande par défaut :

```bash
uv run finishers-scraper
```

Commande équivalente :

```bash
uv run python scrape_finishers.py
```

Le script écrit par défaut `finishers_events.json` dans le dossier courant.

Pour enrichir chaque événement avec les courses et les résultats :

```bash
uv run finishers-race-scraper
```

Commande équivalente :

```bash
uv run python scrape_finishers_races.py
```

Ce script lit `finishers_events.json` par défaut et écrit `finishers_events_with_races.json`.

### Options

Choisir un fichier de sortie :

```bash
uv run finishers-scraper --output data/finishers_events.json
```

Choisir le mois de départ et la fenêtre :

```bash
uv run finishers-scraper --start-month 2026-03 --months 6
```

Limiter le nombre d'URLs de test :

```bash
uv run finishers-scraper --limit 20
```

Paramètres disponibles pour le scraper principal :

- `--output` : chemin du JSON de sortie
- `--start-month` : mois de départ au format `YYYY-MM`
- `--months` : nombre de mois à inclure, mois courant inclus
- `--limit` : nombre maximum d'URLs à traiter depuis le sitemap
- `--workers` : nombre de requêtes parallèles

Pour le scraper d'enrichissement :

- `--input` : chemin du fichier `finishers_events.json` à enrichir
- `--output` : chemin du JSON enrichi
- `--limit` : nombre maximum d'événements à enrichir
- `--workers` : nombre de requêtes parallèles

### Fonctionnement

Le script principal :

1. lit le sitemap `https://www.finishers.com/sitemap/events.xml`
2. garde les URLs françaises de type `/course/...`
3. visite chaque fiche événement Finishers
4. extrait les données embarquées dans `__NEXT_DATA__`
5. filtre les événements sur la fenêtre demandée
6. exporte le résultat dans `finishers_events.json`

Le script d'enrichissement :

1. lit chaque entrée de `finishers_events.json`
2. revisite la page détail associée
3. extrait les liens externes, éditions, courses et résultats
4. exporte le résultat enrichi dans `finishers_events_with_races.json`
