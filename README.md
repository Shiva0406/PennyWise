# Splitwise Lab — Full-stack Expense Sharing App

A beginner-friendly Splitwise-style learning project: React + FastAPI + MySQL, Docker Compose, Kubernetes on Kind, deployment strategies, Argo CD, Prometheus and Grafana.

## Features
- Register/login with JWT authentication
- Create groups and add members
- Add shared expenses with equal splitting between group members
- View group expenses and who owes whom (net balances)
- Record settlements
- Responsive dashboard with a clean, modern interface
- Backend health and Prometheus metrics endpoints

> Learning project note: this is a practical lab, not a production financial system. Use test credentials and do not expose MySQL publicly.

## Architecture

```text
Browser :3000
   |
   v
React + Nginx frontend
   |
   | /api/* (Nginx proxy)
   v
FastAPI backend :8000 ---- MySQL :3306
   |
   +---- /metrics (Prometheus)
                 |
             Prometheus :9090
                 |
              Grafana :3001
```

## 1. Run locally with Docker Compose (recommended first)

Requirements: Docker Engine + Docker Compose plugin.

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Open:
- App: http://localhost:3000
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/health
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin / admin123)

Register a user, create a group, add another registered user's email as a member, then add expenses.

Stop without deleting data:
```bash
docker compose down
```
Delete containers and database volume (destructive):
```bash
docker compose down -v
```

## 2. Deploy to Kind on Ubuntu EC2

### EC2 prerequisites
Recommended lab instance: Ubuntu 22.04/24.04, 2 vCPU and 4–8 GiB RAM. Install Docker, kubectl, Kind, Helm (optional), and Git.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker

ARCH="$(dpkg --print-architecture)"
curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-${ARCH}"
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

If Docker group membership was just changed, reconnect SSH if `docker ps` still says permission denied.

### Build images on the EC2 host and load into Kind
Edit `k8s/overlays/kind/kustomization.yaml` if you change image tags.

```bash
docker build -t splitwise-backend:1.0.0 ./backend
docker build -t splitwise-frontend:1.0.0 ./frontend
kind create cluster --name splitwise --config kind/kind-config.yaml
kind load docker-image splitwise-backend:1.0.0 --name splitwise
kind load docker-image splitwise-frontend:1.0.0 --name splitwise
kubectl apply -k k8s/overlays/kind
kubectl get pods -n splitwise -w
```

Access from your laptop through an SSH tunnel (recommended):
```bash
# Run on your laptop; replace EC2_PUBLIC_IP and key path
ssh -i your-key.pem -L 3000:127.0.0.1:30080 -L 3001:127.0.0.1:30300 ubuntu@EC2_PUBLIC_IP
```
Then browse http://localhost:3000 and http://localhost:3001. The Kind config maps host ports 30080 and 30300. If you want direct public access instead, configure the EC2 security group and host firewall deliberately; do not expose database port 3306.

### EC2 security group ports
| Port | Source | Purpose |
|---|---|---|
| 22/TCP | Your public IP only | SSH |
| 30080/TCP | Prefer SSH tunnel; otherwise your trusted IP only | App NodePort |
| 30300/TCP | Prefer SSH tunnel; otherwise your trusted IP only | Grafana NodePort |
| 3306/TCP | **Do not open** | MySQL stays internal |
| 8000/TCP, 9090/TCP | **Do not open** | Internal API/Prometheus; use port-forward if needed |

Kind is a local learning cluster, not a production managed Kubernetes cluster.

## 3. Kubernetes deployment
The base manifests create namespace, MySQL StatefulSet + PVC, backend Deployment/Service, frontend Deployment/Service, and monitoring.

```bash
kubectl apply -k k8s/overlays/kind
kubectl get all -n splitwise
kubectl get pvc -n splitwise
kubectl port-forward -n splitwise svc/backend 8000:8000
```

For browser access use the NodePort 30080 via the SSH tunnel above.

## 4. Practice deployment strategies

These are separate exercises. Do one at a time and inspect rollout status/events.

### Rolling update (default Deployment strategy)
```bash
kubectl apply -f k8s/strategies/rolling/backend-deployment.yaml
kubectl rollout status deployment/backend -n splitwise
kubectl set image deployment/backend backend=splitwise-backend:1.0.1 -n splitwise
kubectl rollout history deployment/backend -n splitwise
kubectl rollout undo deployment/backend -n splitwise
```
Build/load 1.0.1 first if testing a real new image.

### Recreate
```bash
kubectl apply -f k8s/strategies/recreate/backend-deployment.yaml
kubectl describe deployment backend -n splitwise
```
Recreate terminates old Pods before creating new ones, causing downtime.

### Blue/Green
```bash
kubectl apply -f k8s/strategies/blue-green/
kubectl get svc app-live -n splitwise -o yaml
# Switch traffic by changing selector version: blue -> green
kubectl patch svc app-live -n splitwise -p '{"spec":{"selector":{"app":"strategy-demo","version":"green"}}}'
# Roll back:
kubectl patch svc app-live -n splitwise -p '{"spec":{"selector":{"app":"strategy-demo","version":"blue"}}}'
```
Blue/green is illustrated with tiny nginx demo Pods to avoid disrupting the main application.

### Canary
```bash
kubectl apply -f k8s/strategies/canary/
kubectl get pods -n splitwise -l app=canary-demo
```
The canary service selects both stable and canary Pods. Replica counts are a teaching approximation of traffic weighting; Kubernetes Services do not guarantee exact percentages. For production-grade weighted routing use an ingress/service mesh that supports it.

## 5. Argo CD GitOps
1. Push this project to your Git repository.
2. Update `argocd/application.yaml` `repoURL` and `targetRevision`.
3. Install Argo CD:
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
kubectl apply -f argocd/application.yaml
kubectl port-forward svc/argocd-server -n argocd 8080:443
```
Open https://localhost:8080. Initial password:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
```
Login user `admin`. Change the password after first login. Argo CD syncs `k8s/overlays/kind` from Git. For private repositories, configure repository credentials in Argo CD.

## 6. Prometheus and Grafana
The K8s monitoring overlay deploys Prometheus with a scrape config for the backend `/metrics`, and Grafana with a provisioned Prometheus datasource.
```bash
kubectl port-forward -n splitwise svc/prometheus 9090:9090
kubectl port-forward -n splitwise svc/grafana 3001:3000
```
Grafana login: admin / admin123. Change it for anything beyond a disposable lab.

## 7. Useful troubleshooting
```bash
kubectl get pods,svc,pvc -n splitwise
kubectl describe pod POD_NAME -n splitwise
kubectl logs deployment/backend -n splitwise
kubectl logs deployment/frontend -n splitwise
kubectl get events -n splitwise --sort-by=.lastTimestamp
docker compose logs -f backend
docker compose logs -f mysql
```
- `ImagePullBackOff`: ensure image name/tag matches and image is loaded into Kind; use `imagePullPolicy: IfNotPresent`.
- Backend cannot connect to DB: check `MYSQL_HOST=mysql` in Compose and `mysql` Service name in Kubernetes; wait for MySQL readiness.
- Frontend API errors: frontend Nginx proxies `/api/` to backend Service; do not set browser API URL to `localhost:8000` in a container.
- PVC Pending: check Kind storage provisioner and `kubectl describe pvc`.
- Never put real passwords in Git. Kubernetes Secret values here are lab placeholders; use a secret manager for real environments.

## Folder map
```text
splitwise-lab/
├── backend/                 # FastAPI, SQLAlchemy, JWT, metrics
├── frontend/                # React + Vite + Nginx
├── docker-compose.yml
├── .env.example
├── scripts/                  # One-command Compose, Kind and prerequisites\n├── kind/kind-config.yaml
├── k8s/                     # app + monitoring manifests, Kustomize
├── k8s/strategies/           # rolling, recreate, blue/green, canary labs
└── argocd/application.yaml
```
# PennyWise
