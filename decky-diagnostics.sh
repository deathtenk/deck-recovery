#!/usr/bin/env bash
# Read-only diagnostics; no service restarts or configuration changes.
set -uo pipefail
exec /usr/bin/python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/decky_diagnostics.py" "$@"
