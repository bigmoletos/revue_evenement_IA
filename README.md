# 📅 Revue des Événements IA en France

Pipeline automatisé de veille événementielle IA en France. Collecte quotidienne des salons, meetups, conférences, ateliers et événements corporate liés à l'intelligence artificielle.

## Sources

- **Eventbrite** — Événements IA en France
- **Meetup** — Groupes et meetups tech/IA
- **Luma** — Événements communautaires IA
- **Conférences** — AI Paris, VivaTech, Big Data & AI Paris, France is AI, World AI Cannes
- **Corporate** — Google Cloud, Microsoft, AWS, OVHcloud, Dataiku

## Villes prioritaires

Paris · Marseille · Aix-en-Provence · Cannes · Toulon

## Fonctionnalités

- Collecte parallèle multi-sources (ThreadPoolExecutor)
- Déduplication en 2 passes (URL + nom/date/ville)
- Classification automatique par type (Salon, Conférence, Meetup, Atelier, Corporate, Webinaire)
- Rapport HTML interactif dark-theme avec 4 filtres (recherche, ville, type, mois)
- Publication GitHub Pages avec archives
- Email SMTP avec événements des 30 prochains jours groupés par semaine
- Notification Windows locale (toast + navigateur)
- CI/CD GitHub Actions (lun-ven 06h30 UTC)

## Installation locale

```bash
pip install -r requirements.txt
cp .env.example .env
# Éditer .env avec vos identifiants
python run_ci.py
```

## Configuration

Copier `.env.example` en `.env` et renseigner :

| Variable | Description |
|----------|-------------|
| `SMTP_HOST` | Serveur SMTP (défaut: smtp.gmail.com) |
| `SMTP_PORT` | Port SMTP (défaut: 587) |
| `SMTP_USER` | Adresse email expéditrice |
| `SMTP_PASSWORD` | Mot de passe d'application |
| `MAIL_TO` | Destinataire(s), séparés par virgule |
| `GITHUB_TOKEN` | Token GitHub pour push gh-pages |
| `GITHUB_REPOSITORY` | Format owner/repo |

## GitHub Actions

### Secrets requis

- `REVUE_GITHUB_TOKEN` — Token avec permissions `contents:write`
- `SMTP_USER` — Adresse email
- `SMTP_PASSWORD` — Mot de passe d'application
- `MAIL_TO` — Destinataire(s)

### Activer GitHub Pages

1. Settings → Pages → Source: "Deploy from a branch"
2. Branch: `gh-pages` / `/ (root)`

## Structure

```
├── config.py             # Configuration (.env / variables d'environnement)
├── scraper.py            # Collecte multi-sources + déduplication + classification
├── mailer.py             # Génération HTML rapport + email + envoi SMTP
├── pages_publisher.py    # Publication GitHub Pages
├── notifier.py           # Notifications Windows (toast)
├── run_ci.py             # Point d'entrée CI/CD et local
├── requirements.txt      # Dépendances Python
├── .env.example          # Template configuration
└── .github/workflows/    # GitHub Actions
```

## Dépendances

- `requests` ≥ 2.32
- `python-dotenv` ≥ 1.0
- Python 3.11+
