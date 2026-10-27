# Step 1: Prepare the Pi

**Goal:** a clean, quiet baseline. If the Pi's own Wi-Fi adds noise, the data is useless for prediction.

## What we started with

Raspberry Pi Zero 2 W running Raspberry Pi OS Lite 32-bit (Debian 13 "trixie"), reachable over SSH.

## 1. Read-only checks (change nothing)

```bash
echo "=== OS ===" && cat /etc/os-release | head -n 4 && uname -m
echo "=== Wi-Fi interface ===" && iw dev
echo "=== Link and signal ===" && iw dev wlan0 link
echo "=== Power save ===" && iw dev wlan0 get power_save
echo "=== Network manager in use ===" && (systemctl is-active NetworkManager; systemctl is-active dhcpcd)
echo "=== Default gateway ===" && ip route | grep default
echo "=== Python and traceroute ===" && python3 --version && (which traceroute || echo "traceroute not installed")
echo "=== Memory and disk ===" && free -m && df -h /
```

Why each one matters:

- **OS and architecture:** newer releases manage Wi-Fi with NetworkManager, older ones with dhcpcd. That decides how power saving is turned off.
- **`iw dev`:** confirms the interface name (`wlan0`).
- **`iw dev wlan0 link`:** shows signal strength in dBm and bitrate, which the probe will log.
- **Default gateway:** the router's address, which the probe pings to separate local problems from ISP problems.
- **Python and traceroute:** confirms what is already installed.

### What we saw

| Item | Result |
|---|---|
| OS | Raspbian GNU/Linux 13 (trixie), `armv7l` (32-bit) |
| Wi-Fi manager | NetworkManager active, dhcpcd inactive |
| Power save | **on** (needs fixing) |
| Signal | about -35 dBm (excellent; Pi next to the access point) |
| Bitrate | 72.2 Mbit/s (normal maximum for the Zero 2 W's single-antenna 2.4 GHz Wi-Fi) |
| Python | 3.13.5 |
| traceroute | already installed (`/usr/sbin/traceroute`) |
| Memory | about 424 MB total, about 311 MB available |

If `traceroute` is missing on your Pi: `sudo apt update && sudo apt install -y traceroute`. Everything else uses Python's standard library.

## 2. Turn off Wi-Fi power saving

Power saving on the Zero 2 W's Wi-Fi chip is a known cause of random latency spikes. We don't want our own hardware adding noise.

This writes a NetworkManager config (so it survives reboots) and applies it immediately. The value `2` means "disable":

```bash
sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf > /dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
sudo iw dev wlan0 set power_save off
iw dev wlan0 get power_save
```

The last line should print `Power save: off`.

> If your system uses dhcpcd instead of NetworkManager, this config file will not apply. Use the `iw dev wlan0 set power_save off` command from a boot script instead. We only tested the NetworkManager route.

## 3. Verify connectivity

```bash
ping -c 5 <router-ip>
ping -c 5 1.1.1.1
```

Our baseline: about 1.5 ms to the router and about 44 ms to 1.1.1.1, both with 0% loss.

## 4. Reboot test

```bash
sudo reboot
# reconnect over SSH after about a minute, then:
iw dev wlan0 get power_save
```

It should still say `off`. Ours did.

> Run `iw` on the Pi, not in the Windows PowerShell window you SSH from. That's an easy mistake, and the error looks alarming but is harmless.

**Next:** [02-probe.md](02-probe.md)
