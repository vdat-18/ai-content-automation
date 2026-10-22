#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 BACKUP_SET" >&2
  exit 2
fi

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="$repository_root/deploy/compose.yaml"
environment_file="$repository_root/deploy/.env"
backup_set=$(CDPATH= cd -- "$1" && pwd)
backup_root=$(CDPATH= cd -- "$repository_root/.backups" && pwd)
case "$backup_set" in
  "$backup_root"/*) ;;
  *) echo "BACKUP_SET must be inside $backup_root" >&2; exit 2 ;;
esac
backup_name=$(basename "$backup_set")
project_name="aicontent-ai-restore-$(date -u +%Y%m%d%H%M%S)"

cd "$repository_root"
cleanup() {
  docker compose --project-name "$project_name" --env-file "$environment_file" \
    -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" up --detach postgres rabbitmq object-storage
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" --profile tools run --rm maintenance restore \
  --backup-set "/backups/$backup_name"
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" run --rm migrate
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" --profile tools run --rm maintenance recover-execution \
  --backup-set "/backups/$backup_name"
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" up --detach api outbox-publisher worker
docker compose --project-name "$project_name" --env-file "$environment_file" \
  -f "$compose_file" --profile tools run --rm maintenance verify-http \
  --backup-set "/backups/$backup_name" --base-url http://api:8000
