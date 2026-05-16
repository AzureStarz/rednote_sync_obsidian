#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_RC="${1:-$HOME/.zshrc}"

mkdir -p "$(dirname "$SHELL_RC")"

add_alias() {
  local name="$1"
  local owner="$2"
  local line="alias $name='cd "$PROJECT_ROOT" && ./scripts/sync_local_vault.sh $owner'"
  if grep -Fq "alias $name=" "$SHELL_RC" 2>/dev/null; then
    echo "skip: alias $name already exists in $SHELL_RC"
  else
    printf '\n%s\n' "$line" >> "$SHELL_RC"
    echo "added: $line"
  fi
}

add_alias sync-rednote-hongbin hongbin
add_alias sync-rednote-zhangyu zhangyu

echo "Reload with: source $SHELL_RC"
