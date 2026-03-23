# Document d'Exigences — Revue des Événements IA en France

## Introduction

Outil automatisé de veille événementielle IA en France. Le système collecte, classe et publie quotidiennement les événements liés à l'intelligence artificielle (salons, meetups, conférences, ateliers, événements d'entreprise) avec un focus sur Paris, Marseille, Aix-en-Provence, Cannes et Toulon. L'architecture suit le modèle du projet existant `revue_de_presse_IA` (Python, scraping, rapport HTML, email, GitHub Pages, GitHub Actions CI/CD).

## Glossaire

- **Collecteur** : Module Python responsable du scraping des sources d'événements (Eventbrite, Meetup, Luma, sites de conférences IA, etc.)
- **Événement** : Objet de données contenant : nom, date(s), ville, lieu, organisateur, description, lien d'inscription, prix (gratuit/payant), type
- **Classificateur** : Module qui catégorise les événements par type (salon, meetup, conférence, atelier, événement corporate)
- **Générateur_HTML** : Module qui produit le rapport HTML interactif dark-theme avec cartes d'événements
- **Expéditeur_Email** : Module SMTP qui envoie les événements à venir par email
- **Publicateur_Pages** : Module qui publie le rapport sur GitHub Pages (branche gh-pages)
- **Pipeline_CI** : Workflow GitHub Actions exécuté automatiquement par cron
- **Villes_Prioritaires** : Paris, Marseille, Aix-en-Provence, Cannes, Toulon
- **Villes_Secondaires** : Toutes les autres villes de France métropolitaine

## Exigences

### Exigence 1 : Collecte d'événements multi-sources

**User Story :** En tant qu'utilisateur, je veux que le système collecte automatiquement les événements IA depuis plusieurs sources web, afin d'avoir une vue complète de l'écosystème événementiel IA en France.

#### Critères d'acceptation

1. WHEN le Collecteur est déclenché, THE Collecteur SHALL scraper les événements depuis Eventbrite (recherche "intelligence artificielle" + "IA" + "AI" en France)
2. WHEN le Collecteur est déclenché, THE Collecteur SHALL scraper les événements depuis Meetup (groupes et événements IA en France)
3. WHEN le Collecteur est déclenché, THE Collecteur SHALL scraper les événements depuis Luma (événements IA en France)
4. WHEN le Collecteur est déclenché, THE Collecteur SHALL scraper les sites de conférences et salons IA connus (AI Paris, VivaTech, Big Data & AI Paris, etc.)
5. WHEN le Collecteur est déclenché, THE Collecteur SHALL rechercher les événements corporate IA organisés par des entreprises pour leurs clients
6. THE Collecteur SHALL exécuter les requêtes de scraping en parallèle via ThreadPoolExecutor avec un maximum de 10 workers
7. WHEN une source est indisponible ou retourne une erreur, THE Collecteur SHALL journaliser l'erreur et continuer la collecte depuis les autres sources
8. THE Collecteur SHALL respecter un timeout de 10 secondes par requête HTTP

### Exigence 2 : Extraction des données d'événements

**User Story :** En tant qu'utilisateur, je veux que chaque événement contienne toutes les informations utiles, afin de pouvoir décider rapidement si un événement m'intéresse.

#### Critères d'acceptation

1. THE Collecteur SHALL extraire pour chaque événement : le nom, la ou les dates, la ville, le lieu précis, l'organisateur, une description, le lien d'inscription et le prix (gratuit ou payant avec montant)
2. WHEN un champ obligatoire (nom ou date) est absent, THE Collecteur SHALL exclure l'événement de la collecte
3. WHEN un champ optionnel (lieu précis, prix, organisateur) est absent, THE Collecteur SHALL conserver l'événement avec la valeur "Non précisé" pour le champ manquant
4. THE Collecteur SHALL normaliser les dates au format ISO 8601 (YYYY-MM-DD)
5. THE Collecteur SHALL normaliser les noms de villes en majuscules avec accents (PARIS, MARSEILLE, AIX-EN-PROVENCE, CANNES, TOULON)

### Exigence 3 : Filtrage géographique par villes

**User Story :** En tant qu'utilisateur, je veux que les événements soient filtrés par ville avec une priorité sur mes villes d'intérêt, afin de voir en premier les événements proches de moi.

#### Critères d'acceptation

1. THE Collecteur SHALL filtrer les événements pour ne conserver que ceux situés en France métropolitaine
2. THE Collecteur SHALL marquer les événements des Villes_Prioritaires (Paris, Marseille, Aix-en-Provence, Cannes, Toulon) avec un indicateur de priorité
3. THE Collecteur SHALL accepter les événements en ligne (webinaires, événements virtuels) et les marquer avec la ville "EN LIGNE"
4. WHEN un événement est situé dans une Ville_Prioritaire, THE Générateur_HTML SHALL afficher un badge visuel distinctif sur la carte de l'événement

### Exigence 4 : Déduplication des événements

**User Story :** En tant qu'utilisateur, je veux que les événements en double soient éliminés, afin de ne pas voir le même événement plusieurs fois.

#### Critères d'acceptation

1. THE Collecteur SHALL dédupliquer les événements par URL d'inscription identique
2. THE Collecteur SHALL dédupliquer les événements par combinaison nom normalisé + date + ville identiques
3. WHEN deux événements sont détectés comme doublons, THE Collecteur SHALL conserver celui avec le plus d'informations renseignées

### Exigence 5 : Classification par type d'événement

**User Story :** En tant qu'utilisateur, je veux que les événements soient classés par type, afin de trouver rapidement le format qui m'intéresse.

#### Critères d'acceptation

1. THE Classificateur SHALL catégoriser chaque événement dans exactement un type parmi : Salon/Exposition, Conférence, Meetup, Atelier/Workshop, Événement Corporate, Webinaire, Autre
2. THE Classificateur SHALL détecter le type par analyse de mots-clés dans le nom, la description et les métadonnées de la source
3. WHEN le type ne peut pas être déterminé, THE Classificateur SHALL attribuer le type "Autre"

### Exigence 6 : Tri chronologique

**User Story :** En tant qu'utilisateur, je veux que les événements soient triés par date, afin de voir en premier les événements les plus proches dans le temps.

#### Critères d'acceptation

1. THE Collecteur SHALL trier les événements par date croissante (événements les plus proches en premier)
2. THE Collecteur SHALL exclure les événements dont la date est passée de plus de 1 jour
3. WHEN deux événements ont la même date, THE Collecteur SHALL trier par ville prioritaire en premier, puis par ordre alphabétique de nom

### Exigence 7 : Génération du rapport HTML interactif

**User Story :** En tant qu'utilisateur, je veux un rapport HTML dark-theme interactif avec des cartes d'événements, afin de consulter facilement les événements depuis un navigateur.

#### Critères d'acceptation

1. THE Générateur_HTML SHALL produire un fichier HTML autonome (CSS inline, JavaScript inline) avec un thème sombre
2. THE Générateur_HTML SHALL afficher chaque événement sous forme de carte contenant : nom, date(s), ville, lieu, organisateur, type (badge coloré), prix, lien d'inscription
3. THE Générateur_HTML SHALL regrouper les événements par type avec un compteur par section
4. THE Générateur_HTML SHALL inclure un champ de recherche textuelle filtrant les cartes en temps réel
5. THE Générateur_HTML SHALL inclure un filtre par ville (dropdown avec les Villes_Prioritaires + "Toutes les villes")
6. THE Générateur_HTML SHALL inclure un filtre par type d'événement
7. THE Générateur_HTML SHALL inclure un filtre par mois
8. THE Générateur_HTML SHALL afficher le nombre total d'événements visibles après filtrage
9. THE Générateur_HTML SHALL utiliser des cartes collapsibles (balise details/summary) avec le nom et la ville comme label visible

### Exigence 8 : Publication GitHub Pages

**User Story :** En tant qu'utilisateur, je veux que le rapport soit publié automatiquement sur GitHub Pages, afin d'y accéder depuis n'importe quel appareil.

#### Critères d'acceptation

1. WHEN le rapport HTML est généré, THE Publicateur_Pages SHALL pousser le fichier sur la branche gh-pages du dépôt
2. THE Publicateur_Pages SHALL maintenir un fichier index.html listant tous les rapports archivés par date
3. IF le token GitHub est absent, THEN THE Publicateur_Pages SHALL journaliser un avertissement et continuer sans publier
4. THE Publicateur_Pages SHALL nommer les fichiers selon le format "revue_evenements_ia_YYYY-MM-DD.html"

### Exigence 9 : Envoi email des événements à venir

**User Story :** En tant qu'utilisateur, je veux recevoir un email avec les événements à venir dans les 30 prochains jours, afin de ne rien manquer.

#### Critères d'acceptation

1. WHEN la collecte est terminée, THE Expéditeur_Email SHALL envoyer un email HTML contenant les événements dont la date est dans les 30 prochains jours
2. THE Expéditeur_Email SHALL grouper les événements par semaine dans l'email
3. THE Expéditeur_Email SHALL produire un HTML compatible Outlook et Gmail (table-based, sans JavaScript)
4. THE Expéditeur_Email SHALL supporter plusieurs destinataires séparés par virgule ou point-virgule
5. IF la configuration SMTP est incomplète, THEN THE Expéditeur_Email SHALL journaliser un message et continuer sans envoyer
6. THE Expéditeur_Email SHALL inclure un lien vers le rapport complet sur GitHub Pages

### Exigence 10 : Pipeline CI/CD GitHub Actions

**User Story :** En tant qu'utilisateur, je veux que la collecte et la publication soient automatisées, afin de recevoir les mises à jour sans intervention manuelle.

#### Critères d'acceptation

1. THE Pipeline_CI SHALL s'exécuter automatiquement du lundi au vendredi à 06h30 UTC via un cron GitHub Actions
2. THE Pipeline_CI SHALL supporter le déclenchement manuel via workflow_dispatch
3. THE Pipeline_CI SHALL utiliser Python 3.12 avec cache pip
4. THE Pipeline_CI SHALL passer les secrets GitHub (REVUE_GITHUB_TOKEN, SMTP_USER, SMTP_PASSWORD, MAIL_TO) comme variables d'environnement
5. THE Pipeline_CI SHALL avoir un timeout de 25 minutes
6. IF la collecte retourne 0 événement, THEN THE Pipeline_CI SHALL terminer avec un code d'erreur (exit 1)

### Exigence 11 : Configuration par variables d'environnement

**User Story :** En tant qu'utilisateur, je veux configurer le système via un fichier .env ou des secrets GitHub, afin de ne pas exposer mes identifiants dans le code.

#### Critères d'acceptation

1. THE Collecteur SHALL charger la configuration depuis un fichier .env local ou depuis les variables d'environnement système
2. THE Collecteur SHALL supporter les variables : SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_TO, GITHUB_TOKEN, GITHUB_REPOSITORY
3. THE Collecteur SHALL fournir un fichier .env.example documentant toutes les variables requises
4. WHEN le fichier .env est absent, THE Collecteur SHALL utiliser les variables d'environnement système sans erreur

### Exigence 12 : Exécution locale

**User Story :** En tant que développeur, je veux pouvoir exécuter le système en local, afin de tester et déboguer la collecte.

#### Critères d'acceptation

1. THE Collecteur SHALL pouvoir être exécuté via `python run_ci.py` en local
2. THE Collecteur SHALL sauvegarder le rapport HTML dans un dossier `rapports/` local
3. WHEN le système est exécuté en local sous Windows, THE Collecteur SHALL afficher une notification toast Windows et ouvrir le rapport dans le navigateur
4. THE Collecteur SHALL fonctionner avec uniquement `requests` et `python-dotenv` comme dépendances obligatoires