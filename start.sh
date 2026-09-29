#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  AURA OS — Autonomous Launcher
#  Starts backend (FastAPI :8000) + frontend dev server (Vite :5173)
#  Ctrl-C or SIGTERM shuts both down cleanly.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/venv"
PID_FILE="/tmp/aura-os-pids"

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'
CYN='\033[0;36m'; RST='\033[0m'

info()  { echo -e "${CYN}[aura]${RST} $*"; }
ok()    { echo -e "${GRN}[aura]${RST} $*"; }
warn()  { echo -e "${YLW}[aura]${RST} $*"; }
fail()  { echo -e "${RED}[aura]${RST} $*"; exit 1; }

# ── Cleanup ──────────────────────────────────────────────────
cleanup() {
  info "Shutting down AURA OS..."
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  ok "Stopped."
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── 1. Prerequisites ────────────────────────────────────────
info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || fail "python3 not found"
command -v node    >/dev/null 2>&1 || fail "node not found (install Node.js >=20)"
command -v npm     >/dev/null 2>&1 || fail "npm not found"

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
NODE_VER=$(node -v | sed 's/v//')
info "Python $PYTHON_VER  |  Node $NODE_VER"

# ── 2. Virtual environment + backend deps ────────────────────
if [ ! -d "$VENV" ]; then
  info "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

VENV_PY="$VENV/bin/python"

# Install/update backend requirements if fastapi is missing
if ! "$VENV_PY" -c "import fastapi" 2>/dev/null; then
  info "Installing backend dependencies..."
  "$VENV_PY" -m pip install -q -r "$BACKEND/requirements.txt" -r "$BACKEND/requirements-voice.txt" 2>&1 | tail -1
  ok "Backend deps installed."
fi

# Check voice deps (non-fatal)
"$VENV_PY" -c "import edge_tts" 2>/dev/null && VOICE_OK=1 || VOICE_OK=0
if [ "$VOICE_OK" -eq 0 ]; then
  warn "edge-tts not installed (voice features degraded). Run: venv/bin/pip install edge-tts"
fi

# ── 3. Frontend deps ────────────────────────────────────────
if [ ! -d "$FRONTEND/node_modules" ]; then
  info "Installing frontend dependencies..."
  (cd "$FRONTEND" && npm ci --no-audit --no-fund 2>&1 | tail -1)
  ok "Frontend deps installed."
fi

# ── 4. Ollama check ─────────────────────────────────────────
OLLAMA_OK=0
if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  OLLAMA_OK=1
  MODELS=$(curl -sf http://127.0.0.1:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
print(', '.join(names[:5]) + ('...' if len(names) > 5 else ''))
" 2>/dev/null || echo "unknown")
  ok "Ollama online — models: $MODELS"
else
  warn "Ollama not reachable at :11434 — AURA will use builtin composer fallback"
fi

# ── 5. Create data directory ────────────────────────────────
mkdir -p "$ROOT/data"

# ── 6. Start backend ────────────────────────────────────────
info "Starting backend on :8000..."
(cd "$BACKEND" && AURA_DATA_DIR="$ROOT/data" \
  "$VENV_PY" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info) &
BACKEND_PID=$!
echo "$BACKEND_PID" >> "$PID_FILE"

# Wait for backend to be ready (max 30s)
info "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/me >/dev/null 2>&1; then
    ok "Backend ready (pid $BACKEND_PID)"
    break
  fi
  [ "$i" -eq 30 ] && fail "Backend failed to start after 30s"
  sleep 1
done

# ── 7. Start frontend dev server ────────────────────────────
info "Starting frontend dev server on :5173..."
(cd "$FRONTEND" && npx vite --host 0.0.0.0 --port 5173 --strictPort) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" >> "$PID_FILE"

# Wait for frontend
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:5173 >/dev/null 2>&1; then
    ok "Frontend ready (pid $FRONTEND_PID)"
    break
  fi
  [ "$i" -eq 20 ] && { warn "Frontend slow to start; continuing anyway"; break; }
  sleep 1
done

# ── 8. Summary ──────────────────────────────────────────────
echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "${GRN}║           AURA OS v1.15 — Running                  ║${RST}"
echo -e "${GRN}╠══════════════════════════════════════════════════════╣${RST}"
echo -e "${GRN}║${RST}  Backend API    ${CYN}http://127.0.0.1:8000${RST}"
echo -e "${GRN}║${RST}  Frontend Dev   ${CYN}http://127.0.0.1:5173${RST}"
echo -e "${GRN}║${RST}  API Docs       ${CYN}http://127.0.0.1:8000/docs${RST}"
echo -e "${GRN}║${RST}  Health Check   ${CYN}http://127.0.0.1:8000/api/health${RST}"
if [ "$OLLAMA_OK" -eq 1 ]; then
echo -e "${GRN}║${RST}  Ollama         ${GRN}online${RST} (http://127.0.0.1:11434)"
else
echo -e "${GRN}║${RST}  Ollama         ${YLW}offline${RST} (builtin engine active)"
fi
echo -e "${GRN}║${RST}  Data Dir       $ROOT/data"
echo -e "${GRN}╠══════════════════════════════════════════════════════╣${RST}"
echo -e "${GRN}║${RST}  ${YLW}Press Ctrl-C to stop${RST}"
echo -e "${GRN}╚══════════════════════════════════════════════════════╝${RST}"
echo ""

# ── 9. Wait forever (trap handles shutdown) ─────────────────
wait
