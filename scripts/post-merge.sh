#!/usr/bin/env bash
# Post-merge hook for the main checkout: push main, refresh this repo's map,
# and rebuild the local cbi install when the merge touched it.
# Install: ln -sf ../../scripts/post-merge.sh .git/hooks/post-merge
set -uo pipefail

repo=$(git rev-parse --show-toplevel)
common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
# Only the main checkout on main; lane worktrees and other branches do nothing.
[[ "$(git rev-parse --git-dir)" == ".git" || "$(cd "$(git rev-parse --git-dir)" && pwd)" == "$common" ]] || exit 0
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || exit 0

log="$common/cbi-post-merge.log"
changed=$(git diff --name-only ORIG_HEAD HEAD 2>/dev/null || true)
{
  echo "== $(date '+%F %T') merge to $(git rev-parse --short HEAD)"

  # 1. Push and verify the remote has it.
  if git push -q origin main; then
    git fetch -q origin main
    if [[ "$(git rev-parse origin/main)" == "$(git rev-parse HEAD)" ]]; then
      echo "pushed $(git rev-parse --short HEAD)"
    else
      echo "PUSH MISMATCH: origin/main $(git rev-parse --short origin/main)"
    fi
  else
    echo "PUSH FAILED"
  fi

  # 3. Rebuild the local cbi install when the merge touched it.
  if grep -qE '^(pyproject\.toml|uv\.lock)$' <<<"$changed"; then
    uv tool install -q --force --editable "$repo" && echo "cbi CLI reinstalled"
  fi
  if grep -q '^app/' <<<"$changed"; then
    "$repo/scripts/install-app.sh" >/dev/null 2>&1 && echo "desktop app reinstalled" || echo "APP INSTALL FAILED (run scripts/install-app.sh)"
  fi

  # 2. Refresh this repo's own map (deterministic part; open tasks are left for an agent).
  if command -v cbi >/dev/null; then
    (cd "$repo" && cbi scan >/dev/null 2>&1 && cbi build >/dev/null 2>&1) && echo "map rescanned and built; $(cd "$repo" && cbi tasks 2>/dev/null | grep -cv '^no open tasks') open tasks"
  fi
} >>"$log" 2>&1 &
disown
exit 0
