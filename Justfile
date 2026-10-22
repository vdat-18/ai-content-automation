set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

compose := "docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.observability.yaml -f deploy/compose.langfuse.yaml -f deploy/compose.debug.yaml"
profiles := "--profile observability --profile langfuse --profile debug"
stack := compose + " " + profiles

# Show the available local development commands.
default:
    @just --list

# Validate the merged Compose configuration.
config:
    {{ stack }} config --quiet

# Build and start the complete local stack, including debug UIs.
up: config && urls
    {{ stack }} up -d --build

# Start the existing local images without rebuilding them.
start: config && urls
    {{ stack }} up -d

# Rebuild only the shared Python application image and recreate its services.
rebuild-backend: config
    {{ stack }} up -d --build migrate api outbox-publisher worker

# Rebuild only the Dashboard image and recreate its service.
rebuild-frontend: config
    {{ stack }} up -d --build frontend

# Stop the complete local stack while preserving named volumes.
down:
    {{ stack }} down

# Show container and health status for the complete local stack.
ps:
    {{ stack }} ps

# Follow logs for all services or only the supplied service names.
logs *services:
    {{ stack }} logs --follow {{ services }}

# Restart all services or only the supplied service names.
restart *services:
    {{ stack }} restart {{ services }}

# Run the application smoke test against the local stack.
smoke:
    {{ stack }} run --rm --no-deps smoke

# Create and verify a local backup, then mirror it off-site when configured.
backup:
    powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File deploy/scripts/backup.ps1

# Back up durable data, fast-forward pull, migrate/start, and run the smoke test.
deploy-safe:
    powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File deploy/scripts/deploy-safe.ps1

# Linux/SSH equivalents used by a persistent server checkout.
backup-server:
    sh deploy/scripts/backup.sh

deploy-safe-server:
    sh deploy/scripts/deploy-safe.sh

backup-fetch-server backup_id:
    sh deploy/scripts/fetch-offsite-backup.sh "{{ backup_id }}"

# Print the primary local URLs.
urls:
    @echo "Dashboard:        http://127.0.0.1:8080/dashboard/"
    @echo "API Swagger:      http://127.0.0.1:8000/docs"
    @echo "Grafana:          http://127.0.0.1:3000"
    @echo "Langfuse:         http://127.0.0.1:3001"
    @echo "Adminer:          http://127.0.0.1:8081"
    @echo "SeaweedFS Filer:  http://127.0.0.1:8888"
    @echo "SeaweedFS Master: http://127.0.0.1:9333"
    @echo "RabbitMQ:         http://127.0.0.1:15672"
    @echo "Prometheus:       http://127.0.0.1:9090"
    @echo "Alertmanager:     http://127.0.0.1:9093"
    @echo "RedisInsight:     http://127.0.0.1:5540"
    @echo "MinIO Console:    http://127.0.0.1:19001"

# Create persistent SSH-native Runpod configuration once.
runpod-configure:
    bash deploy/runpod/manual/configure.sh

# Install or repair the SSH-native Runpod runtime under /workspace.
runpod-install:
    bash deploy/runpod/manual/install.sh

# Start Dashboard, API, worker and 9Router without nested Docker.
runpod-start:
    bash deploy/runpod/manual/start.sh

# Stop all SSH-native Runpod services while preserving /workspace data.
runpod-stop:
    bash deploy/runpod/manual/stop.sh

# Restart all SSH-native Runpod services.
runpod-restart:
    bash deploy/runpod/manual/restart.sh

# Pull the current Git branch, rebuild dependencies and restart services.
runpod-update:
    bash deploy/runpod/manual/update.sh

# Verify process state plus Dashboard and 9Router health.
runpod-status:
    bash deploy/runpod/manual/status.sh

# Follow one persistent service log: api, worker, nine-router or nginx.
runpod-logs service="":
    bash deploy/runpod/manual/logs.sh "{{ service }}"

# The previous GHCR/GitHub Actions deployment path is intentionally disabled.
runpod-deploy:
    @echo "Image-based Runpod deployment is disabled. SSH to the Pod and run 'just runpod-update'."
