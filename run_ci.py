"""
Point d'entrée CI/CD — GitHub Actions + exécution locale.
Collecte → HTML → GitHub Pages → Email → Notification locale.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, date, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    TZ_PARIS = timezone(timedelta(hours=1))


def _today_paris() -> date:
    return datetime.now(TZ_PARIS).date()


# Charger .env local si présent
_env = Path(__file__).parent / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env, override=True)
    except ImportError:
        pass

from scraper import collect_events
from mailer import build_html, send_email
from pages_publisher import publish_to_pages


def main():
    print("=== Revue des Événements IA en France ===")

    # 1. Collecte
    events = collect_events()
    print(f"Événements collectés: {len(events)}")
    if not events:
        print("Aucun événement — arrêt.")
        sys.exit(1)

    # 2. Génération HTML
    html = build_html(events)
    today = _today_paris().strftime("%Y-%m-%d")

    # 3. Sauvegarde locale
    out_dir = Path(__file__).parent / "rapports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"revue_evenements_ia_{today}.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"Rapport local: {out_file}")

    # 4. Publication GitHub Pages
    pages_url = publish_to_pages(html, len(events))
    if pages_url:
        print(f"Pages: {pages_url}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"## Événements IA France — {today}\n\n")
                f.write(f"- **{len(events)} événements** collectés\n")
                f.write(f"- **Rapport**: [{pages_url}]({pages_url})\n")
    else:
        print("[WARN] GitHub Pages non publié — GITHUB_TOKEN manquant ou erreur")

    # 5. Envoi email
    email_ok = send_email(events, pages_url=pages_url or "")
    if email_ok:
        print("Email envoyé")
    else:
        print("[WARN] Email non envoyé (SMTP indisponible ou config incomplète)")

    # 6. Notification locale (Windows uniquement)
    if os.name == "nt":
        try:
            from notifier import deliver
            deliver(events)
        except Exception as e:
            print(f"[WARN] Notification locale: {e}")


if __name__ == "__main__":
    main()
