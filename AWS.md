# AWS Deployment Guide — 3W Revamped (Testing)

This guide covers a single-instance test deployment on **Amazon Linux 2023** using EC2 + S3. The backend, frontend, Postgres, and GeoServer run via Docker Compose. Raw data is read from S3 and processed Parquet is written back to S3 — no data files accumulate on the EC2 disk.

---

## 1. S3 Bucket

The app reads raw vendor files from S3 and writes all processed Parquet output back to S3. Your bucket (`jejak-mappro-demo`) must already exist with the following prefix layout:

```
jejak-mappro-demo/
  3W-data/
    site-coverage-params/
      referenceData/        ← cell reference XLSB/XLSX
      locationData/         ← site & cell exports
    raw-network-data/       ← weekly xC/xD XLSB files
    train-ai-data/
      pdf-data/             ← RAG training PDFs
      excel-data/           ← RAG training Excel files
    processed/              ← ETL writes Parquet here (auto-created)
```

### IAM Role (recommended over access keys)

1. Go to **IAM → Roles → Create role → EC2**
2. Attach an inline policy scoped to your bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::jejak-mappro-demo",
        "arn:aws:s3:::jejak-mappro-demo/*"
      ]
    }
  ]
}
```

3. Attach this role to the EC2 instance (step 2). With the role attached, you do **not** need to set `AWS_ACCESS_KEY` or `AWS_SECRET_KEY` in `.env` — boto3 and DuckDB will pick up credentials from the instance metadata automatically.

---

## 2. EC2 Instance

### Recommended specs (testing)

| Setting | Value |
|---------|-------|
| **AMI** | Amazon Linux 2023 (latest) — x86_64 or ARM64 (Graviton) |
| **Instance type** | `t4g.medium` (ARM/Graviton, 2 vCPU, 4 GB RAM, ~20% cheaper) or `t3.medium` (x86_64) — Ollama removed, so 4 GB is sufficient |
| **Storage** | 30 GB gp3. Raw files are staged to `/tmp` and deleted after each ETL stage; Parquet lives in S3. |
| **Key pair** | Create new `.pem`, save it |
| **IAM role** | Attach the role from step 1 |

> **Why t3.medium?** Ollama is gone — we no longer host LLM weights locally. The stack is now: FastAPI backend (~200 MB), PostgreSQL (~300 MB), GeoServer (~1 GB heap). 4 GB is comfortable for testing.

### Security Group (inbound rules)

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP only | SSH |
| 80 | TCP | 0.0.0.0/0 | Frontend (nginx) |
| 8000 | TCP | Your IP only | Backend API (optional — proxied via nginx) |
| 8600 | TCP | Your IP only | GeoServer |

> Postgres (5432) should never be exposed publicly. MinIO is no longer needed on the instance — S3 handles object storage directly.

### Launch the instance

1. Review and launch. Wait for **Instance State: Running**.
2. Assign an **Elastic IP** so the address doesn't change on restart.

---

## 3. Connect & Prepare the Instance

```bash
# From your laptop
chmod 400 your-key.pem
ssh -i your-key.pem ec2-user@<EC2-PUBLIC-IP>
```

> Amazon Linux 2023 uses `ec2-user`, not `ubuntu`.

### Install Docker

```bash
# Update packages
sudo dnf update -y

# Install Docker
sudo dnf install -y docker

# Start Docker and enable it on reboot
sudo systemctl start docker
sudo systemctl enable docker

# Add ec2-user to the docker group (avoids sudo on every command)
sudo usermod -aG docker ec2-user
newgrp docker

# Install Docker Compose standalone binary
# Use aarch64 for Graviton (t4g/m7g/c7g) or x86_64 for Intel/AMD (t3/m6i/c6i)
ARCH=$(uname -m)   # prints aarch64 or x86_64
sudo curl -SL "https://github.com/docker/compose/releases/download/v2.29.2/docker-compose-linux-${ARCH}" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify
docker --version
docker-compose version
```

### Install Node.js (for the frontend build step)

```bash
# Amazon Linux 2023 — use the nodesource binary
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs
node --version   # should be 22.x
```

### Install Git

```bash
sudo dnf install -y git
```

---

## 4. Upload the Project

**Option A — Git (recommended)**
```bash
git clone https://github.com/YOUR_ORG/3w-revamped.git
cd 3w-revamped
```

**Option B — SCP from your laptop**
```bash
# From your laptop — zip first to speed up transfer
zip -r 3w-revamped.zip 3w-revamped/ \
  --exclude "*/node_modules/*" \
  --exclude "*/__pycache__/*" \
  --exclude "*/dist/*" \
  --exclude "*/.venv/*"

scp -i your-key.pem 3w-revamped.zip ec2-user@<EC2-PUBLIC-IP>:~

# Then on EC2:
unzip 3w-revamped.zip
cd 3w-revamped
```

---

## 5. Data Setup

With `USE_REAL_S3=true`, **no data files need to be copied to EC2**. The ETL pipeline reads raw files from S3 and writes processed Parquet back to S3. The only step is making sure your raw files are in the right S3 prefixes (see step 1).

To trigger the ETL after deployment, go to **Data Management** in the app UI (admin login required) and click **Run ETL Pipeline**. This streams each raw file from S3, processes it, and writes Parquet output back to S3 — peak disk usage on EC2 is one raw file in `/tmp` at a time (~167 MB max).

To sync the AI knowledge base from S3 training data, click **Sync Knowledge Base** in the same panel.

---

## 6. Configure Environment

```bash
cd ~/3w-revamped/backend
cp .env.example .env
nano .env
```

Fill in the required values:

```env
# PostgreSQL — used by the backend for users, chat, annotations, pricing
POSTGRES_DSN=postgresql+psycopg://threew:change_me@localhost:5432/threew

# JWT — generate with: openssl rand -hex 32
JWT_SECRET=paste_output_here

# Claude AI — required. Get from console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# S3 — USE_REAL_S3=true activates S3-native ETL and Parquet storage.
# With an IAM role attached to the EC2 instance, leave AWS_ACCESS_KEY
# and AWS_SECRET_KEY blank — credentials come from instance metadata.
USE_REAL_S3=true
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY=
AWS_SECRET_KEY=

# Bucket layout — matches jejak-mappro-demo structure
S3_BUCKET=jejak-mappro-demo
S3_CELL_REF_PREFIX=3W-data/site-coverage-params/referenceData/
S3_LOCATION_DATA_PREFIX=3W-data/site-coverage-params/locationData/
S3_NETWORK_DATA_PREFIX=3W-data/raw-network-data/
S3_TRAIN_EXCEL_PREFIX=3W-data/train-ai-data/excel-data/
S3_TRAIN_PDF_PREFIX=3W-data/train-ai-data/pdf-data/
S3_PROCESSED_PREFIX=3W-data/processed/

# CORS — set to your EC2 public IP or domain
CORS_ORIGINS=["http://<EC2-PUBLIC-IP>"]

# GeoServer (optional — map still works without it)
GEOSERVER_URL=http://localhost:8600/geoserver

# DuckDB + local dirs (used even in S3 mode for the DuckDB catalog file
# and temp working space — these paths stay on disk)
DUCKDB_PATH=./data/analytics.duckdb
PARQUET_DIR=./data/parquet
RAW_DATA_DIR=./data/raw
```

Generate a strong JWT secret:
```bash
openssl rand -hex 32
```

---

## 7. Deploy

```bash
cd ~/3w-revamped
chmod +x deploy.sh
./deploy.sh
```

This script:
1. Enables Docker to auto-start on reboot (`sudo systemctl enable docker`)
2. Runs `npm ci && npm run build` for the frontend
3. Builds the backend Docker image
4. Runs Alembic migrations (`alembic upgrade head`) — creates all tables including `knowledge_chunks` with its FTS index
5. Brings up all services with `docker-compose up -d`

First run takes **5–10 minutes** (pulling images, building, npm install). Subsequent deploys are faster.

---

## 8. Verify Everything Is Up

```bash
docker-compose -f infra/docker-compose.yml ps
```

All containers should show `Up`. Then visit:

| Service | URL |
|---------|-----|
| App (frontend) | `http://<EC2-IP>` |
| Backend API docs | `http://<EC2-IP>/api/docs` |
| GeoServer | `http://<EC2-IP>:8600/geoserver/web` |

---

## 9. Useful Commands

```bash
# View live logs for all services
docker-compose -f infra/docker-compose.yml logs -f

# View logs for one service
docker-compose -f infra/docker-compose.yml logs -f backend

# Restart a single service after a code change
docker-compose -f infra/docker-compose.yml restart backend

# Full redeploy after code changes
cd ~/3w-revamped && ./deploy.sh

# Free disk space (prune old Docker images)
docker image prune -f

# Check disk usage — should stay low since Parquet lives in S3
df -h

# Confirm ETL is writing to S3 (list processed Parquet files)
aws s3 ls s3://jejak-mappro-demo/3W-data/processed/ --region ap-southeast-1

# Run Alembic migrations manually (if needed)
docker-compose -f infra/docker-compose.yml exec backend alembic upgrade head

# Check backend environment variables are loaded correctly
docker-compose -f infra/docker-compose.yml exec backend env | grep -E "USE_REAL_S3|S3_BUCKET|ANTHROPIC"
```

---

## 10. Redeploy After Code Changes

```bash
cd ~/3w-revamped
git pull
./deploy.sh
```

---

## Troubleshooting

**ETL fails with S3 permission error**
```bash
# Confirm the IAM role is attached and has S3 access
aws sts get-caller-identity
aws s3 ls s3://jejak-mappro-demo/3W-data/ --region ap-southeast-1
```

**DuckDB can't read from S3**
Make sure `USE_REAL_S3=true` is set. DuckDB httpfs uses `SET s3_use_credential_chain=true` when no explicit keys are provided — this requires the instance to have an IAM role attached.

**Backend won't start — "ANTHROPIC_API_KEY is not set"**
`ANTHROPIC_API_KEY` is required. There is no Ollama fallback. Set it in `.env` and restart: `docker-compose -f infra/docker-compose.yml restart backend`.

**Port 80 not reachable**
Check your EC2 Security Group — inbound rule for port 80 from `0.0.0.0/0` must be present.

---

## Notes for Company Infra Migration

When moving from this test instance to production:

| Component | Test (this guide) | Production recommendation |
|-----------|-------------------|---------------------------|
| Database | Postgres in Docker | Amazon RDS PostgreSQL |
| Object storage | AWS S3 (already in use) | No change needed |
| Frontend | nginx on EC2 | S3 static hosting + CloudFront CDN |
| Backend | Docker on EC2 | ECS Fargate behind an ALB |
| Secrets | `.env` file | AWS Secrets Manager or SSM Parameter Store |
| Instance | Single t3.medium | Auto-scaling group behind ALB |
| GeoServer | Docker on EC2 | Keep on EC2 or dedicated instance |
