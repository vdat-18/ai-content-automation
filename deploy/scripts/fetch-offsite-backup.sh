#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <backup-id>" >&2
  exit 2
fi

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="$repository_root/deploy/compose.yaml"
environment_file="$repository_root/deploy/.env"
backup_id=$1

cd "$repository_root"
docker compose --env-file "$environment_file" -f "$compose_file" --profile tools run --rm maintenance \
  download-offsite --backup-id "$backup_id" --destination /backups

printf '%s\n' "$repository_root/.backups/$backup_id"
