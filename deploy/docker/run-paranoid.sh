#!/usr/bin/env sh
set -eu
docker compose -f compose.paranoid.yaml up --build
