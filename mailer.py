"""
Génération HTML du rapport événements IA + envoi email SMTP.
Fallback silencieux si SMTP indisponible.
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta, timezone

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_TO, EVENT_TYPES, PRIORITY_CITIES

try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    TZ_PARIS = timezone(timedelta(hours=1))


def _today_paris() -> date:
    return datetime.now(TZ_PARIS).date()


# Noms de mois en français
_MOIS_FR = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
    7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
}

# Noms de jours en français
_JOURS_FR = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche",
}


def _build_agenda_html(events: list[dict]) -> str:
    """Construit la vue agenda : événements groupés par mois puis par jour."""
    # Grouper par mois (YYYY-MM) puis par jour (YYYY-MM-DD)
    months: dict[str, dict[str, list[dict]]] = {}
    for ev in events:
        ds = ev.get("date_start", "")
        if not ds or len(ds) < 10:
            continue
        month_key = ds[:7]
        day_key = ds[:10]
        months.setdefault(month_key, {}).setdefault(day_key, []).append(ev)

    html = ""
    for month_key in sorted(months.keys()):
        try:
            y, m = int(month_key[:4]), int(month_key[5:7])
            month_label = f"{_MOIS_FR.get(m, month_key)} {y}"
        except (ValueError, IndexError):
            month_label = month_key

        days_html = ""
        for day_key in sorted(months[month_key].keys()):
            try:
                d = datetime.strptime(day_key, "%Y-%m-%d").date()
                jour = _JOURS_FR.get(d.weekday(), "")
                day_label = f"{jour} {d.day} {_MOIS_FR.get(d.month, '')}"
            except ValueError:
                day_label = day_key

            items_html = ""
            for ev in months[month_key][day_key]:
                name = ev.get("name", "Sans titre")
                link = ev.get("link", "#")
                city = ev.get("city", "")
                etype = ev.get("event_type", "")
                venue = ev.get("venue", "")
                source = ev.get("source", "")
                is_prio = ev.get("is_priority", False)
                prio_icon = '<span class="agenda-prio">⭐</span> ' if is_prio else ""
                date_e = ev.get("date_end", "")
                date_range = day_key[5:]
                if date_e and date_e != day_key:
                    date_range += f" → {date_e[5:]}"
                text_data = f"{name.lower()} {city.lower()} {etype.lower()} {venue.lower()} {source.lower()}"

                items_html += f"""
        <div class="agenda-item" data-city="{city}" data-type="{etype}" data-month="{month_key}" data-text="{text_data}">
          <div class="agenda-time">{date_range}</div>
          <div class="agenda-info">
            <div class="agenda-name">{prio_icon}<a href="{link}" target="_blank" rel="noopener">{name}</a>
              <span class="agenda-type-badge">{etype}</span>
            </div>
            <div class="agenda-meta">📍 {city}{(' · ' + venue) if venue and venue != 'Non précisé' else ''} · {source}</div>
          </div>
        </div>"""

            days_html += f"""
      <div class="agenda-day">
        <div class="agenda-day-label">{day_label}</div>
        {items_html}
      </div>"""

        html += f"""
    <div class="agenda-month">
      <div class="agenda-month-title">{month_label} ({sum(len(v) for v in months[month_key].values())})</div>
      {days_html}
    </div>"""

    return html


def build_html(events: list[dict], pages_url: str = "") -> str:
    """Génère le rapport HTML interactif dark-theme avec filtres."""
    today_label = _today_paris().strftime("%d/%m/%Y")

    # Regrouper par type
    grouped: dict[str, list[dict]] = {t: [] for t in EVENT_TYPES}
    for ev in events:
        t = ev.get("event_type", "Autre")
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(ev)

    # Options villes pour le filtre
    cities = sorted({ev.get("city", "") for ev in events if ev.get("city")})
    city_options = "\n".join(f'<option value="{c}">{c}</option>' for c in cities)

    # Options mois (avec labels français)
    months = sorted({ev.get("date_start", "")[:7] for ev in events if ev.get("date_start")})
    month_options = ""
    for m in months:
        try:
            y, mo = int(m[:4]), int(m[5:7])
            label = f"{_MOIS_FR.get(mo, m)} {y}"
        except (ValueError, IndexError):
            label = m
        month_options += f'<option value="{m}">{label}</option>\n'

    # Options types
    type_options = "\n".join(
        f'<option value="{t}">{t}</option>' for t in EVENT_TYPES if grouped.get(t)
    )

    # Quick-filter buttons — types les plus utiles
    quick_filters = [
        ("Salon/Exposition", "🏛️ Salons"),
        ("Conférence", "🎤 Conférences"),
        ("Meetup", "🤝 Meetups"),
        ("Atelier/Workshop", "🔧 Ateliers"),
        ("Webinaire", "💻 En ligne"),
        ("Événement Corporate", "🏢 Corporate"),
    ]
    quick_btns_html = '<button class="quick-btn" onclick="quickFilter(\'\')" data-type="">Tous</button>\n'
    for qtype, qlabel in quick_filters:
        if grouped.get(qtype):
            quick_btns_html += f'<button class="quick-btn" onclick="quickFilter(\'{qtype}\')" data-type="{qtype}">{qlabel} ({len(grouped[qtype])})</button>\n'

    # Nav thèmes
    nav_links = "\n".join(
        f'<a href="#{t.replace(" ", "-").replace("/", "-")}" class="nav-link">'
        f'{t} <span class="badge">{len(grouped[t])}</span></a>'
        for t in EVENT_TYPES if grouped.get(t)
    )

    pages_link = (
        f'<a href="{pages_url}" target="_blank" class="pages-link">📄 GitHub Pages</a>'
        if pages_url else ""
    )

    # Sections par type
    sections_html = ""
    for etype in EVENT_TYPES:
        evts = grouped.get(etype, [])
        if not evts:
            continue
        anchor = etype.replace(" ", "-").replace("/", "-")
        cards = ""
        for ev in evts:
            name = ev.get("name", "Sans titre")
            link = ev.get("link", "#")
            city = ev.get("city", "")
            date_s = ev.get("date_start", "")
            date_e = ev.get("date_end", "")
            venue = ev.get("venue", "")
            organizer = ev.get("organizer", "")
            price = ev.get("price", "")
            desc = ev.get("description", "")
            source = ev.get("source", "")
            is_prio = ev.get("is_priority", False)
            prio_badge = '<span class="prio-badge">⭐</span>' if is_prio else ""
            date_display = date_s
            if date_e and date_e != date_s:
                date_display = f"{date_s} → {date_e}"

            cards += f"""
        <details class="card" data-city="{city}" data-type="{etype}" data-month="{date_s[:7]}"
                 data-text="{name.lower()} {desc.lower()} {city.lower()} {organizer.lower()}">
          <summary class="card-toggle">
            <span class="card-slug">{prio_badge}{name}</span>
            <span class="card-meta-inline">
              <span class="city-tag">{city}</span>
              <span class="date-tag">{date_display}</span>
            </span>
          </summary>
          <div class="card-body">
            <a href="{link}" target="_blank" rel="noopener" class="card-title">{name}</a>
            <div class="card-details">
              <span>📍 {venue}</span> · <span>🏢 {organizer}</span> · <span>💰 {price}</span>
              · <span class="source">{source}</span>
            </div>
            {"<p class='card-desc'>" + desc[:400] + "</p>" if desc else ""}
            <a href="{link}" target="_blank" rel="noopener" class="read-link">→ S'inscrire / Détails</a>
          </div>
        </details>"""

        sections_html += f"""
      <section id="{anchor}" class="type-section">
        <h2 class="type-title">{etype} <span class="type-count">{len(evts)}</span></h2>
        {cards}
      </section>"""

    import json as _json
    months_js = _json.dumps(months)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Événements IA France - {today_label}</title>
<style>
:root{{--bg:#0f1117;--surface:#1a1d27;--border:#2a2d3a;--accent:#7c6af7;--text:#e2e8f0;--muted:#8892a4;--green:#4ade80;--card-bg:#1e2130;--prio:#f59e0b}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif}}
header{{position:sticky;top:0;z-index:100;background:var(--surface);border-bottom:1px solid var(--border);padding:10px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
header h1{{font-size:1.05rem;color:var(--accent);white-space:nowrap}}
#count{{font-size:.82rem;color:var(--muted)}}
#search{{flex:1;min-width:160px;padding:5px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.88rem}}
select{{padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.88rem}}
.pages-link{{font-size:.82rem;color:var(--accent);text-decoration:none;white-space:nowrap}}
nav{{background:var(--surface);border-bottom:1px solid var(--border);padding:7px 24px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.nav-link{{color:var(--muted);text-decoration:none;font-size:.8rem;padding:3px 8px;border-radius:4px;border:1px solid var(--border)}}
.nav-link:hover{{color:var(--accent);border-color:var(--accent)}}
.badge{{background:var(--border);border-radius:10px;padding:1px 6px;font-size:.75rem}}
.view-toggle{{margin-left:auto;display:flex;gap:4px}}
.view-btn{{background:var(--bg);border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.8rem}}
.view-btn.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
main{{max-width:960px;margin:0 auto;padding:20px 16px}}
.type-section{{margin-bottom:36px}}
.type-title{{font-size:.95rem;font-weight:600;color:var(--accent);border-left:3px solid var(--accent);padding-left:10px;margin-bottom:12px;display:flex;align-items:center;gap:8px}}
.type-count{{background:var(--border);border-radius:10px;padding:1px 7px;font-size:.75rem;color:var(--muted)}}
details.card{{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden}}
details.card:hover{{border-color:var(--accent)}}
summary.card-toggle{{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;cursor:pointer;list-style:none;gap:12px}}
summary.card-toggle::-webkit-details-marker{{display:none}}
summary.card-toggle::before{{content:'▶';font-size:.65rem;color:var(--muted);flex-shrink:0;transition:transform .2s}}
details[open] summary.card-toggle::before{{transform:rotate(90deg)}}
.card-slug{{font-size:.9rem;font-weight:500;flex:1}}
.prio-badge{{color:var(--prio);margin-right:6px}}
.card-meta-inline{{display:flex;gap:10px;font-size:.75rem;flex-shrink:0}}
.city-tag{{color:var(--green)}}.date-tag{{color:var(--muted)}}
.card-body{{padding:0 14px 12px;border-top:1px solid var(--border)}}
.card-title{{display:block;color:var(--accent);text-decoration:none;font-size:.88rem;margin-top:10px}}
.card-details{{color:var(--muted);font-size:.78rem;margin-top:6px}}
.card-desc{{color:var(--muted);font-size:.83rem;margin-top:7px;line-height:1.5}}
.source{{color:var(--green)}}
.read-link{{color:var(--accent);text-decoration:none;font-size:.8rem;display:inline-block;margin-top:8px}}
.hidden{{display:none!important}}
.no-results{{color:var(--muted);text-align:center;padding:40px;font-size:.9rem}}
/* Agenda view */
#agendaView{{display:none}}
#agendaView.active{{display:block}}
#listView.active{{display:block}}
#listView{{display:block}}
.agenda-month{{margin-bottom:32px}}
.agenda-month-title{{font-size:1rem;font-weight:700;color:var(--accent);margin-bottom:12px;padding:8px 12px;background:var(--surface);border-radius:6px;border-left:3px solid var(--accent)}}
.agenda-day{{margin-bottom:16px;padding-left:12px}}
.agenda-day-label{{font-size:.85rem;font-weight:600;color:var(--green);margin-bottom:6px}}
.agenda-item{{display:flex;align-items:flex-start;gap:10px;padding:8px 12px;background:var(--card-bg);border:1px solid var(--border);border-radius:6px;margin-bottom:4px}}
.agenda-item:hover{{border-color:var(--accent)}}
.agenda-time{{font-size:.78rem;color:var(--muted);min-width:70px;flex-shrink:0}}
.agenda-info{{flex:1}}
.agenda-name{{font-size:.88rem;font-weight:500}}
.agenda-name a{{color:var(--text);text-decoration:none}}
.agenda-name a:hover{{color:var(--accent)}}
.agenda-meta{{font-size:.75rem;color:var(--muted);margin-top:2px}}
.agenda-type-badge{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.7rem;background:var(--border);color:var(--muted);margin-left:6px}}
.agenda-prio{{color:var(--prio)}}
/* Quick filter buttons */
.quick-filters{{display:flex;gap:6px;flex-wrap:wrap;padding:8px 24px;background:var(--surface);border-bottom:1px solid var(--border)}}
.quick-btn{{background:var(--bg);border:1px solid var(--border);color:var(--muted);padding:5px 14px;border-radius:20px;cursor:pointer;font-size:.8rem;transition:all .2s}}
.quick-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.quick-btn.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
/* Month navigation */
.month-nav{{display:flex;align-items:center;gap:10px;padding:10px 24px;background:var(--surface);border-bottom:1px solid var(--border)}}
.month-nav-btn{{background:var(--bg);border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.85rem}}
.month-nav-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.month-nav-label{{font-size:.9rem;font-weight:600;color:var(--text);min-width:140px;text-align:center}}
.month-nav-select{{padding:4px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:.85rem}}
</style>
</head>
<body>
<header>
  <h1>📅 Événements IA France — {today_label}</h1>
  <span id="count">{len(events)} événements</span>
  <input id="search" type="search" placeholder="Rechercher..." oninput="applyFilters()"/>
  <select id="cityFilter" onchange="applyFilters()">
    <option value="">Toutes les villes</option>
    {city_options}
  </select>
  <select id="typeFilter" onchange="applyFilters()">
    <option value="">Tous les types</option>
    {type_options}
  </select>
  <select id="monthFilter" onchange="applyFilters()">
    <option value="">Tous les mois</option>
    {month_options}
  </select>
  {pages_link}
</header>
<nav>
  {nav_links}
  <div class="view-toggle">
    <button class="view-btn active" onclick="switchView('list')" id="btnList">📋 Liste</button>
    <button class="view-btn" onclick="switchView('agenda')" id="btnAgenda">📅 Agenda</button>
  </div>
</nav>
<div class="quick-filters">
  {quick_btns_html}
</div>
<div class="month-nav" id="monthNav" style="display:none">
  <button class="month-nav-btn" onclick="navMonth(-1)">◀ Précédent</button>
  <span class="month-nav-label" id="monthNavLabel">—</span>
  <button class="month-nav-btn" onclick="navMonth(1)">Suivant ▶</button>
  <select class="month-nav-select" id="monthNavSelect" onchange="jumpMonth(this.value)">
    <option value="">Aller au mois…</option>
    {month_options}
  </select>
  <button class="month-nav-btn" onclick="navMonth(0)">✕ Tous</button>
</div>
<main id="main">
  <div id="listView" class="active">
    {sections_html}
  </div>
  <div id="agendaView">
    {_build_agenda_html(events)}
  </div>
  <p id="noResults" class="no-results hidden">Aucun événement ne correspond.</p>
</main>
<script>
var agendaMonths={months_js};
var currentMonthIdx=-1;
function switchView(v){{
  document.getElementById('listView').style.display=v==='list'?'block':'none';
  document.getElementById('agendaView').style.display=v==='agenda'?'block':'none';
  document.getElementById('btnList').classList.toggle('active',v==='list');
  document.getElementById('btnAgenda').classList.toggle('active',v==='agenda');
  document.getElementById('monthNav').style.display=v==='agenda'?'flex':'none';
  if(v==='agenda'){{currentMonthIdx=-1;updateMonthLabel();}}
  applyFilters();
}}
function quickFilter(t){{
  document.getElementById('typeFilter').value=t;
  document.querySelectorAll('.quick-btn').forEach(function(b){{
    b.classList.toggle('active',b.dataset.type===t);
  }});
  applyFilters();
}}
function navMonth(dir){{
  if(dir===0){{currentMonthIdx=-1;}}
  else if(currentMonthIdx<0){{currentMonthIdx=dir>0?0:agendaMonths.length-1;}}
  else{{currentMonthIdx+=dir;if(currentMonthIdx<0)currentMonthIdx=agendaMonths.length-1;if(currentMonthIdx>=agendaMonths.length)currentMonthIdx=0;}}
  updateMonthLabel();
  if(currentMonthIdx>=0){{document.getElementById('monthFilter').value=agendaMonths[currentMonthIdx];}}
  else{{document.getElementById('monthFilter').value='';}}
  applyFilters();
}}
function jumpMonth(v){{
  if(!v){{currentMonthIdx=-1;}}
  else{{currentMonthIdx=agendaMonths.indexOf(v);if(currentMonthIdx<0)currentMonthIdx=-1;}}
  updateMonthLabel();
  document.getElementById('monthFilter').value=v;
  applyFilters();
}}
function updateMonthLabel(){{
  var lbl=document.getElementById('monthNavLabel');
  var sel=document.getElementById('monthNavSelect');
  if(currentMonthIdx<0||currentMonthIdx>=agendaMonths.length){{lbl.textContent='Tous les mois';sel.value='';}}
  else{{var m=agendaMonths[currentMonthIdx];var opt=sel.querySelector('option[value="'+m+'"]');lbl.textContent=opt?opt.textContent:m;sel.value=m;}}
}}
function applyFilters(){{
  var q=document.getElementById('search').value.toLowerCase().trim();
  var city=document.getElementById('cityFilter').value;
  var type=document.getElementById('typeFilter').value;
  var month=document.getElementById('monthFilter').value;
  var cards=document.querySelectorAll('details.card');
  var visible=0;
  cards.forEach(function(c){{
    var ok=(!q||(c.dataset.text||'').includes(q))
      &&(!city||c.dataset.city===city)
      &&(!type||c.dataset.type===type)
      &&(!month||c.dataset.month===month);
    c.classList.toggle('hidden',!ok);
    if(ok)visible++;
  }});
  document.querySelectorAll('.type-section').forEach(function(s){{
    s.classList.toggle('hidden',s.querySelectorAll('details.card:not(.hidden)').length===0);
  }});
  var items=document.querySelectorAll('.agenda-item');
  var agendaVisible=0;
  items.forEach(function(it){{
    var ok=(!q||(it.dataset.text||'').includes(q))
      &&(!city||it.dataset.city===city)
      &&(!type||it.dataset.type===type)
      &&(!month||it.dataset.month===month);
    it.classList.toggle('hidden',!ok);
    if(ok)agendaVisible++;
  }});
  document.querySelectorAll('.agenda-day').forEach(function(d){{
    d.classList.toggle('hidden',d.querySelectorAll('.agenda-item:not(.hidden)').length===0);
  }});
  document.querySelectorAll('.agenda-month').forEach(function(m){{
    m.classList.toggle('hidden',m.querySelectorAll('.agenda-item:not(.hidden)').length===0);
  }});
  var isList=document.getElementById('listView').style.display!=='none';
  var total=isList?visible:agendaVisible;
  document.getElementById('count').textContent=total+' événement'+(total>1?'s':'');
  document.getElementById('noResults').classList.toggle('hidden',total>0);
}}
document.querySelectorAll('.quick-btn').forEach(function(b){{if(b.dataset.type==='')b.classList.add('active');}});
</script>
</body>
</html>"""


def build_email_html(events: list[dict], pages_url: str = "") -> tuple[str, int]:
    """Génère un HTML table-based compatible email. Événements des 30 prochains jours groupés par semaine."""
    today = _today_paris()
    cutoff = today + timedelta(days=30)
    today_str = today.strftime("%Y-%m-%d")
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    upcoming = [e for e in events if today_str <= e.get("date_start", "") <= cutoff_str]
    if not upcoming:
        upcoming = events[:20]

    # Grouper par semaine
    weeks: dict[str, list[dict]] = {}
    for ev in upcoming:
        ds = ev.get("date_start", "")
        try:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            delta = (d - today).days
            if delta < 0:
                label = "Cette semaine"
            elif delta < 7:
                label = "Cette semaine"
            elif delta < 14:
                label = "Semaine prochaine"
            elif delta < 21:
                label = "Dans 2 semaines"
            else:
                label = "Plus tard"
        except ValueError:
            label = "Plus tard"
        weeks.setdefault(label, []).append(ev)

    today_label = today.strftime("%d/%m/%Y")
    pages_btn = (
        f'<tr><td align="center" style="padding:16px 0 8px;">'
        f'<a href="{pages_url}" style="background:#7c6af7;color:#fff;padding:10px 24px;'
        f'border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;">'
        f'📅 Voir tous les événements</a></td></tr>'
    ) if pages_url else ""

    sections = ""
    for week_label in ["Cette semaine", "Semaine prochaine", "Dans 2 semaines", "Plus tard"]:
        evts = weeks.get(week_label, [])
        if not evts:
            continue
        rows = ""
        for ev in evts:
            name = ev.get("name", "Sans titre")
            link = ev.get("link", "#")
            city = ev.get("city", "")
            ds = ev.get("date_start", "")
            etype = ev.get("event_type", "")
            price = ev.get("price", "")
            prio = "⭐ " if ev.get("is_priority") else ""
            rows += f"""
        <tr><td style="padding:10px 16px 0;">
          <a href="{link}" style="color:#7c6af7;font-size:15px;font-weight:600;text-decoration:none;">{prio}{name}</a>
          <span style="color:#8892a4;font-size:12px;margin-left:8px;">{city} · {ds} · {etype} · {price}</span>
        </td></tr>
        <tr><td style="padding:2px 16px 8px;">
          <a href="{link}" style="color:#4ade80;font-size:12px;text-decoration:none;">→ Détails / Inscription</a>
        </td></tr>
        <tr><td style="border-bottom:1px solid #2a2d3a;"></td></tr>"""

        sections += f"""
      <tr><td style="padding:20px 16px 6px;">
        <span style="color:#7c6af7;font-size:13px;font-weight:700;text-transform:uppercase;
          letter-spacing:.05em;border-left:3px solid #7c6af7;padding-left:8px;">
          {week_label} ({len(evts)})
        </span>
      </td></tr>{rows}"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f1117;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;">
  <tr><td align="center" style="padding:20px 10px;">
    <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;
      background:#1a1d27;border-radius:10px;border:1px solid #2a2d3a;">
      <tr><td style="padding:24px 24px 16px;border-bottom:1px solid #2a2d3a;">
        <span style="font-size:22px;font-weight:700;color:#e2e8f0;">📅 Événements IA France</span>
        <span style="font-size:14px;color:#8892a4;margin-left:12px;">{today_label}</span>
        <br><span style="font-size:13px;color:#8892a4;">{len(upcoming)} événements dans les 30 prochains jours</span>
      </td></tr>
      {pages_btn}
      {sections}
      <tr><td style="padding:20px 24px;border-top:1px solid #2a2d3a;text-align:center;">
        <span style="color:#8892a4;font-size:12px;">
          Revue Événements IA · Généré le {today_label}
          {f' · <a href="{pages_url}" style="color:#7c6af7;">Archive</a>' if pages_url else ''}
        </span>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""
    return html, len(upcoming)


def send_email(events: list[dict], pages_url: str = "") -> bool:
    """Envoie l'email SMTP. Retourne False si config incomplète."""
    if not all([SMTP_USER, SMTP_PASSWORD, MAIL_TO]):
        print("[MAILER] Config SMTP incomplète — skip email")
        return False

    recipients = [r.strip() for r in MAIL_TO.replace(";", ",").split(",") if r.strip()]
    if not recipients:
        print("[MAILER] Aucun destinataire valide — skip email")
        return False

    try:
        html, nb = build_email_html(events, pages_url=pages_url)
        today_label = _today_paris().strftime("%d/%m/%Y")
        subject = f"Événements IA France — {today_label} ({nb} événements)"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html", "utf-8"))
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"[MAILER] Email envoyé à {', '.join(recipients)} ({nb} événements)")
        return True
    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        print(f"[MAILER] SMTP indisponible ({e}) — fallback rapport HTML")
        return False
    except Exception as e:
        print(f"[MAILER] Erreur inattendue: {e}")
        return False
