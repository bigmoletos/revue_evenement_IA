---
name: commit-push
description: >-
  Committe les modifications que l'agent vient de faire, pousse sur le remote
  quand c'est autorisé, et enregistre l'épisode dans Memgraph si le changement
  mérite d'être tracé. Déclenché par /commit-push ou par des demandes du type
  « commit et push », « pousse tes modifs », « commit push mes changements ».
---

# Commit et push

Committe **les modifications que l'agent vient de faire**, pousse sur le remote
quand c'est autorisé, et enregistre l'épisode dans Memgraph si le changement
mérite d'être tracé.

## Quand l'utiliser

- L'utilisateur tape `/commit-push`.
- L'utilisateur demande « commit et push », « pousse tes modifs », « commit push
  mes changements », ou toute formulation équivalente.

## Ce que ce skill NE fait PAS

- Il ne committe pas aveuglément tout le repo. Il cible les fichiers que
  **l'agent vient de modifier** dans la conversation en cours. Si des
  changements non liés traînent dans l'arbre de travail, il les signale et
  demande confirmation avant de les inclure.
- Il n'écrase pas l'historique git (`--amend`, `reset --hard`, `push --force`
  sont interdits sauf demande explicite de l'utilisateur).
- Il ne touche pas à `git config` ni aux hooks (`--no-verify` interdit).

## Procédure

### 1. Identifier les fichiers modifiés par l'agent

Récapitule mentalement les fichiers que tu as créés ou édités pendant ce tour /
cette session, puis confronte-les à l'état réel du dépôt :

```powershell
git -C "$env:USERPROFILE\dev" status --porcelain
```

- Si l'arbre contient uniquement les fichiers que tu as touchés → continue.
- Si l'arbre contient aussi des fichiers que tu n'as **pas** touchés → liste-les
  à l'utilisateur et demande s'il faut les inclure ou se limiter aux tiens.
- Si aucun changement n'est détecté → informe l'utilisateur (« Rien à
  committer ») et arrête-toi.

> Rappel sécurité : signale tout fichier susceptible de contenir des secrets
> (`.env`, `*.env`, `api-keys.env`, `credentials*`, `*.pem`, `*.key`) avant de
> l'ajouter. Ne jamais committer `~\.secrets\`. Vérifie qu'il est bien dans
> `.gitignore`.

### 2. Stager uniquement les fichiers concernés

Ajoute les fichiers **par nom**, jamais `git add -A` ni `git add .` (pour éviter
d'embarquer des changements non liés) :

```powershell
git -C "$env:USERPROFILE\dev" add -- "chemin/relatif/fichier1" "chemin/relatif/fichier2"
```

### 3. Rédiger le message de commit

Suis la convention du projet (voir steering `development-workflow`) :

```
<type>: <description courte>

[corps optionnel]
```

Types : `feat`, `fix`, `docs`, `refactor`, `chore`, `test`.

Exemples :
- `feat: ajoute le skill commit-push`
- `fix: corrige le conflit de PATH Node.js v24`
- `docs: met à jour ai-multimedia-tools.md`

Le message doit décrire **ce que l'agent vient de faire**, pas un libellé
générique « auto-commit ».

```powershell
git -C "$env:USERPROFILE\dev" commit -m "<type>: <description>"
```

### 4. Pousser quand c'est autorisé

Le push est autorisé si :
- un remote `origin` existe, **et**
- la branche courante n'est **pas** `main`/`master` (sinon, demander
  confirmation explicite à l'utilisateur avant de pousser).

```powershell
# branche courante
git -C "$env:USERPROFILE\dev" rev-parse --abbrev-ref HEAD
# remote configuré ?
git -C "$env:USERPROFILE\dev" remote get-url origin
```

Push normal (avec suivi de branche si nouvelle branche) :

```powershell
git -C "$env:USERPROFILE\dev" push -u origin HEAD
```

Si le remote est absent, ou si on est sur `main`/`master` sans accord : committe
quand même en local, puis explique à l'utilisateur pourquoi le push a été
suspendu et ce qu'il doit faire.

### 5. Enregistrer l'épisode dans Memgraph (si le changement mérite d'être tracé)

**Enregistrer** quand le changement a une valeur de traçabilité : nouvelle
fonctionnalité, correctif notable, décision d'architecture, modification du
DevKit, d'un steering, d'un hook ou d'un spec.

**Ne pas enregistrer** pour un changement trivial (typo, reformatage, bump de
version mineur) — dans ce cas, mentionne juste que l'épisode n'a pas été jugé
utile à tracer.

La base `Base_Project` écoute sur `bolt://localhost:7688`. Le schéma du nœud est
`Episode(type, content, timestamp, palier, source)`.

Avant d'écrire, vérifie que Memgraph répond. S'il ne répond pas, **ne bloque
pas** le skill : signale que l'épisode n'a pas pu être enregistré et termine
normalement (dégradation gracieuse).

L'enregistrement est délégué au script versionné
`scripts/record-episode.py` (situé dans ce dossier de skill). Il évite les
pièges d'échappement PowerShell/Python et gère la dégradation gracieuse
lui-même (sortie code 0 même si Memgraph ou le driver manque).

```powershell
python "$env:USERPROFILE\dev\.kiro\skills\commit-push\scripts\record-episode.py" `
    --type commit `
    --content "<type>: <description du commit> (commit <hash>)" `
    --palier 0
```

Paramètres :
- `--type` : type d'épisode (`commit`, `decision`, `error`, ...).
- `--content` : résumé lisible, idéalement le message de commit + le hash.
- `--palier` : palier concerné (`0` si hors palier).
- `--source` : optionnel, défaut `commit-push`.
- `--uri` : optionnel, défaut `bolt://localhost:7688`.

> Le driver `neo4j` (compatible bolt / Memgraph) est utilisé par les scripts
> `qm` existants. Si Python ou le driver manque, ou si Memgraph ne répond pas,
> le script affiche un avertissement et sort proprement sans faire échouer le
> skill.

### 6. Rapport final

Résume en quelques lignes :
- fichiers committés,
- hash / message de commit,
- statut du push (poussé sur `<branche>`, ou suspendu + raison),
- statut Memgraph (épisode enregistré / ignoré / indisponible).

## Garde-fous

- Jamais de `git add -A` / `git add .` : staging par nom de fichier uniquement.
- Jamais de push direct sur `main`/`master` sans accord explicite.
- Jamais `--amend`, `--force`, `reset --hard`, `clean -f`, `--no-verify` sauf
  demande explicite.
- Toujours `$env:USERPROFILE` pour les chemins — jamais de nom d'utilisateur en
  dur.
- Memgraph indisponible ne doit jamais faire échouer le commit/push.
