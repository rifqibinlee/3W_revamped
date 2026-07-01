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
docker compose down --remove-orphans

echo "==> Building backend image..."
docker compose build --no-cache backend

echo "==> Starting all services..."
docker compose up -d

echo ""
echo "All done. Services and their ports:"
echo "  Frontend (nginx) : http://<your-ec2-ip>:80"
echo "  Backend (API)    : http://<your-ec2-ip>:8000  (internal, proxied via /api/)"
echo "  MinIO console    : http://<your-ec2-ip>:9001"
echo "  GeoServer        : http://<your-ec2-ip>:8600/geoserver"
echo "  Metabase         : http://<your-ec2-ip>:3001"
echo ""
echo "Services will auto-start on every EC2 reboot (restart:always + Docker systemd unit)."
