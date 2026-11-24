#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then cp .env.example .env; echo "Created .env; review passwords before continuing."; fi
docker compose up -d --build
echo "App:        http://localhost:3000"
echo "API docs:   http://localhost:8000/docs"
echo "Prometheus: http://localhost:9090"
echo "Grafana:    http://localhost:3001 (admin/admin123)"
