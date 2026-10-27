# Step 4: The dashboard ("Network Pulse")

`probe/dashboard.py` serves a single-page, phone-first web UI on port 8080. It reads `probe.db` **read-only**, so it can never corrupt the probe's data.

## What's on the page

- **Status card:** gradient colour per state, a health score out of 100, and a one-line summary built from real numbers.
- **Four tiles:** Home Wi-Fi hop (ms, loss, dBm), Cloudflare 1.1.1.1, Google 8.8.8.8, DNS time. Each has a badge computed from thresholds, so it turns into a warning when that metric degrades.
- **Latency Trends chart:** 1 hour / 24 hours / 7 days. Long ranges are averaged into buckets (1, 5 and 15 minutes) so a Pi Zero and a phone browser can draw them. Missing data is drawn as a **gap**, never a false zero.
- **Stability Note:** generated from the data for the selected range. It skips any window listed in the `ignore_windows` table.
- **Run Test:** a one-off check (pings, DNS, HTTP) shown on screen only. It does **not** write to the database, so your data stays clean for analysis.
- **Refresh data:** reloads the page data. (A "Fix Wi-Fi" button from the original design was deliberately left out: the dashboard is served over the same Wi-Fi, so a reconnect would cut you off.)
- **Bottom navigation bar:** Overview is active. Telemetry, Diagnostics and Settings are greyed out and do nothing. There is only one page by design.

## How the status is decided

Based on the last ~6 saved readings (about a minute):

| Condition | Status |
|---|---|
| Newest saved reading is older than 150 s | Probe not reporting |
| Router loss at or above 50% | Local Wi-Fi problem |
| Both outside targets at or above 50% loss | Internet down (Telecel/upstream) |
| Average outside loss at or above 10%, or average latency above 150 ms | Degraded |
| Otherwise | OK |

The probe writes in about one-minute batches, so the status can lag by up to a minute, which is why the "not reporting" threshold is 150 s and not 45 s.

These thresholds are starting guesses. Tune them in the constants at the top of `dashboard.py` once you've seen real bad moments.

## Health score

Starts at 100 and subtracts: outside loss (2.5 points per percent, max 50), router loss (0.6 per percent, max 30), latency above 80 ms (1 point per 5 ms, max 20), jitter above 15 ms (max 10), DNS failure (10) or DNS time above 1000 ms (up to 10). Then it is capped at 80 when degraded, 30 for a Wi-Fi problem and 20 when down. It is a visible, simple formula, **not** a validated metric.

## Install

On the Pi, from the repo root:

```bash
# 1. The runtime files (skip if already copied during step 2/3)
cp -r probe ~/probe

# 2. Chart.js, served locally so the page works during an outage
scripts/fetch-chartjs.sh ~/probe/static

# 3. Table used to skip known test windows (safe to run repeatedly)
python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.path.expanduser("~/probe/probe.db"), timeout=10)
db.execute("CREATE TABLE IF NOT EXISTS ignore_windows (start_ts TEXT, end_ts TEXT, reason TEXT)")
db.commit()
PY

# 4. Try it in the foreground first
python3 ~/probe/dashboard.py &
sleep 2
curl -s localhost:8080/api/status; echo
hostname -I
# open http://<hostname>.local:8080 (or the IP) on your laptop and phone; then:
kill %1

# 5. Run on boot
sudo cp systemd/netdash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now netdash.service
systemctl is-active netdash.service
```

The status JSON should show `"state": "ok"` with a `tiles` section. Some phones can't resolve `.local` names, so use the Pi's IP address as a backup.

## What we saw

- Layout, tiles, chart and bottom bar rendered correctly on phone-width and laptop screens.
- When the Pi was powered off for about six hours, the dashboard showed "Failed to fetch" and the last saved reading from before the outage. Once it was back on, the 1-hour chart showed data only for the time since boot: the gap is a real gap.
- First real degradation caught: Cloudflare at 117 ms while Google stayed at 55 ms, DNS at 2032 ms ("Very slow"), peak latency 349 ms, and 1 of 84 checks dropping a packet. Because it hit one target and DNS but not the other target, it shows why the probe uses more than one target.

## Not done or not verified

- **Run Test** writing no rows to the database: designed that way, but the before/after row count was not checked.
- On a fetch error, the health score still shows the last good value (it should show `--`).
- No login, no HTTPS. See [known-issues.md](known-issues.md).
