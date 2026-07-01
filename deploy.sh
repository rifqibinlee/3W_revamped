#!/bin/bash
set -euo pipefail

# ─── 3W Revamped — EC2 Deploy Script ─────────────────────────────────────────
# Amazon Linux 2023, ARM (Graviton / t4g). Run once after cloning, or any time
# you want to redeploy. After completion all services auto-start on every reboot
# via Docker's restart:always policy + the Docker systemd unit enabled below.
# ─────────────────────────────────────────────────────────────────────────────

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/backend/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy backend/.env.example and fill it in first." >&2
  exit 1
fi

echo "==> Enabling Docker to start on boot..."
sudo systemctl enable docker
sudo systemctl start docker

echo "==> Adding ec2-user to docker group (takes effect on next login)..."
sudo usermod -aG docker ec2-user || true

echo "==> Building frontend..."
cd "$REPO_DIR/frontend"
npm ci --prefer-offline
npm run build
cd "$REPO_DIR"

echo "==> Stopping any existing containers..."
cd "$REPO_DIR/infra"
docker-compose --env-file "$ENV_FILE" down --remove-orphans 2>/dev/null || true

echo "==> Building backend image..."
docker-compose --env-file "$ENV_FILE" build --no-cache backend

echo "==> Starting all services..."
docker-compose --env-file "$ENV_FILE" up -d

echo "==> Waiting for backend to become healthy..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:5000/api/health" >/dev/null 2>&1; then
    echo "    Backend is up."
    break
  fi
  echo "    Waiting ($i/30)..."
  sleep 3
done

echo ""
echo "All done."
echo ""
echo "  App URL  : http://$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<ec2-ip>'):5000"
echo "  Health   : http://$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<ec2-ip>'):5000/api/health"
echo ""
echo "Next steps:"
echo "  1. Log in as super_admin and go to Data Management → Run ETL Pipeline"
echo "  2. Go to Data Management → Sync Knowledge Base"
echo "  3. Tail logs:  docker-compose --env-file backend/.env -f infra/docker-compose.yml logs -f"
