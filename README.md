# Objective
It is a simple service to practice arithmetic progression concepts. It is necessary to install flask as part of this solution in order to creqte service qnd run as a local server.

# Installing Flask
https://flask.palletsprojects.com/en/1.1.x/installation/

# Running application in Power Shell Terminal

$env:FLASK_APP = "ap.py"

python -m flask run

Example: http://127.0.0.1:5000/sumProgression/2/2/2

# Deploy Bitbucket + Heroku en une commande

## Origine du trafic dans le dashboard

Le dashboard admin (`/admin/usage-dashboard`) affiche les requêtes API par origine : site web, application mobile ou non identifiée. Les mêmes filtres de ville, ligne et dates s'appliquent à cette répartition.

Pour identifier les clients de façon fiable, envoyez `X-Client-Application: web` depuis le site et `X-Client-Application: mobile` depuis l'application. Pour les requêtes historiques sans cet en-tête, le serveur utilise le `User-Agent` lorsqu'il est reconnaissable. Un navigateur sur téléphone reste classé comme site web. Les autres requêtes restent non identifiées.

Un script est disponible: [deploy.sh](deploy.sh)

## Pré-requis

- Avoir les remotes Git configurés:
	- `origin` (Bitbucket)
	- `heroku` (Heroku), ex: `heroku git:remote -a <nom-app>`

## Utilisation

1. Donner les droits d'exécution (une seule fois):

```bash
chmod +x deploy.sh
```

2. Déployer la branche courante vers Bitbucket + Heroku:

```bash
./deploy.sh
```

3. Déployer une branche spécifique:

```bash
./deploy.sh main
```

## Variables optionnelles

- `BITBUCKET_REMOTE` (défaut: `origin`)
- `HEROKU_REMOTE` (défaut: `heroku`)
- `HEROKU_BRANCH` (défaut: `main`)

Exemple:

```bash
HEROKU_BRANCH=master ./deploy.sh
```
