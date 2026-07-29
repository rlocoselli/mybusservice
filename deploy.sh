#!/usr/bin/env bash

set -euo pipefail

BITBUCKET_REMOTE="${BITBUCKET_REMOTE:-origin}"
HEROKU_REMOTE="${HEROKU_REMOTE:-heroku}"
CONTINUE_ON_BITBUCKET_FAIL="${CONTINUE_ON_BITBUCKET_FAIL:-true}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BITBUCKET_BRANCH="${1:-$CURRENT_BRANCH}"
HEROKU_BRANCH="${HEROKU_BRANCH:-main}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Erreur: ce script doit être exécuté dans un dépôt Git."
  exit 1
fi

if ! git remote get-url "$BITBUCKET_REMOTE" >/dev/null 2>&1; then
  echo "Erreur: remote Bitbucket '$BITBUCKET_REMOTE' introuvable."
  echo "Définissez BITBUCKET_REMOTE ou ajoutez le remote: git remote add $BITBUCKET_REMOTE <url>"
  exit 1
fi

if ! git remote get-url "$HEROKU_REMOTE" >/dev/null 2>&1; then
  echo "Erreur: remote Heroku '$HEROKU_REMOTE' introuvable."
  echo "Définissez HEROKU_REMOTE ou ajoutez le remote: heroku git:remote -a <nom-app>"
  exit 1
fi

echo "[1/2] Push Bitbucket: $BITBUCKET_REMOTE $BITBUCKET_BRANCH"
if git push "$BITBUCKET_REMOTE" "$BITBUCKET_BRANCH"; then
  echo "Push Bitbucket OK."
else
  echo "Push Bitbucket en échec."
  if [[ "$CONTINUE_ON_BITBUCKET_FAIL" != "true" ]]; then
    echo "Arrêt du script (CONTINUE_ON_BITBUCKET_FAIL=$CONTINUE_ON_BITBUCKET_FAIL)."
    exit 1
  fi
  echo "Continuation vers Heroku malgré l'échec Bitbucket."
fi

echo "[2/2] Push Heroku: $HEROKU_REMOTE $BITBUCKET_BRANCH:$HEROKU_BRANCH"
git push "$HEROKU_REMOTE" "$BITBUCKET_BRANCH:$HEROKU_BRANCH"

echo "Déploiement terminé sur Bitbucket + Heroku."
