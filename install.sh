#!/usr/bin/env bash
set -euo pipefail
task_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$task_app_dir/packaging/install.py" "$@"
