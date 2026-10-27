# Step 3: Run on boot (systemd)

**Goal:** the probe runs by itself, permanently, with no one logged in. Prediction needs weeks of continuous data, and a probe that only runs while an SSH window is open leaves gaps.

| Without the service | With the service |
|---|---|
| You start it by hand | Starts when the Pi boots |
| Closing SSH stops it | Keeps running in the background |
| A crash ends collection | Restarts 10 seconds after a crash |

## Install

Make sure the probe is not already running in another window (two copies would write duplicate rows).

```bash
sudo cp systemd/netprobe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now netprobe.service
```

What the unit file does:

- `After=network-online.target`: waits for Wi-Fi first. If it still starts too early and finds no gateway, the script exits and `Restart=always` retries 10 seconds later.
- `User=wills`: runs as a normal user, not root. **Change this and the paths if your username is different.**
- `TimeoutStopSec=30`: gives the script time to flush its last batch on shutdown.

## Check

```bash
systemctl status netprobe.service --no-pager
journalctl -u netprobe -n 10 --no-pager
journalctl -u netprobe -f        # live view; Ctrl+C leaves the viewer, the service keeps running
```

You should see `active (running)` and the per-cycle lines.

> **A mistake we made:** the service file was created but `enable --now` hadn't been run, so status showed `disabled` and `inactive (dead)` with no journal entries. The fix was just running the enable command.

## Reboot test

```bash
sudo reboot
# reconnect, then:
systemctl is-active netprobe.service
python3 scripts/check-data.py ~/probe/probe.db
```

### What we saw

`active` after the reboot, and the row count went from 22 to 134 with the newest reading seconds old. The probe starts on boot with no one logged in.

**Next:** [03b-test-outage.md](03b-test-outage.md)
