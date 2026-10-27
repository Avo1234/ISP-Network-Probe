# ISP Network Probe

A small, always-on network monitoring probe for a **Raspberry Pi Zero 2 W**. It measures packet loss, latency, jitter, Wi-Fi quality, DNS speed, and web reachability every 10 seconds, stores everything in SQLite, and shows it on a phone-friendly dashboard ("Network Pulse").

The goal: understand how stable a mobile ISP link really is (built and tested on a Telecel 4G router in Ghana), and eventually **estimate the probability of packet failure and predict availability** using empirical probability.

> **Status: Phase 1 complete (data collection + dashboard).** Phase 2 (probability report), Phase 3 (prediction), a clock fix, and data-usage tracking are planned. See [docs/roadmap.md](docs/roadmap.md) and [docs/known-issues.md](docs/known-issues.md) for what is and isn't done.

## What it measures

Every 10 seconds, 5 pings each to:

| Target | Why |
|---|---|
| Your router (default gateway) | Tests only the local Wi-Fi hop, so Wi-Fi problems are not blamed on the ISP |
| 1.1.1.1 (Cloudflare) | Outside target 1 |
| 8.8.8.8 (Google) | Outside target 2, so one server's bad day doesn't look like an outage |

Plus, once a minute: a DNS lookup of a random made-up name (forces a real upstream lookup instead of a cache hit) and a tiny HTTP request. Wi-Fi signal strength and bitrate are logged each cycle. If **both** outside targets lose 50% or more of their pings, a traceroute is saved (at most once every 5 minutes).

How a drop gets classified:

| Router | Outside targets | Likely cause |
|---|---|---|
| failing | failing | Local Wi-Fi |
| OK | failing | ISP / upstream |
| OK | slow or lossy | ISP congestion |

## Architecture

```
 Raspberry Pi Zero 2 W (Raspberry Pi OS Lite)
 ┌──────────────────────────────────────────────────────┐
 │  probe.py  ──every 10 s──►  ping / DNS / HTTP / iw   │
 │      │                                               │
 │      └─ batches, writes once a minute ─► probe.db    │
 │                                            (SQLite)  │
 │  dashboard.py (port 8080, read-only) ◄───────┘       │
 └──────────────────────────────────────────────────────┘
        ▲                       ▲
   netprobe.service        netdash.service   (systemd, start on boot)

   Phone / laptop on the same Wi-Fi ──► http://<pi>.local:8080
```

Python standard library only, no pip packages. The dashboard serves its own copy of Chart.js, so it works even when the internet is down.

## Quick start

Full walkthrough with expected output: [docs/](docs/). The short version, on the Pi:

```bash
# 1. Get the code and put the runtime files in ~/probe (the service files expect this path)
git clone https://github.com/<your-username>/isp-network-probe.git
cp -r isp-network-probe/probe ~/probe

# 2. Turn off Wi-Fi power saving (see docs/01-prepare-pi.md for why and how to verify)
sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf > /dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
sudo iw dev wlan0 set power_save off

# 3. Download Chart.js for the dashboard
isp-network-probe/scripts/fetch-chartjs.sh ~/probe/static

# 4. Try the probe in the foreground (Ctrl+C to stop)
python3 ~/probe/probe.py

# 5. Install both services (edit User= and paths first if your username is not "wills")
sudo cp isp-network-probe/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now netprobe.service netdash.service
```

Then open `http://<hostname>.local:8080` (or the Pi's IP address) on a device on the same Wi-Fi.

## Repository layout

```
probe/        probe.py (collector), dashboard.py (web UI)
systemd/      netprobe.service, netdash.service
scripts/      fetch-chartjs.sh, check-data.py, simulate-outage.sh
docs/         step-by-step guide, design decisions, known issues, roadmap
```

## Documentation

| Doc | Contents |
|---|---|
| [01-prepare-pi.md](docs/01-prepare-pi.md) | OS checks, turning off Wi-Fi power saving |
| [02-probe.md](docs/02-probe.md) | What the probe measures, the database, first run |
| [03-run-on-boot.md](docs/03-run-on-boot.md) | systemd service and reboot test |
| [03b-test-outage.md](docs/03b-test-outage.md) | Simulated outage to test the traceroute path |
| [04-dashboard.md](docs/04-dashboard.md) | Dashboard setup, status logic, health score |
| [design-decisions.md](docs/design-decisions.md) | Why it is built this way |
| [known-issues.md](docs/known-issues.md) | Open problems and untested parts |
| [roadmap.md](docs/roadmap.md) | What comes next |
| [project-summary.md](docs/project-summary.md) | How this maps to the course project brief |

## Things to know before you use it

- **The dashboard has no login.** Anyone on your Wi-Fi can open it. Don't expose port 8080 to the internet.
- **Your data stays out of this repo.** `probe.db` is in `.gitignore`. Keep it that way if you fork this: it's a timing history of your own network.
- **Estimated data use is about 0.5 GB/month** for the probe's own traffic (not measured yet; see the roadmap).
- **Hard power cuts can corrupt the SD card and lose up to a minute of readings.** Use `sudo shutdown -h now` before unplugging.
- **Don't run `probe.py` by hand while the service is running.** Both would write to the same database.

## License

MIT, see [LICENSE](LICENSE).
