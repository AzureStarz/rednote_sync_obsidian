#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/sync_local_vault.sh <owner> [local_vault]

Examples:
  scripts/sync_local_vault.sh hongbin
  scripts/sync_local_vault.sh zhangyu ~/Documents/zhangyu_raw_rednote_post_vault

Config via environment variables:
  REDNOTE_SYNC_SERVER       SSH target, default: root@120.24.177.252
  REDNOTE_REMOTE_ROOT       Server raw root, default: /opt/rednote_sync_obsidian/data/rednote_raw
  REDNOTE_LOCAL_VAULT       Local vault, default: ~/Documents/raw_rednote_post_vault
  REDNOTE_REMOTE_CACHE_DAYS Server cache days, default: 30
  REDNOTE_SSH_PORT          Optional SSH port
  REDNOTE_REMOTE_PRUNE_SUDO Set to 1 to add --remote-prune-sudo
  REDNOTE_DRY_RUN           Set to 1 to add --dry-run
  REDNOTE_VERBOSE           Set to 1 to add --verbose
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

OWNER="${1:-${REDNOTE_SYNC_OWNER:-}}"
if [[ -z "$OWNER" ]]; then
  echo "error: owner is required, for example: scripts/sync_local_vault.sh hongbin" >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env.sync" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_ROOT/.env.sync"
  set +a
fi
PYTHON_BIN="${REDNOTE_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

SERVER="${REDNOTE_SYNC_SERVER:-root@120.24.177.252}"
REMOTE_ROOT="${REDNOTE_REMOTE_ROOT:-/opt/rednote_sync_obsidian/data/rednote_raw}"
LOCAL_VAULT="${2:-${REDNOTE_LOCAL_VAULT:-$HOME/Documents/raw_rednote_post_vault}}"
CACHE_DAYS="${REDNOTE_REMOTE_CACHE_DAYS:-30}"

cmd=(
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/sync_raw_vault.py"
  --server "$SERVER"
  --remote-root "$REMOTE_ROOT"
  --owner "$OWNER"
  --local-vault "$LOCAL_VAULT"
  --remote-cache-days "$CACHE_DAYS"
)

if [[ -n "${REDNOTE_SSH_PORT:-}" ]]; then
  cmd+=(--ssh-port "$REDNOTE_SSH_PORT")
fi
if [[ -n "${REDNOTE_SSH_KEY:-}" ]]; then
  cmd+=(--ssh-key "$REDNOTE_SSH_KEY")
fi
if [[ "${REDNOTE_REMOTE_PRUNE_SUDO:-0}" == "1" ]]; then
  cmd+=(--remote-prune-sudo)
fi
if [[ "${REDNOTE_DRY_RUN:-0}" == "1" ]]; then
  cmd+=(--dry-run)
fi
if [[ "${REDNOTE_VERBOSE:-0}" == "1" ]]; then
  cmd+=(--verbose)
fi

printf 'Sync owner=%s from %s:%s to %s\n' "$OWNER" "$SERVER" "$REMOTE_ROOT/users/$OWNER" "$LOCAL_VAULT"
exec "${cmd[@]}"
