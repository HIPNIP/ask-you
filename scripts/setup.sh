#!/usr/bin/env bash
# Ask-You setup script
# Installs dependencies, creates the venv, and writes your .env

set -euo pipefail

# ─── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗ ERROR:${RESET} $*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         Ask-You Setup Script         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""

# ─── Step 1: Check required tools ──────────────────────────────────────
echo -e "${BOLD}[1/5] Checking required tools...${RESET}"

# brew
if ! command -v brew &>/dev/null; then
  die "Homebrew is not installed.\n  Install it from: https://brew.sh\n  Then re-run this script."
fi
ok "Homebrew found"

# python3.12
if ! command -v python3.12 &>/dev/null; then
  info "Python 3.12 not found — installing via Homebrew..."
  brew install python@3.12 || die "Failed to install Python 3.12"
fi
ok "Python 3.12 found ($(python3.12 --version))"

# git
if ! command -v git &>/dev/null; then
  die "git is not installed. Install Xcode Command Line Tools:\n  xcode-select --install"
fi
ok "git found"

# gcloud
if ! command -v gcloud &>/dev/null; then
  die "Google Cloud SDK not found.\n  Install from: https://cloud.google.com/sdk/docs/install\n  Then re-run this script."
fi
ok "gcloud found"

echo ""

# ─── Step 2: Create venv ───────────────────────────────────────────────
echo -e "${BOLD}[2/5] Setting up Python virtual environment...${RESET}"

if [ -d "venv" ]; then
  warn "venv already exists — skipping creation"
else
  info "Creating venv with Python 3.12..."
  python3.12 -m venv venv
  ok "venv created"
fi

echo ""

# ─── Step 3: Install dependencies ─────────────────────────────────────
echo -e "${BOLD}[3/5] Installing Python dependencies...${RESET}"
info "This may take 2-3 minutes on first run"

# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

ok "All packages installed"
echo ""

# ─── Step 4: Configure .env ───────────────────────────────────────────
echo -e "${BOLD}[4/5] Configuring environment...${RESET}"

if [ -f ".env" ]; then
  warn ".env already exists."
  read -r -p "  Overwrite it? [y/N] " OVERWRITE
  if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
    info "Keeping existing .env"
    SKIP_ENV=true
  else
    SKIP_ENV=false
  fi
else
  SKIP_ENV=false
fi

if [ "$SKIP_ENV" = false ]; then
  echo ""
  echo -e "  ${CYAN}Enter your configuration values.${RESET}"
  echo -e "  ${CYAN}Press Enter to accept defaults shown in [brackets].${RESET}"
  echo ""

  read -r -p "  Your name [You]: " YOUR_NAME
  YOUR_NAME="${YOUR_NAME:-You}"

  read -r -p "  GCP Project ID: " GCP_PROJECT_ID
  [ -z "$GCP_PROJECT_ID" ] && die "GCP_PROJECT_ID is required"

  while true; do
    read -r -p "  Supabase URL (https://xxxx.supabase.co): " SUPABASE_URL
    if [[ "$SUPABASE_URL" == https://*.supabase.co ]]; then
      break
    fi
    warn "Must start with https:// and end with .supabase.co — try again"
  done

  while true; do
    read -r -p "  Supabase Service Key (sb_secret_...): " SUPABASE_SERVICE_KEY
    if [[ "$SUPABASE_SERVICE_KEY" == sb_secret_* ]]; then
      break
    fi
    warn "Must start with sb_secret_ — try again"
  done

  cat > .env <<EOF
YOUR_NAME=${YOUR_NAME}
CUSTOM_SYSTEM_PROMPT=
GCP_PROJECT_ID=${GCP_PROJECT_ID}
GCP_LOCATION=us-central1
SUPABASE_URL=${SUPABASE_URL}
SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY}
EOF

  ok ".env written"
fi

echo ""

# ─── Step 5: Google Cloud auth ─────────────────────────────────────────
echo -e "${BOLD}[5/5] Google Cloud authentication...${RESET}"
echo ""
echo -e "  ${YELLOW}⚠  You need to authenticate with Google Cloud so the server can call${RESET}"
echo -e "  ${YELLOW}   Vertex AI (Gemini) on your behalf.${RESET}"
echo ""
read -r -p "  Run 'gcloud auth application-default login' now? [Y/n] " DO_AUTH
if [[ ! "$DO_AUTH" =~ ^[Nn]$ ]]; then
  gcloud auth application-default login
  ok "Google Cloud auth complete"
else
  warn "Skipped. Run this before starting the server:"
  echo "  gcloud auth application-default login"
fi

echo ""

# ─── SQL migration reminder ────────────────────────────────────────────
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║  IMPORTANT: Run the SQL migration in Supabase next       ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  1. Open your Supabase project → SQL Editor"
echo -e "  2. Paste and run ${CYAN}docs/migration.sql${RESET} (Section 1 for new users,"
echo -e "     Section 2 if migrating from ask-isaac)"
echo -e "  ${RED}Nothing will work until you do this.${RESET}"
echo ""

# ─── Done ─────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}✓ Setup complete!${RESET}"
echo ""
echo -e "  To ingest your writing:"
echo -e "    ${CYAN}cd backend${RESET}"
echo -e "    ${CYAN}python ingest.py --preview${RESET}               # preview Drive files"
echo -e "    ${CYAN}python ingest.py --source drive${RESET}          # ingest from Drive"
echo -e "    ${CYAN}python ingest.py --source local --path ~/folder${RESET}  # ingest local files"
echo ""
echo -e "  To start the server:"
echo -e "    ${CYAN}cd ${REPO_ROOT}/backend && source ../venv/bin/activate && uvicorn server:app --reload --port 8000${RESET}"
echo ""
echo -e "  Then open: ${CYAN}frontend/ask-you.html${RESET} in your browser"
echo ""
