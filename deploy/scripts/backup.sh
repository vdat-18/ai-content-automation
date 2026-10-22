#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="$repository_root/deploy/compose.yaml"
environment_file="$repository_root/deploy/.env"
backup_id=$(date -u +%Y%m%dT%H%M%SZ)
source_revision=$(git -C "$repository_root" rev-parse HEAD)
if [ -n "$(git -C "$repository_root" status --porcelain)" ]; then
  source_dirty=true
else
  source_dirty=false
fi

cd "$repository_root"
restart_application() {
  docker compose --env-file "$environment_file" -f "$compose_file" \
    start outbox-publisher worker api frontend
}
docker compose --env-file "$environment_file" -f "$compose_file" stop frontend api
docker compose --env-file "$environment_file" -f "$compose_file" stop outbox-publisher worker
trap restart_application EXIT
docker compose --env-file "$environment_file" -f "$compose_file" --profile tools run --rm maintenance create \
  --destination /backups \
  --backup-id "$backup_id" \
  --source-revision "$source_revision" \
  --source-dirty "$source_dirty"
restart_application
trap - EXIT
docker compose --env-file "$environment_file" -f "$compose_file" --profile tools run --rm maintenance \
  upload-offsite --backup-set "/backups/$backup_id"

printf '%s\n' "$repository_root/.backups/$backup_id"
