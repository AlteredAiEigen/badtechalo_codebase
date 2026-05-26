#!/usr/bin/env bash
set -euo pipefail
cd /home/ec2-user/backend
exec /home/ec2-user/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
