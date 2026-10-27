# Step 2: The probe

`probe/probe.py` is one Python script (standard library only). It runs a cycle every 10 seconds and writes to SQLite.

## What each cycle does

1. **Pings** the router, 1.1.1.1 and 8.8.8.8 in parallel threads, 5 pings each, 0.5 s apart. Records packets lost (as % of 5), min/avg/max latency, and jitter (average gap between consecutive latencies). Uses the system `ping`, which needs no root.
2. **Wi-Fi quality** from `iw dev wlan0 link`: signal (dBm) and bitrate.
3. **DNS and HTTP** every 6th cycle (about once a minute):
   - DNS resolves a random made-up subdomain (like `x7k2q....google.com`). A fresh name forces a real upstream lookup. A "name does not exist" reply counts as a working DNS, because we only care how fast and whether it answers.
   - HTTP fetches `http://connectivitycheck.gstatic.com/generate_204` and records the status (expect 204) and time.
4. **Traceroute on failure:** if both outside targets show 50% or more loss, saves a traceroute to 1.1.1.1 (at most once every 5 minutes).
5. **Storage:** readings are buffered in memory and written in one batch about every minute (less SD card wear). Timestamps are UTC. Ctrl+C or a service stop flushes the buffer first.

All settings are constants at the top of the file (targets, interval, interface name, thresholds).

## Database

`probe.db` (SQLite, WAL mode), next to the script.

**`samples`**, one row per cycle:

| Columns | Meaning |
|---|---|
| `ts` | UTC ISO timestamp |
| `gw_*`, `net1_*`, `net2_*` | for router / 1.1.1.1 / 8.8.8.8: `loss` (%), `min`, `avg`, `max`, `jitter` (ms) |
| `signal_dbm`, `bitrate_mbps` | Wi-Fi quality |
| `dns_ms`, `dns_ok`, `http_status`, `http_ms` | filled only on the slow cycles (otherwise NULL) |

**`traces`**: `ts`, `target`, `output` (the traceroute text).

Column naming note: the router column prefix is `gw`, and it measures only the local Wi-Fi hop, because the router answers from inside itself.

## Run it in the foreground first

```bash
mkdir -p ~/probe
cp probe/probe.py ~/probe/
python3 ~/probe/probe.py
```

(`Permission denied` if you try `~/probe/probe.py` directly is harmless: the file isn't marked executable. Use `python3`.)

Each cycle prints a line like:

```
08:41:10 gw 0% 2ms | 1.1.1.1 0% 44ms | 8.8.8.8 0% 41ms | wifi -35.0dBm | dns 38ms ok=1 http 204 95ms
```

Leave it about 2 minutes, then Ctrl+C. You should see `Stopped cleanly.`

## Check the saved data

```bash
python3 scripts/check-data.py ~/probe/probe.db
```

### What we saw

- **22 rows in about 3.5 minutes:** matches one row per 10 s, so batching and the clean flush work.
- `dns_ok=1` and `http 204` on every slow check.
- Baseline: 0% loss everywhere, about 2 ms to the router, 42-56 ms to the outside targets, Wi-Fi between -25 and -33 dBm.
- DNS times were 316, 487, 313, then **2304 ms** while pings stayed perfect: a first example of an "internet feels down but isn't" moment.

## Data use (estimate, not measured)

About 16-17 MB/day, roughly 0.5 GB/month, for the outside pings, DNS and HTTP checks. Pings to the router stay on the local network. The Pi's own background traffic (clock sync, OS updates) is extra. See [roadmap.md](roadmap.md) for the plan to measure it.

**Next:** [03-run-on-boot.md](03-run-on-boot.md)
