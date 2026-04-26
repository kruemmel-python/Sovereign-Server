#!/usr/bin/env sh
set -eu
docker compose -f compose.distroless.yaml up --build
