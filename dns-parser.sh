#!/bin/bash
# Compatibility wrapper for existing systemd units and old shell habits.
# The real service manager lives in scripts/dns-parser.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$SCRIPT_DIR/scripts/dns-parser.sh" "$@"
