#!/usr/bin/env python3
"""Network Pulse dashboard: read-only view of probe.db (Overview page only)."""
import json, os, sqlite3, sys, threading, time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import probe  # reuse ping / DNS / HTTP helpers for the Run Test button

PORT = 8080
DB_PATH = os.path.join(BASE, "probe.db")
CHART_JS = os.path.join(BASE, "static", "chart.umd.js")
RANGES = {"1h": (3600, 60), "24h": (86400, 300), "7d": (604800, 900)}  # (span s, bucket s)
STALE_SECONDS = 150      # probe saves in ~60 s batches, so allow slack
LOSS_DOWN = 50           # % loss that counts as "down"
LOSS_DEGRADED = 10       # % average outside loss that counts as "degraded"
LATENCY_DEGRADED = 150   # ms average outside latency that counts as "degraded"

BADGE_TEXT = {"ok": "Optimal", "degraded": "Degraded", "down": "Internet down",
              "wifi": "Wi-Fi problem", "nodata": "No data"}
HEADLINE = {"ok": "Your internet is running smoothly",
            "degraded": "Your internet is struggling",
            "down": "Telecel or upstream looks down",
            "wifi": "Your Wi-Fi link to the router is unreliable",
            "nodata": "The probe is not reporting"}
VERDICT = {"ok": "Everything looks healthy.",
           "degraded": "Internet is degraded (loss or high latency).",
           "down": "Router is fine but both outside targets are unreachable: Telecel/upstream problem.",
           "wifi": "The router is not answering: local Wi-Fi problem."}


def db():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)


def avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def r1(v):
    return None if v is None else round(v, 1)


def classify(gw, n1, n2, lat):
    out_loss = avg([n1, n2])
    if (gw or 0) >= LOSS_DOWN:
        return "wifi"
    if n1 is not None and n2 is not None and n1 >= LOSS_DOWN and n2 >= LOSS_DOWN:
        return "down"
    if (out_loss or 0) >= LOSS_DEGRADED or (lat is not None and lat > LATENCY_DEGRADED):
        return "degraded"
    return "ok"


def health(state, gw, out_loss, lat, jit, dns_ms, dns_ok):
    s = 100.0
    s -= min(50, (out_loss or 0) * 2.5)
    s -= min(30, (gw or 0) * 0.6)
    if lat is not None:
        s -= min(20, max(0, lat - 80) / 5)
    if jit is not None:
        s -= min(10, max(0, jit - 15) / 2)
    if dns_ok == 0:
        s -= 10
    elif dns_ms is not None:
        s -= min(10, max(0, dns_ms - 1000) / 300)
    cap = {"down": 20, "wifi": 30, "degraded": 80}.get(state)
    if cap is not None:
        s = min(s, cap)
    return int(round(max(0, s)))


def signal_label(dbm):
    if dbm is None:
        return "no reading"
    if dbm >= -50:
        return "Excellent"
    if dbm >= -60:
        return "Good"
    if dbm >= -70:
        return "Fair"
    return "Weak"


def tile_gw(ms, loss, dbm):
    if loss >= LOSS_DOWN:
        badge, tone = "Unreachable", "bad"
    elif loss >= LOSS_DEGRADED or (ms or 0) > 25:
        badge, tone = "Unstable", "warn"
    elif ms is not None and ms <= 5:
        badge, tone = "Super Close", "good"
    else:
        badge, tone = "Good", "good"
    sub = "no signal reading" if dbm is None else f"{dbm:.0f} dBm ({signal_label(dbm)})"
    return {"ms": r1(ms), "loss": loss, "badge": badge, "tone": tone, "sub": sub}


def tile_out(ms, loss):
    if loss >= LOSS_DOWN:
        badge, tone, sub = "Down", "bad", "Not responding"
    elif loss >= LOSS_DEGRADED or (ms or 0) > LATENCY_DEGRADED:
        badge, tone, sub = "Degraded", "warn", "Latency or loss elevated"
    elif loss == 0 and (ms or 0) <= 80:
        badge, tone, sub = "Fast & Stable", "good", "Outside latency nominal"
    else:
        badge, tone, sub = "Stable", "good", "Outside latency acceptable"
    return {"ms": r1(ms), "loss": loss, "badge": badge, "tone": tone, "sub": sub}


def tile_dns(ms, ok):
    if ms is None:
        return {"ms": None, "badge": "No data", "tone": "neutral", "sub": "Waiting for a DNS check"}
    if ok == 0:
        return {"ms": r1(ms), "badge": "Failing", "tone": "bad", "sub": "Lookups are failing"}
    if ms <= 800:
        badge, tone, sub = "Responsive", "good", "Websites resolve promptly"
    elif ms <= 2000:
        badge, tone, sub = "Slow", "warn", "Lookups are slow"
    else:
        badge, tone, sub = "Very slow", "bad", "Lookups taking a long time"
    return {"ms": r1(ms), "badge": badge, "tone": tone, "sub": sub}


def jitter_word(j):
    if j is None:
        return "unknown"
    return "low" if j < 10 else ("moderate" if j < 30 else "high")


def get_status():
    con = db()
    try:
        rows = con.execute(
            "SELECT ts, gw_loss, gw_avg, gw_jitter, net1_loss, net1_avg, net1_jitter, "
            "net2_loss, net2_avg, net2_jitter, signal_dbm FROM samples "
            "ORDER BY ts DESC LIMIT 6").fetchall()
        slow = con.execute(
            "SELECT dns_ms, dns_ok FROM samples WHERE dns_ms IS NOT NULL "
            "ORDER BY ts DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if not rows:
        return {"state": "nodata", "badge_text": BADGE_TEXT["nodata"], "headline": "No data yet",
                "text": "The probe has not saved any readings.", "score": None,
                "updated": None, "tiles": None}

    age = (datetime.now(timezone.utc) - datetime.fromisoformat(rows[0][0])).total_seconds()
    gw = avg([r[1] for r in rows])
    n1 = avg([r[4] for r in rows])
    n2 = avg([r[7] for r in rows])
    lat = avg([r[5] for r in rows] + [r[8] for r in rows])
    jit = avg([r[6] for r in rows] + [r[9] for r in rows])
    out_loss = avg([n1, n2])
    dns_ms, dns_ok = (slow[0], slow[1]) if slow else (None, None)

    if age > STALE_SECONDS:
        return {"state": "nodata", "badge_text": BADGE_TEXT["nodata"], "headline": HEADLINE["nodata"],
                "text": f"Newest saved reading is {int(age)} s old. Is netprobe running?",
                "score": None, "updated": rows[0][0], "tiles": None}

    state = classify(gw, n1, n2, lat)
    if state == "wifi":
        text = f"Packet loss to your router is {gw:.0f}%."
    elif state == "down":
        text = f"Router is fine, but 1.1.1.1 loses {n1:.0f}% and 8.8.8.8 loses {n2:.0f}%."
    else:
        parts = [f"{out_loss:.0f}% packet loss"]
        if lat is not None:
            parts.append(f"{lat:.0f} ms response")
        parts.append(f"{jitter_word(jit)} jitter")
        text = " \u2022 ".join(parts)

    latest = rows[0]
    return {
        "state": state, "badge_text": BADGE_TEXT[state], "headline": HEADLINE[state], "text": text,
        "score": health(state, gw, out_loss, lat, jit, dns_ms, dns_ok),
        "updated": latest[0],
        "tiles": {
            "gw": tile_gw(latest[2], latest[1], latest[10]),
            "net1": tile_out(latest[5], latest[4]),
            "net2": tile_out(latest[8], latest[7]),
            "dns": tile_dns(dns_ms, dns_ok),
        },
    }


def ignore_windows(con):
    try:
        return con.execute("SELECT start_ts, end_ts FROM ignore_windows").fetchall()
    except sqlite3.OperationalError:
        return []


def get_note(con, since, wins):
    clause, params = "", []
    for s, e in wins:
        clause += " AND NOT (ts >= ? AND ts <= ?)"
        params += [s, e]
    base = "FROM samples WHERE ts >= ?" + clause
    args = [since] + params
    n, avg_loss, lossy, down = con.execute(
        "SELECT COUNT(*), AVG((net1_loss + net2_loss) / 2.0), "
        "SUM(CASE WHEN (net1_loss + net2_loss) > 0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN net1_loss >= 50 AND net2_loss >= 50 THEN 1 ELSE 0 END) " + base, args).fetchone()
    peak = con.execute(
        "SELECT ts, (net1_avg + net2_avg) / 2.0 " + base +
        " AND net1_avg IS NOT NULL AND net2_avg IS NOT NULL "
        "ORDER BY (net1_avg + net2_avg) DESC LIMIT 1", args).fetchone()
    excluded = sum(1 for s, e in wins if e >= since)
    return {"n": n or 0, "avg_loss": r1(avg_loss) if avg_loss is not None else 0,
            "lossy": lossy or 0,
            "down_min": round((down or 0) * probe.CYCLE_SECONDS / 60, 1),
            "peak_ms": r1(peak[1]) if peak else None,
            "peak_ts": peak[0] if peak else None,
            "excluded": excluded}


_cache = {}


def get_series(rng):
    hit = _cache.get(rng)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    span, bucket = RANGES[rng]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(seconds=span)).isoformat(timespec="seconds")
    con = db()
    try:
        rows = con.execute(
            "SELECT CAST(strftime('%s', substr(ts,1,19)) AS INTEGER) / ? * ? AS b, "
            "AVG(gw_avg), AVG(net1_avg), AVG(net2_avg) FROM samples "
            "WHERE ts >= ? GROUP BY b ORDER BY b", (bucket, bucket, since)).fetchall()
        note = get_note(con, since, ignore_windows(con))
    finally:
        con.close()
    by_bucket = {r[0]: r for r in rows}
    end_b = int(now.timestamp()) // bucket * bucket
    start_b = end_b - (span // bucket) * bucket
    times = list(range(start_b, end_b + bucket, bucket))
    out = {"times": times, "gw": [], "net1": [], "net2": [], "note": note}
    for t in times:
        r = by_bucket.get(t)
        out["gw"].append(r1(r[1]) if r else None)
        out["net1"].append(r1(r[2]) if r else None)
        out["net2"].append(r1(r[3]) if r else None)
    _cache[rng] = (time.time(), out)
    return out


TEST_LOCK = threading.Lock()


def run_test():
    """One-off check shown on screen only. Nothing is written to the database."""
    if not TEST_LOCK.acquire(blocking=False):
        return {"error": "A test is already running."}
    try:
        gateway = probe.get_gateway()
        if not gateway:
            return {"error": "No default gateway found."}
        targets = {"gw": gateway, "net1": "1.1.1.1", "net2": "8.8.8.8"}
        res = {}
        threads = [threading.Thread(target=lambda k=k, ip=ip: res.__setitem__(k, probe.ping(ip)))
                   for k, ip in targets.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        dns_ms, dns_ok = probe.dns_check()
        http_status, http_ms = probe.http_check()
        signal, bitrate = probe.wifi()
        lat = avg([res["net1"]["avg"], res["net2"]["avg"]])
        state = classify(res["gw"]["loss"], res["net1"]["loss"], res["net2"]["loss"], lat)
        return {"state": state, "verdict": VERDICT[state],
                "gw": res["gw"], "net1": res["net1"], "net2": res["net2"],
                "dns_ms": r1(dns_ms), "dns_ok": dns_ok,
                "http_status": http_status, "http_ms": r1(http_ms), "signal": signal}
    finally:
        TEST_LOCK.release()


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Network Pulse</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#6b7280;--line:#e6e8ec;--navbg:rgba(255,255,255,.94);
--good-bg:#dcfce7;--good-fg:#166534;--warn-bg:#fef3c7;--warn-fg:#92400e;--bad-bg:#fee2e2;--bad-fg:#991b1b;
--neutral-bg:#eef0f3;--neutral-fg:#4b5563;--chip:#f1f3f6;--accent:#0f9d6b;--accent-soft:#d9f5e8;--dark:#14171c;--darktext:#fff}
@media (prefers-color-scheme: dark){:root{--bg:#101215;--card:#1a1d22;--text:#eceef1;--muted:#9aa3af;--line:#2a2f36;
--navbg:rgba(26,29,34,.94);--good-bg:#12351f;--good-fg:#86efac;--warn-bg:#3a2f0b;--warn-fg:#fcd34d;--bad-bg:#3b1517;--bad-fg:#fca5a5;
--neutral-bg:#262b32;--neutral-fg:#b6bdc7;--chip:#242930;--accent:#34d399;--accent-soft:#12372a;--dark:#eceef1;--darktext:#14171c}}
*{box-sizing:border-box}[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding-bottom:calc(88px + env(safe-area-inset-bottom,0px))}
.wrap{max-width:560px;margin:0 auto;padding:0 14px}
header{display:flex;align-items:center;justify-content:space-between;padding:calc(12px + env(safe-area-inset-top,0px)) 14px 12px;
max-width:560px;margin:0 auto}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:1.2rem}
.brand svg{color:var(--accent)}
.hright{display:flex;align-items:center;gap:10px}
.pill{display:flex;align-items:center;gap:6px;background:var(--chip);border:1px solid var(--line);border-radius:999px;
padding:5px 11px;font:600 .8rem ui-monospace,SFMono-Regular,Menlo,monospace}
.dot{width:8px;height:8px;border-radius:50%;background:#7a7a7a}
.iconbtn{background:none;border:none;color:var(--text);padding:6px;border-radius:8px;cursor:pointer;display:flex}
.spin svg{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
main{display:flex;flex-direction:column;gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}
.hero{color:#fff;border:none;padding:18px;background:#7a7a7a}
.st-ok{background:linear-gradient(135deg,#0c9a68,#2bc88b)}
.st-degraded{background:linear-gradient(135deg,#c78a00,#eeb12e)}
.st-down{background:linear-gradient(135deg,#c93a3a,#ea6868)}
.st-wifi{background:linear-gradient(135deg,#cc6a18,#f0964a)}
.st-nodata{background:linear-gradient(135deg,#6b7280,#8b93a1)}
.herotop{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.hbadge{background:rgba(255,255,255,.95);color:#14171c;font-weight:700;border-radius:999px;padding:6px 14px;font-size:.95rem}
.score{font:600 .95rem ui-monospace,SFMono-Regular,Menlo,monospace;opacity:.95}
.hero h2{margin:0 0 6px;font-size:1.65rem;line-height:1.15}
.hero p{margin:0;opacity:.95;font-size:.95rem}
.herofoot{display:flex;justify-content:space-between;gap:10px;margin-top:14px;padding-top:10px;
border-top:1px solid rgba(255,255,255,.35);font:.72rem ui-monospace,SFMono-Regular,Menlo,monospace;opacity:.9}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.tile{display:flex;flex-direction:column;gap:6px;padding:14px;min-width:0}
.ttop{display:flex;justify-content:space-between;align-items:center}
.ico{width:34px;height:34px;border-radius:10px;background:var(--chip);display:flex;align-items:center;justify-content:center;color:var(--accent)}
.badge{font:600 .7rem ui-monospace,SFMono-Regular,Menlo,monospace;padding:3px 8px;border-radius:7px;white-space:nowrap}
.badge.good{background:var(--good-bg);color:var(--good-fg)}.badge.warn{background:var(--warn-bg);color:var(--warn-fg)}
.badge.bad{background:var(--bad-bg);color:var(--bad-fg)}.badge.neutral{background:var(--neutral-bg);color:var(--neutral-fg)}
.tname{font-size:.9rem;margin-top:4px}
.tval{font-size:1.45rem;font-weight:700}
.tval small{font:500 .75rem ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);margin-left:2px}
.tsub{font-size:.8rem;color:var(--muted)}
.chead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.chead h3{margin:0;font-size:1.15rem}
.seg{display:flex;background:var(--chip);border-radius:10px;padding:3px;gap:2px;margin-bottom:12px;width:fit-content}
.seg button{border:none;background:none;color:var(--muted);padding:6px 12px;border-radius:8px;
font:600 .78rem ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
.seg button.active{background:var(--dark);color:var(--darktext)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font:.78rem ui-monospace,SFMono-Regular,Menlo,monospace;margin-bottom:8px}
.legend i{display:inline-block;width:14px;height:4px;border-radius:2px;margin-right:6px;vertical-align:middle}
.chartbox{position:relative;height:260px}
.note{display:flex;gap:10px;background:var(--chip);border-radius:12px;padding:12px;margin-top:14px;font-size:.88rem}
.note svg{flex:none;margin-top:2px}.note.ok svg{color:var(--accent)}.note.warn svg{color:#d19a00}.note.bad svg{color:#d64545}
.note b{display:block;margin-bottom:2px}
.actions h3{margin:0;font-size:1.05rem}
.arow{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.arow span{color:var(--muted);font-size:.8rem}
.abtns{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.abtn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;border-radius:14px;font-weight:700;
font-size:1rem;cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--text)}
.abtn.primary{background:var(--dark);color:var(--darktext);border-color:var(--dark)}
.abtn:disabled{opacity:.6;cursor:wait}
.trow{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:.9rem}
.trow:last-child{border-bottom:none}.trow span:first-child{color:var(--muted)}
.tverdict{margin-top:10px;font-weight:600;font-size:.92rem}.tfoot{margin-top:6px;color:var(--muted);font-size:.75rem}
nav{position:fixed;left:0;right:0;bottom:0;background:var(--navbg);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
border-top:1px solid var(--line);padding:8px 10px calc(8px + env(safe-area-inset-bottom,0px));z-index:10}
.navin{max-width:560px;margin:0 auto;display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
.navbtn{display:flex;flex-direction:column;align-items:center;gap:3px;padding:7px 4px;border-radius:14px;border:none;
background:none;color:var(--muted);font:600 .68rem ui-monospace,SFMono-Regular,Menlo,monospace}
.navbtn[aria-current="page"]{background:var(--accent-soft);color:var(--accent)}
.navbtn[aria-disabled="true"]{opacity:.4;cursor:default}
</style></head>
<body>
<header>
  <div class="brand">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5.5 5.5 0 0 1 7 0"/><circle cx="12" cy="19" r="1" fill="currentColor"/><path d="M2 9a14 14 0 0 1 20 0"/></svg>
    <span>Network Pulse</span>
  </div>
  <div class="hright">
    <div class="pill"><span class="dot" id="dot"></span><span id="clock">--:--</span></div>
    <button class="iconbtn" id="hrefresh" aria-label="Refresh">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
    </button>
  </div>
</header>
<div class="wrap"><main>
  <section id="hero" class="card hero st-nodata">
    <div class="herotop"><span class="hbadge" id="hbadge">Loading</span><span class="score" id="score">--/100 Health</span></div>
    <h2 id="headline">Loading...</h2>
    <p id="htext"></p>
    <div class="herofoot"><span>Probe checks every 10 s</span><span id="updated"></span></div>
  </section>

  <section class="tiles">
    <div class="card tile">
      <div class="ttop"><div class="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5.5 5.5 0 0 1 7 0"/><circle cx="12" cy="19" r="1" fill="currentColor"/></svg></div><span class="badge neutral" id="gw_badge">--</span></div>
      <div class="tname">Home Wi-Fi hop</div>
      <div class="tval"><span id="gw_ms">--</span><small id="gw_loss">/ -- loss</small></div>
      <div class="tsub" id="gw_sub">--</div>
    </div>
    <div class="card tile">
      <div class="ttop"><div class="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17 9a4.5 4.5 0 0 1 .5 9z"/></svg></div><span class="badge neutral" id="net1_badge">--</span></div>
      <div class="tname">Cloudflare (1.1.1.1)</div>
      <div class="tval"><span id="net1_ms">--</span><small id="net1_loss">/ -- loss</small></div>
      <div class="tsub" id="net1_sub">--</div>
    </div>
    <div class="card tile">
      <div class="ttop"><div class="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z"/></svg></div><span class="badge neutral" id="net2_badge">--</span></div>
      <div class="tname">Google (8.8.8.8)</div>
      <div class="tval"><span id="net2_ms">--</span><small id="net2_loss">/ -- loss</small></div>
      <div class="tsub" id="net2_sub">--</div>
    </div>
    <div class="card tile">
      <div class="ttop"><div class="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"/></svg></div><span class="badge neutral" id="dns_badge">--</span></div>
      <div class="tname">DNS resolution</div>
      <div class="tval"><span id="dns_ms">--</span><small>total</small></div>
      <div class="tsub" id="dns_sub">--</div>
    </div>
  </section>

  <section class="card">
    <div class="chead"><h3>Latency Trends</h3></div>
    <div class="seg" id="ranges">
      <button data-r="1h" class="active">1 hour</button><button data-r="24h">24 hours</button><button data-r="7d">7 days</button>
    </div>
    <div class="legend">
      <span><i style="background:#4a5068"></i><span id="lg_gw">Wi-Fi hop</span></span>
      <span><i style="background:#10b981"></i><span id="lg_n1">1.1.1.1</span></span>
      <span><i style="background:#f59e0b"></i><span id="lg_n2">8.8.8.8</span></span>
    </div>
    <div class="chartbox"><canvas id="chart"></canvas></div>
    <div class="note ok" id="note">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/></svg>
      <div><b>Stability Note</b><span id="notetext">Loading...</span></div>
    </div>
  </section>

  <section class="card actions">
    <div class="arow"><h3>Instant Actions</h3><span>Test is not saved</span></div>
    <div class="abtns">
      <button class="abtn primary" id="runbtn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l13 8-13 8z"/></svg><span id="runlabel">Run Test</span>
      </button>
      <button class="abtn" id="refbtn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg><span>Refresh data</span>
      </button>
    </div>
  </section>

  <section class="card" id="testcard" hidden>
    <div id="testbody"></div>
  </section>
</main></div>

<nav><div class="navin">
  <button class="navbtn" aria-current="page"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/></svg>Overview</button>
  <button class="navbtn" aria-disabled="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>Telemetry</button>
  <button class="navbtn" aria-disabled="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><path d="M8 11h6"/></svg>Diagnostics</button>
  <button class="navbtn" aria-disabled="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/><path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/></svg>Settings</button>
</div></nav>

<script src="/chart.js"></script>
<script>
const COLORS = { ok:"#2e9e57", degraded:"#d19a00", down:"#d64545", wifi:"#d9731f", nodata:"#7a7a7a" };
const RANGE_WORDS = { "1h":"the last hour", "24h":"the last 24 hours", "7d":"the last 7 days" };
let range = "1h", chart = null;
const $ = id => document.getElementById(id);

async function getJSON(u, opts) {
  const r = await fetch(u, Object.assign({ cache: "no-store" }, opts || {}));
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
const n0 = v => (v === null || v === undefined) ? "--" : Number(v).toFixed(0);
const clock = () => { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
const fmtTime = iso => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function setTile(key, t, hasLoss) {
  const b = $(key + "_badge");
  if (!t) {
    b.className = "badge neutral"; b.textContent = "--";
    $(key + "_ms").textContent = "--"; $(key + "_sub").textContent = "--";
    if (hasLoss) $(key + "_loss").textContent = "/ -- loss";
    return;
  }
  b.className = "badge " + t.tone; b.textContent = t.badge;
  $(key + "_ms").textContent = t.ms === null ? "--" : n0(t.ms) + " ms";
  if (hasLoss) $(key + "_loss").textContent = "/ " + n0(t.loss) + "% loss";
  $(key + "_sub").textContent = t.sub;
}

async function refreshStatus() {
  try {
    const s = await getJSON("/api/status");
    $("hero").className = "card hero st-" + s.state;
    $("dot").style.background = COLORS[s.state] || COLORS.nodata;
    $("hbadge").textContent = s.badge_text;
    $("score").textContent = (s.score === null ? "--" : s.score) + "/100 Health";
    $("headline").textContent = s.headline;
    $("htext").textContent = s.text;
    $("updated").textContent = s.updated ? "Saved reading " + fmtTime(s.updated) : "";
    const t = s.tiles;
    setTile("gw", t && t.gw, true); setTile("net1", t && t.net1, true);
    setTile("net2", t && t.net2, true); setTile("dns", t && t.dns, false);
    $("lg_gw").textContent = "Wi-Fi hop" + (t && t.gw.ms !== null ? " (" + n0(t.gw.ms) + " ms)" : "");
    $("lg_n1").textContent = "1.1.1.1" + (t && t.net1.ms !== null ? " (" + n0(t.net1.ms) + " ms)" : "");
    $("lg_n2").textContent = "8.8.8.8" + (t && t.net2.ms !== null ? " (" + n0(t.net2.ms) + " ms)" : "");
  } catch (e) {
    $("hero").className = "card hero st-nodata";
    $("hbadge").textContent = "Error"; $("headline").textContent = "Dashboard cannot read data";
    $("htext").textContent = String(e);
  }
}

function renderNote(n) {
  const box = $("note");
  let tone = "ok", text;
  if (!n || !n.n) {
    text = "No readings in this period yet.";
  } else {
    const parts = [];
    if (n.down_min > 0) {
      tone = "bad";
      parts.push("Both outside targets were mostly unreachable for about " + n.down_min + " min.");
    } else if (n.lossy > 0) {
      tone = "warn";
      parts.push("Some packet loss: " + n.lossy + " of " + n.n + " checks dropped at least one packet (average loss " + n.avg_loss + "%).");
    } else {
      parts.push("Zero dropped packets recorded in " + RANGE_WORDS[range] + ".");
    }
    if (n.peak_ms !== null) {
      const d = new Date(n.peak_ts);
      const when = range === "1h" ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString([], { weekday: "short" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      parts.push("Peak latency " + n0(n.peak_ms) + " ms at " + when + ".");
    }
    if (n.excluded > 0) parts.push("A known test window is excluded from this summary.");
    text = parts.join(" ");
  }
  box.className = "note " + tone;
  $("notetext").textContent = text;
}

async function refreshChart() {
  if (typeof Chart === "undefined") {
    $("notetext").textContent = "Chart library missing: run the Chart.js download in Block 0.";
    return;
  }
  try {
    const d = await getJSON("/api/series?range=" + range);
    const labels = d.times.map(t => {
      const x = new Date(t * 1000);
      const hm = x.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return range === "7d" ? x.toLocaleDateString([], { weekday: "short" }) + " " + hm : hm;
    });
    const mk = (label, data, color) => ({ label: label, data: data, borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 0, spanGaps: false, tension: 0.25 });
    const ds = [mk("Wi-Fi hop", d.gw, "#4a5068"), mk("1.1.1.1", d.net1, "#10b981"), mk("8.8.8.8", d.net2, "#f59e0b")];
    const css = getComputedStyle(document.documentElement);
    const grid = css.getPropertyValue("--line").trim(), tick = css.getPropertyValue("--muted").trim();
    if (!chart) {
      chart = new Chart($("chart"), {
        type: "line", data: { labels: labels, datasets: ds },
        options: { responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: "index", intersect: false },
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, grid: { color: grid }, ticks: { color: tick, callback: v => v + " ms" } },
                    x: { grid: { display: false }, ticks: { color: tick, maxTicksLimit: 5, autoSkip: true } } } }
      });
    } else {
      chart.data.labels = labels; chart.data.datasets = ds; chart.update();
    }
    renderNote(d.note);
  } catch (e) { $("notetext").textContent = "Chart error: " + e; }
}

function addRow(parent, a, b) {
  const row = document.createElement("div"); row.className = "trow";
  const x = document.createElement("span"); x.textContent = a;
  const y = document.createElement("span"); y.textContent = b;
  row.appendChild(x); row.appendChild(y); parent.appendChild(row);
}
const pingText = p => (p.avg === null ? "no replies" : n0(p.avg) + " ms") + " \u2022 " + n0(p.loss) + "% loss";

async function runTest() {
  const btn = $("runbtn"), body = $("testbody");
  btn.disabled = true; $("runlabel").textContent = "Testing...";
  $("testcard").hidden = false;
  body.textContent = "Running pings, DNS and web check (about 8 seconds)...";
  try {
    const d = await getJSON("/api/runtest", { method: "POST" });
    if (d.error) throw new Error(d.error);
    body.textContent = "";
    addRow(body, "Router (Wi-Fi hop)", pingText(d.gw));
    addRow(body, "1.1.1.1", pingText(d.net1));
    addRow(body, "8.8.8.8", pingText(d.net2));
    addRow(body, "DNS lookup", n0(d.dns_ms) + " ms" + (d.dns_ok ? "" : " (failed)"));
    addRow(body, "Web check", (d.http_status === null ? "failed" : d.http_status) + " in " + n0(d.http_ms) + " ms");
    addRow(body, "Wi-Fi signal", d.signal === null ? "--" : n0(d.signal) + " dBm");
    const v = document.createElement("div"); v.className = "tverdict"; v.textContent = d.verdict; body.appendChild(v);
    const f = document.createElement("div"); f.className = "tfoot"; f.textContent = "One-off check at " + new Date().toLocaleTimeString() + ". Not saved to the database."; body.appendChild(f);
  } catch (e) {
    body.textContent = "Test failed: " + e.message;
  }
  btn.disabled = false; $("runlabel").textContent = "Run Test";
}

function refreshAll() {
  const b = $("hrefresh"); b.classList.add("spin");
  Promise.all([refreshStatus(), refreshChart()]).finally(() => setTimeout(() => b.classList.remove("spin"), 400));
}

$("ranges").addEventListener("click", ev => {
  const r = ev.target.dataset.r;
  if (!r) return;
  range = r;
  document.querySelectorAll("#ranges button").forEach(b => b.classList.toggle("active", b.dataset.r === r));
  refreshChart();
});
$("runbtn").addEventListener("click", runTest);
$("refbtn").addEventListener("click", refreshAll);
$("hrefresh").addEventListener("click", refreshAll);

clock(); setInterval(clock, 1000);
refreshStatus(); refreshChart();
setInterval(refreshStatus, 10000);
setInterval(refreshChart, 60000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/":
                self.reply(200, "text/html; charset=utf-8", PAGE)
            elif u.path == "/chart.js":
                with open(CHART_JS, "rb") as f:
                    self.reply(200, "application/javascript", f.read())
            elif u.path == "/api/status":
                self.reply(200, "application/json", json.dumps(get_status()))
            elif u.path == "/api/series":
                rng = parse_qs(u.query).get("range", ["1h"])[0]
                if rng not in RANGES:
                    self.reply(400, "application/json", json.dumps({"error": "bad range"}))
                else:
                    self.reply(200, "application/json", json.dumps(get_series(rng)))
            elif u.path == "/favicon.ico":
                self.reply(204, "image/x-icon", b"")
            else:
                self.reply(404, "text/plain", "not found")
        except Exception as e:
            self.reply(500, "application/json", json.dumps({"error": str(e)}))

    def do_POST(self):
        try:
            if urlparse(self.path).path == "/api/runtest":
                self.reply(200, "application/json", json.dumps(run_test()))
            else:
                self.reply(404, "text/plain", "not found")
        except Exception as e:
            self.reply(500, "application/json", json.dumps({"error": str(e)}))

    def log_message(self, *args):
        pass  # keep the journal quiet


if __name__ == "__main__":
    print(f"Dashboard on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
