#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-187.127.12.125}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/root/whatsapp-agent}"

SSH_OPTS=(
  -p "$REMOTE_PORT"
  -o StrictHostKeyChecking=accept-new
)

EXCLUDES=(
  --exclude='.git'
  --exclude='.venv'
  --exclude='.verify-venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
)

if [[ -n "${DEPLOY_PASSWORD:-}" ]]; then
  if command -v sshpass >/dev/null 2>&1; then
    SSH_BASE=(sshpass -p "$DEPLOY_PASSWORD" ssh "${SSH_OPTS[@]}")
  else
    echo "DEPLOY_PASSWORD foi definida, mas 'sshpass' não está instalado."
    echo "Instale sshpass ou remova DEPLOY_PASSWORD para autenticar manualmente."
    exit 1
  fi
else
  SSH_BASE=(ssh "${SSH_OPTS[@]}")
fi

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"

echo "==> Enviando arquivos para ${SSH_TARGET}:${REMOTE_DIR}"
tar czf - "${EXCLUDES[@]}" . | "${SSH_BASE[@]}" "$SSH_TARGET" "mkdir -p '$REMOTE_DIR' && tar xzf - -C '$REMOTE_DIR'"

echo "==> Ajustando docker-compose remoto (evitar bind 6379 em hosts já ocupados)"
"${SSH_BASE[@]}" "$SSH_TARGET" "python3 - <<'PY'
from pathlib import Path
p = Path('$REMOTE_DIR/docker-compose.yml')
text = p.read_text()
lines = text.splitlines()
out = []
in_redis = False
skip = 0
for i, line in enumerate(lines):
    if line.startswith('  redis:'):
        in_redis = True
        out.append(line)
        continue
    if in_redis and line.startswith('  ') and not line.startswith('    '):
        in_redis = False
    if in_redis and line.strip() == 'ports:' and i + 1 < len(lines) and '6379:6379' in lines[i + 1]:
        skip = 1
        continue
    if skip:
        skip -= 1
        continue
    out.append(line)
p.write_text('\n'.join(out) + '\n')
print('docker-compose atualizado')
PY"

echo "==> Subindo containers"
"${SSH_BASE[@]}" "$SSH_TARGET" "cd '$REMOTE_DIR' && docker compose down --remove-orphans || true"
"${SSH_BASE[@]}" "$SSH_TARGET" "cd '$REMOTE_DIR' && docker compose up -d --build"
"${SSH_BASE[@]}" "$SSH_TARGET" "cd '$REMOTE_DIR' && docker compose ps"

echo "==> Validando endpoints"
curl -fsS "http://${REMOTE_HOST}:8000/api/v1/health" && echo
curl -I -fsS "http://${REMOTE_HOST}:3001" | head -n 1

echo "Deploy finalizado com sucesso."
