# Step 3b: Test the failure path with a simulated outage

**Goal:** prove the traceroute-on-failure path works *before* a real outage, because nothing had failed yet.

## How it works

`scripts/simulate-outage.sh` adds a separate nftables table (`probetest`) containing one rule that drops outgoing ping requests to 1.1.1.1 and 8.8.8.8. The router stays reachable, so the probe sees the same pattern as a real ISP outage: router fine, outside targets at 100% loss. The rule doesn't touch any existing firewall rules, SSH keeps working, DNS and HTTP checks keep succeeding (they go to different addresses), and the table disappears on reboot.

```bash
which nft || sudo apt install -y nftables
scripts/simulate-outage.sh start      # note the TEST START time
sleep 90
python3 scripts/check-data.py ~/probe/probe.db
scripts/simulate-outage.sh stop       # note the TEST END time
```

The first command should show `100% packet loss` on the ping.

## What we saw

Test window: **2026-10-27 from 10:40:44 to 10:44:38 UTC.**

- `gw_loss` stayed 0 while `net1_loss` and `net2_loss` went to 100.
- The first cycle caught the rule mid-ping (40% loss, below the 50% threshold), so it correctly did not fire. The first full 100% cycle (10:41:04) triggered the traceroute.
- **Exactly one** trace row for the whole outage: the 5-minute cooldown works.
- DNS ok and HTTP 204 continued during the outage, as expected.
- The traceroute showed the router as hop 1, then a hidden hop, then private addresses beyond it, probably inside the ISP's own network. In a real outage, the last hop that answers shows roughly how far packets got.
- **Recovery looked wrong at first:** right after `stop`, the database still showed 100% loss even though a direct ping worked. This is the one-minute write batching: those rows were stamped before the rule was removed, and the recovery readings were still in memory. A second check a minute later showed 0% loss everywhere.

## Exclude this window from analysis

The test left a fake outage in the database. Record it so it can be skipped later:

```bash
python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.path.expanduser("~/probe/probe.db"), timeout=10)
db.execute("CREATE TABLE IF NOT EXISTS ignore_windows (start_ts TEXT, end_ts TEXT, reason TEXT)")
db.execute("INSERT INTO ignore_windows VALUES (?,?,?)",
           ("2026-10-27T10:40:40+00:00", "2026-10-27T10:44:50+00:00", "nft ping-block test (fake outage)"))
db.commit()
print(db.execute("SELECT * FROM ignore_windows").fetchall())
PY
```

Use your own start/end times if you repeat the test. Currently only the dashboard's Stability Note honors `ignore_windows`. The Phase 2 report and the prediction model are meant to as well.

**Next:** [04-dashboard.md](04-dashboard.md)
