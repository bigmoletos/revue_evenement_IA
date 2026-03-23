"""
Publication sur GitHub Pages via la branche gh-pages.
Pousse le rapport HTML + met à jour index.html.
"""
import os
import subprocess
import tempfile
import shutil
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    TZ_PARIS = timezone(timedelta(hours=1))


def _today_paris() -> date:
    return datetime.now(TZ_PARIS).date()


def publish_to_pages(html_content: str, event_count: int) -> str | None:
    """Clone gh-pages, ajoute le rapport, met à jour index.html, pousse.
    Retourne l'URL publique ou None si échec."""
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "bigmoletos/revue_evenement_IA")

    if not token:
        print("[PAGES] GITHUB_TOKEN manquant — skip")
        return None

    today = _today_paris().strftime("%Y-%m-%d")
    filename = f"revue_evenements_ia_{today}.html"
    owner = repo.split("/")[0]
    repo_name = repo.split("/")[1]
    pages_url = f"https://{owner}.github.io/{repo_name}/{filename}"
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    tmpdir = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "config", "--global", "user.email", "github-actions@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "GitHub Actions"], check=True)

        clone_dir = os.path.join(tmpdir, "repo")
        result = subprocess.run(
            ["git", "clone", "--branch", "gh-pages", "--single-branch", "--depth=1", remote_url, clone_dir],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            os.makedirs(clone_dir, exist_ok=True)
            subprocess.run(["git", "init", clone_dir], check=True)
            subprocess.run(["git", "-C", clone_dir, "remote", "add", "origin", remote_url], check=True)
            subprocess.run(["git", "-C", clone_dir, "checkout", "--orphan", "gh-pages"], check=True)
        tmpdir = clone_dir

        (Path(tmpdir) / filename).write_text(html_content, encoding="utf-8")

        reports = sorted(
            [f.name for f in Path(tmpdir).glob("revue_evenements_ia_*.html")],
            reverse=True,
        )
        _write_index(tmpdir, reports)

        subprocess.run(["git", "-C", tmpdir, "add", "."], check=True)
        subprocess.run(
            ["git", "-C", tmpdir, "commit", "-m", f"revue événements IA {today} ({event_count} événements)"],
            check=True,
        )
        subprocess.run(["git", "-C", tmpdir, "push", "origin", "gh-pages", "--force"], check=True)

        print(f"[PAGES] Publié: {pages_url}")
        return pages_url
    except Exception as e:
        print(f"[PAGES] Erreur: {e}")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_index(tmpdir: str, reports: list[str]):
    """Génère index.html listant tous les rapports archivés."""
    items = ""
    for r in reports:
        d = r.replace("revue_evenements_ia_", "").replace(".html", "")
        items += f'<li><a href="{r}">{d}</a></li>\n'

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Événements IA France — Archives</title>
<style>
  body{{background:#0f1117;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;max-width:600px;margin:60px auto;padding:0 16px}}
  h1{{color:#7c6af7;font-size:1.4rem;margin-bottom:8px}}
  p{{color:#8892a4;font-size:.9rem;margin-bottom:32px}}
  ul{{list-style:none;padding:0}}
  li{{margin-bottom:12px}}
  a{{color:#7c6af7;text-decoration:none;font-size:1rem}}
  a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h1>📅 Événements IA France</h1>
<p>Mise à jour quotidienne — lundi au vendredi à 8h30</p>
<ul>
{items}
</ul>
</body>
</html>"""
    (Path(tmpdir) / "index.html").write_text(html, encoding="utf-8")
