#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$ROOT_DIR/.soc-lab"
API_PID="$STATE_DIR/web-api.pid"
DASH_PID="$STATE_DIR/web-dash.pid"
WATCHER_PID="$STATE_DIR/rules-watcher.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'
info() { printf "  ${GREEN}✓${NC} %s\n" "$*"; }
err()  { printf "  ${RED}✗${NC} %s\n" "$*" >&2; }
step() { printf "\n${BOLD}%s${NC}\n" "$*"; }

_kill_pid_file() {
  local f="$1" label="$2"
  [[ -f "$f" ]] || return 0
  local pid; pid=$(cat "$f" 2>/dev/null || true)
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    # SIGKILL if still alive
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    info "$label stopped"
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
_kill_pid_file "$API_PID" "FastAPI"
_kill_pid_file "$DASH_PID" "Dash"
_kill_pid_file "$WATCHER_PID" "Rules watcher"
_kill_port 8000
_kill_port 8050

step "Stopping Docker stack"
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || {
  err "Docker not available — skipping container stop"
  exit 0
}
cd "$ROOT_DIR"
docker compose stop
info "Containers stopped (volumes preserved)"

printf "\n${BOLD}SOC Lab stopped.${NC}\n"
printf "  Start again: ./start.sh\n"
printf "  Full reset:  ./reset.sh\n\n"
