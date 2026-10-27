#!/usr/bin/env python3
"""Read-only sanity check of probe.db: row count, newest rows, gaps, out-of-order timestamps.
Usage: python3 scripts/check-data.py [path/to/probe.db]   (default: ~/probe/probe.db)"""
import os, sqlite3, sys
from datetime import datetime

path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/probe/probe.db")
db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

rows = [r[0] for r in db.execute("SELECT ts FROM samples ORDER BY rowid")]
print("rows:", len(rows))

print("--- newest 5 (ts, gw_loss, net1_loss, net2_loss, signal_dbm, dns_ok, http_status) ---")
for r in db.execute("SELECT ts, gw_loss, net1_loss, net2_loss, signal_dbm, dns_ok, http_status "
                    "FROM samples ORDER BY rowid DESC LIMIT 5"):
    print(r)

print("--- gaps > 60 s and out-of-order timestamps (insertion order) ---")
prev, odd, gaps = None, 0, 0
for ts in rows:
    t = datetime.fromisoformat(ts)
    if prev and t <= prev:
        odd += 1
        print("out of order or duplicate:", prev.isoformat(), "->", ts)
    if prev and (t - prev).total_seconds() > 60:
        gaps += 1
        print("gap:", prev.isoformat(), "->", ts, f"({(t - prev).total_seconds() / 60:.0f} min)")
    prev = t
print(f"gaps: {gaps} | out-of-order: {odd}")

try:
    print("traceroutes saved:", db.execute("SELECT COUNT(*) FROM traces").fetchone()[0])
except sqlite3.OperationalError:
    print("traceroutes saved: (no traces table)")
try:
    print("ignore windows:", db.execute("SELECT * FROM ignore_windows").fetchall())
except sqlite3.OperationalError:
    print("ignore windows: (none)")
