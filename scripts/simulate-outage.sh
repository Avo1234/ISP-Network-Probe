#!/usr/bin/env bash
# Simulate an upstream outage by dropping outgoing pings to the two outside targets.
# The router stays reachable, so the probe sees "router fine, internet failing".
# Everything lives in its own nftables table, so it never touches other firewall rules,
# and it disappears on reboot. Note the START/END times: exclude that window from analysis.
# Usage: scripts/simulate-outage.sh start | stop
set -euo pipefail
case "${1:-}" in
  start)
    echo "TEST START (UTC): $(date -u +%FT%T)"
    sudo nft add table inet probetest
    sudo nft add chain inet probetest out '{ type filter hook output priority 0 ; policy accept ; }'
    sudo nft add rule inet probetest out ip daddr { 1.1.1.1, 8.8.8.8 } icmp type echo-request drop
    sudo nft list table inet probetest
    ping -c 2 -W 1 1.1.1.1 || true
    ;;
  stop)
    sudo nft delete table inet probetest
    echo "TEST END (UTC): $(date -u +%FT%T)"
    ping -c 3 1.1.1.1
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 1
    ;;
esac
