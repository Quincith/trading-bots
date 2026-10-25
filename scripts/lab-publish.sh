#!/usr/bin/env bash
# After a lab run: open a pull request for each change that passed (lab-out/prs/<strategy>/),
# then one issue that sums up everything tried. Merging a pull request is how a change is approved.
set -euo pipefail
OUT=${1:-lab-out}
REPO=${GITHUB_REPOSITORY:?}
OWNER=${GITHUB_REPOSITORY_OWNER:-${REPO%%/*}}
git config user.name "trading-bots"
git config user.email "trading-bots@users.noreply.github.com"
base=$(git rev-parse HEAD)
links=""
for dir in "$OUT"/prs/*/; do
  [ -d "$dir" ] || continue
  s=$(basename "$dir"); id=$(cat "$dir/id"); branch="lab/$id"
  git checkout --quiet -B "$branch" "$base"
  cp "$dir/$s.yaml" "config/$s.yaml"
  git commit --quiet -am "$(cat "$dir/title")"
  git push --quiet --force origin "$branch"
  if url=$(gh pr create --base main --head "$branch" --title "$(cat "$dir/title")" --body-file "$dir/body.md" \
             --assignee "$OWNER" 2>/dev/null); then
    links+="- **${s^}:** $url"$'\n'
  else
    # GitHub only lets workflows open pull requests if "Allow GitHub Actions to create and approve pull
    # requests" is ticked (Settings > Actions > General). Without it, give a one-click link instead.
    links+="- **${s^}:** [open the pull request](https://github.com/$REPO/compare/main...$branch?expand=1) (one click; see README to let the bot open these itself)"$'\n'
  fi
  git checkout --quiet "$base"
done
body="$OUT/summary.md"
if [ -n "$links" ]; then
  printf '\n## Waiting for your OK\n\n%s' "$links" >> "$body"
fi
gh issue create --title "Strategy lab $(date -u +%Y-%m-%d)" --body-file "$body" --assignee "$OWNER"
