#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$ROOT_DIR/.soc-lab"
API_PID="$STATE_DIR/web-api.pid"
DASH_PID="$STATE_DIR/web-dash.pid"
WATCHER_PID="$STATE_DIR/rules-watcher.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { printf "  ${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "  ${YELLOW}!${NC} %s\n" "$*"; }
err()   { printf "  ${RED}✗${NC} %s\n" "$*" >&2; }
step()  { printf "\n${BOLD}%s${NC}\n" "$*"; }
die()   { err "$*"; exit 1; }

# ── confirm ───────────────────────────────────────────────────────────────────

printf "\n${RED}${BOLD}WARNING:${NC} This will ${BOLD}destroy all data${NC} (Elasticsearch indices, Suricata state).\n"
printf "Docker volumes will be deleted. This cannot be undone.\n\n"
printf "Type 'yes' to confirm: "
read -r confirm
[[ "$confirm" == "yes" ]] || { printf "Aborted.\n"; exit 1; }

# ── stop web processes ─────────────────────────────────────────────────────────

_kill_pid_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local pid; pid=$(cat "$f" 2>/dev/null || true)
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
}

_kill_port() {
  local port="$1"
  local pids; pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  [[ -z "$pids" ]] && return 0
  echo "$pids" | xargs -r kill 2>/dev/null || true
}

step "Stopping web services"
_kill_pid_file "$API_PID"
_kill_pid_file "$DASH_PID"
_kill_pid_file "$WATCHER_PID"
_kill_port 8000
_kill_port 8050
info "Web services stopped"

# ── docker down + wipe volumes ────────────────────────────────────────────────

step "Wiping Docker stack"
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || die "Docker not available"
cd "$ROOT_DIR"
docker compose down -v
info "Containers and volumes removed"

# ── clean runtime state ───────────────────────────────────────────────────────

step "Cleaning runtime state"
rm -f "$STATE_DIR"/*.log "$STATE_DIR"/*.pid "$STATE_DIR/capture-history.json"
info "State directory cleaned"

printf "\n${BOLD}Reset complete.${NC}\n"
printf "  All data has been wiped.\n"
printf "  Run ./start.sh to bring the stack back up.\n\n"
