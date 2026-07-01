#!/bin/bash
set -e

# ─── 3W Revamped — EC2 Deploy Script ────────────────────────────────────────
# Run this once after cloning onto a fresh EC2 instance (or to redeploy).
# After it completes, all services start automatically on every reboot via
# Docker's restart:always policy + the Docker systemd unit (enabled below).
# ─────────────────────────────────────────────────────────────────────────────

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Enabling Docker to start on boot..."
sudo systemctl enable docker
sudo systemctl start docker

echo "==> Building frontend..."
cd "$REPO_DIR/frontend"
npm ci
npm run build
cd "$REPO_DIR"

echo "==> Stopping any existing containers..."
cd "$REPO_DIR/infra"
docker-compose down --remove-orphans

echo "==> Building backend image..."
docker-compose build --no-cache backend

echo "==> Starting all services..."
docker-compose up -d

echo ""
echo "All done. Services:"
echo "  Frontend  : http://<your-ec2-ip>"
echo "  Backend   : http://<your-ec2-ip>/api/  (proxied via nginx)"
echo "  GeoServer : http://<your-ec2-ip>:8600/geoserver"
echo ""
echo "Next steps:"
echo "  1. Log in as admin and go to Data Management → Run ETL Pipeline"
echo "  2. Go to Data Management → Sync Knowledge Base"
echo ""
echo "Services will auto-start on every EC2 reboot (restart:always + Docker systemd unit)."
