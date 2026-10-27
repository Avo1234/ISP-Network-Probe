#!/usr/bin/env python3
"""Network probe: pings, Wi-Fi quality, DNS, HTTP -> SQLite (UTC timestamps)."""
import os, re, signal, socket, sqlite3, subprocess, sys, threading, time, random, string
import urllib.request, urllib.error
from datetime import datetime, timezone

# ---- settings ----
IFACE = "wlan0"
NET_TARGETS = {"net1": "1.1.1.1", "net2": "8.8.8.8"}
PING_COUNT = 5
CYCLE_SECONDS = 10
SLOW_EVERY = 6          # DNS + HTTP every 6th cycle (~60 s)
FLUSH_EVERY = 6         # write to the database every 6 cycles (~60 s)
TRACE_MIN_GAP = 300     # seconds between traceroutes
TRACE_LOSS_PCT = 50     # both outside targets at/above this loss triggers a trace
DNS_ZONE = "google.com"
HTTP_URL = "http://connectivitycheck.gstatic.com/generate_204"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.db")

PREFIXES = ["gw", "net1", "net2"]
FIELDS = ("loss", "min", "avg", "max", "jitter")
NAMES = ["ts"] + [f"{p}_{f}" for p in PREFIXES for f in FIELDS] + [
    "signal_dbm", "bitrate_mbps", "dns_ms", "dns_ok", "http_status", "http_ms"]


def get_gateway():
    out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True).stdout
    m = re.search(r"default via (\S+)", out)
    return m.group(1) if m else None


def ping(ip):
    try:
        out = subprocess.run(["ping", "-c", str(PING_COUNT), "-i", "0.5", "-W", "2", ip],
                             capture_output=True, text=True,
                             timeout=PING_COUNT * 0.5 + 6).stdout
    except subprocess.TimeoutExpired:
        out = ""
    t = [float(x) for x in re.findall(r"time=([\d.]+) ms", out)][:PING_COUNT]
    loss = (PING_COUNT - len(t)) / PING_COUNT * 100
    if not t:
        return {"loss": 100.0, "min": None, "avg": None, "max": None, "jitter": None}
    jitter = sum(abs(a - b) for a, b in zip(t, t[1:])) / (len(t) - 1) if len(t) > 1 else 0.0
    return {"loss": loss, "min": min(t), "avg": sum(t) / len(t), "max": max(t), "jitter": jitter}


def wifi():
    out = subprocess.run(["iw", "dev", IFACE, "link"], capture_output=True, text=True).stdout
    s = re.search(r"signal:\s*(-?\d+)", out)
    b = re.search(r"tx bitrate:\s*([\d.]+)", out)
    return (float(s.group(1)) if s else None, float(b.group(1)) if b else None)


def dns_check():
    # random name forces a real upstream lookup; "no such name" still counts as a working DNS
    name = "".join(random.choices(string.ascii_lowercase, k=10)) + "." + DNS_ZONE
    res = {}

    def work():
        try:
            socket.getaddrinfo(name, None)
            res["ok"] = True
        except socket.gaierror as e:
            res["ok"] = (e.errno == socket.EAI_NONAME)
        except Exception:
            res["ok"] = False

    t0 = time.time()
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(5)
    return (time.time() - t0) * 1000, int(res.get("ok", False))


def http_check():
    t0 = time.time()
    try:
        status = urllib.request.urlopen(HTTP_URL, timeout=5).status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = None
    return status, (time.time() - t0) * 1000


def fmt(r):
    return f"{r['loss']:.0f}% " + (f"{r['avg']:.0f}ms" if r["avg"] is not None else "--")


def main():
    gateway = get_gateway()
    if not gateway:
        sys.exit("No default gateway found - is Wi-Fi connected?")
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS samples (ts TEXT, " +
               ", ".join(f"{n} REAL" for n in NAMES[1:]) + ")")
    db.execute("CREATE TABLE IF NOT EXISTS traces (ts TEXT, target TEXT, output TEXT)")
    db.commit()
    insert = (f"INSERT INTO samples ({','.join(NAMES)}) VALUES ({','.join(':' + n for n in NAMES)})")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())

    buffer, n, last_trace, next_t = [], 0, 0.0, time.time()

    def flush():
        try:
            db.executemany(insert, buffer)
            db.commit()
            buffer.clear()
        except Exception as e:
            print("DB write failed, will retry:", e)

    while not stop.is_set():
        gateway = get_gateway() or gateway
        targets = {"gw": gateway, **NET_TARGETS}
        results = {}
        threads = [threading.Thread(target=lambda p=p, ip=ip: results.__setitem__(p, ping(ip)))
                   for p, ip in targets.items()]
        for t in threads: t.start()
        for t in threads: t.join()

        row = dict.fromkeys(NAMES)
        row["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for p in PREFIXES:
            for f in FIELDS:
                row[f"{p}_{f}"] = results[p][f]
        row["signal_dbm"], row["bitrate_mbps"] = wifi()

        extra = ""
        if n % SLOW_EVERY == 0:
            row["dns_ms"], row["dns_ok"] = dns_check()
            row["http_status"], row["http_ms"] = http_check()
            extra = f" | dns {row['dns_ms']:.0f}ms ok={row['dns_ok']} http {row['http_status']} {row['http_ms']:.0f}ms"

        if (results["net1"]["loss"] >= TRACE_LOSS_PCT and results["net2"]["loss"] >= TRACE_LOSS_PCT
                and time.time() - last_trace > TRACE_MIN_GAP):
            last_trace = time.time()
            try:
                tr = subprocess.run(["traceroute", "-n", "-m", "15", "-w", "1", "-q", "1", "1.1.1.1"],
                                    capture_output=True, text=True, timeout=40).stdout
            except subprocess.TimeoutExpired:
                tr = "traceroute timed out"
            db.execute("INSERT INTO traces VALUES (?,?,?)", (row["ts"], "1.1.1.1", tr))
            db.commit()
            extra += " | TRACEROUTE SAVED"

        buffer.append(row)
        n += 1
        print(f"{row['ts'][11:19]} gw {fmt(results['gw'])} | 1.1.1.1 {fmt(results['net1'])} | "
              f"8.8.8.8 {fmt(results['net2'])} | wifi {row['signal_dbm']}dBm{extra}", flush=True)
        if len(buffer) >= FLUSH_EVERY:
            flush()
        next_t += CYCLE_SECONDS
        stop.wait(max(0, next_t - time.time()))

    flush()
    print("Stopped cleanly.")


if __name__ == "__main__":
    main()
