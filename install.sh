#!/usr/bin/env bash
# Investimentos Manual — first-time setup

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

color() { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info() { echo "$(color 36 '[~]') $*"; }
ok()   { echo "$(color 32 '[+]') $*"; }
warn() { echo "$(color 33 '[!]') $*"; }
fail() { echo "$(color 31 '[x]') $*" >&2; exit 1; }

info "Setup completo do Investimentos Manual"

# Refuse to run on a filesystem that strips +x (e.g. NTFS via ntfs-3g) —
# Next.js 16 / Turbopack and venv shims need executable bits.
FS_TYPE="$(stat -f -c '%T' "$PROJECT_DIR" 2>/dev/null || echo "?")"
if [ "$FS_TYPE" = "fuseblk" ] || [ "$FS_TYPE" = "ntfs" ]; then
  warn "Projeto está em filesystem $FS_TYPE (NTFS-like)."
  warn "Next.js 16 e venv exigem bits +x — mova o projeto para ext4."
  warn "Sugestão: cp -r \"$PROJECT_DIR\" ~/investimentos_manual && cd ~/investimentos_manual && ./install.sh"
  exit 2
fi

# 1. Python
command -v python3 >/dev/null 2>&1 || fail "Instale python3.11+ antes (sudo apt install python3.11 python3.11-venv)"

# 2. pnpm
if ! command -v pnpm >/dev/null 2>&1; then
  warn "pnpm não encontrado. Instalando via npm..."
  command -v npm >/dev/null 2>&1 || fail "npm não encontrado (sudo apt install nodejs npm)"
  npm install -g pnpm
fi

# 3. venv + deps Python
if [ ! -x ".venv/bin/python" ]; then
  info "Criando virtualenv"
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
touch .venv/.deps_installed
ok "Python deps prontas"

# 4. frontend deps
(cd frontend && pnpm install)
ok "Frontend deps prontas"

# 5. .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  ok ".env criado a partir do .env.example"
fi

# 6. Desktop shortcut
# Resolve the real localized Desktop dir (e.g. ~/Secretária in pt) via XDG.
if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
else
  DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
fi
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"

# Exec must be Desktop-Entry-spec compliant (no bare ;/&&/quotes). A login
# shell loads PATH so pnpm/claude resolve; start.sh cd's to itself and blocks.
cat > "$APPS_DIR/investimentos-manual.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Assay
GenericName=Finanças e investimentos
Comment=Finanças pessoais e comitê de aportes, tudo local
Exec=bash --login -c "$PROJECT_DIR/start.sh"
Path=$PROJECT_DIR
Icon=$PROJECT_DIR/frontend/public/icon.svg
Terminal=true
Categories=Finance;Office;
Keywords=investimentos;aporte;carteira;claude;
StartupNotify=true
EOF
chmod +x "$APPS_DIR/investimentos-manual.desktop"
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$APPS_DIR" 2>/dev/null || true
ok "Atalho criado em $APPS_DIR/investimentos-manual.desktop"

install_desktop_copy() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  cp "$APPS_DIR/investimentos-manual.desktop" "$dir/Investimentos Manual.desktop"
  chmod +x "$dir/Investimentos Manual.desktop"
  command -v gio >/dev/null 2>&1 && \
    gio set "$dir/Investimentos Manual.desktop" metadata::trusted true 2>/dev/null || true
  ok "Atalho duplo-clicável em $dir/"
}
install_desktop_copy "$DESKTOP_DIR"
[ "$DESKTOP_DIR" != "$HOME/Desktop" ] && install_desktop_copy "$HOME/Desktop"

cat <<BANNER

$(color 32 '✓ Setup concluído!')

  Para iniciar:
    · Clique no atalho $(color 36 'Investimentos Manual') no Desktop
    · Ou rode no terminal: $(color 36 './start.sh')

  Antes do primeiro ciclo:
    1. Cadastre seus ativos atuais em $(color 36 '/ativos')
    2. Em outro terminal, rode: $(color 36 'claude --dangerously-skip-permissions')
       (Opus 4.7 + max reasoning)
    3. Volte ao app, clique $(color 36 'Novo aporte') e siga os 3 prompts

BANNER
