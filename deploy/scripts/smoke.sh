#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="$repository_root/deploy/compose.yaml"
environment_file="$repository_root/deploy/.env"

if [ -f "$environment_file" ]; then
    set -- --env-file "$environment_file"
else
    set --
fi

cd "$repository_root"
docker compose "$@" -f "$compose_file" up --build --detach
docker compose "$@" -f "$compose_file" run --rm smoke
docker compose "$@" -f "$compose_file" restart worker api
docker compose "$@" -f "$compose_file" run --rm smoke
