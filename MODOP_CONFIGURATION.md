# 🛠️ MODOP — Configuration du projet Revue Événements IA

Guide pas-à-pas pour configurer GitHub Actions, GitHub Pages, le token GitHub et Gmail.
Basé sur la même procédure que `revue_de_presse_IA`.

---

## 1. Créer un Token GitHub (Personal Access Token)

1. Aller sur **GitHub** → icône profil → **Settings**
2. Menu gauche → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
3. Cliquer **Generate new token** → **Generate new token (classic)**
4. Remplir :
   - **Note** : `revue-evenement-ia`
   - **Expiration** : 90 days (ou No expiration si vous préférez)
   - **Scopes** : cocher uniquement `repo` (accès complet aux repos privés/publics)
5. Cliquer **Generate token**
6. **Copier le token immédiatement** (il ne sera plus visible après)

> ⚠️ Le token commence par `ghp_...`. Gardez-le dans un endroit sûr temporairement.

---

## 2. Configurer les Secrets GitHub Actions

1. Aller sur le repo : `https://github.com/bigmoletos/revue_evenement_IA`
2. **Settings** → **Secrets and variables** → **Actions**
3. Cliquer **New repository secret** pour chaque secret :

| Secret | Valeur | Description |
|--------|--------|-------------|
| `REVUE_GITHUB_TOKEN` | `ghp_...` | Le token créé à l'étape 1 |
| `SMTP_USER` | `votre-email@gmail.com` | Adresse Gmail expéditrice |
| `SMTP_PASSWORD` | `xxxx xxxx xxxx xxxx` | Mot de passe d'application Gmail (étape 3) |
| `MAIL_TO` | `dest@gmail.com` | Destinataire(s), séparés par virgule |

> Pour plusieurs destinataires : `adresse1@gmail.com,adresse2@example.com`

---

## 3. Configurer le mot de passe d'application Gmail

Gmail n'accepte plus les mots de passe classiques pour SMTP. Il faut un **mot de passe d'application**.

### Prérequis : activer la validation en 2 étapes

1. Aller sur https://myaccount.google.com/security
2. Section **Connexion à Google** → **Validation en 2 étapes**
3. Suivre les étapes pour activer (SMS ou application d'authentification)

### Générer le mot de passe d'application

1. Aller sur https://myaccount.google.com/apppasswords
2. En bas, section **Mots de passe des applications**
3. Sélectionner :
   - **Application** : Autre (nom personnalisé)
   - **Nom** : `revue-evenement-ia`
4. Cliquer **Générer**
5. Un mot de passe de 16 caractères s'affiche (format `xxxx xxxx xxxx xxxx`)
6. **Copier ce mot de passe** → c'est la valeur du secret `SMTP_PASSWORD`

> ⚠️ Ce mot de passe ne sera affiché qu'une seule fois. Si perdu, il faut en régénérer un.

---

## 4. Activer GitHub Pages

1. Aller sur le repo → **Settings** → **Pages**
2. Section **Build and deployment** :
   - **Source** : `Deploy from a branch`
   - **Branch** : `gh-pages`
   - **Folder** : `/ (root)`
3. Cliquer **Save**

> La branche `gh-pages` sera créée automatiquement par le workflow lors de la première exécution.
> L'URL publique sera : `https://bigmoletos.github.io/revue_evenement_IA/`

---

## 5. Premier lancement (important)

Le cron GitHub Actions (`30 6 * * 1-5`) **ne se déclenche pas tant que le workflow n'a jamais été lancé manuellement**.

### Lancement manuel depuis l'interface web

1. Aller sur le repo → **Actions**
2. Cliquer sur **Revue Événements IA France** dans la liste des workflows
3. Cliquer **Run workflow** → **Run workflow**

### Lancement manuel en ligne de commande

```bash
gh workflow run revue-evenement-ia.yml
```

Après ce premier lancement, le cron s'exécutera automatiquement du lundi au vendredi à 06h30 UTC (08h30 heure de Paris).

---

## 6. Configuration locale (optionnel)

Pour tester en local sans GitHub Actions :

```bash
cd revue_evenement_IA
pip install -r requirements.txt
cp .env.example .env
```

Éditer `.env` :

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=votre-email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx
MAIL_TO=destinataire@gmail.com
GITHUB_TOKEN=ghp_...
GITHUB_REPOSITORY=bigmoletos/revue_evenement_IA
```

Lancer :

```bash
python run_ci.py
```

---

## 7. Troubleshooting

| Problème | Cause probable | Solution |
|----------|---------------|----------|
| `403 Write access not granted` | Token sans scope `repo` | Régénérer le token avec le scope `repo` coché |
| `GITHUB_TOKEN manquant` | Secret non configuré | Vérifier que `REVUE_GITHUB_TOKEN` est bien dans Settings > Secrets |
| Pages non accessibles | GitHub Pages pas activé | Settings > Pages > activer sur branche `gh-pages` |
| Email non reçu | Secrets SMTP manquants ou incorrects | Vérifier `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO` dans les Secrets |
| `SMTPAuthenticationError` | Mot de passe Gmail classique utilisé | Utiliser un mot de passe d'application (étape 3) |
| Cron ne se déclenche pas | Workflow jamais lancé manuellement | Faire un premier `Run workflow` depuis l'onglet Actions |
| Timeout CI > 25 min | Sources trop lentes | Vérifier les logs, réduire les sources si nécessaire |
| `gh-pages` branch inexistante | Premier run pas encore fait | Lancer le workflow une première fois (étape 5) |

---

## Récapitulatif des étapes

```
1. Créer le token GitHub (scope repo)
         ↓
2. Ajouter les 4 secrets dans le repo (REVUE_GITHUB_TOKEN, SMTP_USER, SMTP_PASSWORD, MAIL_TO)
         ↓
3. Générer le mot de passe d'application Gmail
         ↓
4. Activer GitHub Pages (branche gh-pages)
         ↓
5. Lancer le workflow manuellement une première fois
         ↓
✅ Le cron prend le relais automatiquement (lun-ven 08h30 Paris)
```
