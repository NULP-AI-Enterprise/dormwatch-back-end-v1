
# Схема деплою — thesis-i.com Kubernetes кластер

Цей документ описує **єдиний правильний спосіб** розгорнути сервіс на кластері.  
Читай його перед тим як писати будь-який Dockerfile, k8s-маніфест або CI workflow.

---

## 1. Огляд інфраструктури

```
GitHub (source) ──push──► GitHub Actions (build)
                                │
                           GHCR image (ghcr.io/nulp-ai-enterprise/<repo>:sha-XXXXXXX)
                                │
                       ArgoCD auto-sync (watches k8s/)
                                │
                    Kubernetes кластер (nulp-k8s-2)
                         IP: 100.107.206.16:6443
                                │
                    Traefik Ingress ──► *.thesis-i.com
```

**Компоненти кластера:**
| Компонент | Namespace | Призначення |
|-----------|-----------|-------------|
| ArgoCD | `argocd` | GitOps auto-sync з GitHub |
| Sealed Secrets (bitnami) | `kube-system` | Шифрування секретів у Git |
| Traefik | `kube-system` | Ingress controller + TLS |

**Існуючі сервіси:**
| Сервіс | Namespace | Домен | GHCR image |
|--------|-----------|-------|------------|
| FastAPI backend | `zzk-register` | `zzk-registr.thesis-i.com` | `ghcr.io/nulp-ai-enterprise/zzk-rep-back` |
| Next.js frontend | `zzk-front` | `zzk.thesis-i.com` | `ghcr.io/nulp-ai-enterprise/zzk-rep-front` |

**Внутрішня адреса між сервісами:**
```
http://<service-name>.<namespace>.svc.cluster.local:<port>
# Приклад: http://zzk-register.zzk-register.svc.cluster.local:8000
```

---

## 2. Структура репозиторію

```
my-service/
├── Dockerfile
├── k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── secret.yaml          ← локально, в .gitignore
│   ├── sealed-secret.yaml   ← комітити
│   └── argocd-app.yaml
└── .github/
    └── workflows/
        └── docker-build.yml
```

`.gitignore` обов'язково:
```
k8s/secret.yaml
```

---

## 3. Dockerfile

### Next.js (App Router, output: standalone)

```dockerfile
# Stage 1: deps
FROM node:22-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile

# Stage 2: builder
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
RUN npm run build

# Stage 3: runner
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs
COPY --from=builder /app/public              ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

`next.config.ts` обов'язково:
```ts
const nextConfig: NextConfig = {
  output: "standalone",
  typescript: { ignoreBuildErrors: true },
};
```

### Python / FastAPI

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

**Правила для будь-якого Dockerfile:**
- Ніколи не копіювати `.env` файли
- Секрети передаються через env vars з k8s Secret (не build args)
- Health check endpoint обов'язковий (`/api/health` або `/health`)
- Образ має запускатись від non-root користувача

---

## 4. Kubernetes маніфести

### namespace.yaml
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-service
  labels:
    app.kubernetes.io/managed-by: argocd
```

### deployment.yaml
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
  namespace: my-service
  labels:
    app: my-service
spec:
  replicas: 1
  strategy:
    type: Recreate          # для stateful або single-replica — завжди Recreate
  selector:
    matchLabels:
      app: my-service
  template:
    metadata:
      labels:
        app: my-service
    spec:
      containers:
        - name: my-service
          # CI автоматично оновлює цей тег після кожного push
          image: ghcr.io/nulp-ai-enterprise/my-service:sha-XXXXXXX
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 3000   # або 8000 для Python
          env:
            - name: NODE_ENV
              value: production
            - name: MY_SECRET_VAR
              valueFrom:
                secretKeyRef:
                  name: my-service-secret
                  key: MY_SECRET_VAR
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 1000m
              memory: 512Mi
          startupProbe:
            httpGet:
              path: /api/health
              port: 3000
            failureThreshold: 12   # 12×10s = 2 хв на старт
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /api/health
              port: 3000
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /api/health
              port: 3000
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
      imagePullSecrets:
        - name: ghcr-secret    # існує в кожному namespace — створити вручну один раз
```

**Створити `ghcr-secret` в новому namespace (один раз вручну):**
```bash
kubectl create secret docker-registry ghcr-secret \
  --namespace=my-service \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<github-pat-with-read-packages>
```

### service.yaml
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
  namespace: my-service
spec:
  type: ClusterIP
  selector:
    app: my-service
  ports:
    - name: http
      port: 3000        # або 8000
      targetPort: http
```

### ingress.yaml
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-service
  namespace: my-service
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web,websecure
spec:
  ingressClassName: traefik
  rules:
    - host: my-service.thesis-i.com   # субдомен thesis-i.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-service
                port:
                  number: 3000
```

### secret.yaml (локальний шаблон, не комітити)
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-service-secret
  namespace: my-service
type: Opaque
stringData:
  DATABASE_URL: "postgresql+asyncpg://user:pass@host/db"
  MY_SECRET_VAR: "value"
```

### sealed-secret.yaml (генерується, комітити)
```bash
# Переконайся що kubeconfig вказує на правильний кластер:
kubectl config set-cluster nulp-k8s-2 --server=https://100.107.206.16:6443

# Запечатати:
kubeseal --format yaml --controller-name=sealed-secrets-controller --controller-namespace=kube-system < k8s/secret.yaml > k8s/sealed-secret.yaml
```

### argocd-app.yaml (реєструє сервіс в ArgoCD, застосовується один раз)
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-service
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/NULP-AI-Enterprise/my-service-repo.git
    targetRevision: main
    path: k8s/
  destination:
    server: https://kubernetes.default.svc
    namespace: my-service
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  ignoreDifferences:
    - group: bitnami.com
      kind: SealedSecret
      jsonPointers:
        - /spec/encryptedData
```

**Застосувати один раз:**
```bash
kubectl apply -f k8s/argocd-app.yaml
```

---

## 5. GitHub Actions CI workflow

```yaml
name: Build & Push Docker image

on:
  workflow_dispatch:
  push:
    branches: [main, master]
    paths:
      - "app/**"
      - "components/**"
      - "lib/**"
      - "Dockerfile"
      - "package.json"
      - "package-lock.json"
      # для Python: "**/*.py", "requirements.txt"

env:
  REGISTRY: ghcr.io
  IMAGE:    ghcr.io/nulp-ai-enterprise/my-service

jobs:
  # Опціонально: typecheck для TypeScript проектів
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - run: npm ci --frozen-lockfile
      - run: npx next typegen    # генерує next-env.d.ts (Next.js обов'язково)
        env:
          BACKEND_URL: "http://localhost:8000"
      - run: npx tsc --noEmit

  build-and-push:
    runs-on: ubuntu-latest
    needs: typecheck             # видалити якщо typecheck не потрібен
    permissions:
      contents: write            # щоб писати в deployment.yaml
      packages: write            # щоб пушити в GHCR

    steps:
      - uses: actions/checkout@v4

      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/setup-buildx-action@v3

      - name: Generate image tags
        id: meta
        run: |
          SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-7)
          echo "sha_tag=sha-${SHORT_SHA}" >> "$GITHUB_OUTPUT"

      - name: Build & push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ steps.meta.outputs.sha_tag }}
            ${{ env.IMAGE }}:latest
          cache-from: type=gha
          cache-to:   type=gha,mode=max

      - name: Pin image SHA in deployment.yaml
        run: |
          TAG="${{ steps.meta.outputs.sha_tag }}"
          sed -i "s|image: ${{ env.IMAGE }}:.*|image: ${{ env.IMAGE }}:${TAG}|g" k8s/deployment.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add k8s/deployment.yaml
          git diff --staged --quiet || git commit -m "ci: pin image to ${TAG} [skip ci]"
          git push
```

**Важливо:** `[skip ci]` в повідомленні CI-коміту запобігає нескінченному циклу збірки.

---

## 6. Типовий workflow нового сервісу (покрокова інструкція)

```bash
# 1. Створити репозиторій на GitHub в організації NULP-AI-Enterprise

# 2. Підготувати файли (Dockerfile, k8s/, .github/workflows/, .gitignore)

# 3. Заповнити k8s/secret.yaml (НЕ комітити)

# 4. Запечатати секрет
kubectl config set-cluster nulp-k8s-2 --server=https://100.107.206.16:6443
kubeseal --format yaml --controller-name=sealed-secrets-controller --controller-namespace=kube-system < k8s/secret.yaml > k8s/sealed-secret.yaml

# 5. Створити ghcr-secret в namespace (один раз)
kubectl create namespace my-service
kubectl create secret docker-registry ghcr-secret \
  --namespace=my-service \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<github-pat>

# 6. Зареєструвати в ArgoCD (один раз)
kubectl apply -f k8s/argocd-app.yaml

# 7. Закомітити і запушити — CI збере образ і оновить deployment.yaml
git add . && git commit -m "feat: initial deployment" && git push

# 8. ArgoCD автоматично задеплоїть протягом ~2 хв
# Перевірити: kubectl get pods -n my-service
```

---

## 7. Чеклист перед пушем

- [ ] `k8s/secret.yaml` є в `.gitignore`
- [ ] `k8s/sealed-secret.yaml` згенеровано і закомічено
- [ ] `k8s/argocd-app.yaml` вказує правильний `repoURL` і `namespace`
- [ ] `ghcr-secret` існує в namespace кластера
- [ ] Health endpoint повертає 200 (`/api/health`)
- [ ] `deployment.yaml` має `imagePullSecrets: [{name: ghcr-secret}]`
- [ ] `ingress.yaml` використовує `ingressClassName: traefik`
- [ ] CI workflow має `permissions: contents: write, packages: write`

---

## 8. Діагностика

```bash
# Стан подів
kubectl get pods -n my-service

# Логи
kubectl logs -n my-service deploy/my-service --tail=100

# Опис поду (ImagePullBackOff, CrashLoopBackOff тощо)
kubectl describe pod -n my-service -l app=my-service

# ArgoCD статус
kubectl get application my-service -n argocd

# Перевірити секрет
kubectl get secret my-service-secret -n my-service

# Переконатись що kubeconfig вказує правильно
kubectl cluster-info
# має показати: https://100.107.206.16:6443
# якщо ні — виправити:
kubectl config set-cluster nulp-k8s-2 --server=https://100.107.206.16:6443
```

**Поширені помилки:**
| Симптом | Причина | Виправлення |
|---------|---------|-------------|
| `ImagePullBackOff` | `ghcr-secret` відсутній або в неправильному namespace | `kubectl create secret docker-registry ghcr-secret --namespace=my-service ...` |
| `i/o timeout` при kubeseal | kubeconfig вказує старий IP кластера | `kubectl config set-cluster nulp-k8s-2 --server=https://100.107.206.16:6443` |
| CI не тригериться | файли не входять в `paths:` фільтр | додати потрібний glob в `paths:` або запустити `workflow_dispatch` |
| Стара версія після деплою | CI-коміт не був запушений локально перед пушем | `git pull --rebase origin main && git push` |
| `[rejected] fetch first` при пуші | CI-бот запінував SHA поки ти працював | `git pull --rebase origin main && git push` |
