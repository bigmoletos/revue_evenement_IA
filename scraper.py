"""
Collecte d'événements IA en France — multi-sources.
Sources : Eventbrite, Meetup, Luma, Weezevent, HelloAsso, OpenAgenda,
          Mobilizon, BilletWeb, Bevy/GDG, conférences, corporate.
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
KEYWORDS_SALON = ["salon", "exposition", "expo", "forum", "foire", "show", "trade show", "tech show"]
KEYWORDS_CONFERENCE = ["conférence", "conference", "summit", "sommet", "keynote", "symposium", "congress", "congrès"]
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
    "NANTERRE",  # Paris La Défense Arena
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


def _parse_meetup_events(html: str, seen_urls: set, source: str = "Meetup") -> list[dict]:
    """Extrait les événements JSON-LD d'une page Meetup et retourne une liste de dicts."""
    import json
    events = []
    matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") != "Event":
                    continue
                ev_url = item.get("url", "")
                if ev_url in seen_urls:
                    continue
                seen_urls.add(ev_url)
                loc = item.get("location", {}) or {}
                addr = loc.get("address", {}) or {}
                city = addr.get("addressLocality", "")
                # Événement en ligne : normaliser la ville
                if not city or loc.get("@type") == "VirtualLocation":
                    city = "EN LIGNE"
                events.append({
                    "name": _clean_html(item.get("name", "")),
                    "date_start": (item.get("startDate") or "")[:10],
                    "date_end": (item.get("endDate") or "")[:10],
                    "city": city,
                    "venue": loc.get("name", ""),
                    "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                    "description": _clean_html((item.get("description") or "")[:500]),
                    "link": ev_url,
                    "price": "Gratuit",
                    "source": source,
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return events


def fetch_meetup(max_items: int = 30) -> list[dict]:
    """Scrape les événements Meetup IA/GPU/dev en France et par ville PACA."""
    events = []
    try:
        # Mots-clés nationaux IA
        _QUERIES_NATIONAL = [
            "intelligence-artificielle",
            "machine-learning",
            "ai-artificial-intelligence",
        ]
        # Mots-clés ciblés Marseille/PACA : IA + GPU + dev/coding
        _QUERIES_MARSEILLE = [
            "intelligence-artificielle",
            "machine-learning",
            "data-science",
            "cafe-ia",
            "llm",
            "genai",
            "gpu",
            "vibe-coding",
            "python",
            "coding",
            "deep-learning",
            "tech",
        ]

        search_combos = []
        for query in _QUERIES_NATIONAL:
            search_combos.append(("fr--France", query))
        for city in _PACA_CITIES:
            slug = city.lower().replace(" ", "-").replace("'", "-")
            for query in _QUERIES_MARSEILLE:
                search_combos.append((f"fr--{slug}", query))

        seen_urls: set = set()
        for location, query in search_combos:
            url = f"https://www.meetup.com/find/?keywords={query}&location={location}&source=EVENTS"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            events.extend(_parse_meetup_events(resp.text, seen_urls))

        print(f"  [SCRAPER] Meetup: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Meetup erreur: {e}")
    return events[:max_items]


def fetch_meetup_online(max_items: int = 30) -> list[dict]:
    """Scrape les meetups en ligne (France) sur les thèmes IA, GPU, vibe-coding, LLM, dev."""
    events = []
    try:
        # Recherches dédiées aux événements en ligne sur ces sujets
        _ONLINE_QUERIES = [
            "intelligence-artificielle",
            "ai-artificial-intelligence",
            "llm",
            "genai",
            "gpu",
            "vibe-coding",
            "deep-learning",
            "machine-learning",
            "python-ia",
            "coding",
            "data-science",
        ]

        seen_urls: set = set()
        for query in _ONLINE_QUERIES:
            # Filtre eventType=online de Meetup
            url = (
                f"https://www.meetup.com/find/?keywords={query}"
                f"&source=EVENTS&eventType=online"
            )
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            raw = _parse_meetup_events(resp.text, seen_urls, source="Meetup (en ligne)")
            # S'assurer que la ville est bien "EN LIGNE" pour tous ces résultats
            for ev in raw:
                if not ev["city"] or ev["city"].upper() in ("", "ONLINE"):
                    ev["city"] = "EN LIGNE"
            events.extend(raw)

        print(f"  [SCRAPER] Meetup en ligne: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Meetup en ligne erreur: {e}")
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


# ── Helper JSON-LD générique ──────────────────────────────────────────────────

def _parse_jsonld_events(html: str, seen_urls: set, source: str) -> list[dict]:
    """Extrait tous les événements JSON-LD d'une page HTML quelconque."""
    import json
    events = []
    matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") != "Event":
                    continue
                ev_url = item.get("url", "")
                if ev_url in seen_urls:
                    continue
                seen_urls.add(ev_url)
                loc = item.get("location", {}) or {}
                addr = loc.get("address", {}) or {}
                city = addr.get("addressLocality", "")
                if not city and loc.get("@type") == "VirtualLocation":
                    city = "EN LIGNE"
                events.append({
                    "name": _clean_html(item.get("name", "")),
                    "date_start": (item.get("startDate") or "")[:10],
                    "date_end": (item.get("endDate") or "")[:10],
                    "city": city,
                    "venue": loc.get("name", ""),
                    "organizer": (item.get("organizer", {}) or {}).get("name", ""),
                    "description": _clean_html((item.get("description") or "")[:500]),
                    "link": ev_url,
                    "price": "Gratuit" if item.get("isAccessibleForFree") else "Non précisé",
                    "source": source,
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return events


# ── Weezevent ─────────────────────────────────────────────────────────────────

def fetch_weezevent(max_items: int = 25) -> list[dict]:
    """Scrape les événements Weezevent IA/tech en France."""
    events = []
    seen_urls: set = set()
    _QUERIES = [
        "intelligence artificielle",
        "machine learning GPU",
        "vibe coding dev",
        "data science IA",
    ]
    try:
        for query in _QUERIES:
            url = (
                "https://my.weezevent.com/events"
                f"?keyword={requests.utils.quote(query)}&country=FR"
            )
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            events.extend(_parse_jsonld_events(resp.text, seen_urls, "Weezevent"))
        print(f"  [SCRAPER] Weezevent: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Weezevent erreur: {e}")
    return events[:max_items]


# ── HelloAsso ─────────────────────────────────────────────────────────────────

def fetch_helloasso(max_items: int = 25) -> list[dict]:
    """Scrape les événements HelloAsso IA/tech en France (associations, meetups)."""
    import json
    events = []
    seen_urls: set = set()
    _QUERIES = [
        "intelligence artificielle",
        "IA machine learning",
        "GPU coding dev",
        "data science",
        "café IA",
    ]
    _CITIES = ["Marseille", "Aix-en-Provence", "Paris", "Lyon"]
    try:
        combos = [(q, "") for q in _QUERIES] + [(q, c) for q in _QUERIES[:2] for c in _CITIES]
        for query, city in combos:
            params = f"q={requests.utils.quote(query)}&type=Event"
            if city:
                params += f"&location={requests.utils.quote(city)}"
            url = f"https://www.helloasso.com/recherche?{params}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            # Tenter JSON-LD standard
            evs = _parse_jsonld_events(resp.text, seen_urls, "HelloAsso")
            events.extend(evs)
            # Fallback : données Next.js embarquées (__NEXT_DATA__)
            if not evs:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                if m:
                    try:
                        nd = json.loads(m.group(1))
                        results = (
                            nd.get("props", {})
                            .get("pageProps", {})
                            .get("initialSearchResults", {})
                            .get("results", [])
                        )
                        for item in results:
                            if item.get("type") not in ("Event", "event"):
                                continue
                            ev_url = item.get("url", "") or item.get("link", "")
                            if ev_url in seen_urls:
                                continue
                            seen_urls.add(ev_url)
                            events.append({
                                "name": _clean_html(item.get("name", "") or item.get("title", "")),
                                "date_start": (item.get("startDate") or item.get("date") or "")[:10],
                                "date_end": (item.get("endDate") or "")[:10],
                                "city": item.get("city", "") or item.get("place", ""),
                                "venue": item.get("place", ""),
                                "organizer": item.get("organizationName", ""),
                                "description": _clean_html((item.get("description") or "")[:500]),
                                "link": ev_url,
                                "price": "Gratuit",
                                "source": "HelloAsso",
                            })
                    except (json.JSONDecodeError, KeyError):
                        pass
        print(f"  [SCRAPER] HelloAsso: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] HelloAsso erreur: {e}")
    return events[:max_items]


# ── OpenAgenda ────────────────────────────────────────────────────────────────

def fetch_openagenda(max_items: int = 30) -> list[dict]:
    """Scrape les événements OpenAgenda IA/tech en France.

    Utilise l'API v2 si OPENAGENDA_KEY est défini dans les variables d'env,
    sinon scrape les pages de recherche publiques (JSON-LD).
    """
    import json
    from config import OPENAGENDA_KEY  # clé optionnelle, "" si absente
    events = []
    seen_urls: set = set()
    _KEYWORDS = ["intelligence artificielle", "IA", "machine learning", "GPU", "vibe coding", "LLM", "data science"]

    try:
        if OPENAGENDA_KEY:
            # ── Mode API ──────────────────────────────────────────────────
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            for kw in _KEYWORDS:
                url = "https://api.openagenda.com/v2/events"
                params = {
                    "key": OPENAGENDA_KEY,
                    "search": kw,
                    "size": 20,
                    "timings[gte]": today,
                    "sort[]": "dateRange.asc",
                    "lang": "fr",
                }
                try:
                    resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("events", []):
                    ev_url = (
                        item.get("canonicalUrl")
                        or f"https://openagenda.com/events/{item.get('uid', '')}"
                    )
                    if ev_url in seen_urls:
                        continue
                    seen_urls.add(ev_url)
                    loc = item.get("location", {}) or {}
                    timings = item.get("timings", [{}])
                    date_start = (timings[0].get("begin") or "")[:10] if timings else ""
                    date_end = (timings[-1].get("end") or "")[:10] if timings else ""
                    city = loc.get("city", "") or loc.get("postalAddress", {}).get("addressLocality", "")
                    events.append({
                        "name": _clean_html(item.get("title", {}).get("fr", "") or item.get("title", "")),
                        "date_start": date_start,
                        "date_end": date_end,
                        "city": city,
                        "venue": loc.get("name", ""),
                        "organizer": "",
                        "description": _clean_html(
                            ((item.get("description") or {}).get("fr", "") or "")[:500]
                        ),
                        "link": ev_url,
                        "price": "Non précisé",
                        "source": "OpenAgenda",
                    })
        else:
            # ── Mode scraping web (fallback sans clé API) ─────────────────
            for kw in _KEYWORDS:
                url = f"https://openagenda.com/recherche?q={requests.utils.quote(kw)}&lang=fr"
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=10)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
                events.extend(_parse_jsonld_events(resp.text, seen_urls, "OpenAgenda"))

        print(f"  [SCRAPER] OpenAgenda: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] OpenAgenda erreur: {e}")
    return events[:max_items]


# ── Mobilizon ─────────────────────────────────────────────────────────────────

def fetch_mobilizon(max_items: int = 25) -> list[dict]:
    """Scrape les événements Mobilizon (instance mobilizon.fr — Framasoft) IA/tech."""
    import json
    events = []
    seen_urls: set = set()
    GRAPHQL_URL = "https://mobilizon.fr/api"
    _TERMS = [
        "intelligence artificielle", "IA", "machine learning",
        "GPU", "vibe coding", "LLM", "data science", "Python dev",
    ]
    _GQL = """
        query SearchEvents($term: String!) {
            searchEvents(term: $term, page: 1, limit: 20) {
                total
                elements {
                    title
                    beginsOn
                    endsOn
                    url
                    description
                    onlineAddress { url }
                    physicalAddress { locality description }
                    organizerActor { name preferredUsername }
                }
            }
        }
    """
    try:
        for term in _TERMS:
            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json={"query": _GQL, "variables": {"term": term}},
                    headers={**HEADERS, "Content-Type": "application/json"},
                    timeout=10,
                )
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            data = resp.json()
            elements = (
                (data.get("data") or {})
                .get("searchEvents", {})
                .get("elements", [])
            )
            for item in elements:
                ev_url = item.get("url", "")
                if ev_url in seen_urls:
                    continue
                seen_urls.add(ev_url)
                phys = item.get("physicalAddress") or {}
                online = item.get("onlineAddress") or {}
                city = phys.get("locality", "") or ("EN LIGNE" if online.get("url") else "")
                org = item.get("organizerActor") or {}
                events.append({
                    "name": _clean_html(item.get("title", "")),
                    "date_start": (item.get("beginsOn") or "")[:10],
                    "date_end": (item.get("endsOn") or "")[:10],
                    "city": city,
                    "venue": phys.get("description", ""),
                    "organizer": org.get("name") or org.get("preferredUsername") or "",
                    "description": _clean_html((item.get("description") or "")[:500]),
                    "link": ev_url or online.get("url", ""),
                    "price": "Gratuit",
                    "source": "Mobilizon",
                })
        print(f"  [SCRAPER] Mobilizon: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Mobilizon erreur: {e}")
    return events[:max_items]


# ── BilletWeb ─────────────────────────────────────────────────────────────────

def fetch_billetweb(max_items: int = 20) -> list[dict]:
    """Scrape les événements BilletWeb IA/tech en France."""
    events = []
    seen_urls: set = set()
    _QUERIES = [
        "intelligence artificielle",
        "IA machine learning",
        "GPU vibe coding",
        "data science tech",
    ]
    try:
        for query in _QUERIES:
            url = (
                "https://www.billetweb.fr/recherche"
                f"?search={requests.utils.quote(query)}&type=event"
            )
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            events.extend(_parse_jsonld_events(resp.text, seen_urls, "BilletWeb"))
        print(f"  [SCRAPER] BilletWeb: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] BilletWeb erreur: {e}")
    return events[:max_items]


# ── Bevy (GDG / AWS User Groups / communautés tech) ──────────────────────────

# Pages communautaires connues hébergées sur Bevy
_BEVY_COMMUNITY_URLS = [
    ("GDG France", "https://gdg.community.dev/events/#/list?c=France"),
    ("GDG Marseille", "https://gdg.community.dev/gdg-marseille/"),
    ("GDG Aix-en-Provence", "https://gdg.community.dev/gdg-aix-en-provence/"),
    ("GDG Nice Sophia", "https://gdg.community.dev/gdg-nice-sophia-antipolis/"),
    ("AWS UG France", "https://community.aws/events?lang=fr&country=France"),
    ("CNCF Community", "https://community.cncf.io/events/"),
    ("PyData France", "https://www.meetup.com/pydata-paris/events/"),
]


def fetch_bevy(max_items: int = 20) -> list[dict]:
    """Scrape les événements Bevy (GDG, AWS UG, PyData…) IA/dev en France."""
    events = []
    seen_urls: set = set()
    try:
        for name, url in _BEVY_COMMUNITY_URLS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            evs = _parse_jsonld_events(resp.text, seen_urls, f"Bevy/{name}")
            events.extend(evs)
        print(f"  [SCRAPER] Bevy/GDG: {len(events)} événement(s)")
    except Exception as e:
        print(f"  [SCRAPER] Bevy/GDG erreur: {e}")
    return events[:max_items]


# Sites de conférences et grands salons IA connus en France
_CONFERENCE_SITES = [
    # ── Grands salons Paris ──────────────────────────────────────────────
    ("AI Paris", "https://aiparis.fr"),
    ("VivaTech", "https://vivatechnology.com"),                          # Porte de Versailles, juin
    ("Big Data & AI Paris", "https://www.bigdataparis.com"),             # Porte de Versailles, sept
    ("France is AI", "https://www.franceisai.com"),
    ("dotAI Paris", "https://www.dotai.io"),                             # Folies Bergère, sept
    ("RAISE Summit", "https://www.raisesummit.com"),                     # Carrousel du Louvre, juil
    ("AI Pulse", "https://www.ai-pulse.eu"),                             # Station F, oct
    ("Tech Show Paris", "https://www.techshowparis.com"),                # Porte de Versailles, nov
    ("Cloud Expo Europe Paris", "https://www.cloudexpoeurope.fr"),       # Porte de Versailles, nov
    ("IT Partners", "https://www.itpartners.fr"),                        # Paris La Défense Arena, fév
    ("Paris Cyber Summit", "https://www.paris-cyber-summit.com"),        # Paris
    ("Adopt AI", "https://adoptai.artefact.com"),                        # Grand Palais
    ("IDC AI & Data Summit", "https://event.idc.com/event/ai-data-summit_en/"),
    # ── Marseille / PACA ─────────────────────────────────────────────────
    ("World AI Cannes", "https://worldaicannes.com"),
    ("AIM Marseille", "https://aim-marseille.com"),                      # Marseille, nov (annuel)
    ("La Maison de l'IA", "https://www.maison-intelligence-artificielle.com"),  # Aix, permanent
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


# ── Événements connus 2025-2026 (fallback scraping) ───────────────────────
# Beaucoup de sites de conférences n'exposent pas de JSON-LD.
# Cette liste garantit la présence des grands rendez-vous confirmés.

_KNOWN_EVENTS = [
    # ── 2025 ─────────────────────────────────────────────────────────────
    {
        "name": "VivaTech 2025",
        "date_start": "2025-06-11", "date_end": "2025-06-14",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "VivaTech", "event_type": "Salon/Exposition",
        "link": "https://vivatechnology.com",
        "description": "Le plus grand salon européen dédié à l'innovation et aux startups tech/IA.",
        "source": "Calendrier connu",
    },
    {
        "name": "Big Data & AI Paris 2025",
        "date_start": "2025-09-15", "date_end": "2025-09-16",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "Corp Agency", "event_type": "Salon/Exposition",
        "link": "https://www.bigdataparis.com",
        "description": "Salon professionnel Big Data, IA et Analytics.",
        "source": "Calendrier connu",
    },
    {
        "name": "dotAI 2025",
        "date_start": "2025-09-17", "date_end": "",
        "city": "Paris", "venue": "Folies Bergère",
        "organizer": "dotConferences", "event_type": "Conférence",
        "link": "https://www.dotai.io",
        "description": "Conférence développeurs sur l'IA appliquée.",
        "source": "Calendrier connu",
    },
    {
        "name": "RAISE Summit 2025",
        "date_start": "2025-07-08", "date_end": "2025-07-09",
        "city": "Paris", "venue": "Carrousel du Louvre",
        "organizer": "RAISE", "event_type": "Conférence",
        "link": "https://www.raisesummit.com",
        "description": "Sommet européen sur l'IA responsable et l'investissement tech.",
        "source": "Calendrier connu",
    },
    {
        "name": "AI Pulse 2025",
        "date_start": "2025-10-13", "date_end": "",
        "city": "Paris", "venue": "Station F",
        "organizer": "AI Pulse", "event_type": "Conférence",
        "link": "https://www.ai-pulse.eu",
        "description": "Conférence IA à Station F — startups, recherche, industrie.",
        "source": "Calendrier connu",
    },
    {
        "name": "Cloud Expo Europe Paris 2025",
        "date_start": "2025-11-18", "date_end": "2025-11-19",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "CloserStill Media", "event_type": "Salon/Exposition",
        "link": "https://www.cloudexpoeurope.fr",
        "description": "Salon Cloud, Cybersécurité et IA — Porte de Versailles.",
        "source": "Calendrier connu",
    },
    {
        "name": "IT Partners 2025",
        "date_start": "2025-02-04", "date_end": "2025-02-05",
        "city": "Nanterre", "venue": "Paris La Défense Arena",
        "organizer": "Informa", "event_type": "Salon/Exposition",
        "link": "https://www.itpartners.fr",
        "description": "Salon de l'écosystème IT, cloud et IA — La Défense Arena.",
        "source": "Calendrier connu",
    },
    {
        "name": "World AI Cannes Festival 2025",
        "date_start": "2025-02-13", "date_end": "2025-02-14",
        "city": "Cannes", "venue": "Palais des Festivals",
        "organizer": "World AI Cannes", "event_type": "Conférence",
        "link": "https://worldaicannes.com",
        "description": "Festival international de l'IA à Cannes.",
        "source": "Calendrier connu",
    },
    {
        "name": "AIM — AI Marseille 2025",
        "date_start": "2025-11-15", "date_end": "",
        "city": "Marseille", "venue": "Palais du Pharo",
        "organizer": "AIM", "event_type": "Conférence",
        "link": "https://aim-marseille.com",
        "description": "Conférence annuelle IA à Marseille — recherche, industrie, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "AI Paris 2025",
        "date_start": "2025-06-10", "date_end": "",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "AI Paris", "event_type": "Conférence",
        "link": "https://aiparis.fr",
        "description": "Conférence IA de référence en France — Palais des Congrès.",
        "source": "Calendrier connu",
    },
    {
        "name": "Adopt AI Summit 2025",
        "date_start": "2025-05-22", "date_end": "",
        "city": "Paris", "venue": "Grand Palais",
        "organizer": "Artefact", "event_type": "Conférence",
        "link": "https://adoptai.artefact.com",
        "description": "Sommet sur l'adoption de l'IA en entreprise — Grand Palais.",
        "source": "Calendrier connu",
    },
    {
        "name": "Tech Show Paris 2025",
        "date_start": "2025-11-25", "date_end": "2025-11-26",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "Tech Show", "event_type": "Salon/Exposition",
        "link": "https://www.techshowparis.com",
        "description": "Salon des technologies émergentes — IA, IoT, Cloud.",
        "source": "Calendrier connu",
    },
    {
        "name": "Paris Cyber Summit 2025",
        "date_start": "2025-10-07", "date_end": "2025-10-08",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "Paris Cyber Summit", "event_type": "Conférence",
        "link": "https://www.paris-cyber-summit.com",
        "description": "Sommet cybersécurité et IA — Palais des Congrès.",
        "source": "Calendrier connu",
    },
    {
        "name": "France is AI 2025",
        "date_start": "2025-10-14", "date_end": "",
        "city": "Paris", "venue": "Station F",
        "organizer": "France is AI", "event_type": "Conférence",
        "link": "https://www.franceisai.com",
        "description": "Écosystème IA français — conférences, networking, démos.",
        "source": "Calendrier connu",
    },
    # ── Grands salons 2025 (hors Paris) ──────────────────────────────────
    {
        "name": "FIC 2025",
        "date_start": "2025-01-22", "date_end": "2025-01-23",
        "city": "Lille", "venue": "Grand Palais de Lille",
        "organizer": "Ceis / IN-CYBER", "event_type": "Salon/Exposition",
        "link": "https://www.forum-fic.com",
        "description": "Forum International de la Cybersécurité — cybersécurité, IA et souveraineté numérique.",
        "source": "Calendrier connu",
    },
    {
        "name": "Global Industrie Paris 2025",
        "date_start": "2025-03-25", "date_end": "2025-03-28",
        "city": "Villepinte", "venue": "Paris Nord Villepinte",
        "organizer": "Sepem Industries / GL events", "event_type": "Salon/Exposition",
        "link": "https://www.global-industrie.com",
        "description": "Le grand rendez-vous de l'industrie du futur — IA, robotique, automatisation, industrie 4.0.",
        "source": "Calendrier connu",
    },
    {
        "name": "SIDO Lyon 2025",
        "date_start": "2025-04-02", "date_end": "2025-04-03",
        "city": "Lyon", "venue": "Eurexpo Lyon",
        "organizer": "GL events", "event_type": "Salon/Exposition",
        "link": "https://www.sido-event.com",
        "description": "Le salon de référence IoT, IA et Robotique — convergence des technologies du futur.",
        "source": "Calendrier connu",
    },
    {
        "name": "Bpifrance Inno Génération 2025",
        "date_start": "2025-10-16", "date_end": "2025-10-16",
        "city": "Paris", "venue": "Accor Arena",
        "organizer": "Bpifrance", "event_type": "Salon/Exposition",
        "link": "https://www.bpifrance-innogeneration.fr",
        "description": "Le plus grand rassemblement entrepreneurial français — IA, deeptech, innovation, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "DATA.IA Summit 2025",
        "date_start": "2025-10-09", "date_end": "2025-10-10",
        "city": "Bordeaux", "venue": "Cité du Vin, Bordeaux",
        "organizer": "DATA.IA", "event_type": "Conférence",
        "link": "https://www.dataiasummit.com",
        "description": "Sommet national Data et IA — écosystème français, startups, grands groupes, recherche.",
        "source": "Calendrier connu",
    },
    {
        "name": "Open Source Experience 2025",
        "date_start": "2025-11-05", "date_end": "2025-11-06",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "Systematic Paris-Region", "event_type": "Salon/Exposition",
        "link": "https://www.opensource-experience.com",
        "description": "Le salon de l'open source, des logiciels libres et de l'IA ouverte.",
        "source": "Calendrier connu",
    },
    # ── Marseille / Aix-en-Provence / PACA 2025 ──────────────────────────
    {
        "name": "Les Rencontres Économiques d'Aix-en-Provence 2025",
        "date_start": "2025-07-03", "date_end": "2025-07-05",
        "city": "Aix-en-Provence", "venue": "Aix-en-Provence",
        "organizer": "Cercle des Économistes", "event_type": "Conférence",
        "link": "https://www.rencontres-economiques.fr",
        "description": "Grand forum économique et sociétal d'Aix — IA, transitions numériques, débats prospectifs.",
        "source": "Calendrier connu",
    },
    {
        "name": "RivieraDev 2025",
        "date_start": "2025-05-22", "date_end": "2025-05-23",
        "city": "Nice", "venue": "Acropolis Nice",
        "organizer": "RivieraDev", "event_type": "Conférence",
        "link": "https://rivieradev.fr",
        "description": "Conférence tech et IA pour développeurs — Côte d'Azur, sessions en français et anglais.",
        "source": "Calendrier connu",
    },
    {
        "name": "Med'Innovant 2025",
        "date_start": "2025-10-14", "date_end": "2025-10-15",
        "city": "Marseille", "venue": "Palais du Pharo",
        "organizer": "Aix-Marseille-Provence Métropole", "event_type": "Salon/Exposition",
        "link": "https://www.medinnovant.fr",
        "description": "Salon de l'innovation et du numérique de la métropole Aix-Marseille — IA, smart city, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "Sophia Antipolis AI & Tech Days 2025",
        "date_start": "2025-06-05", "date_end": "2025-06-06",
        "city": "Sophia Antipolis", "venue": "Sophia Antipolis",
        "organizer": "Fondation Sophia Antipolis", "event_type": "Conférence",
        "link": "https://www.sophia-antipolis.fr",
        "description": "Journées tech et IA à Sophia Antipolis — recherche, deeptech, startups méditerranéennes.",
        "source": "Calendrier connu",
    },
    # ── 2026 ─────────────────────────────────────────────────────────────
    {
        "name": "IT Partners 2026",
        "date_start": "2026-02-03", "date_end": "2026-02-04",
        "city": "Nanterre", "venue": "Paris La Défense Arena",
        "organizer": "Informa", "event_type": "Salon/Exposition",
        "link": "https://www.itpartners.fr",
        "description": "Salon de l'écosystème IT, cloud et IA — La Défense Arena.",
        "source": "Calendrier connu",
    },
    {
        "name": "World AI Cannes Festival 2026",
        "date_start": "2026-02-12", "date_end": "2026-02-13",
        "city": "Cannes", "venue": "Palais des Festivals",
        "organizer": "World AI Cannes", "event_type": "Conférence",
        "link": "https://worldaicannes.com",
        "description": "Festival international de l'IA à Cannes.",
        "source": "Calendrier connu",
    },
    {
        "name": "Adopt AI Summit 2026",
        "date_start": "2026-05-21", "date_end": "",
        "city": "Paris", "venue": "Grand Palais",
        "organizer": "Artefact", "event_type": "Conférence",
        "link": "https://adoptai.artefact.com",
        "description": "Sommet sur l'adoption de l'IA en entreprise — Grand Palais.",
        "source": "Calendrier connu",
    },
    {
        "name": "AI Paris 2026",
        "date_start": "2026-06-09", "date_end": "",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "AI Paris", "event_type": "Conférence",
        "link": "https://aiparis.fr",
        "description": "Conférence IA de référence en France — Palais des Congrès.",
        "source": "Calendrier connu",
    },
    {
        "name": "VivaTech 2026",
        "date_start": "2026-06-17", "date_end": "2026-06-20",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "VivaTech", "event_type": "Salon/Exposition",
        "link": "https://vivatechnology.com",
        "description": "Le plus grand salon européen dédié à l'innovation et aux startups tech/IA.",
        "source": "Calendrier connu",
    },
    {
        "name": "RAISE Summit 2026",
        "date_start": "2026-07-08", "date_end": "2026-07-09",
        "city": "Paris", "venue": "Carrousel du Louvre",
        "organizer": "RAISE", "event_type": "Conférence",
        "link": "https://www.raisesummit.com",
        "description": "Sommet européen sur l'IA responsable et l'investissement tech.",
        "source": "Calendrier connu",
    },
    {
        "name": "Big Data & AI Paris 2026",
        "date_start": "2026-09-15", "date_end": "2026-09-16",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "Corp Agency", "event_type": "Salon/Exposition",
        "link": "https://www.bigdataparis.com",
        "description": "Salon professionnel Big Data, IA et Analytics.",
        "source": "Calendrier connu",
    },
    {
        "name": "dotAI 2026",
        "date_start": "2026-09-17", "date_end": "",
        "city": "Paris", "venue": "Folies Bergère",
        "organizer": "dotConferences", "event_type": "Conférence",
        "link": "https://www.dotai.io",
        "description": "Conférence développeurs sur l'IA appliquée.",
        "source": "Calendrier connu",
    },
    {
        "name": "Big Data & AI World Paris 2026",
        "date_start": "2026-10-18", "date_end": "2026-10-19",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "CloserStill Media", "event_type": "Salon/Exposition",
        "link": "https://www.bigdataworld.com",
        "description": "Salon international Big Data & IA — Porte de Versailles.",
        "source": "Calendrier connu",
    },
    {
        "name": "France is AI 2026",
        "date_start": "2026-10-13", "date_end": "",
        "city": "Paris", "venue": "Station F",
        "organizer": "France is AI", "event_type": "Conférence",
        "link": "https://www.franceisai.com",
        "description": "Écosystème IA français — conférences, networking, démos.",
        "source": "Calendrier connu",
    },
    {
        "name": "AI Pulse 2026",
        "date_start": "2026-10-14", "date_end": "",
        "city": "Paris", "venue": "Station F",
        "organizer": "AI Pulse", "event_type": "Conférence",
        "link": "https://www.ai-pulse.eu",
        "description": "Conférence IA à Station F — startups, recherche, industrie.",
        "source": "Calendrier connu",
    },
    {
        "name": "Paris Cyber Summit 2026",
        "date_start": "2026-10-06", "date_end": "2026-10-07",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "Paris Cyber Summit", "event_type": "Conférence",
        "link": "https://www.paris-cyber-summit.com",
        "description": "Sommet cybersécurité et IA — Palais des Congrès.",
        "source": "Calendrier connu",
    },
    {
        "name": "AIM — AI Marseille 2026",
        "date_start": "2026-11-14", "date_end": "",
        "city": "Marseille", "venue": "Palais du Pharo",
        "organizer": "AIM", "event_type": "Conférence",
        "link": "https://aim-marseille.com",
        "description": "Conférence annuelle IA à Marseille — recherche, industrie, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "Cloud Expo Europe Paris 2026",
        "date_start": "2026-11-17", "date_end": "2026-11-18",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "CloserStill Media", "event_type": "Salon/Exposition",
        "link": "https://www.cloudexpoeurope.fr",
        "description": "Salon Cloud, Cybersécurité et IA — Porte de Versailles.",
        "source": "Calendrier connu",
    },
    {
        "name": "Tech Show Paris 2026",
        "date_start": "2026-11-24", "date_end": "2026-11-25",
        "city": "Paris", "venue": "Paris Expo Porte de Versailles",
        "organizer": "Tech Show", "event_type": "Salon/Exposition",
        "link": "https://www.techshowparis.com",
        "description": "Salon des technologies émergentes — IA, IoT, Cloud.",
        "source": "Calendrier connu",
    },
    # ── Grands salons 2026 (hors Paris) ──────────────────────────────────
    {
        "name": "FIC 2026",
        "date_start": "2026-01-21", "date_end": "2026-01-22",
        "city": "Lille", "venue": "Grand Palais de Lille",
        "organizer": "Ceis / IN-CYBER", "event_type": "Salon/Exposition",
        "link": "https://www.forum-fic.com",
        "description": "Forum International de la Cybersécurité — cybersécurité, IA et souveraineté numérique.",
        "source": "Calendrier connu",
    },
    {
        "name": "SIDO 2026",
        "date_start": "2026-04-01", "date_end": "2026-04-02",
        "city": "Lyon", "venue": "Eurexpo Lyon",
        "organizer": "GL events", "event_type": "Salon/Exposition",
        "link": "https://www.sido-event.com",
        "description": "Le salon de référence IoT, IA et Robotique — convergence des technologies du futur.",
        "source": "Calendrier connu",
    },
    {
        "name": "Bpifrance Inno Génération 2026",
        "date_start": "2026-10-15", "date_end": "2026-10-15",
        "city": "Paris", "venue": "Accor Arena",
        "organizer": "Bpifrance", "event_type": "Salon/Exposition",
        "link": "https://www.bpifrance-innogeneration.fr",
        "description": "Le plus grand rassemblement entrepreneurial français — IA, deeptech, innovation, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "DATA.IA Summit 2026",
        "date_start": "2026-10-08", "date_end": "2026-10-09",
        "city": "Bordeaux", "venue": "Bordeaux",
        "organizer": "DATA.IA", "event_type": "Conférence",
        "link": "https://www.dataiasummit.com",
        "description": "Sommet national Data et IA — écosystème français, startups, grands groupes, recherche.",
        "source": "Calendrier connu",
    },
    {
        "name": "Open Source Experience 2026",
        "date_start": "2026-11-04", "date_end": "2026-11-05",
        "city": "Paris", "venue": "Palais des Congrès",
        "organizer": "Systematic Paris-Region", "event_type": "Salon/Exposition",
        "link": "https://www.opensource-experience.com",
        "description": "Le salon de l'open source, des logiciels libres et de l'IA ouverte.",
        "source": "Calendrier connu",
    },
    {
        "name": "Pollutec 2026",
        "date_start": "2026-11-24", "date_end": "2026-11-27",
        "city": "Lyon", "venue": "Eurexpo Lyon",
        "organizer": "GL events", "event_type": "Salon/Exposition",
        "link": "https://www.pollutec.com",
        "description": "Salon international de l'environnement et des énergies — smart tech, IA et transitions.",
        "source": "Calendrier connu",
    },
    # ── Marseille / Aix-en-Provence / PACA 2026 ──────────────────────────
    {
        "name": "Les Rencontres Économiques d'Aix-en-Provence 2026",
        "date_start": "2026-07-02", "date_end": "2026-07-04",
        "city": "Aix-en-Provence", "venue": "Aix-en-Provence",
        "organizer": "Cercle des Économistes", "event_type": "Conférence",
        "link": "https://www.rencontres-economiques.fr",
        "description": "Grand forum économique et sociétal d'Aix — IA, transitions numériques, débats prospectifs.",
        "source": "Calendrier connu",
    },
    {
        "name": "RivieraDev 2026",
        "date_start": "2026-05-21", "date_end": "2026-05-22",
        "city": "Nice", "venue": "Acropolis Nice",
        "organizer": "RivieraDev", "event_type": "Conférence",
        "link": "https://rivieradev.fr",
        "description": "Conférence tech et IA pour développeurs — Côte d'Azur, sessions en français et anglais.",
        "source": "Calendrier connu",
    },
    {
        "name": "Med'Innovant 2026",
        "date_start": "2026-10-13", "date_end": "2026-10-14",
        "city": "Marseille", "venue": "Palais du Pharo",
        "organizer": "Aix-Marseille-Provence Métropole", "event_type": "Salon/Exposition",
        "link": "https://www.medinnovant.fr",
        "description": "Salon de l'innovation et du numérique de la métropole Aix-Marseille — IA, smart city, startups.",
        "source": "Calendrier connu",
    },
    {
        "name": "Sophia Antipolis AI & Tech Days 2026",
        "date_start": "2026-06-04", "date_end": "2026-06-05",
        "city": "Sophia Antipolis", "venue": "Sophia Antipolis",
        "organizer": "Fondation Sophia Antipolis", "event_type": "Conférence",
        "link": "https://www.sophia-antipolis.fr",
        "description": "Journées tech et IA à Sophia Antipolis — recherche, deeptech, startups méditerranéennes.",
        "source": "Calendrier connu",
    },
]


def fetch_known_events() -> list[dict]:
    """Retourne les événements connus (hardcodés) comme fallback au scraping.

    Ces événements sont des grands salons/conférences dont les sites
    n'exposent pas toujours de JSON-LD exploitable.
    """
    events = []
    for ev in _KNOWN_EVENTS:
        events.append({
            "name": ev["name"],
            "date_start": ev["date_start"],
            "date_end": ev.get("date_end", ""),
            "city": ev.get("city", ""),
            "venue": ev.get("venue", ""),
            "organizer": ev.get("organizer", ""),
            "description": ev.get("description", ""),
            "link": ev.get("link", ""),
            "price": ev.get("price", ""),
            "event_type": ev.get("event_type", ""),
            "source": ev.get("source", "Calendrier connu"),
        })
    print(f"  [SCRAPER] Événements connus: {len(events)} événement(s)")
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
        ("Meetup en ligne (IA/GPU/dev)", lambda: fetch_meetup_online()),
        ("Luma", lambda: fetch_luma()),
        ("Weezevent", lambda: fetch_weezevent()),
        ("HelloAsso", lambda: fetch_helloasso()),
        ("OpenAgenda", lambda: fetch_openagenda()),
        ("Mobilizon", lambda: fetch_mobilizon()),
        ("BilletWeb", lambda: fetch_billetweb()),
        ("Bevy/GDG", lambda: fetch_bevy()),
        ("Conférences", lambda: fetch_conferences()),
        ("Corporate", lambda: fetch_corporate_events()),
        ("Agrégateurs", lambda: fetch_aggregators()),
        ("Événements connus", lambda: fetch_known_events()),
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
