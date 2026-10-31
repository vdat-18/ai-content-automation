set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

compose := "docker compose --env-file deploy/.env -f deploy/compose.yaml"
stack := compose

# Full stack with observability (Grafana/Tempo), Langfuse, and debug UIs (heavy, optional)
compose-full := "docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.observability.yaml -f deploy/compose.langfuse.yaml -f deploy/compose.debug.yaml"
profiles-full := "--profile observability --profile langfuse --profile debug"
stack-full := compose-full + " " + profiles-full

# Show the available local development commands.
default:
    @just --list

# Validate the lean Compose configuration.
config:
    {{ stack }} config --quiet

# Build and start the lean local stack (~1GB RAM, without Grafana/Langfuse).
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

# Stop all containers including any previously running full/observability containers.
down-all:
    {{ stack-full }} down

# Build and start the full stack including Grafana, Langfuse, and debug UIs (heavy).
up-full:
    {{ stack-full }} config --quiet
    {{ stack-full }} up -d --build
    @echo "Dashboard:        http://127.0.0.1:8080/dashboard/"
    @echo "API Swagger:      http://127.0.0.1:8000/docs"
    @echo "Grafana:          http://127.0.0.1:3000"
    @echo "Langfuse:         http://127.0.0.1:3001"
    @echo "Adminer:          http://127.0.0.1:8081"
    @echo "RabbitMQ:         http://127.0.0.1:15672"
    @echo "Prometheus:       http://127.0.0.1:9090"
    @echo "Alertmanager:     http://127.0.0.1:9093"
    @echo "RedisInsight:     http://127.0.0.1:5540"
