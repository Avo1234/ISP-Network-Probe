#!/usr/bin/env bash
# Download Chart.js (pinned) so the dashboard can serve it locally.
# The dashboard must not depend on the internet: it is most useful DURING an outage.
# Usage: scripts/fetch-chartjs.sh [target-dir]     (default: ../probe/static next to this script)
set -euo pipefail
DEFAULT="$(cd "$(dirname "$0")/.." && pwd)/probe/static"
DIR="${1:-$DEFAULT}"
mkdir -p "$DIR"
curl -fL -o "$DIR/chart.umd.js" "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"
ls -l "$DIR/chart.umd.js"
