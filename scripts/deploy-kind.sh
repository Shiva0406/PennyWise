#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker is required"; exit 1; }
command -v kind >/dev/null || { echo "Kind is required"; exit 1; }
command -v kubectl >/dev/null || { echo "kubectl is required"; exit 1; }
docker build -t splitwise-backend:1.0.0 ./backend
docker build -t splitwise-frontend:1.0.0 ./frontend
kind get clusters | grep -qx splitwise || kind create cluster --name splitwise --config kind/kind-config.yaml
kind load docker-image splitwise-backend:1.0.0 --name splitwise
kind load docker-image splitwise-frontend:1.0.0 --name splitwise
kubectl apply -k k8s/overlays/kind
kubectl rollout status deployment/backend -n splitwise --timeout=240s
kubectl rollout status deployment/frontend -n splitwise --timeout=240s
echo "App: http://localhost:30080"
echo "Grafana: http://localhost:30300 (admin/admin123)"
