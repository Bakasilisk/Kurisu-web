#!/usr/bin/env bash
# Finishes a deploy on the server: restarts kurisu-web so it picks up whatever
# was last pulled, pushes any local commits, and offers to delete remote
# branches that are already merged into main.
#
# It still has to be run by hand rather than by an agent or a hook: the
# restart needs a sudo password, and the prune asks before it deletes
# anything. GitHub auth is no longer part of that — the deploy key wired up
# in preflight means the push doesn't stop to ask for credentials.
#
# Safe to re-run: every step checks whether it's already been done.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="kurisu-web"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$*"; }

git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$REPO" \
  || git config --global --add safe.directory "$REPO"

cd "$REPO"

# ---------------------------------------------------------------- preflight
say "Preflight"

if [[ -n "$(git status --porcelain)" ]]; then
  warn "Working tree is dirty:"
  git status --short | sed 's/^/      /'
  warn "Commit or stash before continuing; nothing here has run yet."
  exit 1
fi
ok "Working tree clean"

# The share this repo lives on gets chmod -R 777'd periodically, which flips
# every tracked file to mode 100755. With core.fileMode=true git reads that as
# 28 modified files and refuses to pull. Setting it false is what keeps the
# clean check above meaningful.
[[ "$(git config --get core.fileMode)" == "false" ]] \
  && ok "core.fileMode=false (chmod noise ignored)" \
  || warn "core.fileMode is not false — a chmod -R 777 will block the next pull"

# Both the push and the branch prune talk to GitHub. This box has no gh CLI
# and no credential helper, so over HTTPS git stops to ask for a username and
# a PAT — neither of which an unattended run can answer. Pointing it at a
# deploy key is what makes those steps go through. IdentitiesOnly stops ssh
# from offering every ~/.ssh/id_* first and being rejected before it ever
# gets to this one.
DEPLOY_KEY="${DEPLOY_KEY:-/home/kurisu/.ssh/git_ed25519}"

if [[ -r "$DEPLOY_KEY" ]]; then
  # The same chmod -R 777 sweep noted above also lands on the key, and ssh
  # flatly refuses a private key that's group- or world-readable. That needs
  # re-tightening rather than just reporting — but only we can do it if we
  # own the file, so otherwise say so and let ssh's own error explain.
  KEY_MODE="$(stat -c '%a' "$DEPLOY_KEY")"
  if [[ "$KEY_MODE" != "600" ]]; then
    if [[ -O "$DEPLOY_KEY" ]] && chmod 600 "$DEPLOY_KEY"; then
      ok "Re-tightened $DEPLOY_KEY from $KEY_MODE to 600 (ssh rejects looser modes)"
    else
      warn "$DEPLOY_KEY is mode $KEY_MODE and owned by $(stat -c '%U' "$DEPLOY_KEY"), not $(id -un)"
      warn "  ssh will refuse it; chmod 600 it as its owner"
    fi
  fi
  # Exported even when the mode check above failed: ssh's own refusal is the
  # clearer error to fail on, and saying "Deploy key ..." in green right under
  # a warning that it won't work would just be confusing.
  export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes"
  [[ "$(stat -c '%a' "$DEPLOY_KEY")" == "600" ]] && ok "Deploy key $DEPLOY_KEY"
else
  warn "No readable deploy key at $DEPLOY_KEY — falling back to ssh's own defaults"
fi

# A key is no use while origin still points at https://; git wouldn't touch
# ssh at all and would go back to asking for a PAT.
if [[ "$(git remote get-url origin)" == https://* ]]; then
  warn "origin is an HTTPS URL, so the deploy key won't be used:"
  warn "  git remote set-url origin git@github.com:Bakasilisk/Kurisu-web.git"
else
  ok "origin is $(git remote get-url origin)"
fi

# --------------------------------------------------------------- dependencies
say "Dependencies"

# Pins are checked against installed metadata rather than by importing
# anything — no network, and no risk of running app.main's .env loader as a
# side effect just to find out whether uvicorn is present.
if .venv/bin/python - <<'PY'
import sys
from importlib.metadata import version, PackageNotFoundError

stale = []
for line in open("requirements.txt"):
    line = line.split("#")[0].strip()
    if not line or "==" not in line:
        continue
    name, want = line.split("==", 1)
    name = name.split("[")[0]          # uvicorn[standard] -> uvicorn
    try:
        have = version(name)
    except PackageNotFoundError:
        stale.append(f"{name}: missing (want {want})")
        continue
    if have != want:
        stale.append(f"{name}: {have} installed, want {want}")

if stale:
    print("\n".join("      " + s for s in stale), file=sys.stderr)
    sys.exit(1)
PY
then
  ok "Virtualenv matches requirements.txt"
else
  warn "Virtualenv doesn't match requirements.txt — installing"
  .venv/bin/pip install -q -r requirements.txt
fi

# ------------------------------------------------------------------ restart
say "Restart $SERVICE"

echo "    Currently up since: $(systemctl show "$SERVICE" -p ActiveEnterTimestamp --value)"
echo "    Deploying:          $(git log -1 --format='%h %s')"

sudo systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
  ok "Active since $(systemctl show "$SERVICE" -p ActiveEnterTimestamp --value)"
else
  warn "Service failed to come back up:"
  systemctl status "$SERVICE" --no-pager | sed 's/^/      /'
  warn "To roll back, reset to a known-good commit and restart:"
  warn "  git -C $REPO log --oneline -10"
  warn "  git -C $REPO reset --hard <sha> && sudo systemctl restart $SERVICE"
  exit 1
fi

# --------------------------------------------------------------------- push
say "Push to origin"

git fetch --quiet origin
AHEAD="$(git rev-list --count origin/main..HEAD)"

if [[ "$AHEAD" -eq 0 ]]; then
  ok "Already pushed, nothing to send"
else
  echo "    $AHEAD commit(s) to push:"
  git log --oneline origin/main..HEAD | sed 's/^/      /'
  # Authenticated by the deploy key set up in preflight, via GIT_SSH_COMMAND.
  git push origin main
  ok "Pushed"
fi

# --------------------------------------------------- prune merged branches
say "Merged remote branches"

# Detected rather than listed, so this doesn't need editing every time a
# branch lands. --merged only reports refs whose tip is reachable from
# origin/main, which is exactly the safe-to-delete set.
#
# The %(symref) test drops origin/HEAD. It has to be filtered by symref and
# not by name: git shortens refs/remotes/origin/HEAD to plain "origin", so a
# name filter looking for "HEAD" sails straight past it and puts "origin" in
# the delete list.
mapfile -t MERGED < <(
  git for-each-ref --merged origin/main \
      --format='%(refname:short) %(symref)' refs/remotes/origin \
    | awk '$2 == "" { print $1 }' \
    | sed 's|^origin/||' \
    | grep -vxF 'main' || true
)

if [[ ${#MERGED[@]} -eq 0 ]]; then
  ok "Nothing to prune"
else
  # Everything above reads remote-tracking refs, which are only as fresh as
  # the last fetch. Two things can have happened on GitHub since, and each
  # needs catching for a different reason:
  #
  #   gone   — the branch was already deleted. Harmless in itself, but git
  #            aborts an entire multi-ref delete over one unexpected ref, so
  #            a single stale entry would stop every other branch from being
  #            deleted. That happened for real on 2026-07-28.
  #   moved  — the branch got new commits pushed to it. Those commits are not
  #            in the --merged result that put it on this list, so deleting it
  #            now could drop work. This is the one that actually matters.
  declare -A LIVE=()
  while read -r sha ref; do
    LIVE["${ref#refs/heads/}"]="$sha"
  done < <(git ls-remote --heads origin)

  TO_DELETE=()
  for b in "${MERGED[@]}"; do
    if [[ -z "${LIVE[$b]:-}" ]]; then
      warn "origin/$b is already gone on GitHub — skipping"
    elif [[ "${LIVE[$b]}" != "$(git rev-parse "origin/$b")" ]]; then
      warn "origin/$b moved since the last fetch (now ${LIVE[$b]:0:7}) — skipping"
      warn "  it may have unmerged commits now; re-run to re-check it"
    else
      TO_DELETE+=("$b")
    fi
  done

  if [[ ${#TO_DELETE[@]} -eq 0 ]]; then
    ok "Nothing left to prune once checked against the live remote"
    git remote prune origin
  else
    echo "    Fully merged into main, still at the tip we checked, safe to delete:"
    for b in "${TO_DELETE[@]}"; do
      printf '      origin/%-32s (last: %s)\n' "$b" "$(git log -1 --format='%ar' "origin/$b")"
    done
    read -rp "    Delete these on GitHub? [y/N] " reply
    if [[ "$reply" == [yY] ]]; then
      # One ref per push, for the same reason as the "gone" case above: a
      # single rejected ref must not take the rest of the batch down with it.
      FAILED=()
      for b in "${TO_DELETE[@]}"; do
        git push origin --delete "$b" || FAILED+=("$b")
      done
      git remote prune origin
      if [[ ${#FAILED[@]} -eq 0 ]]; then
        ok "Deleted and pruned"
      else
        warn "Deleted all but: ${FAILED[*]}"
      fi
    else
      ok "Left alone"
    fi
  fi
fi

# ------------------------------------------------------------------ verify
say "Verify"

git fetch --quiet origin
printf '    HEAD            %s\n' "$(git rev-parse --short HEAD)"
printf '    origin/main     %s\n' "$(git rev-parse --short origin/main)"
printf '    service         %s\n' "$(systemctl is-active "$SERVICE")"

[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
  && ok "Local and origin agree" \
  || warn "HEAD and origin/main differ — something above didn't finish"

# design/published/styles.css is meant to be a byte-for-byte mirror of the
# app stylesheet; its readme says so, and the published previews render
# against it. Drift means the design system is showing something the site
# doesn't.
if [[ -f design/published/styles.css ]]; then
  if cmp -s app/static/css/style.css design/published/styles.css; then
    ok "design/published/styles.css mirrors the app stylesheet"
  else
    warn "design/published/styles.css has drifted from app/static/css/style.css"
    warn "  cp app/static/css/style.css design/published/styles.css   # then re-publish"
  fi
fi

cat <<'EOF'

Worth checking by eye on the live site — the charts read CSS custom properties
through getComputedStyle at draw time, so a renamed or malformed token shows up
as a blank chart rather than a console error. Load a dashboard, in both light
and dark, and confirm the charts and the heatmap actually paint.
EOF
