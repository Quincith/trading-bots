#!/usr/bin/env bash
# Keeps the bots' memory (positions, trade log, deposits, reports) on the `bot-data` branch, in ./data.
#   data-branch.sh pull          -> fetch it into ./data (or start fresh)
#   data-branch.sh push "msg"    -> commit ./data back to the branch
set -euo pipefail
BRANCH=bot-data
URL="https://x-access-token:${GITHUB_TOKEN:?GITHUB_TOKEN must be set}@github.com/${GITHUB_REPOSITORY}.git"

case "${1:-}" in
  pull)
    if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
      git clone --quiet --depth 20 --branch "$BRANCH" "$URL" data
    else
      mkdir -p data && cd data && git init --quiet -b "$BRANCH" && git remote add origin "$URL"
      printf '# Bot data\n\nWritten by the trading bots. Each folder has summary.md (latest run), trades.csv, decisions.csv, deposits.csv and equity.csv.\n' > README.md
    fi
    ;;
  push)
    cd data
    git config user.name "trading-bots"
    git config user.email "trading-bots@users.noreply.github.com"
    git add -A
    git diff --cached --quiet && { echo "nothing to save"; exit 0; }
    git commit --quiet -m "${2:-update}"
    for i in 1 2 3 4; do
      git push --quiet origin "$BRANCH" && exit 0
      sleep $((2 ** i)); git pull --quiet --rebase origin "$BRANCH" || true
    done
    echo "could not save bot data" >&2; exit 1
    ;;
  *) echo "usage: $0 pull|push [message]" >&2; exit 2 ;;
esac
