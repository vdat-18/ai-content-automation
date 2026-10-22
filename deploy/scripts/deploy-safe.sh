#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

if [ -n "$(git -C "$repository_root" status --porcelain)" ]; then
  echo "Deployment checkout has uncommitted changes; aborting before backup or pull." >&2
  exit 1
fi

cd "$repository_root"
sh deploy/scripts/backup.sh
git pull --ff-only
just up
just smoke
