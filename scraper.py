"""
Collecte d'événements IA en France — multi-sources.
Sources : Eventbrite, Meetup, Luma, conférences, corporate.
"""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import PRIORITY_CITIES, EVENT_TYPES

# ── En-têtes HTTP ─────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RevueEvenementIA/1.0)"}

# ── Mots-clés de recherche ────────────────────────────────────────────────
SEARCH_QUERIES = [
    "intelligence artificielle", "IA", "AI",
    "machine learning", "deep learning", "LLM",
    "data science", "chatbot", "GenAI", "IA générative",
    "café IA", "cafe IA",
]

# ── Mots-clés de classification par type ──────────────────────────────────
KEYWORDS_SALON = ["salon", "exposition", "expo", "forum", "foire", "show"]
KEYWORDS_CONFERENCE = ["conférence", "conference", "summit", "sommet", "keynote", "symposium"]
KEYWORDS_MEETUP = ["meetup", "meet-up", "rencontre", "afterwork", "networking", "café ia", "cafe ia"]
KEYWORDS_ATELIER = ["atelier", "workshop", "hands-on", "bootcamp", "formation", "masterclass"]
KEYWORDS_CORPORATE = ["corporate", "entreprise", "client", "partenaire", "business"]
KEYWORDS_WEBINAIRE = ["webinaire", "webinar", "en ligne", "online", "virtuel", "remote"]


# ── Helpers ───────────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités pour obtenir du texte brut."""
    if not text:
        return ""
    # Supprimer les balises HTML
    text = re.sub(r"<[^>]+>", " ", text)
    # Décoder les entités HTML (&amp; &lt; &#39; etc.)
    text = unescape(text)
    # Normaliser les espaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Normalisation ─────────────────────────────────────────────────────────

# Formats de date français courants : JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA
_FR_DATE_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")


def normalize_date(date_str: str) -> str:
    """Normalise n'importe quel format de date en YYYY-MM-DD.

    Formats supportés :
    - ISO 8601 : 2025-09-15, 2025-09-15T10:00:00Z, 2025-09-15T10:00:00+02:00
    - RFC 2822 : Mon, 15 Sep 2025 10:00:00 +0200
    - Français : 15/09/2025, 15-09-2025, 15.09.2025
    """
    if not date_str or not date_str.strip():
        return ""

    s = date_str.strip()

    # 1. Déjà au format YYYY-MM-DD ?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # 2. ISO 8601 avec heure/timezone (2025-09-15T10:00:00Z ou +02:00)
    if "T" in s or s.startswith("20") or s.startswith("19"):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    # 3. RFC 2822 (email.utils gère les variantes)
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # 4. Formats français JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA
    m = _FR_DATE_RE.match(s)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return ""

    # 5. Dernière tentative : formats courants supplémentaires
    for fmt in (
        "%d %B %Y",      # 15 septembre 2025
        "%d %b %Y",      # 15 sep 2025
        "%B %d, %Y",     # September 15, 2025
        "%b %d, %Y",     # Sep 15, 2025
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822 variante
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return ""


def normalize_city(city: str) -> str:
    """Normalise le nom de ville en majuscules avec accents préservés.

    Python upper() gère nativement les accents Unicode :
    'aix-en-provence' → 'AIX-EN-PROVENCE'
    'marseille' → 'MARSEILLE'
    """
    if not city or not city.strip():
        return ""
    return city.strip().upper()


def _normalize_for_dedup(name: str) -> str:
    """Normalise un nom pour la déduplication.

    Minuscules, suppression ponctuation, espaces multiples → un seul, tronqué à 60 chars.
    """
    if not name:
        return ""
    result = name.lower()
    result = re.sub(r"[^\w\s]", "", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result[:60]


# ── Mots-clés pour la détection d'événements en ligne ─────────────────────
_ONLINE_KEYWORDS = ["en ligne", "online", "webinar", "virtuel", "remote"]


def _detect_online(venue: str, description: str) -> bool:
    """Détecte si un événement est en ligne via mots-clés dans le lieu ou la description.

    Vérifie la présence de : en ligne, online, webinar, virtuel, remote.
    La recherche est insensible à la casse.
    """
    text = f"{venue or ''} {description or ''}".lower()
    return any(kw in text for kw in _ONLINE_KEYWORDS)


def validate_event(raw_dict: dict) -> dict | None:
    """Valide et normalise un dictionnaire d'événement brut.

    - Exclut l'événement si ``name`` ou ``date_start`` est absent ou vide → retourne None.
    - Met ``"Non précisé"`` pour les champs optionnels manquants (venue, price, organizer).
    - Normalise ``date_start`` via :func:`normalize_date`.
    - Normalise ``city`` via :func:`normalize_city`.
    - Détecte les événements en ligne → fixe ``city`` à ``"EN LIGNE"`` et ``is_online`` à True.
    - Calcule ``is_priority`` selon :data:`PRIORITY_CITIES`.
    - Fixe ``event_type`` à ``"Autre"`` si absent.
    - Fixe ``source`` à ``"Inconnu"`` si absent.

    Returns:
        Un dictionnaire validé ou ``None`` si l'événement est invalide.
    """
    if not raw_dict:
        return None

    name = (raw_dict.get("name") or "").strip()
    date_start_raw = (raw_dict.get("date_start") or "").strip()

    # Champs obligatoires : name et date_start
    if not name or not date_start_raw:
        return None

    # Normaliser la date
    date_start = normalize_date(date_start_raw)
    if not date_start:
        return None

    # Champs optionnels → "Non précisé" si absents/vides
    venue = (raw_dict.get("venue") or "").strip() or "Non précisé"
    price = (raw_dict.get("price") or "").strip() or "Non précisé"
    organizer = (raw_dict.get("organizer") or "").strip() or "Non précisé"

    # Autres champs
    description = (raw_dict.get("description") or "").strip()
    link = (raw_dict.get("link") or "").strip()
    date_end = (raw_dict.get("date_end") or "").strip()
    event_type = (raw_dict.get("event_type") or "").strip() or "Autre"
    source = (raw_dict.get("source") or "").strip() or "Inconnu"

    # Normaliser la ville
    city = normalize_city(raw_dict.get("city") or "")

    # Détection événement en ligne
    is_online = _detect_online(venue, description)
    if is_online:
        city = "EN LIGNE"

    # Priorité géographique
    is_priority = city in PRIORITY_CITIES

    return {
        "name": name,
        "date_start": date_start,
        "date_end": normalize_date(date_end) if date_end else "",
        "city": city,
        "venue": venue,
        "organizer": organizer,
        "description": description,
        "link": link,
        "price": price,
        "event_type": event_type,
        "source": source,
        "is_priority": is_priority,
        "is_online": is_online,
    }


# ── Classification par type ───────────────────────────────────────────────

def detect_event_type(name: str, description: str, source: str = "") -> str:
    """Classifie un événement dans exactement un type valide.

    Analyse les mots-clés dans le nom, la description et la source.
    Retourne "Autre" si aucun mot-clé ne correspond.
    """
    text = f"{name or ''} {description or ''} {source or ''}".lower()

    # Ordre de priorité : salon > conférence > meetup > atelier > corporate > webinaire
    for keywords, event_type in [
        (KEYWORDS_SALON, "Salon/Exposition"),
        (KEYWORDS_CONFERENCE, "Conférence"),
        (KEYWORDS_MEETUP, "Meetup"),
        (KEYWORDS_ATELIER, "Atelier/Workshop"),
        (KEYWORDS_CORPORATE, "Événement Corporate"),
        (KEYWORDS_WEBINAIRE, "Webinaire"),
    ]:
        if any(kw in text for kw in keywords):
            return event_type

    return "Autre"


# ── Déduplication ─────────────────────────────────────────────────────────

def _count_filled_fields(event: dict) -> int:
    """Compte les champs non-vides et non-'Non précisé'."""
    count = 0
    for k, v in event.items():
        if isinstance(v, str) and v and v != "Non précisé":
            count += 1
        elif isinstance(v, bool):
            count += 1
    return count


def deduplicate(events: list[dict]) -> list[dict]:
    """Déduplique les événements en deux passes.

    Passe 1 : par URL (link identique) — conserve le plus complet.
    Passe 2 : par clé nom normalisé + date_start + city — même logique.
    """
    if not events:
        return []

    # Passe 1 : par URL
    by_url: dict[str, dict] = {}
    no_url: list[dict] = []
    for ev in events:
        url = (ev.get("link") or "").strip()
        if not url:
            no_url.append(ev)
            continue
        if url in by_url:
            if _count_filled_fields(ev) > _count_filled_fields(by_url[url]):
                by_url[url] = ev
        else:
            by_url[url] = ev

    after_url = list(by_url.values()) + no_url

    # Passe 2 : par nom + date + ville
    by_key: dict[str, dict] = {}
    for ev in after_url:
        key = _normalize_for_dedup(ev.get("name", "")) + ev.get("date_start", "") + ev.get("city", "")
        if key in by_key:
            if _count_filled_fields(ev) > _count_filled_fields(by_key[key]):
                by_key[key] = ev
        else:
            by_key[key] = ev

    return list(by_key.values())


# ── Tri et filtrage ───────────────────────────────────────────────────────

# Villes françaises connues (non exhaustif, pour le filtrage géographique)
_FRENCH_CITIES = {
    "PARIS", "MARSEILLE", "LYON", "TOULOUSE", "NICE", "NANTES", "STRASBOURG",
    "MONTPELLIER", "BORDEAUX", "LILLE", "RENNES", "REIMS", "TOULON", "GRENOBLE",
    "DIJON", "ANGERS", "NÎMES", "VILLEURBANNE", "CLERMONT-FERRAND", "LE MANS",
    "AIX-EN-PROVENCE", "BREST", "TOURS", "AMIENS", "LIMOGES", "METZ", "PERPIGNAN",
    "BESANÇON", "ORLÉANS", "ROUEN", "MULHOUSE", "CAEN", "NANCY", "ARGENTEUIL",
    "SAINT-DENIS", "MONTREUIL", "CANNES", "AVIGNON", "VERSAILLES", "POITIERS",
    "LA ROCHELLE", "PAU", "CALAIS", "ANTIBES", "DUNKERQUE", "BÉZIERS",
    "SAINT-ÉTIENNE", "COLMAR", "TROYES", "VALENCE", "CHAMBÉRY", "ANNECY",
    "LA DÉFENSE", "SOPHIA ANTIPOLIS", "SACLAY", "ISSY-LES-MOULINEAUX",
    "BOULOGNE-BILLANCOURT", "LEVALLOIS-PERRET", "NEUILLY-SUR-SEINE",
    "EN LIGNE",  # Événements en ligne acceptés
}


def filter_france(events: list[dict]) -> list[dict]:
    """Filtre pour ne garder que les événements en France ou en ligne."""
    result = []
    for ev in events:
        city = ev.get("city", "")
        if ev.get("is_online"):
            result.append(ev)
        elif city in _FRENCH_CITIES:
            result.append(ev)
        elif any(fc in city for fc in _FRENCH_CITIES if len(fc) > 3):
            result.append(ev)
    return result


def sort_events(events: list[dict]) -> list[dict]:
    """Trie par date ASC, puis is_priority DESC, puis name ASC."""
    return sorted(events, key=lambda e: (
        e.get("date_start", "9999-99-99"),
        not e.get("is_priority", False),
        e.get("name", "").lower(),
    ))


def filter_past_events(events: list[dict]) -> list[dict]:
    """Exclut les événements dont date_start < aujourd'hui - 1 jour."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [ev for ev in events if ev.get("date_start", "") >= cutoff]


# ── Collecteurs par source ────────────────────────────────────────────────

def fetch_eventbrite(query: str = "intelligence artificielle", max_items: int = 20, city: str = "") -> list[dict]:
    """Scrape les événements Eventbrite en France liés à l'IA.

    Si ``city`` est fourni, recherche spécifiquement dans cette ville.
    """
    events = []
    try:
        if city:
            slug = city.lower().replace(" ", "-").replace("'", "-")
            url = f"https://www.eventbrite.fr/d/france--{slug}/{query.replace(' ', '-')}/"
        else:
            url = f"https://www.eventbrite.fr/d/france/{query.replace(' ', '-')}/"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        html = resp.text

        # Extraction basique des événements depuis le HTML
        # Eventbrite utilise des balises structurées avec data-testid
        import json
        # Chercher les données JSON embarquées dans la page
        pattern = r'<script type="application/ld\+json">(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches[:max_items]:
            try:
                data = json.loads(match)
                if isinstance(data, list):
                    for item in data:
                        ev = _parse_eventbrite_jsonld(item)
                        if ev:
                            events.append(ev)
                elif isinstance(data, dict):
                    ev = _parse_eventbrite_jsonld(data)
                    if ev:
                        events.append(ev)
            except (json.JSONDecodeError, KeyError):
                continue

        print(f"  [SCRAPER] Eventbrite '{query}': {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Eventbrite erreur: {e}")
    return events[:max_items]


def _parse_eventbrite_jsonld(data: dict) -> dict | None:
    """Parse un objet JSON-LD Eventbrite en dict événement."""
    if data.get("@type") != "Event":
        return None
    name = data.get("name", "")
    if not name:
        return None
    location = data.get("location", {})
    address = location.get("address", {})
    city = address.get("addressLocality", "") if isinstance(address, dict) else ""
    return {
        "name": _clean_html(name),
        "date_start": (data.get("startDate") or "")[:10],
        "date_end": (data.get("endDate") or "")[:10],
        "city": city,
        "venue": location.get("name", ""),
        "organizer": (data.get("organizer", {}) or {}).get("name", ""),
        "description": _clean_html((data.get("description") or "")[:500]),
        "link": data.get("url", ""),
        "price": "Gratuit" if data.get("isAccessibleForFree") else "Payant",
        "source": "Eventbrite",
    }


def fetch_meetup(max_items: int = 20) -> list[dict]:
    """Scrape les événements Meetup IA en France et par ville PACA."""
    events = []
    try:
        # Recherches nationales + recherches ciblées par ville PACA
        search_combos = []
        for query in ["intelligence-artificielle", "machine-learning", "ai-artificial-intelligence"]:
            search_combos.append(("fr--France", query))
        for city in _PACA_CITIES:
            slug = city.lower().replace(" ", "-").replace("'", "-")
            for query in ["intelligence-artificielle", "machine-learning", "data-science", "tech", "cafe-ia"]:
                search_combos.append((f"fr--{slug}", query))

        seen_urls = set()
        for location, query in search_combos:
            url = f"https://www.meetup.com/find/?keywords={query}&location={location}&source=EVENTS"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            # Extraction JSON-LD
            import json
            matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "Event":
                            ev_url = item.get("url", "")
                            if ev_url in seen_urls:
                                continue
                            seen_urls.add(ev_url)
                            loc = item.get("location", {}) or {}
                            addr = loc.get("address", {}) or {}
                            events.append({
                                "name": _clean_html(item.get("name", "")),
                                "date_start": (item.get("startDate") or "")[:10],
                                "date_end": (item.get("endDate") or "")[:10],
                                "city": addr.get("addressLocality", ""),
                                "venue": loc.get("name", ""),
                                "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                                "description": _clean_html((item.get("description") or "")[:500]),
                                "link": ev_url,
                                "price": "Gratuit",
                                "source": "Meetup",
                            })
                except (json.JSONDecodeError, KeyError):
                    continue
        print(f"  [SCRAPER] Meetup: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Meetup erreur: {e}")
    return events[:max_items]


def fetch_luma(max_items: int = 15) -> list[dict]:
    """Scrape les événements Luma IA en France et PACA."""
    events = []
    try:
        queries = [
            "AI+France",
            "AI+Marseille",
            "intelligence+artificielle+Marseille",
            "tech+Aix-en-Provence",
        ]
        seen_urls = set()
        for query in queries:
            url = f"https://lu.ma/discover?query={query}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                import json
                matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
                for match in matches:
                    try:
                        data = json.loads(match)
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if item.get("@type") == "Event":
                                ev_url = item.get("url", "")
                                if ev_url in seen_urls:
                                    continue
                                seen_urls.add(ev_url)
                                loc = item.get("location", {}) or {}
                                addr = loc.get("address", {}) or {}
                                events.append({
                                    "name": _clean_html(item.get("name", "")),
                                    "date_start": (item.get("startDate") or "")[:10],
                                    "city": addr.get("addressLocality", ""),
                                    "venue": loc.get("name", ""),
                                    "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                                    "description": _clean_html((item.get("description") or "")[:500]),
                                    "link": ev_url,
                                    "price": "Gratuit",
                                    "source": "Luma",
                                })
                    except (json.JSONDecodeError, KeyError):
                        continue
        print(f"  [SCRAPER] Luma: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Luma erreur: {e}")
    return events[:max_items]


# Sites de conférences IA connus en France
_CONFERENCE_SITES = [
    ("AI Paris", "https://aiparis.fr"),
    ("VivaTech", "https://vivatechnology.com"),
    ("Big Data & AI Paris", "https://www.bigdataparis.com"),
    ("France is AI", "https://www.franceisai.com"),
    ("World AI Cannes", "https://worldaicannes.com"),
    ("AIM Marseille", "https://aim-marseille.com"),
    ("La Maison de l'IA", "https://www.maison-intelligence-artificielle.com"),
]

# Villes PACA pour recherches ciblées
_PACA_CITIES = ["Marseille", "Aix-en-Provence", "Toulon", "Cannes", "Nice"]

# Sources d'agrégateurs d'événements (dev.events, 10times, conferencealert)
_AGGREGATOR_URLS = [
    ("dev.events Marseille", "https://dev.events/EU/FR/Marseille/ai"),
    ("dev.events Aix", "https://dev.events/EU/FR/Aix-en-Provence/ai"),
    ("dev.events Nice", "https://dev.events/EU/FR/Nice/ai"),
    ("10times Marseille", "https://www.10times.com/marseille-fr/technology"),
    ("10times Aix", "https://www.10times.com/aix-en-provence-fr/technology"),
    ("ConferenceAlert Marseille", "https://www.conferencealert.com/marseille/artificial-intelligence"),
]


def fetch_conferences() -> list[dict]:
    """Scrape les sites de conférences IA connues en France."""
    events = []
    import json
    for name, url in _CONFERENCE_SITES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "Event":
                            loc = item.get("location", {}) or {}
                            addr = loc.get("address", {}) or {}
                            events.append({
                                "name": _clean_html(item.get("name", "")),
                                "date_start": (item.get("startDate") or "")[:10],
                                "date_end": (item.get("endDate") or "")[:10],
                                "city": addr.get("addressLocality", ""),
                                "venue": loc.get("name", ""),
                                "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                                "description": _clean_html((item.get("description") or "")[:500]),
                                "link": item.get("url", url),
                                "price": "",
                                "source": name,
                            })
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            print(f"  [SCRAPER] Conférence {name} erreur: {e}")
    print(f"  [SCRAPER] Conférences: {len(events)} événement(s)")
    return events


# Sites corporate connus pour événements IA
_CORPORATE_SITES = [
    ("Google Cloud Events", "https://cloud.google.com/events"),
    ("Microsoft AI Events", "https://events.microsoft.com"),
    ("AWS Events", "https://aws.amazon.com/fr/events/"),
    ("OVHcloud Events", "https://events.ovhcloud.com"),
    ("Dataiku Events", "https://www.dataiku.com/events/"),
]


def fetch_corporate_events() -> list[dict]:
    """Scrape les pages événements d'entreprises tech."""
    events = []
    import json
    for name, url in _CORPORATE_SITES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "Event":
                            loc = item.get("location", {}) or {}
                            addr = loc.get("address", {}) or {}
                            country = addr.get("addressCountry", "")
                            # Filtrer uniquement France
                            if country and country.upper() not in ("FR", "FRANCE"):
                                continue
                            events.append({
                                "name": _clean_html(item.get("name", "")),
                                "date_start": (item.get("startDate") or "")[:10],
                                "date_end": (item.get("endDate") or "")[:10],
                                "city": addr.get("addressLocality", ""),
                                "venue": loc.get("name", ""),
                                "organizer": name.split(" ")[0],
                                "description": _clean_html((item.get("description") or "")[:500]),
                                "link": item.get("url", url),
                                "price": "",
                                "source": name,
                            })
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            print(f"  [SCRAPER] Corporate {name} erreur: {e}")
    print(f"  [SCRAPER] Corporate: {len(events)} événement(s)")
    return events


def fetch_aggregators() -> list[dict]:
    """Scrape les agrégateurs d'événements (dev.events, 10times, conferencealert).

    Ces sites listent des conférences et événements tech par ville,
    ce qui permet de capter des événements PACA absents d'Eventbrite/Meetup.
    """
    events = []
    import json
    for name, url in _AGGREGATOR_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            html = resp.text

            # Tenter JSON-LD d'abord
            matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "Event":
                            loc = item.get("location", {}) or {}
                            addr = loc.get("address", {}) or {}
                            events.append({
                                "name": _clean_html(item.get("name", "")),
                                "date_start": (item.get("startDate") or "")[:10],
                                "date_end": (item.get("endDate") or "")[:10],
                                "city": addr.get("addressLocality", ""),
                                "venue": loc.get("name", ""),
                                "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                                "description": _clean_html((item.get("description") or "")[:500]),
                                "link": item.get("url", url),
                                "price": "",
                                "source": name,
                            })
                except (json.JSONDecodeError, KeyError):
                    continue

            # Fallback : extraction basique de liens d'événements depuis le HTML
            # Chercher des patterns de titre + date dans le HTML brut
            if not events or "10times" in name.lower():
                # 10times utilise des cartes avec titre et date
                card_pattern = r'<h\d[^>]*>(.*?)</h\d>.*?(\d{1,2}\s+\w+\s+\d{4})'
                card_matches = re.findall(card_pattern, html, re.DOTALL)
                for title, date_str in card_matches[:10]:
                    clean_title = _clean_html(title)
                    # Filtrer les titres liés à l'IA/tech
                    if not any(kw in clean_title.lower() for kw in
                               ["ai", "ia", "intelligence", "machine learning",
                                "data", "deep learning", "tech", "digital",
                                "cloud", "cyber", "robot", "café ia", "cafe ia"]):
                        continue
                    # Extraire la ville depuis le nom de la source
                    city = ""
                    for c in _PACA_CITIES:
                        if c.lower() in name.lower():
                            city = c
                            break
                    events.append({
                        "name": clean_title,
                        "date_start": normalize_date(date_str),
                        "city": city,
                        "venue": "",
                        "organizer": "",
                        "description": "",
                        "link": url,
                        "price": "",
                        "source": name,
                    })

        except Exception as e:
            print(f"  [SCRAPER] Agrégateur {name} erreur: {e}")
    print(f"  [SCRAPER] Agrégateurs: {len(events)} événement(s)")
    return events


# ── Orchestrateur principal ───────────────────────────────────────────────

def collect_events() -> list[dict]:
    """Collecte, valide, déduplique, classe, filtre et trie les événements.

    Exécute les collecteurs en parallèle via ThreadPoolExecutor(max_workers=10).
    Inclut des recherches ciblées par ville PACA pour maximiser la couverture
    Marseille, Aix-en-Provence, Toulon, Cannes, Nice.
    Retourne la liste finale d'événements prêts pour le rapport.
    """
    print("=== Collecte des événements IA en France ===")

    tasks = [
        # Recherches nationales
        ("Eventbrite IA", lambda: fetch_eventbrite("intelligence artificielle")),
        ("Eventbrite AI", lambda: fetch_eventbrite("AI artificial intelligence")),
        ("Meetup", lambda: fetch_meetup()),
        ("Luma", lambda: fetch_luma()),
        ("Conférences", lambda: fetch_conferences()),
        ("Corporate", lambda: fetch_corporate_events()),
        ("Agrégateurs", lambda: fetch_aggregators()),
        # Recherches Eventbrite ciblées par ville PACA
        ("Eventbrite Marseille IA", lambda: fetch_eventbrite("intelligence artificielle", city="Marseille")),
        ("Eventbrite Marseille tech", lambda: fetch_eventbrite("tech data", city="Marseille")),
        ("Eventbrite Aix IA", lambda: fetch_eventbrite("intelligence artificielle", city="Aix-en-Provence")),
        ("Eventbrite Toulon IA", lambda: fetch_eventbrite("intelligence artificielle", city="Toulon")),
        ("Eventbrite Cannes IA", lambda: fetch_eventbrite("intelligence artificielle", city="Cannes")),
        ("Eventbrite Nice IA", lambda: fetch_eventbrite("intelligence artificielle", city="Nice")),
        ("Eventbrite Marseille data", lambda: fetch_eventbrite("data science machine learning", city="Marseille")),
    ]

    all_raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                all_raw.extend(result)
            except Exception as e:
                print(f"  [SCRAPER] {name} erreur: {e}")

    print(f"  → Brut: {len(all_raw)} événements collectés")

    # Validation
    validated = []
    for raw in all_raw:
        ev = validate_event(raw)
        if ev:
            # Classifier le type
            ev["event_type"] = detect_event_type(ev["name"], ev["description"], ev["source"])
            validated.append(ev)

    print(f"  → Validés: {len(validated)}")

    # Déduplication
    unique = deduplicate(validated)
    print(f"  → Dédupliqués: {len(unique)}")

    # Filtrage géographique
    france = filter_france(unique)
    print(f"  → France: {len(france)}")

    # Filtrage temporel
    future_events = filter_past_events(france)
    print(f"  → Futurs: {len(future_events)}")

    # Tri
    sorted_events = sort_events(future_events)
    print(f"  → Total final: {len(sorted_events)} événements")

    return sorted_events
