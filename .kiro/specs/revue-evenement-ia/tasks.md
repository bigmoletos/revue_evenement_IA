# Plan d'Implémentation : Revue des Événements IA en France

## Vue d'ensemble

Implémentation du pipeline de veille événementielle IA en France, calqué sur l'architecture de `revue_de_presse_IA`. Le projet est créé dans `revue_evenement_IA/` avec les modules : `config.py`, `scraper.py`, `mailer.py`, `pages_publisher.py`, `notifier.py`, `run_ci.py`, plus le workflow GitHub Actions et les tests.

## Tâches

- [x] 1. Initialiser la structure du projet et la configuration
  - [x] 1.1 Créer la structure de répertoires `revue_evenement_IA/` avec les fichiers de base
  - [x] 1.2 Implémenter `config.py` — chargement configuration
  - [ ]* 1.3 Écrire les tests unitaires pour `config.py`

- [x] 2. Implémenter le modèle de données et les fonctions utilitaires du scraper
  - [x] 2.1 Créer les fonctions de normalisation dans `scraper.py`
  - [ ]* 2.2 Écrire le test property-based pour la normalisation des dates
  - [ ]* 2.3 Écrire le test property-based pour la normalisation des villes
  - [x] 2.4 Implémenter la validation des événements
  - [ ]* 2.5 Écrire le test property-based pour la validation des événements
  - [ ]* 2.6 Écrire le test property-based pour la classification géographique

- [x] 3. Implémenter la classification et la déduplication
  - [x] 3.1 Implémenter `detect_event_type(name, description, source)` dans `scraper.py`
  - [ ]* 3.2 Écrire le test property-based pour la classification par type
  - [x] 3.3 Implémenter `deduplicate(events)` dans `scraper.py`
  - [ ]* 3.4 Écrire le test property-based pour la déduplication
  - [x] 3.5 Implémenter le tri et le filtrage temporel
  - [ ]* 3.6 Écrire les tests property-based pour le tri et le filtrage

- [ ] 4. Checkpoint — Vérifier les fonctions utilitaires

- [x] 5. Implémenter les collecteurs par source
  - [x] 5.1 Implémenter `fetch_eventbrite(query, max_items)` dans `scraper.py`
  - [x] 5.2 Implémenter `fetch_meetup(max_items)` dans `scraper.py`
  - [x] 5.3 Implémenter `fetch_luma(max_items)` dans `scraper.py`
  - [x] 5.4 Implémenter `fetch_conferences()` dans `scraper.py`
  - [x] 5.5 Implémenter `fetch_corporate_events()` dans `scraper.py`
  - [x] 5.6 Implémenter `collect_events()` — orchestrateur principal
  - [ ]* 5.7 Écrire le test property-based pour la résilience aux erreurs
  - [ ]* 5.8 Écrire les tests unitaires pour les collecteurs

- [ ] 6. Checkpoint — Vérifier le scraper complet

- [x] 7. Implémenter la génération HTML et l'envoi email
  - [x] 7.1 Implémenter `build_html(events, pages_url)` dans `mailer.py`
  - [ ]* 7.2 Écrire les tests property-based pour le rendu HTML
  - [x] 7.3 Implémenter `build_email_html(events, pages_url)` dans `mailer.py`
  - [ ]* 7.4 Écrire les tests property-based pour l'email
  - [x] 7.5 Implémenter `send_email(events, pages_url)` dans `mailer.py`
  - [ ]* 7.6 Écrire le test property-based pour le parsing multi-destinataires
  - [ ]* 7.7 Écrire les tests unitaires pour mailer.py

- [x] 8. Implémenter la publication GitHub Pages et les notifications
  - [x] 8.1 Implémenter `pages_publisher.py`
  - [ ]* 8.2 Écrire les tests unitaires pour pages_publisher.py
  - [x] 8.3 Implémenter `notifier.py`

- [x] 9. Implémenter le point d'entrée et le workflow CI/CD
  - [x] 9.1 Implémenter `run_ci.py`
  - [x] 9.2 Créer le workflow GitHub Actions `.github/workflows/revue-evenement-ia.yml`
  - [x] 9.3 Créer le fichier `README.md`

- [x] 10. Créer les fixtures de test et le fichier conftest.py
  - [x] 10.1 Créer `tests/conftest.py` avec les fixtures et générateurs Hypothesis partagés

- [ ] 11. Checkpoint final — Vérifier l'ensemble du projet
