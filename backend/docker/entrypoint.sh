#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn app.main:build_default_app --factory --host 0.0.0.0 --port 8000 --ws-max-size 65536 --no-server-header
