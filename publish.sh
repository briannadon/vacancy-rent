#!/usr/bin/env bash
# Push the built site/ to the gh-pages branch.
set -euo pipefail

cd "$(dirname "$0")"
[ -f site/index.html ] || { echo "site/index.html missing; run: uv run build-data --offline" >&2; exit 1; }

WT=$(mktemp -d)
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT

if git show-ref --verify --quiet refs/heads/gh-pages; then
  git worktree add "$WT" gh-pages
else
  git worktree add --detach "$WT"
  git -C "$WT" checkout --orphan gh-pages
  git -C "$WT" rm -rf . >/dev/null 2>&1 || true
fi

rm -rf "$WT"/*
cp site/index.html site/plotly.min.js "$WT"/
touch "$WT"/.nojekyll

git -C "$WT" add -A
git -C "$WT" commit -q -m "Publish site from $(git rev-parse --short HEAD)" || { echo "no changes"; exit 0; }
git -C "$WT" push -u origin gh-pages
echo "pushed gh-pages"
