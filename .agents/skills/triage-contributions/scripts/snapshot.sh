#!/usr/bin/env bash
# Snapshot of open PRs and issues, and a check that nothing moved before you push.
#   snapshot.sh          list open PRs/issues; record each PR's head commit and origin/main
#   snapshot.sh verify   before pushing: every merged pr-<N> branch must still match GitHub's head
#                        and the recorded head, and origin/main must not have moved
# Writes only to diagnostics/triage/ (ignored by git). Needs gh and git.
set -euo pipefail
REPO=wesbos/photo-frame-dashboard
cd "$(git rev-parse --show-toplevel)"
OUT=diagnostics/triage
mkdir -p "$OUT"
git fetch -q origin

if [ "${1:-}" = verify ]; then
  [ -f "$OUT/heads.txt" ] || { echo "STOP: run snapshot.sh first"; exit 1; }
  fail=0
  if [ "$(git rev-parse origin/main)" != "$(cat "$OUT/main.txt")" ]; then
    echo "STOP: origin/main moved since the snapshot. Merge it in and re-check."; fail=1
  fi
  for ref in $(git for-each-ref --format='%(refname:short)' 'refs/heads/pr-*'); do
    n=${ref#pr-}
    local_sha=$(git rev-parse "$ref")
    recorded=$(awk -v n="$n" '$1==n{print $2}' "$OUT/heads.txt")
    remote=$(gh pr view "$n" --repo $REPO --json headRefOid --jq .headRefOid)
    if [ "$local_sha" != "$remote" ] || { [ -n "$recorded" ] && [ "$local_sha" != "$recorded" ]; }; then
      echo "STOP: #$n changed (merged ${local_sha:0:7}, recorded ${recorded:0:7}, GitHub ${remote:0:7}). Review the new commits."
      fail=1
    fi
  done
  [ $fail = 0 ] && echo "OK: PR heads unchanged and origin/main has not moved."
  exit $fail
fi

git rev-parse origin/main > "$OUT/main.txt"
gh pr list --repo $REPO --state open --limit 200 --json number,headRefOid --jq '.[] | "\(.number) \(.headRefOid)"' \
  | sort -n > "$OUT/heads.txt.new"
if [ -f "$OUT/heads.txt" ] && cmp -s "$OUT/heads.txt" "$OUT/heads.txt.new"; then
  echo "No PR changes since the last snapshot."
fi
mv "$OUT/heads.txt.new" "$OUT/heads.txt"
echo "== Open PRs ($(wc -l < "$OUT/heads.txt" | tr -d ' '))"
gh pr list --repo $REPO --state open --limit 200 \
  --json number,title,author,isDraft,additions,deletions,files,updatedAt \
  --jq '.[] | "#\(.number) [\(.author.login)] \(if .isDraft then "DRAFT " else "" end)+\(.additions)/-\(.deletions) updated \(.updatedAt[0:16]) | \(.title)\n    \([.files[].path] | join(", ") | .[0:240])"'
echo "== Open issues"
gh issue list --repo $REPO --state open --limit 200 --json number,title,author,comments,updatedAt \
  --jq '.[] | "issue #\(.number) [\(.author.login)] comments=\(.comments|length) updated \(.updatedAt[0:16]) | \(.title)"'
